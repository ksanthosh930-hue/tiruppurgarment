"""
DigiGarment - Phase 1D-2: Google Analytics 4 (GA4) Growth Analytics Router
Authoritative read-only integration with GA4 Data API for web traffic, conversion funnels,
organic search performance, and landing page intelligence.

Governance:
1. Zero-PII: Only aggregate statistical counts and percentages are processed.
2. System Separation: GA4 metrics (cookies/sessions) are NEVER summed with PostgreSQL user accounts.
3. Graceful Fallback: Operates without error in unconfigured environments.
"""

import os
import json
import time
import base64
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
from fastapi import APIRouter, HTTPException, Depends, Query, Cookie

logger = logging.getLogger("ga4_analytics")

router = APIRouter(prefix="/api/admin/ga4-analytics", tags=["Admin GA4 Analytics"])

# ---------------------------------------------------------------------------
# Thread-safe in-memory 10-Minute TTL Cache
# ---------------------------------------------------------------------------
class GA4AnalyticsTTLCache:
    def __init__(self, ttl_seconds: int = 600):
        self.ttl = ttl_seconds
        self.cache: Dict[str, Tuple[float, Any]] = {}
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

ga4_cache = GA4AnalyticsTTLCache(ttl_seconds=600)

# ---------------------------------------------------------------------------
# Auth Dependency & Lifecycle Helpers
# ---------------------------------------------------------------------------
auth_helpers = {
    "get_current_admin": None,
    "last_successful_fetch": None
}

def init_ga4_analytics_router(auth_fn):
    """Injects admin authentication dependency from main application."""
    auth_helpers["get_current_admin"] = auth_fn

async def require_admin(session_id: Optional[str] = Cookie(None)):
    """Enforces admin session validation. Rejects unauthorized requests with 401."""
    auth_fn = auth_helpers.get("get_current_admin")
    if not auth_fn:
        raise HTTPException(status_code=401, detail="Unauthorized: Admin auth service unavailable.")
    return await auth_fn(session_id=session_id)


# ---------------------------------------------------------------------------
# Credential & Client Management (Strict Zero-PII / Zero-Leak)
# ---------------------------------------------------------------------------
def get_ga4_config() -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
    """
    Safely retrieves and validates GA4 configuration without exposing private keys.
    Returns: (property_id, creds_dict, error_message)
    """
    property_id = os.getenv("GA4_PROPERTY_ID", "564842012").strip()
    raw_creds = os.getenv("GA4_SERVICE_ACCOUNT_JSON", "").strip()

    if not raw_creds:
        return property_id, None, "GA4_SERVICE_ACCOUNT_JSON environment variable is not configured."

    # Support base64-encoded JSON if passed as base64
    if raw_creds.startswith("eyJ"):  # Base64 for {"
        try:
            raw_creds = base64.b64decode(raw_creds).decode("utf-8")
        except Exception as e:
            logger.warning("Failed to decode base64 GA4_SERVICE_ACCOUNT_JSON")

    try:
        creds_info = json.loads(raw_creds)
    except json.JSONDecodeError:
        logger.error("Failed to parse GA4_SERVICE_ACCOUNT_JSON: Malformed JSON structure.")
        return property_id, None, "Invalid JSON structure in GA4_SERVICE_ACCOUNT_JSON."

    # Validate essential service account keys without printing values
    required_keys = ["project_id", "client_email", "private_key"]
    missing = [k for k in required_keys if not creds_info.get(k)]
    if missing:
        logger.error(f"GA4 credentials missing required keys: {missing}")
        return property_id, None, f"Service account credentials missing required fields: {', '.join(missing)}"

    return property_id, creds_info, None


