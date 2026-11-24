import os
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query, Cookie

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/growth-analytics", tags=["Admin Growth Analytics"])

# ---------------------------------------------------------------------------
# Thread-safe in-memory 10-Minute TTL Cache
# ---------------------------------------------------------------------------
class AnalyticsTTLCache:
    def __init__(self, ttl_seconds: int = 600):
        self.ttl = ttl_seconds
        self.cache: Dict[str, tuple[float, Any]] = {}
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            if key in self.cache:
                timestamp, val = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    return val
                else:
                    del self.cache[key]
            return None

    def set(self, key: str, val: Any) -> None:
        with self.lock:
            self.cache[key] = (time.time(), val)

    def clear(self) -> None:
        with self.lock:
            self.cache.clear()

analytics_cache = AnalyticsTTLCache(ttl_seconds=600)

# ---------------------------------------------------------------------------
# Database and Auth Helper Injections
# ---------------------------------------------------------------------------
db_helpers = {
    "db_enabled": False,
    "query_db": None,
    "get_current_admin": None
}

def init_growth_analytics_router(enabled: bool, query_fn, auth_fn):
    db_helpers["db_enabled"] = enabled
    db_helpers["query_db"] = query_fn
    db_helpers["get_current_admin"] = auth_fn

async def require_admin(session_id: Optional[str] = Cookie(None)):
    auth_fn = db_helpers.get("get_current_admin")
    if not auth_fn:
        raise HTTPException(status_code=401, detail="Unauthorized: Admin auth service unavailable.")
    return await auth_fn(session_id=session_id)


# ---------------------------------------------------------------------------
# Helper: Parse Date Range Filter for SQL (IST Timezone Boundary)
# ---------------------------------------------------------------------------
def get_range_sql_filter(range_str: str, date_col: str) -> str:
    if range_str == "today":
        return f"{date_col} >= (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date AT TIME ZONE 'Asia/Kolkata'"
    elif range_str == "7d":
        return f"{date_col} >= (CURRENT_TIMESTAMP - INTERVAL '7 days')"
    elif range_str == "30d":
        return f"{date_col} >= (CURRENT_TIMESTAMP - INTERVAL '30 days')"
    elif range_str == "90d":
        return f"{date_col} >= (CURRENT_TIMESTAMP - INTERVAL '90 days')"
    else:  # all
        return "1=1"


# ---------------------------------------------------------------------------
# 1. EXECUTIVE OVERVIEW ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/overview")
def get_growth_overview(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|all)$"),
    refresh: bool = Query(False),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """
    Returns high-level Executive Growth KPI Scorecards and aggregate performance
    metrics calculated directly from PostgreSQL system of record tables.
    Guaranteed Zero-PII payload.
    """
    cache_key = f"growth_overview_{range}"
    if not refresh:
        cached_data = analytics_cache.get(cache_key)
        if cached_data:
            return cached_data

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        return {
            "success": True,
            "data_source": "PostgreSQL (Offline/Mock)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "kpis": {},
            "period_metrics": {},
            "rates": {}
        }

    try:
        # 1. Total All-time Ground Truth KPIs
        kpi_rows = db_helpers["query_db"]("""
            SELECT
                -- Job Seekers
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'individual') AS total_jobseekers,
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'individual' AND email_verified = TRUE) AS verified_jobseekers,
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'individual' AND COALESCE(is_active, TRUE) = TRUE) AS active_jobseekers,

                -- Employers
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'company') AS total_employers,
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'company' AND email_verified = TRUE) AS verified_employers,
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'company' AND COALESCE(is_active, TRUE) = TRUE) AS active_employers,

                -- Profiles
                (SELECT COUNT(*) FROM individual_profiles) AS total_jobseeker_profiles,
                (SELECT COUNT(*) FROM company_profiles) AS total_company_profiles,
                (SELECT COUNT(*) FROM company_profiles WHERE LOWER(COALESCE(verification_status, '')) = 'verified') AS verified_company_profiles,

                -- Jobs
                (SELECT COUNT(*) FROM jobs) AS total_jobs,
                (SELECT COUNT(*) FROM jobs WHERE LOWER(status) = 'published' AND COALESCE(is_archived, FALSE) = FALSE AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)) AS active_jobs,
                (SELECT COUNT(*) FROM jobs WHERE LOWER(status) IN ('closed', 'expired') OR COALESCE(is_archived, FALSE) = TRUE OR (expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP)) AS closed_or_expired_jobs,

                -- Applications
                (SELECT COUNT(*) FROM job_applications) AS total_applications;
        """)
        kpi = kpi_rows[0] if kpi_rows else {}

        # 2. Period Metrics (Filtered by Range)
        user_filter = get_range_sql_filter(range, "created_at")
        job_filter = get_range_sql_filter(range, "created_at")
        app_filter = get_range_sql_filter(range, "applied_at")

        period_rows = db_helpers["query_db"](f"""
            SELECT
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'individual' AND {user_filter}) AS new_jobseekers,
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'individual' AND email_verified = TRUE AND {user_filter}) AS new_verified_jobseekers,
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'company' AND {user_filter}) AS new_employers,
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'company' AND email_verified = TRUE AND {user_filter}) AS new_verified_employers,
                (SELECT COUNT(*) FROM company_profiles WHERE {user_filter}) AS new_company_profiles,
                (SELECT COUNT(*) FROM jobs WHERE {job_filter}) AS new_jobs_posted,
                (SELECT COUNT(*) FROM job_applications WHERE {app_filter}) AS new_applications;
        """)
        period = period_rows[0] if period_rows else {}

        # 3. Employer Activation Count (Employers who have posted at least 1 job)
        act_rows = db_helpers["query_db"]("""
            WITH employers_with_jobs AS (
                SELECT DISTINCT u.id
                FROM public_users u
                LEFT JOIN company_profiles cp ON cp.user_id = u.id
                WHERE u.account_type = 'company'
                  AND (
                      EXISTS (SELECT 1 FROM jobs j WHERE j.employer_user_id = u.id)
                      OR (cp.id IS NOT NULL AND EXISTS (SELECT 1 FROM jobs j WHERE j.company_profile_id = cp.id))
                      OR EXISTS (SELECT 1 FROM employer_jobs_meta ejm WHERE ejm.employer_user_id = u.id)
                  )
            )
            SELECT COUNT(*) AS activated_employers FROM employers_with_jobs;
        """)
        activated_employers = act_rows[0]["activated_employers"] if act_rows else 0

        # Calculate Rates
        total_js = kpi.get("total_jobseekers", 0) or 0
        ver_js = kpi.get("verified_jobseekers", 0) or 0
        prof_js = kpi.get("total_jobseeker_profiles", 0) or 0

        total_emp = kpi.get("total_employers", 0) or 0
        ver_emp = kpi.get("verified_employers", 0) or 0
        prof_emp = kpi.get("total_company_profiles", 0) or 0

        active_jobs = kpi.get("active_jobs", 0) or 0
        total_apps = kpi.get("total_applications", 0) or 0

        rates = {
            "jobseeker_verification_rate": round((ver_js / total_js * 100), 2) if total_js > 0 else 0.0,
            "jobseeker_profile_completion_rate": round((prof_js / total_js * 100), 2) if total_js > 0 else 0.0,
            "employer_verification_rate": round((ver_emp / total_emp * 100), 2) if total_emp > 0 else 0.0,
            "employer_profile_completion_rate": round((prof_emp / total_emp * 100), 2) if total_emp > 0 else 0.0,
            "employer_activation_rate": round((activated_employers / total_emp * 100), 2) if total_emp > 0 else 0.0,
            "avg_applications_per_active_job": round(total_apps / active_jobs, 2) if active_jobs > 0 else 0.0
        }

        response_data = {
            "success": True,
            "data_source": "PostgreSQL (Direct System of Record)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "kpis": {
                **kpi,
                "activated_employers": activated_employers
            },
            "period_metrics": period,
            "rates": rates
        }

        analytics_cache.set(cache_key, response_data)
        return response_data

    except Exception as e:
        logger.error(f"Error loading growth overview: {e}")
        raise HTTPException(status_code=500, detail=f"Database error loading overview metrics: {e}")


