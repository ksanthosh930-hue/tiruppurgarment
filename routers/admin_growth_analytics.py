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