def execute_ga4_report(
    property_id: str,
    creds_info: Dict[str, Any],
    dimensions: List[Dict[str, str]],
    metrics: List[Dict[str, str]],
    date_ranges: List[Dict[str, str]],
    dimension_filter: Optional[Dict[str, Any]] = None,
    order_bys: Optional[List[Dict[str, Any]]] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Executes a standard runReport request using AuthorizedSession or Google Analytics Data API.
    """
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession

        scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
        credentials = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        authed_session = AuthorizedSession(credentials)

        url = f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
        payload: Dict[str, Any] = {
            "dimensions": dimensions,
            "metrics": metrics,
            "dateRanges": date_ranges,
            "limit": limit
        }
        if dimension_filter:
            payload["dimensionFilter"] = dimension_filter
        if order_bys:
            payload["orderBys"] = order_bys

        response = authed_session.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            auth_helpers["last_successful_fetch"] = datetime.now(timezone.utc).isoformat()
            return response.json()
        else:
            error_msg = response.text
            logger.error(f"GA4 Data API returned HTTP {response.status_code}: {error_msg}")
            return {"error": f"GA4 API HTTP {response.status_code}", "detail": error_msg}
    except Exception as e:
        logger.error(f"GA4 Data API execution exception: {str(e)}")
        return {"error": "Execution exception", "detail": str(e)}


def execute_ga4_funnel_report(
    property_id: str,
    creds_info: Dict[str, Any],
    funnel_steps: List[Dict[str, Any]],
    date_ranges: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Executes a sequential runFunnelReport request using GA4 Data API v1alpha.
    """
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession

        scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
        credentials = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        authed_session = AuthorizedSession(credentials)

        url = f"https://analyticsdata.googleapis.com/v1alpha/properties/{property_id}:runFunnelReport"
        payload = {
            "funnelSteps": funnel_steps,
            "dateRanges": date_ranges
        }

        response = authed_session.post(url, json=payload, timeout=20)
        if response.status_code == 200:
            auth_helpers["last_successful_fetch"] = datetime.now(timezone.utc).isoformat()
            return response.json()
        else:
            logger.warning(f"GA4 Funnel API returned HTTP {response.status_code}: {response.text}")
            return {"error": f"GA4 Funnel HTTP {response.status_code}", "detail": response.text}
    except Exception as e:
        logger.warning(f"GA4 Funnel API execution exception: {str(e)}")
        return {"error": "Funnel execution exception", "detail": str(e)}


# ---------------------------------------------------------------------------
# Date Range Resolution (Asia/Kolkata Boundaries)
# ---------------------------------------------------------------------------
def resolve_date_range(
    range_str: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Tuple[str, str, str]:
    """
    Resolves standard or custom date ranges into GA4 API-compatible dates.
    Returns: (start_date, end_date, resolved_range_label)
    """
    if range_str == "custom" and start_date and end_date:
        try:
            d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            d_end = datetime.strptime(end_date, "%Y-%m-%d").date()
            if d_start > d_end:
                d_start, d_end = d_end, d_start
            return d_start.strftime("%Y-%m-%d"), d_end.strftime("%Y-%m-%d"), f"{start_date} to {end_date}"
        except ValueError:
            pass  # Fallback to 30d if invalid

    if range_str == "today":
        return "today", "today", "Today (IST)"
    elif range_str == "7d":
        return "7daysAgo", "yesterday", "Last 7 Days"
    elif range_str == "90d":
        return "90daysAgo", "yesterday", "Last 90 Days"
    else:  # default 30d
        return "30daysAgo", "yesterday", "Last 30 Days"


# ---------------------------------------------------------------------------
# 1. GA4 STATUS ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/status")
def get_ga4_status(admin=Depends(require_admin)):
    """
    Returns the operational configuration and connectivity status of the GA4 Data API.
    Zero-PII: Never outputs private keys, client secrets, or auth tokens.
    """
    property_id, creds_info, err = get_ga4_config()
    is_configured = creds_info is not None

    status_data = {
        "success": True,
        "configured": is_configured,
        "property_id": property_id,
        "measurement_id": "G-JWR79C4JQE",
        "service_account_configured": is_configured,
        "reporting_timezone": "Asia/Kolkata (IST)",
        "reporting_currency": "INR",
        "last_successful_fetch": auth_helpers.get("last_successful_fetch"),
        "status_message": "GA4 Data API is configured and operational." if is_configured else (err or "Unconfigured"),
        "cache_active": True,
        "ttl_seconds": 600
    }
    return status_data


# ---------------------------------------------------------------------------
# 2. TRAFFIC OVERVIEW ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/overview")
def get_ga4_overview(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    refresh: bool = False,
    admin=Depends(require_admin)
):
    """
    Executive traffic overview metrics: total users, new users, sessions,
    organic search traffic, engaged sessions, engagement rate, and event count.
    """
    property_id, creds_info, err = get_ga4_config()
    ga4_start, ga4_end, label = resolve_date_range(range, start_date, end_date)
    cache_key = f"overview:{property_id}:{ga4_start}:{ga4_end}"

    if not refresh:
        cached = ga4_cache.get(cache_key)
        if cached:
            return cached

    if not creds_info:
        return {
            "success": True,
            "configured": False,
            "range": range,
            "date_range_label": label,
            "reporting_timezone": "Asia/Kolkata",
            "message": "GA4 credentials not configured in environment.",
            "metrics": {
                "total_users": 0,
                "new_users": 0,
                "sessions": 0,
                "organic_users": 0,
                "organic_sessions": 0,
                "engaged_sessions": 0,
                "engagement_rate": 0.0,
                "event_count": 0
            }
        }

    # Query 1: Overall totals
    report_totals = execute_ga4_report(
        property_id=property_id,
        creds_info=creds_info,
        dimensions=[{"name": "platform"}],
        metrics=[
            {"name": "totalUsers"},
            {"name": "newUsers"},
            {"name": "sessions"},
            {"name": "engagedSessions"},
            {"name": "engagementRate"},
            {"name": "eventCount"}
        ],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}]
    )

    # Query 2: Organic Search segment
    report_organic = execute_ga4_report(
        property_id=property_id,
        creds_info=creds_info,
        dimensions=[{"name": "sessionDefaultChannelGroup"}],
        metrics=[
            {"name": "totalUsers"},
            {"name": "sessions"}
        ],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}],
        dimension_filter={
            "filter": {
                "fieldName": "sessionDefaultChannelGroup",
                "stringFilter": {"matchType": "EXACT", "value": "Organic Search", "caseSensitive": False}
            }
        }
    )

    # Parse totals safely
    total_users = 0
    new_users = 0
    sessions = 0
    engaged_sessions = 0
    engagement_rate = 0.0
    event_count = 0

    if "rows" in report_totals and len(report_totals["rows"]) > 0:
        row = report_totals["rows"][0]["metricValues"]
        total_users = int(row[0].get("value", 0))
        new_users = int(row[1].get("value", 0))
        sessions = int(row[2].get("value", 0))
        engaged_sessions = int(row[3].get("value", 0))
        engagement_rate = round(float(row[4].get("value", 0.0)) * 100, 2)
        event_count = int(row[5].get("value", 0))

    # Parse organic segment safely
    organic_users = 0
    organic_sessions = 0
    if "rows" in report_organic and len(report_organic["rows"]) > 0:
        row = report_organic["rows"][0]["metricValues"]
        organic_users = int(row[0].get("value", 0))
        organic_sessions = int(row[1].get("value", 0))

    result = {
        "success": True,
        "configured": True,
        "range": range,
        "date_range_label": label,
        "reporting_timezone": "Asia/Kolkata",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "total_users": total_users,
            "new_users": new_users,
            "sessions": sessions,
            "organic_users": organic_users,
            "organic_sessions": organic_sessions,
            "engaged_sessions": engaged_sessions,
            "engagement_rate": engagement_rate,
            "event_count": event_count
        }
    }
    ga4_cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# 3. REGISTRATION CONVERSION FUNNEL ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/funnel")