# ---------------------------------------------------------------------------
# 2. JOB SEEKER ANALYTICS ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/jobseekers")
def get_jobseeker_growth(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|all)$"),
    refresh: bool = Query(False),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """
    Returns Job Seeker registration growth, verification counts, profile completion
    breakdowns, and daily registration time series.
    Guaranteed Zero-PII payload.
    """
    cache_key = f"growth_jobseekers_{range}"
    if not refresh:
        cached_data = analytics_cache.get(cache_key)
        if cached_data:
            return cached_data

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        return {
            "success": True,
            "data_source": "PostgreSQL (Offline/Mock)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "summary": {},
            "auth_provider_breakdown": [],
            "daily_registrations": [],
            "monthly_registrations": []
        }

    try:
        # 1. Job Seeker Summary & Profile stats
        summary_rows = db_helpers["query_db"]("""
            SELECT
                COUNT(*) AS total_registered,
                COUNT(*) FILTER (WHERE email_verified = TRUE) AS total_verified,
                COUNT(*) FILTER (WHERE COALESCE(is_active, TRUE) = TRUE) AS total_active,
                (SELECT COUNT(DISTINCT user_id) FROM individual_profiles) AS profiles_completed,
                (SELECT COUNT(*) FROM individual_profiles WHERE resume_url IS NOT NULL AND LENGTH(TRIM(resume_url)) > 0) AS with_resume,
                (SELECT COUNT(*) FROM individual_profiles WHERE skills IS NOT NULL AND LENGTH(TRIM(skills)) > 0) AS with_skills
            FROM public_users
            WHERE account_type = 'individual';
        """)
        summary = summary_rows[0] if summary_rows else {}
        total = summary.get("total_registered", 0) or 0
        completed = summary.get("profiles_completed", 0) or 0
        summary["profile_completion_rate"] = round((completed / total * 100), 2) if total > 0 else 0.0

        # 2. Auth Provider Breakdown
        auth_rows = db_helpers["query_db"]("""
            SELECT
                COALESCE(auth_provider, 'local') AS provider,
                COUNT(*) AS count
            FROM public_users
            WHERE account_type = 'individual'
            GROUP BY 1
            ORDER BY count DESC;
        """)

        # 3. Daily Registrations Time-Series (Zero-Filled)
        days_count = 30
        if range == "today":
            days_count = 1
        elif range == "7d":
            days_count = 7
        elif range == "30d":
            days_count = 30
        elif range == "90d":
            days_count = 90
        else: # all -> default 90 days for daily chart
            days_count = 90

        daily_rows = db_helpers["query_db"](f"""
            WITH dates AS (
                SELECT generate_series(
                    CURRENT_DATE - INTERVAL '{days_count - 1} days',
                    CURRENT_DATE,
                    '1 day'::interval
                )::date AS day
            ),
            reg AS (
                SELECT
                    DATE(created_at AT TIME ZONE 'Asia/Kolkata') AS day,
                    COUNT(*) AS registered,
                    COUNT(*) FILTER (WHERE email_verified = TRUE) AS verified,
                    COUNT(*) FILTER (WHERE auth_provider = 'google') AS google_auth,
                    COUNT(*) FILTER (WHERE auth_provider = 'local' OR auth_provider IS NULL) AS local_auth
                FROM public_users
                WHERE account_type = 'individual'
                  AND created_at >= (CURRENT_TIMESTAMP - INTERVAL '{days_count} days')
                GROUP BY 1
            )
            SELECT
                d.day::text AS date,
                COALESCE(r.registered, 0) AS registered,
                COALESCE(r.verified, 0) AS verified,
                COALESCE(r.google_auth, 0) AS google_auth,
                COALESCE(r.local_auth, 0) AS local_auth
            FROM dates d
            LEFT JOIN reg r ON r.day = d.day
            ORDER BY d.day ASC;
        """)

        # 4. Monthly Registrations (Last 12 Months)
        monthly_rows = db_helpers["query_db"]("""
            WITH months AS (
                SELECT generate_series(
                    DATE_TRUNC('month', CURRENT_DATE - INTERVAL '11 months')::date,
                    DATE_TRUNC('month', CURRENT_DATE)::date,
                    '1 month'::interval
                )::date AS month_start
            ),
            reg AS (
                SELECT
                    DATE_TRUNC('month', created_at AT TIME ZONE 'Asia/Kolkata')::date AS month_start,
                    COUNT(*) AS registered,
                    COUNT(*) FILTER (WHERE email_verified = TRUE) AS verified
                FROM public_users
                WHERE account_type = 'individual'
                GROUP BY 1
            )
            SELECT
                to_char(m.month_start, 'YYYY-MM') AS month,
                COALESCE(r.registered, 0) AS registered,
                COALESCE(r.verified, 0) AS verified
            FROM months m
            LEFT JOIN reg r ON r.month_start = m.month_start
            ORDER BY m.month_start ASC;
        """)

        response_data = {
            "success": True,
            "data_source": "PostgreSQL (Direct System of Record)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "auth_provider_breakdown": auth_rows,
            "daily_registrations": daily_rows,
            "monthly_registrations": monthly_rows
        }

        analytics_cache.set(cache_key, response_data)
        return response_data

    except Exception as e:
        logger.error(f"Error loading jobseeker growth: {e}")
        raise HTTPException(status_code=500, detail=f"Database error loading jobseeker metrics: {e}")