def get_ga4_funnel(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    refresh: bool = False,
    admin=Depends(require_admin)
):
    """
    Evaluates the registration conversion funnel across:
    1. registration_start -> otp_requested -> otp_verified -> sign_up (Email OTP path)
    2. Google OAuth 1-Click path (skips OTP steps)
    Prevents false classification of Google OAuth users as OTP drop-offs.
    """
    property_id, creds_info, err = get_ga4_config()
    ga4_start, ga4_end, label = resolve_date_range(range, start_date, end_date)
    cache_key = f"funnel:{property_id}:{ga4_start}:{ga4_end}"

    if not refresh:
        cached = ga4_cache.get(cache_key)
        if cached:
            return cached

    if not creds_info:
        return {
            "success": True,
            "configured": False,
            "range": range,
            "date_range_label": label,
            "reporting_timezone": "Asia/Kolkata",
            "message": "GA4 credentials not configured in environment.",
            "methodology_notes": [
                "Google OAuth registrations bypass OTP verification steps entirely.",
                "Phase 1C conversion tracking events (registration_start, otp_requested, otp_verified) were deployed Nov 23, 2026."
            ],
            "email_otp_funnel": {
                "stages": [],
                "overall_email_conversion_rate": 0.0
            },
            "google_oauth_funnel": {
                "sign_up_users": 0,
                "note": "Awaiting credentials"
            },
            "sequential_cta_funnel": {
                "supported": False,
                "completion_rate": None,
                "abandonment_rate": None,
                "steps": []
            }
        }

    # Query event counts and total users for all registration lifecycle events
    report_events = execute_ga4_report(
        property_id=property_id,
        creds_info=creds_info,
        dimensions=[{"name": "eventName"}, {"name": "customEvent:method"}],
        metrics=[{"name": "eventCount"}, {"name": "totalUsers"}],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}],
        dimension_filter={
            "filter": {
                "fieldName": "eventName",
                "inListFilter": {
                    "values": [
                        "registration_start",
                        "otp_requested",
                        "otp_verified",
                        "sign_up",
                        "reg_cta_click"
                    ],
                    "caseSensitive": True
                }
            }
        }
    )

    events_summary: Dict[str, Dict[str, int]] = {
        "reg_cta_click": {"events": 0, "users": 0},
        "registration_start": {"events": 0, "users": 0},
        "otp_requested": {"events": 0, "users": 0},
        "otp_verified": {"events": 0, "users": 0},
        "sign_up": {"events": 0, "users": 0, "google_users": 0, "email_users": 0}
    }

    if "rows" in report_events:
        for r in report_events["rows"]:
            ev_name = r["dimensionValues"][0].get("value", "")
            method_val = r["dimensionValues"][1].get("value", "").lower()
            e_count = int(r["metricValues"][0].get("value", 0))
            u_count = int(r["metricValues"][1].get("value", 0))

            if ev_name in events_summary:
                events_summary[ev_name]["events"] += e_count
                events_summary[ev_name]["users"] += u_count

                if ev_name == "sign_up":
                    if method_val == "google":
                        events_summary["sign_up"]["google_users"] += u_count
                    else:
                        events_summary["sign_up"]["email_users"] += u_count

    # Calculate Email OTP Micro-Funnel metrics
    r_start_users = events_summary["registration_start"]["users"]
    otp_req_users = events_summary["otp_requested"]["users"]
    otp_ver_users = events_summary["otp_verified"]["users"]
    email_signup_users = events_summary["sign_up"]["email_users"]

    # Calculate Drop-off and Progression percentages safely
    otp_req_rate = round((otp_req_users / r_start_users * 100), 2) if r_start_users > 0 else 0.0
    otp_ver_rate = round((otp_ver_users / otp_req_users * 100), 2) if otp_req_users > 0 else 0.0
    signup_from_otp_rate = round((email_signup_users / otp_ver_users * 100), 2) if otp_ver_users > 0 else 0.0
    overall_email_conversion = round((email_signup_users / r_start_users * 100), 2) if r_start_users > 0 else 0.0

    # Sequential Funnel test via runFunnelReport (reg_cta_click -> sign_up)
    sequential_funnel_data = {
        "supported": False,
        "completion_rate": None,
        "abandonment_rate": None,
        "steps": []
    }

    funnel_api_res = execute_ga4_funnel_report(
        property_id=property_id,
        creds_info=creds_info,
        funnel_steps=[
            {
                "name": "1. CTA Click",
                "filterExpression": {"funnelEventFilter": {"eventName": "reg_cta_click"}},
                "isDirectlyFollowedBy": False
            },
            {
                "name": "2. Completed Sign Up",
                "filterExpression": {"funnelEventFilter": {"eventName": "sign_up"}},
                "isDirectlyFollowedBy": False
            }
        ],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}]
    )

    if "funnelTable" in funnel_api_res and "rows" in funnel_api_res["funnelTable"]:
        f_rows = funnel_api_res["funnelTable"]["rows"]
        if len(f_rows) >= 2:
            step1_users = int(f_rows[0]["metricValues"][0].get("value", 0))
            step2_users = int(f_rows[1]["metricValues"][0].get("value", 0))
            comp_rate = round(float(f_rows[0]["metricValues"][1].get("value", 0.0)) * 100, 2)
            abandon_rate = round(float(f_rows[0]["metricValues"][3].get("value", 0.0)) * 100, 2)
            sequential_funnel_data = {
                "supported": True,
                "completion_rate": comp_rate,
                "abandonment_rate": abandon_rate,
                "steps": [
                    {"step_name": "Registration CTA Click", "active_users": step1_users},
                    {"step_name": "Completed Sign Up", "active_users": step2_users}
                ]
            }

    result = {
        "success": True,
        "configured": True,
        "range": range,
        "date_range_label": label,
        "reporting_timezone": "Asia/Kolkata",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "methodology_notes": [
            "Google OAuth registrations bypass OTP verification steps entirely.",
            "Phase 1C conversion tracking events (registration_start, otp_requested, otp_verified) were deployed Nov 23, 2026.",
            "Sequential conversion enforces strict step order within the same user session."
        ],
        "email_otp_funnel": {
            "stages": [
                {
                    "stage_index": 1,
                    "event_name": "registration_start",
                    "display_name": "Registration Started",
                    "users": r_start_users,
                    "events": events_summary["registration_start"]["events"],
                    "progression_rate": 100.0,
                    "drop_off_rate": 0.0
                },
                {
                    "stage_index": 2,
                    "event_name": "otp_requested",
                    "display_name": "OTP Requested",
                    "users": otp_req_users,
                    "events": events_summary["otp_requested"]["events"],
                    "progression_rate": otp_req_rate,
                    "drop_off_rate": round(100.0 - otp_req_rate, 2) if otp_req_rate > 0 else 0.0
                },
                {
                    "stage_index": 3,
                    "event_name": "otp_verified",
                    "display_name": "OTP Verified",
                    "users": otp_ver_users,
                    "events": events_summary["otp_verified"]["events"],
                    "progression_rate": otp_ver_rate,
                    "drop_off_rate": round(100.0 - otp_ver_rate, 2) if otp_ver_rate > 0 else 0.0
                },
                {
                    "stage_index": 4,
                    "event_name": "sign_up",
                    "display_name": "Email Registration Complete",
                    "users": email_signup_users,
                    "events": email_signup_users,
                    "progression_rate": signup_from_otp_rate,
                    "overall_conversion": overall_email_conversion
                }
            ],
            "overall_email_conversion_rate": overall_email_conversion
        },
        "google_oauth_funnel": {
            "sign_up_users": events_summary["sign_up"]["google_users"],
            "note": "Google OAuth 1-Click signups bypass email and phone OTP verification directly."
        },
        "sequential_cta_funnel": sequential_funnel_data
    }
    ga4_cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# 4. ROLE-BASED FUNNEL & CONVERSION ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/roles")
def get_ga4_roles(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    refresh: bool = False,
    admin=Depends(require_admin)
):
    """
    Attempts to segment conversions by role (Job Seeker vs Employer).
    Checks if customEvent:role is registered in GA4. If missing, returns a
    clear configuration notice without failing or crashing the dashboard.
    """
    property_id, creds_info, err = get_ga4_config()
    ga4_start, ga4_end, label = resolve_date_range(range, start_date, end_date)
    cache_key = f"roles:{property_id}:{ga4_start}:{ga4_end}"

    if not refresh:
        cached = ga4_cache.get(cache_key)
        if cached:
            return cached

    if not creds_info:
        return {
            "success": True,
            "configured": False,
            "range": range,
            "date_range_label": label,
            "role_dimension_available": False,
            "warning": "GA4 credentials not configured in environment.",
            "message": "GA4 credentials not configured.",
            "employer_dedicated_metrics": {
                "employer_reg_start_users": 0,
                "employer_reg_complete_users": 0,
                "employer_login_users": 0,
                "employer_conversion_rate": 0.0
            },
            "role_breakdown": []
        }

    # Attempt to query customEvent:role
    report_roles = execute_ga4_report(
        property_id=property_id,
        creds_info=creds_info,
        dimensions=[{"name": "eventName"}, {"name": "customEvent:role"}],
        metrics=[{"name": "eventCount"}, {"name": "totalUsers"}],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}],
        limit=50
    )

    role_dimension_available = "error" not in report_roles

    # Check dedicated employer events as ground truth proxy
    report_employer_events = execute_ga4_report(
        property_id=property_id,
        creds_info=creds_info,
        dimensions=[{"name": "eventName"}],
        metrics=[{"name": "eventCount"}, {"name": "totalUsers"}],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}],
        dimension_filter={
            "filter": {
                "fieldName": "eventName",
                "inListFilter": {
                    "values": ["employer_reg_start", "employer_reg_complete", "employer_login"],
                    "caseSensitive": True
                }
            }
        }
    )

    employer_proxy = {
        "employer_reg_start_users": 0,
        "employer_reg_complete_users": 0,
        "employer_login_users": 0,
        "employer_conversion_rate": 0.0
    }

    if "rows" in report_employer_events:
        for r in report_employer_events["rows"]:
            ev = r["dimensionValues"][0].get("value", "")
            u = int(r["metricValues"][1].get("value", 0))
            if ev == "employer_reg_start":
                employer_proxy["employer_reg_start_users"] = u
            elif ev == "employer_reg_complete":
                employer_proxy["employer_reg_complete_users"] = u
            elif ev == "employer_login":
                employer_proxy["employer_login_users"] = u

        if employer_proxy["employer_reg_start_users"] > 0:
            employer_proxy["employer_conversion_rate"] = round(
                (employer_proxy["employer_reg_complete_users"] / employer_proxy["employer_reg_start_users"]) * 100, 2
            )

    result = {
        "success": True,
        "configured": True,
        "range": range,
        "date_range_label": label,
        "role_dimension_available": role_dimension_available,
        "warning": None if role_dimension_available else (
            "Custom dimension 'role' (customEvent:role) is not yet registered in the GA4 Admin UI. "
            "To enable role segmentation, navigate to Admin -> Custom definitions -> Create custom dimension "
            "(Dimension name: 'Role', Scope: 'Event', Event parameter: 'role')."
        ),
        "employer_dedicated_metrics": employer_proxy,
        "role_breakdown": report_roles.get("rows", []) if role_dimension_available else []
    }
    ga4_cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# 5. ORGANIC TRAFFIC & ACQUISITION SOURCES ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/organic")