# ---------------------------------------------------------------------------
# 3. EMPLOYER ANALYTICS ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/employers")
def get_employer_growth(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|all)$"),
    refresh: bool = Query(False),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """
    Returns Employer registration growth, profile creation volume, activation rates,
    and daily/monthly onboarding trends.
    Guaranteed Zero-PII payload.
    """
    cache_key = f"growth_employers_{range}"
    if not refresh:
        cached_data = analytics_cache.get(cache_key)
        if cached_data:
            return cached_data

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        return {
            "success": True,
            "data_source": "PostgreSQL (Offline/Mock)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "summary": {},
            "top_locations": [],
            "daily_registrations": [],
            "monthly_registrations": []
        }

    try:
        # 1. Employer Summary & Activation Stats
        summary_rows = db_helpers["query_db"]("""
            WITH employers_with_jobs AS (
                SELECT DISTINCT u.id
                FROM public_users u
                LEFT JOIN company_profiles cp ON cp.user_id = u.id
                WHERE u.account_type = 'company'
                  AND (
                      EXISTS (SELECT 1 FROM jobs j WHERE j.employer_user_id = u.id)
                      OR (cp.id IS NOT NULL AND EXISTS (SELECT 1 FROM jobs j WHERE j.company_profile_id = cp.id))
                      OR EXISTS (SELECT 1 FROM employer_jobs_meta ejm WHERE ejm.employer_user_id = u.id)
                  )
            )
            SELECT
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'company') AS total_registered,
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'company' AND email_verified = TRUE) AS total_verified,
                (SELECT COUNT(*) FROM public_users WHERE account_type = 'company' AND COALESCE(is_active, TRUE) = TRUE) AS total_active,
                (SELECT COUNT(*) FROM company_profiles) AS company_profiles_created,
                (SELECT COUNT(*) FROM company_profiles WHERE LOWER(COALESCE(verification_status, '')) = 'verified') AS company_profiles_verified,
                (SELECT COUNT(*) FROM employers_with_jobs) AS activated_employers;
        """)
        summary = summary_rows[0] if summary_rows else {}
        total = summary.get("total_registered", 0) or 0
        profiles = summary.get("company_profiles_created", 0) or 0
        activated = summary.get("activated_employers", 0) or 0

        summary["profile_completion_rate"] = round((profiles / total * 100), 2) if total > 0 else 0.0
        summary["employer_activation_rate"] = round((activated / total * 100), 2) if total > 0 else 0.0

        # 2. Top Employer Locations (Aggregate Anonymized)
        loc_rows = db_helpers["query_db"]("""
            SELECT
                COALESCE(NULLIF(TRIM(location), ''), 'Tiruppur') AS location,
                COUNT(*) AS count
            FROM company_profiles
            GROUP BY 1
            ORDER BY count DESC
            LIMIT 10;
        """)

        # 3. Daily Registrations & Profile Creation (Zero-Filled)
        days_count = 30
        if range == "today":
            days_count = 1
        elif range == "7d":
            days_count = 7
        elif range == "30d":
            days_count = 30
        elif range == "90d":
            days_count = 90
        else:
            days_count = 90

        daily_rows = db_helpers["query_db"](f"""
            WITH dates AS (
                SELECT generate_series(
                    CURRENT_DATE - INTERVAL '{days_count - 1} days',
                    CURRENT_DATE,
                    '1 day'::interval
                )::date AS day
            ),
            reg AS (
                SELECT
                    DATE(created_at AT TIME ZONE 'Asia/Kolkata') AS day,
                    COUNT(*) AS registered,
                    COUNT(*) FILTER (WHERE email_verified = TRUE) AS verified
                FROM public_users
                WHERE account_type = 'company'
                  AND created_at >= (CURRENT_TIMESTAMP - INTERVAL '{days_count} days')
                GROUP BY 1
            ),
            prof AS (
                SELECT
                    DATE(created_at AT TIME ZONE 'Asia/Kolkata') AS day,
                    COUNT(*) AS profiles_created
                FROM company_profiles
                WHERE created_at >= (CURRENT_TIMESTAMP - INTERVAL '{days_count} days')
                GROUP BY 1
            )
            SELECT
                d.day::text AS date,
                COALESCE(r.registered, 0) AS registered,
                COALESCE(r.verified, 0) AS verified,
                COALESCE(p.profiles_created, 0) AS profiles_created
            FROM dates d
            LEFT JOIN reg r ON r.day = d.day
            LEFT JOIN prof p ON p.day = d.day
            ORDER BY d.day ASC;
        """)

        # 4. Monthly Registrations
        monthly_rows = db_helpers["query_db"]("""
            WITH months AS (
                SELECT generate_series(
                    DATE_TRUNC('month', CURRENT_DATE - INTERVAL '11 months')::date,
                    DATE_TRUNC('month', CURRENT_DATE)::date,
                    '1 month'::interval
                )::date AS month_start
            ),
            reg AS (
                SELECT
                    DATE_TRUNC('month', created_at AT TIME ZONE 'Asia/Kolkata')::date AS month_start,
                    COUNT(*) AS registered,
                    COUNT(*) FILTER (WHERE email_verified = TRUE) AS verified
                FROM public_users
                WHERE account_type = 'company'
                GROUP BY 1
            )
            SELECT
                to_char(m.month_start, 'YYYY-MM') AS month,
                COALESCE(r.registered, 0) AS registered,
                COALESCE(r.verified, 0) AS verified
            FROM months m
            LEFT JOIN reg r ON r.month_start = m.month_start
            ORDER BY m.month_start ASC;
        """)

        response_data = {
            "success": True,
            "data_source": "PostgreSQL (Direct System of Record)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "top_locations": loc_rows,
            "daily_registrations": daily_rows,
            "monthly_registrations": monthly_rows
        }

        analytics_cache.set(cache_key, response_data)
        return response_data

    except Exception as e:
        logger.error(f"Error loading employer growth: {e}")
        raise HTTPException(status_code=500, detail=f"Database error loading employer metrics: {e}")