def get_ga4_organic(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    refresh: bool = False,
    admin=Depends(require_admin)
):
    """
    Retrieves Google Organic Search traffic, engagement, daily trends,
    and granular traffic source/medium breakdown (e.g. google / organic,
    google_jobs_apply / organic, chatgpt.com / ai-assistant).
    """
    property_id, creds_info, err = get_ga4_config()
    ga4_start, ga4_end, label = resolve_date_range(range, start_date, end_date)
    cache_key = f"organic:{property_id}:{ga4_start}:{ga4_end}"

    if not refresh:
        cached = ga4_cache.get(cache_key)
        if cached:
            return cached

    if not creds_info:
        return {
            "success": True,
            "configured": False,
            "range": range,
            "date_range_label": label,
            "message": "GA4 credentials not configured.",
            "organic_summary": {},
            "sources": [],
            "daily_trends": []
        }

    # Query 1: Sources Breakdown (Top 10)
    report_sources = execute_ga4_report(
        property_id=property_id,
        creds_info=creds_info,
        dimensions=[{"name": "sessionSourceMedium"}],
        metrics=[
            {"name": "totalUsers"},
            {"name": "sessions"},
            {"name": "engagedSessions"},
            {"name": "conversions"}
        ],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}],
        order_bys=[{"metric": {"metricName": "sessions"}, "desc": True}],
        limit=15
    )

    # Query 2: Daily Organic Search Trends
    report_daily = execute_ga4_report(
        property_id=property_id,
        creds_info=creds_info,
        dimensions=[{"name": "date"}],
        metrics=[
            {"name": "totalUsers"},
            {"name": "sessions"},
            {"name": "engagedSessions"}
        ],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}],
        dimension_filter={
            "filter": {
                "fieldName": "sessionDefaultChannelGroup",
                "stringFilter": {"matchType": "EXACT", "value": "Organic Search", "caseSensitive": False}
            }
        },
        order_bys=[{"dimension": {"dimensionName": "date"}, "desc": False}],
        limit=100
    )

    sources_list = []
    organic_users_total = 0
    organic_sessions_total = 0
    organic_engaged_total = 0

    if "rows" in report_sources:
        for r in report_sources["rows"]:
            src = r["dimensionValues"][0].get("value", "")
            u = int(r["metricValues"][0].get("value", 0))
            s = int(r["metricValues"][1].get("value", 0))
            eng = int(r["metricValues"][2].get("value", 0))
            conv = float(r["metricValues"][3].get("value", 0.0))
            eng_rate = round((eng / s * 100), 2) if s > 0 else 0.0

            sources_list.append({
                "source_medium": src,
                "users": u,
                "sessions": s,
                "engaged_sessions": eng,
                "engagement_rate": eng_rate,
                "conversions": conv
            })

            if "organic" in src.lower():
                organic_users_total += u
                organic_sessions_total += s
                organic_engaged_total += eng

    daily_trends = []
    if "rows" in report_daily:
        for r in report_daily["rows"]:
            d_raw = r["dimensionValues"][0].get("value", "")  # YYYYMMDD
            try:
                formatted_d = f"{d_raw[:4]}-{d_raw[4:6]}-{d_raw[6:]}"
            except Exception:
                formatted_d = d_raw
            u = int(r["metricValues"][0].get("value", 0))
            s = int(r["metricValues"][1].get("value", 0))
            eng = int(r["metricValues"][2].get("value", 0))
            daily_trends.append({
                "date": formatted_d,
                "users": u,
                "sessions": s,
                "engaged_sessions": eng
            })

    result = {
        "success": True,
        "configured": True,
        "range": range,
        "date_range_label": label,
        "reporting_timezone": "Asia/Kolkata",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "organic_summary": {
            "organic_users": organic_users_total,
            "organic_sessions": organic_sessions_total,
            "organic_engaged_sessions": organic_engaged_total,
            "organic_engagement_rate": round((organic_engaged_total / organic_sessions_total * 100), 2) if organic_sessions_total > 0 else 0.0
        },
        "sources": sources_list,
        "daily_trends": daily_trends
    }
    ga4_cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# 6. TOP LANDING PAGES PERFORMANCE ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/landing-pages")
def get_ga4_landing_pages(
    range: str = Query("30d", pattern="^(today|7d|30d|90d|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(20, ge=5, le=50),
    refresh: bool = False,
    admin=Depends(require_admin)
):
    """
    Returns Top landing pages ranked by sessions with total users,
    engaged sessions, and key event conversions (sign_up) where attribution applies.
    """
    property_id, creds_info, err = get_ga4_config()
    ga4_start, ga4_end, label = resolve_date_range(range, start_date, end_date)
    cache_key = f"landing_pages:{property_id}:{ga4_start}:{ga4_end}:{limit}"

    if not refresh:
        cached = ga4_cache.get(cache_key)
        if cached:
            return cached

    if not creds_info:
        return {
            "success": True,
            "configured": False,
            "range": range,
            "date_range_label": label,
            "reporting_timezone": "Asia/Kolkata",
            "message": "GA4 credentials not configured.",
            "attribution_notes": (
                "Conversions represent GA4 key events (sign_up) attributed to the session's first landing page."
            ),
            "total_landing_pages_shown": 0,
            "landing_pages": []
        }

    report_pages = execute_ga4_report(
        property_id=property_id,
        creds_info=creds_info,
        dimensions=[{"name": "landingPagePlusQueryString"}],
        metrics=[
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "engagedSessions"},
            {"name": "conversions"}
        ],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}],
        order_bys=[{"metric": {"metricName": "sessions"}, "desc": True}],
        limit=limit
    )

    pages_list = []
    if "rows" in report_pages:
        for r in report_pages["rows"]:
            page_path = r["dimensionValues"][0].get("value", "")
            s = int(r["metricValues"][0].get("value", 0))
            u = int(r["metricValues"][1].get("value", 0))
            eng = int(r["metricValues"][2].get("value", 0))
            conv = float(r["metricValues"][3].get("value", 0.0))
            eng_rate = round((eng / s * 100), 2) if s > 0 else 0.0

            # Determine page type
            page_type = "other"
            if page_path == "/":
                page_type = "homepage"
            elif page_path.startswith("/jobs/"):
                page_type = "job_detail"
            elif page_path == "/jobs":
                page_type = "jobs_directory"
            elif page_path.startswith("/admin"):
                page_type = "admin"

            pages_list.append({
                "landing_page": page_path,
                "page_type": page_type,
                "sessions": s,
                "users": u,
                "engaged_sessions": eng,
                "engagement_rate": eng_rate,
                "conversions": int(conv)
            })

    result = {
        "success": True,
        "configured": True,
        "range": range,
        "date_range_label": label,
        "reporting_timezone": "Asia/Kolkata",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "attribution_notes": (
            "Conversions represent GA4 key events (sign_up) attributed to the session's first landing page. "
            "Programmatic job landing pages (/jobs/<slug>) directly acquire search users who convert."
        ),
        "total_landing_pages_shown": len(pages_list),
        "landing_pages": pages_list
    }
    ga4_cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# 7. GROWTH TRENDS ENDPOINT (DAILY / WEEKLY / MONTHLY)