# ---------------------------------------------------------------------------
# 3B. EMPLOYER ACQUISITION & ACTIVATION DEEP-DIVE ENDPOINT (Phase 1D-3A)
# ---------------------------------------------------------------------------
@router.get("/employers/deep-dive")
def get_employer_deep_dive(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|all|custom)$"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    refresh: bool = Query(False),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """
    Returns granular Employer Acquisition & Activation Analytics calculated
    directly from PostgreSQL system of record tables.
    Includes Executive KPIs, Cohort Funnel, Activation Velocity, Job Distribution,
    Profile Completeness, Acquisition Channels, and IST Daily Time-Series Trends.
    Guaranteed Zero-PII payload.
    """
    custom_start_dt: Optional[str] = None
    custom_end_dt: Optional[str] = None
    date_range_label = "Last 30 Days"
    days_count = 30

    if range == "today":
        days_count = 1
        date_range_label = "Today (IST)"
        p_filter = lambda col: f"({col} AT TIME ZONE 'Asia/Kolkata')::date = (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date"
        p_params = None
    elif range == "7d":
        days_count = 7
        date_range_label = "Last 7 Days"
        p_filter = lambda col: f"{col} >= (CURRENT_TIMESTAMP - INTERVAL '7 days')"
        p_params = None
    elif range == "30d":
        days_count = 30
        date_range_label = "Last 30 Days"
        p_filter = lambda col: f"{col} >= (CURRENT_TIMESTAMP - INTERVAL '30 days')"
        p_params = None
    elif range == "90d":
        days_count = 90
        date_range_label = "Last 90 Days"
        p_filter = lambda col: f"{col} >= (CURRENT_TIMESTAMP - INTERVAL '90 days')"
        p_params = None
    elif range == "all":
        days_count = 365
        date_range_label = "All Time"
        p_filter = lambda col: "1=1"
        p_params = None
    elif range == "custom":
        if not start_date or not end_date:
            raise HTTPException(
                status_code=400,
                detail="start_date and end_date are required when range='custom' (format: YYYY-MM-DD)"
            )
        try:
            d_start = datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
            d_end = datetime.strptime(end_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format for start_date or end_date. Expected format: YYYY-MM-DD"
            )
        if d_start > d_end:
            d_start, d_end = d_end, d_start
        custom_start_dt = d_start.strftime("%Y-%m-%d")
        custom_end_dt = d_end.strftime("%Y-%m-%d")
        days_count = max(1, (d_end - d_start).days + 1)
        date_range_label = f"Custom ({custom_start_dt} to {custom_end_dt})"
        p_filter = lambda col: f"({col} AT TIME ZONE 'Asia/Kolkata')::date >= %s::date AND ({col} AT TIME ZONE 'Asia/Kolkata')::date <= %s::date"
        p_params = (custom_start_dt, custom_end_dt)

    cache_key = f"growth_employer_deep_dive_{range}_{custom_start_dt}_{custom_end_dt}"
    if not refresh:
        cached_data = analytics_cache.get(cache_key)
        if cached_data:
            return cached_data

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        return {
            "success": True,
            "data_source": "PostgreSQL (Offline/Mock)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "date_range_label": date_range_label,
            "start_date": custom_start_dt,
            "end_date": custom_end_dt,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "kpis": {
                "all_time_totals": {
                    "total_registered_employers": 0,
                    "active_accounts": 0,
                    "profile_completed_employers": 0,
                    "activated_employers": 0,
                    "pending_activation_employers": 0,
                    "activation_rate_pct": 0.0,
                    "published_employers": 0,
                    "published_rate_pct": 0.0,
                    "total_employer_jobs": 0,
                    "published_employer_jobs": 0,
                    "archived_employer_jobs": 0,
                    "draft_employer_jobs": 0,
                    "median_time_to_first_job_mins": None,
                    "avg_time_to_first_job_mins": None,
                    "repeat_job_posting_employers": 0,
                    "repeat_posting_rate_pct": 0.0
                },
                "period_metrics": {
                    "new_registrations_in_period": 0,
                    "new_activations_in_period": 0,
                    "period_activation_rate_pct": 0.0,
                    "jobs_created_in_period": 0,
                    "jobs_published_in_period": 0,
                    "cohort_size": 0,
                    "cohort_activated": 0,
                    "cohort_activation_rate_pct": 0.0
                }
            },
            "funnel": {
                "pre_registration": {
                    "raw_otp_requests_count": 0,
                    "cohort_conversion_tracked": False,
                    "note": "Raw OTP request events are logged anonymously before account creation. Identity linkage from pre-registration OTP to user account is unmeasured in database."
                },
                "cohort_stages": []
            },
            "activation_velocity": {
                "total_activated_measured": 0,
                "under_5_mins": {"count": 0, "percentage": 0.0},
                "mins_5_to_15": {"count": 0, "percentage": 0.0},
                "mins_15_to_60": {"count": 0, "percentage": 0.0},
                "hours_1_to_24": {"count": 0, "percentage": 0.0},
                "over_24_hours": {"count": 0, "percentage": 0.0}
            },
            "job_distribution": {
                "total_posting_employers": 0,
                "employers_with_1_job": {"count": 0, "percentage": 0.0},
                "employers_with_2_jobs": {"count": 0, "percentage": 0.0},
                "employers_with_3_jobs": {"count": 0, "percentage": 0.0},
                "employers_with_4_plus_jobs": {"count": 0, "percentage": 0.0}
            },
            "profile_completeness": {
                "total_employers": 0,
                "core_contact": {"count": 0, "percentage": 0.0, "fields": ["company_name", "contact_person", "mobile", "email"]},
                "business_info": {"count": 0, "percentage": 0.0, "fields": ["business_type", "company_description"]},
                "location_info": {"count": 0, "percentage": 0.0, "fields": ["location", "address", "area"]},
                "branding_info": {"count": 0, "percentage": 0.0, "fields": ["company_logo", "website"]}
            },
            "acquisition": {
                "auth_providers": [
                    {"provider": "local", "count": 0, "percentage": 0.0, "description": "Email OTP verification (Note: Not direct marketing traffic)"},
                    {"provider": "google", "count": 0, "percentage": 0.0, "description": "Google OAuth 1-Click"}
                ],
                "marketing_attribution": {
                    "status": "unmeasured_in_database",
                    "source_tracking_column_present": False,
                    "note": "PostgreSQL public_users and company_profiles tables do not store UTM parameters, referrers, or acquisition campaigns. Do not label auth_provider='local' as Direct traffic. Marketing campaign attribution must be cross-referenced with GA4 acquisition reports."
                }
            },
            "trends": [],
            "methodology": {
                "registered_employer": "Any user account in public_users where account_type = 'company'.",
                "active_account": "An employer user where COALESCE(is_active, true) = true. Represents account login eligibility, distinct from employer activation.",
                "profile_completed_employer": "An employer with a linked company_profiles record possessing mandatory contact fields (company_name, contact_person, mobile, email).",
                "activated_employer": "An employer who has successfully authored at least one job record in the jobs table linked to their account.",
                "published_job_employer": "An employer who has at least one job in status = 'published'.",
                "repeat_employer": "An employer who has authored two or more jobs in the jobs table.",
                "timezone": "All date-range truncations and time-series aggregations are calculated in Asia/Kolkata (IST)."
            },
            "data_quality_warnings": [
                "Database connection offline/mock mode."
            ]
        }

    try:
        # 1. Executive KPIs & All-Time Totals
        kpi_sql = """
            WITH employer_users AS (
                SELECT
                    u.id,
                    u.created_at,
                    COALESCE(u.is_active, true) as is_active,
                    u.email_verified,
                    cp.id as profile_id,
                    cp.company_name,
                    cp.contact_person,
                    cp.mobile,
                    cp.email as profile_email,
                    cp.business_type,
                    cp.location,
                    cp.address,
                    cp.website,
                    cp.company_description,
                    cp.company_logo
                FROM public_users u
                LEFT JOIN company_profiles cp ON cp.user_id = u.id
                WHERE u.account_type = 'company'
            ),
            employer_jobs_agg AS (
                SELECT
                    j.employer_user_id,
                    COUNT(j.id) as total_jobs,
                    COUNT(CASE WHEN j.status = 'published' THEN 1 END) as published_jobs,
                    COUNT(CASE WHEN j.status = 'archived' THEN 1 END) as archived_jobs,
                    COUNT(CASE WHEN j.status = 'draft' THEN 1 END) as draft_jobs,
                    MIN(j.created_at) as first_job_created_at,
                    MIN(COALESCE(j.published_at, j.created_at)) as first_job_published_at
                FROM jobs j
                WHERE j.employer_user_id IS NOT NULL
                GROUP BY j.employer_user_id
            )
            SELECT
                COUNT(eu.id) as total_registered,
                COUNT(CASE WHEN eu.is_active THEN 1 END) as active_accounts,
                COUNT(CASE WHEN eu.profile_id IS NOT NULL
                            AND eu.company_name IS NOT NULL AND TRIM(eu.company_name) != ''
                            AND eu.contact_person IS NOT NULL AND TRIM(eu.contact_person) != ''
                            AND eu.mobile IS NOT NULL AND TRIM(eu.mobile) != ''
                      THEN 1 END) as profile_completed,
                COUNT(eja.employer_user_id) as activated_employers,
                COUNT(CASE WHEN eja.employer_user_id IS NULL THEN 1 END) as pending_activation,
                COALESCE(SUM(eja.total_jobs), 0) as total_employer_jobs,
                COALESCE(SUM(eja.published_jobs), 0) as published_employer_jobs,
                COALESCE(SUM(eja.archived_jobs), 0) as archived_employer_jobs,
                COALESCE(SUM(eja.draft_jobs), 0) as draft_employer_jobs,
                COUNT(CASE WHEN eja.published_jobs >= 1 THEN 1 END) as published_employers,
                COUNT(CASE WHEN eja.total_jobs >= 2 THEN 1 END) as repeat_employers,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (eja.first_job_created_at - eu.created_at)) / 60.0) as median_time_to_first_job_mins,
                AVG(EXTRACT(EPOCH FROM (eja.first_job_created_at - eu.created_at)) / 60.0) as avg_time_to_first_job_mins
            FROM employer_users eu
            LEFT JOIN employer_jobs_agg eja ON eu.id = eja.employer_user_id;
        """
        kpi_rows = db_helpers["query_db"](kpi_sql)
        kpi_row = kpi_rows[0] if kpi_rows else {}
        tot_reg = int(kpi_row.get("total_registered") or 0)
        act_emp = int(kpi_row.get("activated_employers") or 0)
        rep_emp = int(kpi_row.get("repeat_employers") or 0)
        pub_emp = int(kpi_row.get("published_employers") or 0)
        tot_jobs = int(kpi_row.get("total_employer_jobs") or 0)
        prof_comp_count = int(kpi_row.get("profile_completed") or 0)

        # 2. Period Metrics & Cohorts
        p_regs_sql = f"SELECT COUNT(*) as count FROM public_users WHERE account_type = 'company' AND {p_filter('created_at')};"
        p_regs_rows = db_helpers["query_db"](p_regs_sql, p_params)
        p_regs_count = int(p_regs_rows[0].get("count") or 0) if p_regs_rows else 0

        cohort_sql = f"""
            WITH cohort_regs AS (
                SELECT id
                FROM public_users
                WHERE account_type = 'company' AND {p_filter('created_at')}
            ),
            cohort_acts AS (
                SELECT DISTINCT employer_user_id as id
                FROM jobs
                WHERE employer_user_id IN (SELECT id FROM cohort_regs)
            )
            SELECT
                (SELECT COUNT(*) FROM cohort_regs) as cohort_size,
                (SELECT COUNT(*) FROM cohort_acts) as cohort_activated;
        """
        cohort_rows = db_helpers["query_db"](cohort_sql, p_params)
        cohort_row = cohort_rows[0] if cohort_rows else {}
        c_size = int(cohort_row.get("cohort_size") or 0)
        c_act = int(cohort_row.get("cohort_activated") or 0)

        new_act_sql = f"""
            WITH first_jobs AS (
                SELECT employer_user_id, MIN(created_at) as first_job_created
                FROM jobs
                WHERE employer_user_id IS NOT NULL
                GROUP BY employer_user_id
            )
            SELECT COUNT(DISTINCT employer_user_id) as count
            FROM first_jobs
            WHERE {p_filter('first_job_created')};
        """
        new_act_rows = db_helpers["query_db"](new_act_sql, p_params)
        new_act_in_p = int(new_act_rows[0].get("count") or 0) if new_act_rows else 0

        pj_created_sql = f"SELECT COUNT(*) as count FROM jobs WHERE employer_user_id IS NOT NULL AND {p_filter('created_at')};"
        pj_created_rows = db_helpers["query_db"](pj_created_sql, p_params)
        pj_created = int(pj_created_rows[0].get("count") or 0) if pj_created_rows else 0

        pj_pub_sql = f"SELECT COUNT(*) as count FROM jobs WHERE employer_user_id IS NOT NULL AND status = 'published' AND {p_filter('COALESCE(published_at, created_at)')};"
        pj_pub_rows = db_helpers["query_db"](pj_pub_sql, p_params)
        pj_published = int(pj_pub_rows[0].get("count") or 0) if pj_pub_rows else 0

        # 3. Funnel Stages
        raw_otp_rows = db_helpers["query_db"]("SELECT COUNT(*) as count FROM job_analytics_events WHERE event_type = 'registration_start' AND metadata->>'account_type' = 'company';")
        raw_otp_count = int(raw_otp_rows[0].get("count") or 0) if raw_otp_rows else 0

        email_ver_rows = db_helpers["query_db"]("SELECT COUNT(*) as count FROM public_users WHERE account_type = 'company' AND email_verified = true;")
        email_ver_count = int(email_ver_rows[0].get("count") or 0) if email_ver_rows else 0

        funnel_stages = [
            {
                "stage": "account_created",
                "label": "Registered Employers",
                "count": tot_reg,
                "conversion_from_registered_pct": 100.0,
                "drop_off_from_prior_pct": 0.0
            },
            {
                "stage": "email_verified",
                "label": "Email OTP Verified",
                "count": email_ver_count,
                "conversion_from_registered_pct": round((email_ver_count / tot_reg * 100), 2) if tot_reg > 0 else 0.0,
                "drop_off_from_prior_pct": round(((tot_reg - email_ver_count) / tot_reg * 100), 2) if tot_reg > 0 else 0.0
            },
            {
                "stage": "company_profile_created",
                "label": "Company Profile Setup",
                "count": prof_comp_count,
                "conversion_from_registered_pct": round((prof_comp_count / tot_reg * 100), 2) if tot_reg > 0 else 0.0,
                "drop_off_from_prior_pct": round(((email_ver_count - prof_comp_count) / email_ver_count * 100), 2) if email_ver_count > 0 else 0.0
            },
            {
                "stage": "first_job_created",
                "label": "First Job Authored",
                "count": act_emp,
                "conversion_from_registered_pct": round((act_emp / tot_reg * 100), 2) if tot_reg > 0 else 0.0,
                "drop_off_from_prior_pct": round(((prof_comp_count - act_emp) / prof_comp_count * 100), 2) if prof_comp_count > 0 else 0.0
            },
            {
                "stage": "first_job_published",
                "label": "First Job Published",
                "count": pub_emp,
                "conversion_from_registered_pct": round((pub_emp / tot_reg * 100), 2) if tot_reg > 0 else 0.0,
                "drop_off_from_prior_pct": round(((act_emp - pub_emp) / act_emp * 100), 2) if act_emp > 0 else 0.0
            },
            {
                "stage": "repeat_job_posting",
                "label": "Multi-Job Employer (>=2)",
                "count": rep_emp,
                "conversion_from_registered_pct": round((rep_emp / tot_reg * 100), 2) if tot_reg > 0 else 0.0,
                "drop_off_from_prior_pct": round(((pub_emp - rep_emp) / pub_emp * 100), 2) if pub_emp > 0 else 0.0
            }
        ]

        # 4. Activation Velocity Buckets
        vel_sql = """
            WITH first_jobs AS (
                SELECT
                    u.id as employer_id,
                    EXTRACT(EPOCH FROM (MIN(j.created_at) - u.created_at)) / 60.0 as mins_to_first_job
                FROM public_users u
                JOIN jobs j ON u.id = j.employer_user_id
                WHERE u.account_type = 'company'
                GROUP BY u.id, u.created_at
            )
            SELECT
                COUNT(CASE WHEN mins_to_first_job < 5 THEN 1 END) as under_5_mins,
                COUNT(CASE WHEN mins_to_first_job >= 5 AND mins_to_first_job < 15 THEN 1 END) as mins_5_to_15,
                COUNT(CASE WHEN mins_to_first_job >= 15 AND mins_to_first_job < 60 THEN 1 END) as mins_15_to_60,
                COUNT(CASE WHEN mins_to_first_job >= 60 AND mins_to_first_job < 1440 THEN 1 END) as hours_1_to_24,
                COUNT(CASE WHEN mins_to_first_job >= 1440 THEN 1 END) as over_24_hours,
                COUNT(*) as total_measured
            FROM first_jobs;
        """
        vel_rows = db_helpers["query_db"](vel_sql)
        vel_row = vel_rows[0] if vel_rows else {}
        tot_meas = int(vel_row.get("total_measured") or 0)
        u5 = int(vel_row.get("under_5_mins") or 0)
        m5_15 = int(vel_row.get("mins_5_to_15") or 0)
        m15_60 = int(vel_row.get("mins_15_to_60") or 0)
        h1_24 = int(vel_row.get("hours_1_to_24") or 0)
        o24 = int(vel_row.get("over_24_hours") or 0)

        # 5. Job Distribution
        dist_sql = """
            WITH job_counts AS (
                SELECT
                    u.id as employer_id,
                    COUNT(j.id) as jobs_count
                FROM public_users u
                JOIN jobs j ON u.id = j.employer_user_id
                WHERE u.account_type = 'company'
                GROUP BY u.id
            )
            SELECT
                COUNT(CASE WHEN jobs_count = 1 THEN 1 END) as employers_with_1_job,
                COUNT(CASE WHEN jobs_count = 2 THEN 1 END) as employers_with_2_jobs,
                COUNT(CASE WHEN jobs_count = 3 THEN 1 END) as employers_with_3_jobs,
                COUNT(CASE WHEN jobs_count >= 4 THEN 1 END) as employers_with_4_plus_jobs,
                COUNT(*) as total_posting_employers
            FROM job_counts;
        """
        dist_rows = db_helpers["query_db"](dist_sql)
        dist_row = dist_rows[0] if dist_rows else {}
        tot_posting = int(dist_row.get("total_posting_employers") or 0)
        j1 = int(dist_row.get("employers_with_1_job") or 0)
        j2 = int(dist_row.get("employers_with_2_jobs") or 0)
        j3 = int(dist_row.get("employers_with_3_jobs") or 0)
        j4 = int(dist_row.get("employers_with_4_plus_jobs") or 0)

        # 6. Profile Completeness
        prof_sql = """
            SELECT
                COUNT(u.id) as total_employers,
                COUNT(CASE WHEN cp.company_name IS NOT NULL AND TRIM(cp.company_name) != ''
                            AND cp.contact_person IS NOT NULL AND TRIM(cp.contact_person) != ''
                            AND cp.mobile IS NOT NULL AND TRIM(cp.mobile) != ''
                            AND cp.email IS NOT NULL AND TRIM(cp.email) != '' THEN 1 END) as core_contact_complete,
                COUNT(CASE WHEN (cp.business_type IS NOT NULL AND TRIM(cp.business_type) != '')
                            OR (cp.company_description IS NOT NULL AND TRIM(cp.company_description) != '') THEN 1 END) as business_info_filled,
                COUNT(CASE WHEN (cp.location IS NOT NULL AND TRIM(cp.location) != '')
                            OR (cp.address IS NOT NULL AND TRIM(cp.address) != '')
                            OR (cp.area IS NOT NULL AND TRIM(cp.area) != '') THEN 1 END) as location_info_filled,
                COUNT(CASE WHEN (cp.company_logo IS NOT NULL AND TRIM(cp.company_logo) != '')
                            OR (cp.website IS NOT NULL AND TRIM(cp.website) != '') THEN 1 END) as branding_info_filled
            FROM public_users u
            LEFT JOIN company_profiles cp ON cp.user_id = u.id
            WHERE u.account_type = 'company';
        """
        prof_rows = db_helpers["query_db"](prof_sql)
        prof_row = prof_rows[0] if prof_rows else {}
        core_c = int(prof_row.get("core_contact_complete") or 0)
        biz_c = int(prof_row.get("business_info_filled") or 0)
        loc_c = int(prof_row.get("location_info_filled") or 0)
        brd_c = int(prof_row.get("branding_info_filled") or 0)

        # 7. Acquisition & Auth Providers
        auth_rows = db_helpers["query_db"]("""
            SELECT
                COALESCE(auth_provider, 'local') as provider,
                COUNT(*) as count
            FROM public_users
            WHERE account_type = 'company'
            GROUP BY 1
            ORDER BY count DESC;
        """)
        auth_map = {r["provider"]: int(r["count"]) for r in auth_rows}
        local_auth_count = auth_map.get("local", 0)
        google_auth_count = auth_map.get("google", 0)

        # 8. Data Quality Checks (Job 631 fallback check)
        fallback_check_rows = db_helpers["query_db"]("SELECT COUNT(*) as count FROM jobs WHERE employer_user_id IS NOT NULL AND status = 'published' AND published_at IS NULL;")
        job_631_check = int(fallback_check_rows[0].get("count") or 0) if fallback_check_rows else 0

        # 9. Time Series Trends
        if range == "custom":
            dates_cte = "SELECT generate_series(%s::date, %s::date, '1 day'::interval)::date AS day"
            t_params = (custom_start_dt, custom_end_dt)
        elif range == "today":
            dates_cte = "SELECT generate_series((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date, (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date, '1 day'::interval)::date AS day"
            t_params = None
        elif range == "all":
            dates_cte = """SELECT generate_series(
                COALESCE((SELECT MIN(created_at AT TIME ZONE 'Asia/Kolkata')::date FROM public_users WHERE account_type = 'company'), (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date - INTERVAL '89 days'),
                (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date,
                '1 day'::interval
            )::date AS day"""
            t_params = None
        else:
            dates_cte = f"""SELECT generate_series(
                (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date - INTERVAL '{days_count - 1} days',
                (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date,
                '1 day'::interval
            )::date AS day"""
            t_params = None

        trends_sql = f"""
            WITH dates AS (
                {dates_cte}
            ),
            bounds AS (
                SELECT MIN(day) as min_day, MAX(day) as max_day FROM dates
            ),
            regs AS (
                SELECT
                    (u.created_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
                    COUNT(*) AS count
                FROM public_users u, bounds b
                WHERE u.account_type = 'company'
                  AND (u.created_at AT TIME ZONE 'Asia/Kolkata')::date >= b.min_day
                  AND (u.created_at AT TIME ZONE 'Asia/Kolkata')::date <= b.max_day
                GROUP BY 1
            ),
            first_jobs AS (
                SELECT
                    j.employer_user_id,
                    MIN(j.created_at) as first_job_created
                FROM jobs j
                WHERE j.employer_user_id IS NOT NULL
                GROUP BY j.employer_user_id
            ),
            acts AS (
                SELECT
                    (fj.first_job_created AT TIME ZONE 'Asia/Kolkata')::date AS day,
                    COUNT(*) AS count
                FROM first_jobs fj, bounds b
                WHERE (fj.first_job_created AT TIME ZONE 'Asia/Kolkata')::date >= b.min_day
                  AND (fj.first_job_created AT TIME ZONE 'Asia/Kolkata')::date <= b.max_day
                GROUP BY 1
            ),
            created_jobs AS (
                SELECT
                    (j.created_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
                    COUNT(*) AS count
                FROM jobs j, bounds b
                WHERE j.employer_user_id IS NOT NULL
                  AND (j.created_at AT TIME ZONE 'Asia/Kolkata')::date >= b.min_day
                  AND (j.created_at AT TIME ZONE 'Asia/Kolkata')::date <= b.max_day
                GROUP BY 1
            ),
            pub_jobs AS (
                SELECT
                    (COALESCE(j.published_at, j.created_at) AT TIME ZONE 'Asia/Kolkata')::date AS day,
                    COUNT(*) AS count,
                    COUNT(CASE WHEN j.published_at IS NULL AND j.status = 'published' THEN 1 END) AS fallback_count
                FROM jobs j, bounds b
                WHERE j.employer_user_id IS NOT NULL
                  AND j.status = 'published'
                  AND (COALESCE(j.published_at, j.created_at) AT TIME ZONE 'Asia/Kolkata')::date >= b.min_day
                  AND (COALESCE(j.published_at, j.created_at) AT TIME ZONE 'Asia/Kolkata')::date <= b.max_day
                GROUP BY 1
            )
            SELECT
                d.day::text AS date,
                COALESCE(r.count, 0) AS new_registrations,
                COALESCE(a.count, 0) AS new_activations,
                COALESCE(cj.count, 0) AS jobs_created,
                COALESCE(pj.count, 0) AS jobs_published,
                COALESCE(pj.fallback_count, 0) AS published_fallback_count
            FROM dates d
            LEFT JOIN regs r ON r.day = d.day
            LEFT JOIN acts a ON a.day = d.day
            LEFT JOIN created_jobs cj ON cj.day = d.day
            LEFT JOIN pub_jobs pj ON pj.day = d.day
            ORDER BY d.day ASC;
        """
        trend_rows = db_helpers["query_db"](trends_sql, t_params)

        median_mins = kpi_row.get("median_time_to_first_job_mins")
        avg_mins = kpi_row.get("avg_time_to_first_job_mins")

        response_data = {
            "success": True,
            "data_source": "PostgreSQL Ground Truth",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "date_range_label": date_range_label,
            "start_date": custom_start_dt,
            "end_date": custom_end_dt,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "kpis": {
                "all_time_totals": {
                    "total_registered_employers": tot_reg,
                    "active_accounts": int(kpi_row.get("active_accounts") or 0),
                    "profile_completed_employers": prof_comp_count,
                    "activated_employers": act_emp,
                    "pending_activation_employers": int(kpi_row.get("pending_activation") or 0),
                    "activation_rate_pct": round((act_emp / tot_reg * 100), 2) if tot_reg > 0 else 0.0,
                    "published_employers": pub_emp,
                    "published_rate_pct": round((pub_emp / tot_reg * 100), 2) if tot_reg > 0 else 0.0,
                    "total_employer_jobs": tot_jobs,
                    "published_employer_jobs": int(kpi_row.get("published_employer_jobs") or 0),
                    "archived_employer_jobs": int(kpi_row.get("archived_employer_jobs") or 0),
                    "draft_employer_jobs": int(kpi_row.get("draft_employer_jobs") or 0),
                    "median_time_to_first_job_mins": round(float(median_mins), 2) if median_mins is not None else None,
                    "avg_time_to_first_job_mins": round(float(avg_mins), 2) if avg_mins is not None else None,
                    "repeat_job_posting_employers": rep_emp,
                    "repeat_posting_rate_pct": round((rep_emp / act_emp * 100), 2) if act_emp > 0 else 0.0
                },
                "period_metrics": {
                    "new_registrations_in_period": p_regs_count,
                    "new_activations_in_period": new_act_in_p,
                    "period_activation_rate_pct": round((new_act_in_p / p_regs_count * 100), 2) if p_regs_count > 0 else 0.0,
                    "jobs_created_in_period": pj_created,
                    "jobs_published_in_period": pj_published,
                    "cohort_size": c_size,
                    "cohort_activated": c_act,
                    "cohort_activation_rate_pct": round((c_act / c_size * 100), 2) if c_size > 0 else 0.0
                }
            },
            "funnel": {
                "pre_registration": {
                    "raw_otp_requests_count": raw_otp_count,
                    "cohort_conversion_tracked": False,
                    "note": "Raw OTP request events are logged anonymously before account creation. Identity linkage from pre-registration OTP to user account is unmeasured in database."
                },
                "cohort_stages": funnel_stages
            },
            "activation_velocity": {
                "total_activated_measured": tot_meas,
                "under_5_mins": {"count": u5, "percentage": round((u5 / tot_meas * 100), 2) if tot_meas > 0 else 0.0},
                "mins_5_to_15": {"count": m5_15, "percentage": round((m5_15 / tot_meas * 100), 2) if tot_meas > 0 else 0.0},
                "mins_15_to_60": {"count": m15_60, "percentage": round((m15_60 / tot_meas * 100), 2) if tot_meas > 0 else 0.0},
                "hours_1_to_24": {"count": h1_24, "percentage": round((h1_24 / tot_meas * 100), 2) if tot_meas > 0 else 0.0},
                "over_24_hours": {"count": o24, "percentage": round((o24 / tot_meas * 100), 2) if tot_meas > 0 else 0.0}
            },
            "job_distribution": {
                "total_posting_employers": tot_posting,
                "employers_with_1_job": {"count": j1, "percentage": round((j1 / tot_posting * 100), 2) if tot_posting > 0 else 0.0},
                "employers_with_2_jobs": {"count": j2, "percentage": round((j2 / tot_posting * 100), 2) if tot_posting > 0 else 0.0},
                "employers_with_3_jobs": {"count": j3, "percentage": round((j3 / tot_posting * 100), 2) if tot_posting > 0 else 0.0},
                "employers_with_4_plus_jobs": {"count": j4, "percentage": round((j4 / tot_posting * 100), 2) if tot_posting > 0 else 0.0}
            },
            "profile_completeness": {
                "total_employers": tot_reg,
                "core_contact": {"count": core_c, "percentage": round((core_c / tot_reg * 100), 2) if tot_reg > 0 else 0.0, "fields": ["company_name", "contact_person", "mobile", "email"]},
                "business_info": {"count": biz_c, "percentage": round((biz_c / tot_reg * 100), 2) if tot_reg > 0 else 0.0, "fields": ["business_type", "company_description"]},
                "location_info": {"count": loc_c, "percentage": round((loc_c / tot_reg * 100), 2) if tot_reg > 0 else 0.0, "fields": ["location", "address", "area"]},
                "branding_info": {"count": brd_c, "percentage": round((brd_c / tot_reg * 100), 2) if tot_reg > 0 else 0.0, "fields": ["company_logo", "website"]}
            },
            "acquisition": {
                "auth_providers": [
                    {"provider": "local", "count": local_auth_count, "percentage": round((local_auth_count / tot_reg * 100), 2) if tot_reg > 0 else 0.0, "description": "Email OTP verification (Note: Not direct marketing traffic)"},
                    {"provider": "google", "count": google_auth_count, "percentage": round((google_auth_count / tot_reg * 100), 2) if tot_reg > 0 else 0.0, "description": "Google OAuth 1-Click"}
                ],
                "marketing_attribution": {
                    "status": "unmeasured_in_database",
                    "source_tracking_column_present": False,
                    "note": "PostgreSQL public_users and company_profiles tables do not store UTM parameters, referrers, or acquisition campaigns. Do not label auth_provider='local' as Direct traffic. Marketing campaign attribution must be cross-referenced with GA4 acquisition reports."
                }
            },
            "trends": [
                {
                    "date": str(tr["date"]),
                    "new_registrations": int(tr["new_registrations"]),
                    "new_activations": int(tr["new_activations"]),
                    "jobs_created": int(tr["jobs_created"]),
                    "jobs_published": int(tr["jobs_published"]),
                    "published_fallback_count": int(tr["published_fallback_count"])
                }
                for tr in trend_rows
            ],
            "methodology": {
                "registered_employer": "Any user account in public_users where account_type = 'company'.",
                "active_account": "An employer user where COALESCE(is_active, true) = true. Represents account login eligibility, distinct from employer activation.",
                "profile_completed_employer": "An employer with a linked company_profiles record possessing mandatory contact fields (company_name, contact_person, mobile, email).",
                "activated_employer": "An employer who has successfully authored at least one job record in the jobs table linked to their account.",
                "published_job_employer": "An employer who has at least one job in status = 'published'.",
                "repeat_employer": "An employer who has authored two or more jobs in the jobs table.",
                "timezone": "All date-range truncations and time-series aggregations are calculated in Asia/Kolkata (IST)."
            },
            "data_quality_warnings": [
                f"Small sample size alert: Total registered employer cohort is currently {tot_reg} accounts. Percentages should be interpreted alongside raw counts.",
                "Pre-registration OTP funnel: Raw OTP event counts are tracked anonymously prior to account creation; cohort identity linkage from OTP request to registered account is unmeasured.",
                "Marketing attribution limitation: Acquisition channel sources (UTM/Referrers) are not recorded in PostgreSQL user tables.",
                f"Timestamp fallback: {job_631_check} published job (Job ID 631) has NULL published_at timestamp; created_at was used as an explicit fallback."
            ]
        }

        analytics_cache.set(cache_key, response_data)
        return response_data

    except Exception as e:
        logger.error(f"Error loading employer deep-dive metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Database error loading employer deep-dive metrics: {e}")


# ---------------------------------------------------------------------------
# 4. JOB PERFORMANCE & LIQUIDITY ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/jobs")
def get_jobs_growth(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|all)$"),
    refresh: bool = Query(False),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """
    Returns Job posting inventory, status breakdown, department distribution,
    and marketplace liquidity (applications received).
    Guaranteed Zero-PII payload.
    """
    cache_key = f"growth_jobs_{range}"
    if not refresh:
        cached_data = analytics_cache.get(cache_key)
        if cached_data:
            return cached_data

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        return {
            "success": True,
            "data_source": "PostgreSQL (Offline/Mock)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "summary": {},
            "departments": [],
            "job_types": []
        }

    try:
        # 1. Job Status Summary
        summary_rows = db_helpers["query_db"]("""
            SELECT
                COUNT(*) AS total_jobs,
                COUNT(*) FILTER (WHERE LOWER(status) = 'published' AND COALESCE(is_archived, FALSE) = FALSE AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)) AS active_jobs,
                COUNT(*) FILTER (WHERE LOWER(status) = 'draft' AND COALESCE(is_archived, FALSE) = FALSE) AS draft_jobs,
                COUNT(*) FILTER (WHERE LOWER(status) IN ('pending_review', 'pending') AND COALESCE(is_archived, FALSE) = FALSE) AS pending_jobs,
                COUNT(*) FILTER (WHERE LOWER(status) = 'closed' AND COALESCE(is_archived, FALSE) = FALSE) AS closed_jobs,
                COUNT(*) FILTER (WHERE (LOWER(status) = 'expired' OR (expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP)) AND COALESCE(is_archived, FALSE) = FALSE) AS expired_jobs,
                COUNT(*) FILTER (WHERE COALESCE(is_archived, FALSE) = TRUE OR LOWER(status) = 'archived') AS archived_jobs,
                COUNT(*) FILTER (WHERE is_featured = TRUE AND COALESCE(is_archived, FALSE) = FALSE) AS featured_jobs,
                (SELECT COUNT(*) FROM job_applications) AS total_applications
            FROM jobs;
        """)
        summary = summary_rows[0] if summary_rows else {}
        active = summary.get("active_jobs", 0) or 0
        apps = summary.get("total_applications", 0) or 0
        summary["avg_applications_per_active_job"] = round(apps / active, 2) if active > 0 else 0.0

        # 2. Department Breakdown (Jobs & Applications)
        dept_rows = db_helpers["query_db"]("""
            SELECT
                dept AS department,
                COUNT(DISTINCT j_id) AS total_jobs,
                COUNT(DISTINCT j_id) FILTER (WHERE is_active_job) AS active_jobs,
                COUNT(app_id) AS applications
            FROM (
                SELECT
                    COALESCE(NULLIF(TRIM(j.department), ''), 'General') AS dept,
                    j.id AS j_id,
                    (LOWER(j.status) = 'published' AND COALESCE(j.is_archived, FALSE) = FALSE AND (j.expires_at IS NULL OR j.expires_at > CURRENT_TIMESTAMP)) AS is_active_job,
                    a.id AS app_id
                FROM jobs j
                LEFT JOIN job_applications a ON a.job_id = j.id
            ) sub
            GROUP BY dept
            ORDER BY total_jobs DESC;
        """)

        # 3. Job Type Breakdown
        type_rows = db_helpers["query_db"]("""
            SELECT
                COALESCE(NULLIF(TRIM(job_type), ''), 'Full Time') AS job_type,
                COUNT(*) AS count
            FROM jobs
            GROUP BY 1
            ORDER BY count DESC;
        """)

        response_data = {
            "success": True,
            "data_source": "PostgreSQL (Direct System of Record)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "range": range,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "departments": dept_rows,
            "job_types": type_rows
        }

        analytics_cache.set(cache_key, response_data)
        return response_data

    except Exception as e:
        logger.error(f"Error loading jobs growth: {e}")
        raise HTTPException(status_code=500, detail=f"Database error loading jobs metrics: {e}")


# ---------------------------------------------------------------------------
# 5. GROWTH TRENDS (TIME-SERIES) ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/trends")
def get_growth_trends(
    granularity: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    range: str = Query("30d", pattern="^(today|7d|30d|90d|all)$"),
    refresh: bool = Query(False),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """
    Returns synchronized time-series growth trends across Job Seekers, Employers,
    Jobs, and Applications, grouped by daily, weekly, or monthly periods.
    Guaranteed Zero-PII payload.
    """
    cache_key = f"growth_trends_{granularity}_{range}"
    if not refresh:
        cached_data = analytics_cache.get(cache_key)
        if cached_data:
            return cached_data

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        return {
            "success": True,
            "data_source": "PostgreSQL (Offline/Mock)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "granularity": granularity,
            "range": range,
            "trends": []
        }

    try:
        if granularity == "weekly":
            query = """
                WITH periods AS (
                    SELECT generate_series(
                        DATE_TRUNC('week', CURRENT_DATE - INTERVAL '11 weeks')::date,
                        DATE_TRUNC('week', CURRENT_DATE)::date,
                        '1 week'::interval
                    )::date AS period_start
                ),
                js AS (
                    SELECT DATE_TRUNC('week', created_at AT TIME ZONE 'Asia/Kolkata')::date AS period_start, COUNT(*) AS count
                    FROM public_users
                    WHERE account_type = 'individual'
                    GROUP BY 1
                ),
                emp AS (
                    SELECT DATE_TRUNC('week', created_at AT TIME ZONE 'Asia/Kolkata')::date AS period_start, COUNT(*) AS count
                    FROM public_users
                    WHERE account_type = 'company'
                    GROUP BY 1
                ),
                jb AS (
                    SELECT DATE_TRUNC('week', created_at AT TIME ZONE 'Asia/Kolkata')::date AS period_start, COUNT(*) AS count
                    FROM jobs
                    GROUP BY 1
                ),
                app AS (
                    SELECT DATE_TRUNC('week', applied_at AT TIME ZONE 'Asia/Kolkata')::date AS period_start, COUNT(*) AS count
                    FROM job_applications
                    GROUP BY 1
                )
                SELECT
                    to_char(p.period_start, 'YYYY-\"W\"IW') AS period_label,
                    p.period_start::text AS start_date,
                    COALESCE(js.count, 0) AS jobseekers,
                    COALESCE(emp.count, 0) AS employers,
                    COALESCE(jb.count, 0) AS jobs,
                    COALESCE(app.count, 0) AS applications
                FROM periods p
                LEFT JOIN js ON js.period_start = p.period_start
                LEFT JOIN emp ON emp.period_start = p.period_start
                LEFT JOIN jb ON jb.period_start = p.period_start
                LEFT JOIN app ON app.period_start = p.period_start
                ORDER BY p.period_start ASC;
            """
        elif granularity == "monthly":
            query = """
                WITH periods AS (
                    SELECT generate_series(
                        DATE_TRUNC('month', CURRENT_DATE - INTERVAL '11 months')::date,
                        DATE_TRUNC('month', CURRENT_DATE)::date,
                        '1 month'::interval
                    )::date AS period_start
                ),
                js AS (
                    SELECT DATE_TRUNC('month', created_at AT TIME ZONE 'Asia/Kolkata')::date AS period_start, COUNT(*) AS count
                    FROM public_users
                    WHERE account_type = 'individual'
                    GROUP BY 1
                ),
                emp AS (
                    SELECT DATE_TRUNC('month', created_at AT TIME ZONE 'Asia/Kolkata')::date AS period_start, COUNT(*) AS count
                    FROM public_users
                    WHERE account_type = 'company'
                    GROUP BY 1
                ),
                jb AS (
                    SELECT DATE_TRUNC('month', created_at AT TIME ZONE 'Asia/Kolkata')::date AS period_start, COUNT(*) AS count
                    FROM jobs
                    GROUP BY 1
                ),
                app AS (
                    SELECT DATE_TRUNC('month', applied_at AT TIME ZONE 'Asia/Kolkata')::date AS period_start, COUNT(*) AS count
                    FROM job_applications
                    GROUP BY 1
                )
                SELECT
                    to_char(p.period_start, 'YYYY-MM') AS period_label,
                    p.period_start::text AS start_date,
                    COALESCE(js.count, 0) AS jobseekers,
                    COALESCE(emp.count, 0) AS employers,
                    COALESCE(jb.count, 0) AS jobs,
                    COALESCE(app.count, 0) AS applications
                FROM periods p
                LEFT JOIN js ON js.period_start = p.period_start
                LEFT JOIN emp ON emp.period_start = p.period_start
                LEFT JOIN jb ON jb.period_start = p.period_start
                LEFT JOIN app ON app.period_start = p.period_start
                ORDER BY p.period_start ASC;
            """
        else: # daily
            days_count = 30
            if range == "today":
                days_count = 1
            elif range == "7d":
                days_count = 7
            elif range == "30d":
                days_count = 30
            elif range == "90d":
                days_count = 90
            else:
                days_count = 90

            query = f"""
                WITH dates AS (
                    SELECT generate_series(
                        CURRENT_DATE - INTERVAL '{days_count - 1} days',
                        CURRENT_DATE,
                        '1 day'::interval
                    )::date AS day
                ),
                js AS (
                    SELECT DATE(created_at AT TIME ZONE 'Asia/Kolkata') AS day, COUNT(*) AS count
                    FROM public_users
                    WHERE account_type = 'individual'
                      AND created_at >= (CURRENT_TIMESTAMP - INTERVAL '{days_count} days')
                    GROUP BY 1
                ),
                emp AS (
                    SELECT DATE(created_at AT TIME ZONE 'Asia/Kolkata') AS day, COUNT(*) AS count
                    FROM public_users
                    WHERE account_type = 'company'
                      AND created_at >= (CURRENT_TIMESTAMP - INTERVAL '{days_count} days')
                    GROUP BY 1
                ),
                jb AS (
                    SELECT DATE(created_at AT TIME ZONE 'Asia/Kolkata') AS day, COUNT(*) AS count
                    FROM jobs
                    WHERE created_at >= (CURRENT_TIMESTAMP - INTERVAL '{days_count} days')
                    GROUP BY 1
                ),
                app AS (
                    SELECT DATE(applied_at AT TIME ZONE 'Asia/Kolkata') AS day, COUNT(*) AS count
                    FROM job_applications
                    WHERE applied_at >= (CURRENT_TIMESTAMP - INTERVAL '{days_count} days')
                    GROUP BY 1
                )
                SELECT
                    d.day::text AS period_label,
                    d.day::text AS start_date,
                    COALESCE(js.count, 0) AS jobseekers,
                    COALESCE(emp.count, 0) AS employers,
                    COALESCE(jb.count, 0) AS jobs,
                    COALESCE(app.count, 0) AS applications
                FROM dates d
                LEFT JOIN js ON js.day = d.day
                LEFT JOIN emp ON emp.day = d.day
                LEFT JOIN jb ON jb.day = d.day
                LEFT JOIN app ON app.day = d.day
                ORDER BY d.day ASC;
            """

        trend_rows = db_helpers["query_db"](query)

        response_data = {
            "success": True,
            "data_source": "PostgreSQL (Direct System of Record)",
            "reporting_timezone": "Asia/Kolkata (IST)",
            "granularity": granularity,
            "range": range,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "trends": trend_rows
        }

        analytics_cache.set(cache_key, response_data)
        return response_data

    except Exception as e:
        logger.error(f"Error loading growth trends: {e}")
        raise HTTPException(status_code=500, detail=f"Database error loading trends: {e}")