# ---------------------------------------------------------------------------
@router.get("/trends")
def get_ga4_trends(
    granularity: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    range: str = Query("30d", pattern="^(today|7d|30d|90d|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    refresh: bool = False,
    admin=Depends(require_admin)
):
    """
    Returns time series of GA4 metrics (Total Users, Sessions, Engaged Sessions,
    Signups) grouped by daily, weekly, or monthly periods in Asia/Kolkata timezone.
    """
    property_id, creds_info, err = get_ga4_config()
    ga4_start, ga4_end, label = resolve_date_range(range, start_date, end_date)
    cache_key = f"trends:{property_id}:{granularity}:{ga4_start}:{ga4_end}"

    if not refresh:
        cached = ga4_cache.get(cache_key)
        if cached:
            return cached

    if not creds_info:
        return {
            "success": True,
            "configured": False,
            "granularity": granularity,
            "range": range,
            "date_range_label": label,
            "message": "GA4 credentials not configured.",
            "trends": []
        }

    # Dimension selection based on granularity
    dim_name = "date"
    if granularity == "weekly":
        dim_name = "yearWeek"
    elif granularity == "monthly":
        dim_name = "yearMonth"

    report_trends = execute_ga4_report(
        property_id=property_id,
        creds_info=creds_info,
        dimensions=[{"name": dim_name}],
        metrics=[
            {"name": "totalUsers"},
            {"name": "newUsers"},
            {"name": "sessions"},
            {"name": "engagedSessions"},
            {"name": "conversions"}
        ],
        date_ranges=[{"startDate": ga4_start, "endDate": ga4_end}],
        order_bys=[{"dimension": {"dimensionName": dim_name}, "desc": False}],
        limit=100
    )

    trends_data = []
    if "rows" in report_trends:
        for r in report_trends["rows"]:
            raw_period = r["dimensionValues"][0].get("value", "")
            formatted_period = raw_period
            if granularity == "daily" and len(raw_period) == 8:
                formatted_period = f"{raw_period[:4]}-{raw_period[4:6]}-{raw_period[6:]}"
            elif granularity == "monthly" and len(raw_period) == 6:
                formatted_period = f"{raw_period[:4]}-{raw_period[4:]}"

            u = int(r["metricValues"][0].get("value", 0))
            nu = int(r["metricValues"][1].get("value", 0))
            s = int(r["metricValues"][2].get("value", 0))
            eng = int(r["metricValues"][3].get("value", 0))
            conv = int(float(r["metricValues"][4].get("value", 0.0)))

            trends_data.append({
                "period": formatted_period,
                "total_users": u,
                "new_users": nu,
                "sessions": s,
                "engaged_sessions": eng,
                "sign_ups": conv
            })

    result = {
        "success": True,
        "configured": True,
        "granularity": granularity,
        "range": range,
        "date_range_label": label,
        "reporting_timezone": "Asia/Kolkata",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_data_points": len(trends_data),
        "trends": trends_data
    }
    ga4_cache.set(cache_key, result)
    return result
