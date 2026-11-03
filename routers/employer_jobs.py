import os
import re
import uuid
import datetime
import logging
import psycopg2
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Form, File, UploadFile, Query, Body
from pydantic import BaseModel, Field

from routers.public_auth import require_employer_user
from routers.admin_jobs import slugify
from services.extractor import StructuredJobExtractor

logger = logging.getLogger("DigiGarment.EmployerJobs")

router = APIRouter(prefix="/api/employer", tags=["Employer Jobs & Applications"])

# Database helpers injected from app.py
_query_db = None
_execute_db = None
_execute_db_returning = None
_db_enabled = False
_base_dir = ""
_db_pool = None


def _ensure_employer_portal_schema() -> None:
    """
    Idempotently initializes the additive Employer Portal tables and columns.
    Preserves all existing production tables, records, sequences, and foreign keys.
    """
    if not _db_enabled or not _execute_db:
        return
    try:
        # 1. Employer Job Metadata (for atomic per-job tracking)
        _execute_db("""
            CREATE TABLE IF NOT EXISTS employer_jobs_meta (
                id SERIAL PRIMARY KEY,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                employer_user_id INTEGER NOT NULL,
                company_profile_id INTEGER,
                submission_mode VARCHAR(32) NOT NULL DEFAULT 'single',
                client_request_id VARCHAR(100),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (job_id)
            );
        """)

        # 2. Job Status History (audit trail for publish, edit, repost, archive)
        _execute_db("""
            CREATE TABLE IF NOT EXISTS job_status_history (
                id SERIAL PRIMARY KEY,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                previous_status VARCHAR(50),
                new_status VARCHAR(50) NOT NULL,
                changed_by_user_id INTEGER,
                notes TEXT,
                changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 3. Bulk Job Idempotency Tracking (prevents duplicate creation on retry / concurrent requests)
        _execute_db("""
            CREATE TABLE IF NOT EXISTS employer_bulk_idempotency (
                user_id INTEGER NOT NULL,
                client_request_id VARCHAR(100) NOT NULL,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                slug VARCHAR(255) NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'published',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, client_request_id)
            );
        """)

        # 4. Event-Driven Employer Notifications (strictly user-scoped & deduplicated)
        _execute_db("""
            CREATE TABLE IF NOT EXISTS employer_notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES public_users(id) ON DELETE CASCADE,
                job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
                application_id INTEGER REFERENCES job_applications(id) ON DELETE SET NULL,
                event_type VARCHAR(64) NOT NULL,
                event_key VARCHAR(180) NOT NULL,
                title VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                target_url VARCHAR(255) NOT NULL DEFAULT '/dashboard/company',
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, event_key)
            );
        """)
        _execute_db("""
            CREATE INDEX IF NOT EXISTS idx_employer_notif_user_unread
            ON employer_notifications (user_id, is_read, created_at DESC);
        """)

        # 5. Non-intrusive Employer Viewed Timestamp on job_applications
        _execute_db("""
            ALTER TABLE job_applications
            ADD COLUMN IF NOT EXISTS employer_viewed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL;
        """)
    except Exception as e:
        logger.warning(f"Employer Portal schema initialization warning: {e}")


def init_employer_jobs_helpers(db_enabled_val, query_fn, exec_fn, exec_ret_fn, base_dir_path, db_pool_val=None):
    global _db_enabled, _query_db, _execute_db, _execute_db_returning, _base_dir, _db_pool
    _db_enabled = db_enabled_val
    _query_db = query_fn
    _execute_db = exec_fn
    _execute_db_returning = exec_ret_fn
    _base_dir = base_dir_path
    _db_pool = db_pool_val
    _ensure_employer_portal_schema()


def _clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() != "none" else None


def _clean_num(val: Any, default: Any = None) -> Optional[float]:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _verify_employer_ownership(record: Dict[str, Any], user_id: int, profile_id: Optional[int]) -> None:
    """
    Centralized server-side ownership check.
    Ensures Employer A can never access, edit, archive, repost, or view applications of Employer B.
    """
    rec_user_id = record.get("employer_user_id")
    rec_profile_id = record.get("company_profile_id")
    owns_by_user = (rec_user_id is not None and int(rec_user_id) == int(user_id))
    owns_by_profile = (profile_id is not None and rec_profile_id is not None and int(rec_profile_id) == int(profile_id))
    if not (owns_by_user or owns_by_profile):
        raise HTTPException(status_code=403, detail="Access denied. You do not own this resource.")


# --- Failure-Isolated Notification Helpers ---

def create_employer_notification_safe(
    user_id: Optional[int],
    event_type: str,
    event_key: str,
    title: str,
    message: str,
    target_url: str = "/dashboard/company",
    job_id: Optional[int] = None,
    application_id: Optional[int] = None
) -> None:
    """
    Idempotently records an employer notification scoped strictly to user_id.
    Uses ON CONFLICT (user_id, event_key) DO NOTHING to guarantee zero duplicates.
    Wrapped in try/except so notification errors NEVER fail job publishing or candidate applications.
    """
    if not user_id or not _db_enabled or not _execute_db:
        return
    try:
        _execute_db("""
            INSERT INTO employer_notifications (
                user_id, job_id, application_id, event_type, event_key,
                title, message, target_url, is_read, created_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, FALSE, CURRENT_TIMESTAMP
            )
            ON CONFLICT (user_id, event_key) DO NOTHING;
        """, (
            int(user_id),
            job_id,
            application_id,
            event_type[:64],
            event_key[:180],
            title[:255],
            message,
            target_url[:255]
        ))
    except Exception as e:
        logger.warning(f"Non-blocking notification creation skipped ({event_key}): {e}")


def _sync_employer_state_notifications(user_id: int, profile_id: Optional[int], profile: Dict[str, Any]) -> None:
    """
    On-demand, idempotent synchronization of verification status and job expiry notifications
    when the authenticated employer accesses the dashboard or notification API.
    Zero cron jobs or background threads; ON CONFLICT (user_id, event_key) DO NOTHING prevents duplicates.
    """
    if not user_id or not _db_enabled or not _query_db:
        return
    try:
        # 1. Company verification status notification
        verif_status = (profile.get("verification_status") or "pending").strip().lower()
        comp_name = (profile.get("company_name") or "Your company").strip()
        if verif_status == "verified":
            create_employer_notification_safe(
                user_id=user_id,
                event_type="company_verified",
                event_key=f"company_verified:{profile_id or user_id}",
                title="Company Verification Completed",
                message=f"Congratulations! {comp_name} is now a Verified Employer on DigiGarment.",
                target_url="/employer/profile"
            )
        elif verif_status in ("under_review", "rejected", "unverified"):
            create_employer_notification_safe(
                user_id=user_id,
                event_type="company_verification_updated",
                event_key=f"company_verif_status:{profile_id or user_id}:{verif_status}",
                title="Company Verification Status Updated",
                message=f"Your company verification status is currently '{verif_status.replace('_', ' ').title()}'.",
                target_url="/employer/profile"
            )

        # 2. Expiring Soon (within 5 days) & Expired jobs owned by this employer
        job_rows = _query_db("""
            SELECT
                j.id,
                j.title,
                LOWER(COALESCE(j.status, '')) AS status,
                j.expires_at,
                TO_CHAR(COALESCE(j.published_at, j.created_at, CURRENT_TIMESTAMP), 'YYYY-MM-DD') AS pub_cycle,
                (j.expires_at IS NOT NULL AND j.expires_at < CURRENT_TIMESTAMP) AS is_past_expiry,
                (
                    j.expires_at IS NOT NULL
                    AND j.expires_at >= CURRENT_TIMESTAMP
                    AND j.expires_at <= (CURRENT_TIMESTAMP + INTERVAL '5 days')
                ) AS is_expiring_soon
            FROM jobs j
            WHERE (j.employer_user_id = %s OR (%s IS NOT NULL AND j.company_profile_id = %s))
              AND COALESCE(j.is_archived, FALSE) = FALSE
              AND LOWER(COALESCE(j.status, '')) != 'archived';
        """, (user_id, profile_id, profile_id))

        for jr in (job_rows or []):
            jid = jr["id"]
            jtitle = jr.get("title") or f"Job #{jid}"
            pub_cycle = jr.get("pub_cycle") or "v1"
            st = jr.get("status") or ""

            if st == "expired" or (st == "published" and jr.get("is_past_expiry")):
                create_employer_notification_safe(
                    user_id=user_id,
                    event_type="job_expired",
                    event_key=f"job_expired:{jid}:{pub_cycle}",
                    title="Job Posting Expired",
                    message=f"Your job posting '{jtitle}' has expired. You can repost it anytime from your dashboard.",
                    target_url=f"/dashboard/company?highlight_job={jid}",
                    job_id=jid
                )
            elif st == "published" and jr.get("is_expiring_soon"):
                create_employer_notification_safe(
                    user_id=user_id,
                    event_type="job_expiring_soon",
                    event_key=f"job_expiring_soon:{jid}:{pub_cycle}",
                    title="Job Posting Expiring Soon",
                    message=f"Your job posting '{jtitle}' is expiring within 5 days.",
                    target_url=f"/dashboard/company?highlight_job={jid}",
                    job_id=jid
                )
    except Exception as e:
        logger.warning(f"Non-blocking state notification sync warning: {e}")


# --- Pydantic Models for Employer Job Actions ---

class EmployerJobCreateRequest(BaseModel):
    title: str
    department: str
    job_role: Optional[str] = None
    job_type: Optional[str] = "Full Time"
    workplace_type: Optional[str] = "On-site / Factory"
    experience_level: Optional[str] = None
    experience_min: Optional[int] = 0
    experience_max: Optional[int] = None
    openings_count: Optional[int] = 1
    vacancies: Optional[int] = None
    location: Optional[str] = None
    location_area: Optional[str] = None
    location_city: Optional[str] = None
    pin_code: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_period: Optional[str] = "month"
    salary_text: Optional[str] = None
    description: str
    requirements: Optional[str] = None
    skills: Optional[Any] = None
    qualification: Optional[str] = None
    gender: Optional[str] = "Any"
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_whatsapp: Optional[str] = None
    contact_email: Optional[str] = None
    poster_image_url: Optional[str] = None
    status: Optional[str] = "published"  # 'draft' or direct 'published'
    client_request_id: Optional[str] = None


class BulkEmployerJobsCreateRequest(BaseModel):
    jobs: List[EmployerJobCreateRequest]


class EmployerJobUpdateRequest(BaseModel):
    title: str
    department: str
    job_role: Optional[str] = None
    job_type: Optional[str] = "Full Time"
    workplace_type: Optional[str] = "On-site / Factory"
    experience_level: Optional[str] = None
    experience_min: Optional[int] = 0
    experience_max: Optional[int] = None
    openings_count: Optional[int] = 1
    vacancies: Optional[int] = None
    location: Optional[str] = None
    location_area: Optional[str] = None
    location_city: Optional[str] = None
    pin_code: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_period: Optional[str] = "month"
    salary_text: Optional[str] = None
    description: str
    requirements: Optional[str] = None
    skills: Optional[Any] = None
    qualification: Optional[str] = None
    gender: Optional[str] = "Any"
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_whatsapp: Optional[str] = None
    contact_email: Optional[str] = None
    poster_image_url: Optional[str] = None
    status: Optional[str] = None  # 'draft' or 'published'


class NotificationReadRequest(BaseModel):
    notification_id: Optional[int] = None
    mark_all: Optional[bool] = False


# --- 1. List Employer's Own Jobs & Dashboard Statistics ---
@router.get("/jobs")
def get_employer_jobs(current_user: Dict[str, Any] = Depends(require_employer_user)):
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        return {
            "success": True,
            "jobs": [],
            "total": 0,
            "stats": {
                "total_jobs_posted": 0,
                "active_jobs": 0,
                "expired_jobs": 0,
                "draft_jobs": 0,
                "archived_jobs_count": 0,
                "total_applications_received": 0,
                "unread_applications": 0,
                "jobs_requiring_attention": 0
            },
            "employer_verification_status": profile.get("verification_status", "pending")
        }

    try:
        # Single aggregated query for non-archived employer jobs + application counts (avoids N+1 queries)
        query = """
            SELECT 
                j.id, j.title, j.slug, j.department, j.job_role, j.job_type,
                j.location, j.openings_count, j.experience_min, j.experience_max,
                j.salary_min, j.salary_max, j.salary_text, j.description, j.requirements,
                j.skills, j.qualification, j.gender, j.contact_phone, j.contact_whatsapp,
                j.contact_email, j.poster_image_url, j.status, j.rejection_reason,
                j.is_archived, j.published_at, j.expires_at, j.created_at, j.updated_at,
                (j.expires_at IS NOT NULL AND j.expires_at < CURRENT_TIMESTAMP) AS is_past_expiry,
                COALESCE(app_agg.applications_count, 0) AS applications_count,
                COALESCE(app_agg.unread_applications_count, 0) AS unread_applications_count,
                COALESCE(cp.company_name, '') AS company_name,
                COALESCE(cp.verification_status, 'pending') AS employer_verification_status
            FROM jobs j
            LEFT JOIN company_profiles cp ON j.company_profile_id = cp.id
            LEFT JOIN (
                SELECT
                    job_id,
                    COUNT(*) AS applications_count,
                    COUNT(*) FILTER (
                        WHERE employer_viewed_at IS NULL
                          AND LOWER(COALESCE(status, 'submitted')) IN ('submitted', 'applied')
                    ) AS unread_applications_count
                FROM job_applications
                GROUP BY job_id
            ) app_agg ON j.id = app_agg.job_id
            WHERE (j.employer_user_id = %s OR (%s IS NOT NULL AND j.company_profile_id = %s))
              AND COALESCE(j.is_archived, FALSE) = FALSE
              AND LOWER(COALESCE(j.status, '')) != 'archived'
            ORDER BY j.id DESC;
        """
        rows = _query_db(query, (user_id, profile_id, profile_id)) or []

        # Preserve historical total applications count across all jobs owned by the employer (including archived)
        hist_rows = _query_db("""
            SELECT
                COUNT(DISTINCT j.id) FILTER (
                    WHERE COALESCE(j.is_archived, FALSE) = TRUE OR LOWER(COALESCE(j.status, '')) = 'archived'
                ) AS archived_jobs_count,
                COUNT(a.id) AS total_historical_applications
            FROM jobs j
            LEFT JOIN job_applications a ON j.id = a.job_id
            WHERE (j.employer_user_id = %s OR (%s IS NOT NULL AND j.company_profile_id = %s));
        """, (user_id, profile_id, profile_id))
        hist_info = hist_rows[0] if hist_rows else {}

        active_count = 0
        expired_count = 0
        draft_count = 0
        unread_apps_total = 0
        attention_jobs_count = 0
        visible_apps_sum = 0

        for r in rows:
            raw_status = (r.get("status") or "draft").lower()
            is_past_exp = bool(r.get("is_past_expiry"))
            apps_cnt = int(r.get("applications_count") or 0)
            unread_cnt = int(r.get("unread_applications_count") or 0)

            if raw_status == "expired" or (raw_status == "published" and is_past_exp):
                eff_status = "expired"
                expired_count += 1
            elif raw_status == "draft":
                eff_status = "draft"
                draft_count += 1
            elif raw_status == "closed":
                eff_status = "closed"
            elif raw_status == "published":
                eff_status = "active"
                active_count += 1
            else:
                eff_status = raw_status

            r["effective_status"] = eff_status
            r["applications_count"] = apps_cnt
            r["unread_applications_count"] = unread_cnt
            r["has_applications"] = apps_cnt > 0
            r["has_unread_applications"] = unread_cnt > 0

            visible_apps_sum += apps_cnt
            unread_apps_total += unread_cnt
            if eff_status in ("draft", "expired") or unread_cnt > 0:
                attention_jobs_count += 1

        total_apps_received = max(int(hist_info.get("total_historical_applications") or 0), visible_apps_sum)

        stats = {
            "total_jobs_posted": len(rows),
            "active_jobs": active_count,
            "expired_jobs": expired_count,
            "draft_jobs": draft_count,
            "archived_jobs_count": int(hist_info.get("archived_jobs_count") or 0),
            "total_applications_received": total_apps_received,
            "unread_applications": unread_apps_total,
            "jobs_requiring_attention": attention_jobs_count
        }

        return {
            "success": True,
            "jobs": rows,
            "total": len(rows),
            "stats": stats,
            "employer_verification_status": profile.get("verification_status", "pending")
        }
    except Exception as e:
        logger.error(f"Error fetching employer jobs: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- Internal Atomic Single-Job Creation Helper (Used by Both Single & Bulk Posting) ---

def _create_single_employer_job_atomic(
    req: EmployerJobCreateRequest,
    current_user: Dict[str, Any],
    submission_mode: str = "single"
) -> Dict[str, Any]:
    """
    Executes the 5-step job creation pipeline inside a single atomic PostgreSQL transaction:
      1. Unique SEO slug generation (via existing slugify)
      2. Job record creation (INSERT INTO jobs)
      3. Employer job metadata creation (INSERT INTO employer_jobs_meta)
      4. Job status history creation (INSERT INTO job_status_history)
      5. Idempotency record creation (INSERT INTO employer_bulk_idempotency)
    Includes transaction-scoped advisory lock + UniqueViolation fallback so concurrent
    or retried requests with the same client_request_id never create duplicate jobs.
    """
    user_id = int(current_user["id"])
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not profile_id:
        raise HTTPException(status_code=400, detail="Company profile required before posting a job.")

    t_clean = (req.title or "").strip()
    d_clean = (req.department or "").strip()
    r_clean = (req.job_role or "").strip()
    desc_clean = (req.description or "").strip()

    # Location handling
    loc_clean = (req.location or req.location_area or "").strip()
    if req.location_city and req.location_city.strip() not in loc_clean:
        loc_clean = f"{loc_clean}, {req.location_city.strip()}".strip(", ")
    if not loc_clean:
        loc_clean = profile.get("location") or profile.get("area") or "Tiruppur"

    # Skills handling (accept list or string)
    skills_str = None
    if isinstance(req.skills, list):
        skills_str = ", ".join(str(s) for s in req.skills if s)
    elif req.skills:
        skills_str = str(req.skills).strip()

    if not r_clean:
        r_clean = t_clean

    if not t_clean:
        raise HTTPException(status_code=400, detail="Job Title is required.")
    if not d_clean:
        raise HTTPException(status_code=400, detail="Department is required.")
    if not desc_clean:
        raise HTTPException(status_code=400, detail="Job Description is required.")

    target_status = (req.status or "").strip().lower()
    if target_status != "draft":
        target_status = "published"

    phone_clean = _clean_str(req.contact_phone) or profile.get("mobile")
    wa_clean = _clean_str(req.contact_whatsapp) or profile.get("whatsapp") or profile.get("mobile")
    email_clean = _clean_str(req.contact_email) or profile.get("email") or current_user.get("email")
    openings_cnt = max(int(req.vacancies or req.openings_count or 1), 1)
    verif_status = profile.get("verification_status", "pending")
    client_req_id = _clean_str(req.client_request_id)
    if client_req_id:
        client_req_id = client_req_id[:100]

    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    # Step 1: Unique SEO slug using existing slugify
    base_slug = slugify(t_clean) or "job"
    slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    # Execute all 5 steps inside a single atomic connection transaction
    if _db_pool is not None:
        conn = None
        is_broken = False
        try:
            conn = _db_pool.getconn()
            conn.autocommit = False
            cur = conn.cursor()

            # Concurrent Idempotency Lock & Check (when client_request_id is supplied)
            if client_req_id:
                cur.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s));", (user_id, client_req_id))
                cur.execute(
                    "SELECT job_id, slug, status FROM employer_bulk_idempotency WHERE user_id = %s AND client_request_id = %s;",
                    (user_id, client_req_id)
                )
                existing_row = cur.fetchone()
                if existing_row:
                    conn.commit()
                    cur.close()
                    ex_job_id, ex_slug, ex_status = existing_row[0], existing_row[1], existing_row[2]
                    return {
                        "success": True,
                        "job_id": ex_job_id,
                        "slug": ex_slug,
                        "status": ex_status,
                        "title": t_clean,
                        "idempotent_replay": True,
                        "job": {"id": ex_job_id, "slug": ex_slug, "status": ex_status, "title": t_clean},
                        "message": "Job already published (idempotent replay)."
                    }

            # Step 2: Insert Job Record
            cur.execute("""
                INSERT INTO jobs (
                    company_profile_id, employer_user_id, title, slug, department, job_role,
                    job_type, location, openings_count, experience_min, experience_max,
                    salary_min, salary_max, salary_text, description, requirements,
                    skills, qualification, gender, contact_phone, contact_whatsapp,
                    contact_email, poster_image_url, source_type, source_name,
                    status, is_featured, is_archived, verification_status,
                    published_at, expires_at, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, 'employer', 'Employer Direct Posting',
                    %s, FALSE, FALSE, %s,
                    CASE WHEN %s = 'published' THEN CURRENT_TIMESTAMP ELSE NULL END,
                    CASE WHEN %s = 'published' THEN CURRENT_TIMESTAMP + INTERVAL '30 days' ELSE NULL END,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                ) RETURNING id, slug, status;
            """, (
                profile_id, user_id, t_clean, slug, d_clean, r_clean,
                req.job_type or "Full Time", loc_clean, openings_cnt,
                int(req.experience_min or 0), _clean_num(req.experience_max),
                _clean_num(req.salary_min), _clean_num(req.salary_max), _clean_str(req.salary_text),
                desc_clean, _clean_str(req.requirements),
                skills_str, _clean_str(req.qualification), _clean_str(req.gender) or "Any",
                phone_clean, wa_clean, email_clean, _clean_str(req.poster_image_url),
                target_status, verif_status, target_status, target_status
            ))
            inserted_job = cur.fetchone()
            job_id = inserted_job[0]
            final_slug = inserted_job[1]
            final_status = inserted_job[2]

            effective_req_id = client_req_id or f"single_{job_id}_{uuid.uuid4().hex[:8]}"

            # Step 3: Insert Employer Job Metadata
            cur.execute("""
                INSERT INTO employer_jobs_meta (
                    job_id, employer_user_id, company_profile_id, submission_mode, client_request_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
            """, (job_id, user_id, profile_id, submission_mode, effective_req_id))

            # Step 4: Insert Job Status History
            cur.execute("""
                INSERT INTO job_status_history (
                    job_id, previous_status, new_status, changed_by_user_id, notes, changed_at
                ) VALUES (%s, NULL, %s, %s, %s, CURRENT_TIMESTAMP);
            """, (job_id, final_status, user_id, f"Created via {submission_mode} job posting"))

            # Step 5: Insert Idempotency Record
            cur.execute("""
                INSERT INTO employer_bulk_idempotency (
                    user_id, client_request_id, job_id, slug, status, created_at
                ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
            """, (user_id, effective_req_id, job_id, final_slug, final_status))

            # Commit all 5 steps atomically
            conn.commit()
            cur.close()
        except psycopg2.IntegrityError as ie:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            # Handle race condition on (user_id, client_request_id) unique constraint
            if client_req_id and _query_db:
                idem_rows = _query_db(
                    "SELECT job_id, slug, status FROM employer_bulk_idempotency WHERE user_id = %s AND client_request_id = %s;",
                    (user_id, client_req_id)
                )
                if idem_rows:
                    ir = idem_rows[0]
                    return {
                        "success": True,
                        "job_id": ir["job_id"],
                        "slug": ir["slug"],
                        "status": ir["status"],
                        "title": t_clean,
                        "idempotent_replay": True,
                        "job": {"id": ir["job_id"], "slug": ir["slug"], "status": ir["status"], "title": t_clean},
                        "message": "Job already published (idempotent replay)."
                    }
            logger.error(f"Database integrity error creating employer job: {ie}")
            raise HTTPException(status_code=500, detail="Could not save job due to a database constraint conflict.")
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as oe:
            is_broken = True
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Database connection error creating employer job: {oe}")
            raise HTTPException(status_code=503, detail="Database connection error. Please try again.")
        except HTTPException:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Error in atomic job creation: {e}")
            raise HTTPException(status_code=500, detail="Something went wrong while creating the job.")
        finally:
            if conn:
                _db_pool.putconn(conn, close=is_broken)
    else:
        # Fallback single-query atomic CTE if _db_pool is not directly injected
        effective_req_id = client_req_id or f"single_{uuid.uuid4().hex[:12]}"
        if client_req_id and _query_db:
            idem_rows = _query_db(
                "SELECT job_id, slug, status FROM employer_bulk_idempotency WHERE user_id = %s AND client_request_id = %s;",
                (user_id, client_req_id)
            )
            if idem_rows:
                ir = idem_rows[0]
                return {
                    "success": True,
                    "job_id": ir["job_id"],
                    "slug": ir["slug"],
                    "status": ir["status"],
                    "title": t_clean,
                    "idempotent_replay": True,
                    "job": {"id": ir["job_id"], "slug": ir["slug"], "status": ir["status"], "title": t_clean},
                    "message": "Job already published (idempotent replay)."
                }

        cte_query = """
            WITH ins_job AS (
                INSERT INTO jobs (
                    company_profile_id, employer_user_id, title, slug, department, job_role,
                    job_type, location, openings_count, experience_min, experience_max,
                    salary_min, salary_max, salary_text, description, requirements,
                    skills, qualification, gender, contact_phone, contact_whatsapp,
                    contact_email, poster_image_url, source_type, source_name,
                    status, is_featured, is_archived, verification_status,
                    published_at, expires_at, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, 'employer', 'Employer Direct Posting',
                    %s, FALSE, FALSE, %s,
                    CASE WHEN %s = 'published' THEN CURRENT_TIMESTAMP ELSE NULL END,
                    CASE WHEN %s = 'published' THEN CURRENT_TIMESTAMP + INTERVAL '30 days' ELSE NULL END,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                ) RETURNING id, slug, status
            ),
            ins_meta AS (
                INSERT INTO employer_jobs_meta (job_id, employer_user_id, company_profile_id, submission_mode, client_request_id, created_at)
                SELECT id, %s, %s, %s, %s, CURRENT_TIMESTAMP FROM ins_job
            ),
            ins_hist AS (
                INSERT INTO job_status_history (job_id, previous_status, new_status, changed_by_user_id, notes, changed_at)
                SELECT id, NULL, status, %s, %s, CURRENT_TIMESTAMP FROM ins_job
            ),
            ins_idem AS (
                INSERT INTO employer_bulk_idempotency (user_id, client_request_id, job_id, slug, status, created_at)
                SELECT %s, %s, id, slug, status, CURRENT_TIMESTAMP FROM ins_job
            )
            SELECT id, slug, status FROM ins_job;
        """
        rows = _execute_db_returning(cte_query, (
            profile_id, user_id, t_clean, slug, d_clean, r_clean,
            req.job_type or "Full Time", loc_clean, openings_cnt,
            int(req.experience_min or 0), _clean_num(req.experience_max),
            _clean_num(req.salary_min), _clean_num(req.salary_max), _clean_str(req.salary_text),
            desc_clean, _clean_str(req.requirements),
            skills_str, _clean_str(req.qualification), _clean_str(req.gender) or "Any",
            phone_clean, wa_clean, email_clean, _clean_str(req.poster_image_url),
            target_status, verif_status, target_status, target_status,
            user_id, profile_id, submission_mode, effective_req_id,
            user_id, f"Created via {submission_mode} job posting",
            user_id, effective_req_id
        ))
        job_id = rows[0]["id"]
        final_slug = rows[0]["slug"]
        final_status = rows[0]["status"]

    # Post-Commit Failure-Isolated Notification
    if final_status == "published":
        create_employer_notification_safe(
            user_id=user_id,
            event_type="job_published",
            event_key=f"job_published:{job_id}",
            title="Job Published Successfully",
            message=f"Your job posting '{t_clean}' has been successfully published.",
            target_url=f"/dashboard/company?highlight_job={job_id}",
            job_id=job_id
        )

    msg = (
        "Job saved as draft." if final_status == "draft"
        else "Job published successfully! Your vacancy is now live on Tiruppur Jobs."
    )
    return {
        "success": True,
        "job_id": job_id,
        "slug": final_slug,
        "status": final_status,
        "title": t_clean,
        "idempotent_replay": False,
        "job": {
            "id": job_id,
            "slug": final_slug,
            "status": final_status,
            "title": t_clean
        },
        "message": msg
    }


# --- 2. Create New Single Job ---
@router.post("/jobs")
def create_employer_job(
    req: EmployerJobCreateRequest,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    return _create_single_employer_job_atomic(req=req, current_user=current_user, submission_mode="single")


# --- 2B. Create Multiple Jobs (Bulk Job Entry with Independent Per-Job Transactions) ---
@router.post("/jobs/bulk")
def create_employer_jobs_bulk(
    req: BulkEmployerJobsCreateRequest,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Processes multiple job postings in one session.
    Each job runs in its own independent atomic 5-step transaction and reuses
    _create_single_employer_job_atomic().
    If 8 jobs succeed and 2 fail, the 8 remain published and the 2 return individual errors.
    Retrying with the same client_request_id never creates duplicate jobs.
    """
    if not req.jobs or not isinstance(req.jobs, list):
        raise HTTPException(status_code=400, detail="Please add at least one job to submit.")
    if len(req.jobs) > 25:
        raise HTTPException(status_code=400, detail="You can submit up to 25 jobs at a time.")

    results = []
    published_count = 0
    failed_count = 0

    for idx, job_item in enumerate(req.jobs):
        raw_title = (job_item.title or "").strip() or f"Job #{idx + 1}"
        try:
            res = _create_single_employer_job_atomic(
                req=job_item,
                current_user=current_user,
                submission_mode="bulk"
            )
            published_count += 1
            results.append({
                "index": idx,
                "client_request_id": job_item.client_request_id,
                "success": True,
                "job_id": res["job_id"],
                "slug": res["slug"],
                "title": res["title"],
                "status": res["status"],
                "idempotent_replay": res.get("idempotent_replay", False),
                "message": res["message"]
            })
        except HTTPException as he:
            failed_count += 1
            results.append({
                "index": idx,
                "client_request_id": job_item.client_request_id,
                "success": False,
                "job_id": None,
                "slug": None,
                "title": raw_title,
                "status": "failed",
                "error": str(he.detail)
            })
        except Exception as e:
            logger.error(f"Error in bulk job item #{idx + 1}: {e}")
            failed_count += 1
            results.append({
                "index": idx,
                "client_request_id": job_item.client_request_id,
                "success": False,
                "job_id": None,
                "slug": None,
                "title": raw_title,
                "status": "failed",
                "error": "An unexpected error occurred while saving this job."
            })

    summary_msg = f"Successfully Published: {published_count} Job{'s' if published_count != 1 else ''}"
    if failed_count > 0:
        summary_msg += f" ({failed_count} failed — please review and retry the highlighted job form{'s' if failed_count != 1 else ''})."

    return {
        "success": published_count > 0 and failed_count == 0,
        "partial_success": published_count > 0 and failed_count > 0,
        "total_submitted": len(req.jobs),
        "published_count": published_count,
        "failed_count": failed_count,
        "results": results,
        "message": summary_msg
    }


# --- 3. Get Single Job Details (Ownership Enforced) ---
@router.get("/jobs/{job_id}")
def get_employer_job_detail(
    job_id: int,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    try:
        query = """
            SELECT 
                j.*, 
                COALESCE(cp.company_name, '') AS company_name,
                COALESCE(cp.verification_status, 'pending') AS employer_verification_status
            FROM jobs j
            LEFT JOIN company_profiles cp ON j.company_profile_id = cp.id
            WHERE j.id = %s;
        """
        rows = _query_db(query, (job_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found.")

        job = rows[0]
        _verify_employer_ownership(job, user_id, profile_id)

        return {"success": True, "job": job}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 4. Update Existing Job in Place (Active, Expired, or Draft Jobs Owned by Employer) ---
@router.put("/jobs/{job_id}")
def update_employer_job(
    job_id: int,
    req: EmployerJobUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    try:
        rows = _query_db(
            "SELECT id, title, slug, status, is_archived, company_profile_id, employer_user_id FROM jobs WHERE id = %s;",
            (job_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found.")

        job = rows[0]
        _verify_employer_ownership(job, user_id, profile_id)

        current_status = (job.get("status") or "").lower()
        if job.get("is_archived") or current_status == "archived":
            raise HTTPException(
                status_code=400,
                detail="Archived or deleted jobs cannot be edited."
            )

        t_clean = (req.title or "").strip()
        d_clean = (req.department or "").strip()
        r_clean = (req.job_role or "").strip() or t_clean
        desc_clean = (req.description or "").strip()

        loc_clean = (req.location or req.location_area or "").strip()
        if req.location_city and req.location_city.strip() not in loc_clean:
            loc_clean = f"{loc_clean}, {req.location_city.strip()}".strip(", ")
        if not loc_clean:
            loc_clean = profile.get("location") or profile.get("area") or "Tiruppur"

        skills_str = None
        if isinstance(req.skills, list):
            skills_str = ", ".join(str(s) for s in req.skills if s)
        elif req.skills:
            skills_str = str(req.skills).strip()

        if not t_clean or not d_clean or not desc_clean:
            raise HTTPException(status_code=400, detail="Title, Department, and Description are required.")

        target_status = (req.status or "").strip().lower()
        if target_status != "draft":
            target_status = "published"

        clear_rejection = (target_status == "published")

        query = """
            UPDATE jobs
            SET title = %s, department = %s, job_role = %s, job_type = %s,
                location = %s, openings_count = %s, experience_min = %s, experience_max = %s,
                salary_min = %s, salary_max = %s, salary_text = %s, description = %s,
                requirements = %s, skills = %s, qualification = %s, gender = %s,
                contact_phone = %s, contact_whatsapp = %s, contact_email = %s,
                poster_image_url = %s, status = %s,
                published_at = CASE WHEN %s = 'published' AND published_at IS NULL THEN CURRENT_TIMESTAMP ELSE published_at END,
                expires_at = CASE WHEN %s = 'published' AND expires_at IS NULL THEN CURRENT_TIMESTAMP + INTERVAL '30 days' ELSE expires_at END,
                rejection_reason = CASE WHEN %s = TRUE THEN NULL ELSE rejection_reason END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """
        _execute_db(query, (
            t_clean, d_clean, r_clean, req.job_type or "Full Time",
            loc_clean, max(int(req.vacancies or req.openings_count or 1), 1),
            int(req.experience_min or 0), _clean_num(req.experience_max),
            _clean_num(req.salary_min), _clean_num(req.salary_max), _clean_str(req.salary_text),
            desc_clean, _clean_str(req.requirements),
            skills_str, _clean_str(req.qualification), _clean_str(req.gender) or "Any",
            _clean_str(req.contact_phone) or profile.get("mobile"),
            _clean_str(req.contact_whatsapp) or profile.get("whatsapp"),
            _clean_str(req.contact_email) or profile.get("email"),
            _clean_str(req.poster_image_url), target_status,
            target_status, target_status, clear_rejection, job_id
        ))

        try:
            _execute_db("""
                INSERT INTO job_status_history (job_id, previous_status, new_status, changed_by_user_id, notes, changed_at)
                VALUES (%s, %s, %s, %s, 'Updated job details in place', CURRENT_TIMESTAMP);
            """, (job_id, current_status, target_status, user_id))
        except Exception:
            pass

        if target_status == "published" and current_status != "published":
            create_employer_notification_safe(
                user_id=user_id,
                event_type="job_published",
                event_key=f"job_published:{job_id}",
                title="Job Published Successfully",
                message=f"Your job posting '{t_clean}' has been published.",
                target_url=f"/dashboard/company?highlight_job={job_id}",
                job_id=job_id
            )

        msg = (
            "Job updated and published successfully!" if target_status == "published"
            else "Job draft updated successfully."
        )
        return {
            "success": True,
            "status": target_status,
            "job": {
                "id": job_id,
                "slug": job.get("slug"),
                "status": target_status,
                "title": t_clean
            },
            "message": msg
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 5. Publish Draft/Rejected Job Directly ---
@router.post("/jobs/{job_id}/submit")
def submit_employer_job_for_review(
    job_id: int,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    try:
        rows = _query_db(
            "SELECT id, title, slug, status, is_archived, company_profile_id, employer_user_id FROM jobs WHERE id = %s;",
            (job_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found.")

        job = rows[0]
        _verify_employer_ownership(job, user_id, profile_id)

        current_status = (job.get("status") or "").lower()
        if job.get("is_archived") or current_status == "archived":
            raise HTTPException(status_code=400, detail="Archived jobs cannot be published.")
        if current_status not in ("draft", "rejected", "pending_review"):
            raise HTTPException(status_code=400, detail=f"Job is already in '{current_status}' status.")

        _execute_db("""
            UPDATE jobs
            SET status = 'published',
                published_at = COALESCE(published_at, CURRENT_TIMESTAMP),
                expires_at = COALESCE(expires_at, CURRENT_TIMESTAMP + INTERVAL '30 days'),
                rejection_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (job_id,))

        try:
            _execute_db("""
                INSERT INTO job_status_history (job_id, previous_status, new_status, changed_by_user_id, notes, changed_at)
                VALUES (%s, %s, 'published', %s, 'Published draft job', CURRENT_TIMESTAMP);
            """, (job_id, current_status, user_id))
        except Exception:
            pass

        create_employer_notification_safe(
            user_id=user_id,
            event_type="job_published",
            event_key=f"job_published:{job_id}",
            title="Job Published Successfully",
            message=f"Your job posting '{job.get('title') or 'Job'}' has been published.",
            target_url=f"/dashboard/company?highlight_job={job_id}",
            job_id=job_id
        )

        return {
            "success": True,
            "status": "published",
            "job": {
                "id": job_id,
                "slug": job.get("slug"),
                "status": "published"
            },
            "message": "Job published successfully! Your vacancy is now live on Tiruppur Jobs."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 5B. Repost Expired or Closed Job in Place (Strict State Matrix) ---
@router.post("/jobs/{job_id}/repost")
def repost_employer_job(
    job_id: int,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Reposts an expired or closed job owned by the authenticated employer.
    Strict Rules:
      - Archived / Deleted jobs (is_archived = TRUE or status = 'archived') CANNOT be reposted.
      - Active (published & not expired) or Draft jobs CANNOT be reposted.
      - Reuses the existing Job ID and slug (zero duplicate records).
      - Preserves all historical candidate applications.
    """
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    try:
        rows = _query_db("""
            SELECT
                id, title, slug, status, is_archived, company_profile_id, employer_user_id,
                expires_at,
                (expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP) AS is_past_expiry
            FROM jobs
            WHERE id = %s;
        """, (job_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found.")

        job = rows[0]
        _verify_employer_ownership(job, user_id, profile_id)

        current_status = (job.get("status") or "").lower()
        is_archived = bool(job.get("is_archived")) or (current_status == "archived")
        is_past_expiry = bool(job.get("is_past_expiry"))

        if is_archived:
            raise HTTPException(
                status_code=400,
                detail="Archived or deleted jobs cannot be reposted."
            )

        if current_status == "draft":
            raise HTTPException(
                status_code=400,
                detail="Draft jobs cannot be reposted. Please publish the draft job instead."
            )

        is_expired_state = (current_status == "expired") or (current_status == "published" and is_past_expiry)
        is_closed_state = (current_status == "closed")

        if not (is_expired_state or is_closed_state):
            raise HTTPException(
                status_code=400,
                detail="This job is currently active. Only expired or closed jobs can be reposted."
            )

        _execute_db("""
            UPDATE jobs
            SET status = 'published',
                is_archived = FALSE,
                published_at = CURRENT_TIMESTAMP,
                expires_at = CURRENT_TIMESTAMP + INTERVAL '30 days',
                rejection_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (job_id,))

        try:
            _execute_db("""
                INSERT INTO job_status_history (job_id, previous_status, new_status, changed_by_user_id, notes, changed_at)
                VALUES (%s, %s, 'published', %s, 'Reposted job for a new 30-day validity cycle', CURRENT_TIMESTAMP);
            """, (job_id, current_status, user_id))
        except Exception:
            pass

        today_key = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M")
        create_employer_notification_safe(
            user_id=user_id,
            event_type="job_published",
            event_key=f"job_reposted:{job_id}:{today_key}",
            title="Job Reposted Successfully",
            message=f"Your job posting '{job.get('title') or 'Job'}' has been reposted and is now active.",
            target_url=f"/dashboard/company?highlight_job={job_id}",
            job_id=job_id
        )

        return {
            "success": True,
            "status": "published",
            "job": {
                "id": job_id,
                "slug": job.get("slug"),
                "status": "published",
                "title": job.get("title")
            },
            "message": "Job reposted successfully! Your vacancy is now active on Tiruppur Jobs."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reposting job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong while reposting the job.")


# --- 6. Safe Soft-Delete / Archive Job (Preserves All Candidate Applications & History) ---
@router.delete("/jobs/{job_id}")
def delete_employer_job(
    job_id: int,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Safely soft-deletes (archives) a job belonging to the authenticated employer.
    Never permanently deletes a job or its candidate applications.
    Sets is_archived = TRUE and status = 'archived' so the job is immediately hidden
    from public job listings, public search, and the active employer dashboard while
    preserving all historical candidate applications and audit records.
    """
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    try:
        rows = _query_db(
            "SELECT id, title, status, is_archived, company_profile_id, employer_user_id FROM jobs WHERE id = %s;",
            (job_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found.")

        job = rows[0]
        _verify_employer_ownership(job, user_id, profile_id)

        current_status = (job.get("status") or "").lower()
        if job.get("is_archived") or current_status == "archived":
            return {"success": True, "message": "Job has already been removed."}

        _execute_db("""
            UPDATE jobs
            SET is_archived = TRUE,
                status = 'archived',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (job_id,))

        try:
            _execute_db("""
                INSERT INTO job_status_history (job_id, previous_status, new_status, changed_by_user_id, notes, changed_at)
                VALUES (%s, %s, 'archived', %s, 'Soft-deleted / archived by employer', CURRENT_TIMESTAMP);
            """, (job_id, current_status, user_id))
        except Exception:
            pass

        return {
            "success": True,
            "job_id": job_id,
            "status": "archived",
            "message": "Job posting removed from active listings. Historical applications have been safely preserved."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error archiving job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 7. Poster AI / OCR Extraction Assistant (Reusing Existing Pipeline) ---
@router.post("/jobs/extract-poster")
async def extract_poster_for_draft(
    file: Optional[UploadFile] = File(None),
    poster_file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None),
    poster_text: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Safely processes an uploaded job poster image or pasted raw text using
    the existing StructuredJobExtractor. Returns extracted fields to pre-populate
    the employer posting form without directly publishing.
    """
    effective_file = poster_file or file
    effective_text = (poster_text or raw_text or "").strip()

    if not effective_file and not effective_text:
        raise HTTPException(status_code=400, detail="Please upload a poster image or enter text.")

    image_bytes = None
    image_mime = None
    saved_rel_path = None

    if effective_file:
        file = effective_file
        allowed_mimes = ["image/jpeg", "image/png", "image/webp", "image/jpg"]
        if file.content_type not in allowed_mimes:
            raise HTTPException(status_code=400, detail="Invalid image type. Please upload a JPG, PNG, or WebP image.")

        content = await file.read()
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Poster file size must be less than 5 MB.")

        image_bytes = content
        image_mime = file.content_type

        vault_dir = os.path.join(_base_dir, "assets", "uploads", "source_vault")
        os.makedirs(vault_dir, exist_ok=True)
        ext = ".jpg" if "jpeg" in image_mime or "jpg" in image_mime else (".png" if "png" in image_mime else ".webp")
        filename = f"employer_poster_{uuid.uuid4().hex[:12]}{ext}"
        filepath = os.path.join(vault_dir, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        saved_rel_path = f"/assets/uploads/source_vault/{filename}"

    try:
        extractor = StructuredJobExtractor()
        extracted_result = extractor.process_multi_job_ingestion(
            raw_text=effective_text or None,
            image_bytes=image_bytes,
            image_mime=image_mime
        )

        vacancies = extracted_result.get("vacancies", [])
        primary_vacancy = vacancies[0] if vacancies else {}

        parsed_fields = {
            "title": primary_vacancy.get("title") or "",
            "department": primary_vacancy.get("department") or "",
            "job_role": primary_vacancy.get("job_role") or "",
            "experience_min": primary_vacancy.get("experience_min") or 0,
            "experience_max": primary_vacancy.get("experience_max"),
            "openings_count": primary_vacancy.get("openings_count") or 1,
            "vacancies": primary_vacancy.get("openings_count") or 1,
            "skills": primary_vacancy.get("skills") or "",
            "qualification": primary_vacancy.get("qualification") or "",
            "salary_text": primary_vacancy.get("salary_text") or "",
            "contact_phone": primary_vacancy.get("contact_phone") or "",
            "contact_whatsapp": primary_vacancy.get("contact_whatsapp") or "",
            "location": primary_vacancy.get("location") or "",
            "location_area": primary_vacancy.get("location") or "",
            "description": primary_vacancy.get("description") or primary_vacancy.get("requirements") or "",
            "requirements": primary_vacancy.get("requirements") or "",
            "poster_image_url": saved_rel_path
        }

        return {
            "success": True,
            "draft_job": parsed_fields,
            "extracted_data": parsed_fields,
            "message": "Poster processed successfully. Please review and edit the fields below."
        }
    except Exception as e:
        logger.error(f"Error extracting poster for employer: {e}")
        fallback_data = {"poster_image_url": saved_rel_path}
        return {
            "success": False,
            "draft_job": fallback_data,
            "extracted_data": fallback_data,
            "message": "Could not auto-extract details. You can enter the details manually."
        }


# --- 8. Employer Applications Management APIs ---

class ApplicationStatusUpdateRequest(BaseModel):
    status: str


@router.get("/applications")
def get_employer_applications(
    job_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Pure read-only fetch of candidate applications received for jobs owned by the authenticated employer.
    Opening the applications list NEVER marks applications as read.
    """
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        return {"success": True, "applications": [], "total": 0}

    try:
        conditions = ["(j.employer_user_id = %s OR (%s IS NOT NULL AND j.company_profile_id = %s))"]
        params: List[Any] = [user_id, profile_id, profile_id]

        if job_id:
            conditions.append("a.job_id = %s")
            params.append(job_id)

        if status and status != "All":
            conditions.append("LOWER(a.status) = LOWER(%s)")
            params.append(status.strip())

        where_clause = " WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT 
                a.id, a.job_id, a.candidate_user_id, a.individual_profile_id,
                a.status, a.applied_at, a.employer_viewed_at,
                a.cover_message, a.cover_letter, a.resume_url,
                a.applicant_name, a.applicant_phone, a.applicant_email,
                j.title AS job_title, j.department AS job_department, j.job_role,
                p.full_name AS profile_name, p.mobile AS profile_mobile, p.email AS profile_email,
                p.job_title AS candidate_role, p.department AS candidate_department,
                p.experience_years, p.location AS candidate_location, p.city AS candidate_city,
                p.district AS candidate_district, p.skills AS candidate_skills,
                p.qualification AS candidate_qualification, p.course AS candidate_course,
                p.institution AS candidate_institution, p.passing_year AS candidate_passing_year,
                p.expected_salary AS candidate_expected_salary,
                p.resume_url AS profile_resume_url
            FROM job_applications a
            JOIN jobs j ON a.job_id = j.id
            LEFT JOIN individual_profiles p ON a.individual_profile_id = p.id
            {where_clause}
            ORDER BY a.applied_at DESC;
        """
        rows = _query_db(query, tuple(params)) or []

        apps = []
        for r in rows:
            st_norm = (r["status"] or "submitted").lower()
            is_unread = (r.get("employer_viewed_at") is None) and (st_norm in ("submitted", "applied"))
            apps.append({
                "id": r["id"],
                "job_id": r["job_id"],
                "job_title": r["job_title"],
                "job_department": r["job_department"] or "",
                "job_role": r["job_role"] or "",
                "candidate_name": r["applicant_name"] or r["profile_name"] or "Candidate",
                "candidate_phone": r["applicant_phone"] or r["profile_mobile"] or "-",
                "candidate_email": r["applicant_email"] or r["profile_email"] or "-",
                "candidate_role": r["candidate_role"] or "-",
                "candidate_department": r["candidate_department"] or "-",
                "experience_years": float(r["experience_years"] or 0),
                "location": r["candidate_location"] or r["candidate_city"] or "Tiruppur",
                "city": r["candidate_city"] or "",
                "district": r["candidate_district"] or "",
                "qualification": r["candidate_qualification"] or "-",
                "course": r["candidate_course"] or "",
                "institution": r["candidate_institution"] or "",
                "passing_year": r["candidate_passing_year"] or "",
                "skills": r["candidate_skills"] or "",
                "expected_salary": r["candidate_expected_salary"] or "-",
                "resume_url": r["resume_url"] or r["profile_resume_url"] or None,
                "cover_message": r["cover_message"] or r["cover_letter"] or "",
                "status": st_norm,
                "employer_viewed_at": r.get("employer_viewed_at"),
                "is_unread": is_unread,
                "applied_at": r["applied_at"]
            })

        return {
            "success": True,
            "applications": apps,
            "total": len(apps)
        }
    except Exception as e:
        logger.error(f"Error loading employer applications: {e}")
        raise HTTPException(status_code=500, detail="Could not load applications.")


@router.get("/applications/{app_id}")
def get_employer_application_detail(
    app_id: int,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Pure read-only view of a specific candidate application.
    Does NOT mutate employer_viewed_at or status (use POST /applications/{app_id}/view for read tracking).
    Enforces employer job ownership.
    """
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    try:
        query = """
            SELECT 
                a.id, a.job_id, a.candidate_user_id, a.individual_profile_id,
                a.status, a.applied_at, a.employer_viewed_at,
                a.cover_message, a.cover_letter, a.resume_url,
                a.applicant_name, a.applicant_phone, a.applicant_email,
                j.title AS job_title, j.department AS job_department, j.job_role,
                j.company_profile_id, j.employer_user_id,
                p.full_name AS profile_name, p.mobile AS profile_mobile, p.email AS profile_email,
                p.job_title AS candidate_role, p.department AS candidate_department,
                p.experience_years, p.location AS candidate_location, p.city AS candidate_city,
                p.district AS candidate_district, p.skills AS candidate_skills,
                p.qualification AS candidate_qualification, p.course AS candidate_course,
                p.institution AS candidate_institution, p.passing_year AS candidate_passing_year,
                p.expected_salary AS candidate_expected_salary,
                p.resume_url AS profile_resume_url
            FROM job_applications a
            JOIN jobs j ON a.job_id = j.id
            LEFT JOIN individual_profiles p ON a.individual_profile_id = p.id
            WHERE a.id = %s;
        """
        rows = _query_db(query, (app_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Application not found.")

        r = rows[0]
        _verify_employer_ownership(r, user_id, profile_id)

        st_norm = (r["status"] or "submitted").lower()
        is_unread = (r.get("employer_viewed_at") is None) and (st_norm in ("submitted", "applied"))

        app_detail = {
            "id": r["id"],
            "job_id": r["job_id"],
            "job_title": r["job_title"],
            "job_department": r["job_department"] or "",
            "job_role": r["job_role"] or "",
            "candidate_name": r["applicant_name"] or r["profile_name"] or "Candidate",
            "candidate_phone": r["applicant_phone"] or r["profile_mobile"] or "-",
            "candidate_email": r["applicant_email"] or r["profile_email"] or "-",
            "candidate_role": r["candidate_role"] or "-",
            "candidate_department": r["candidate_department"] or "-",
            "experience_years": float(r["experience_years"] or 0),
            "location": r["candidate_location"] or r["candidate_city"] or "Tiruppur",
            "city": r["candidate_city"] or "",
            "district": r["candidate_district"] or "",
            "qualification": r["candidate_qualification"] or "-",
            "course": r["candidate_course"] or "",
            "institution": r["candidate_institution"] or "",
            "passing_year": r["candidate_passing_year"] or "",
            "skills": r["candidate_skills"] or "",
            "expected_salary": r["candidate_expected_salary"] or "-",
            "resume_url": r["resume_url"] or r["profile_resume_url"] or None,
            "cover_message": r["cover_message"] or r["cover_letter"] or "",
            "status": st_norm,
            "employer_viewed_at": r.get("employer_viewed_at"),
            "is_unread": is_unread,
            "applied_at": r["applied_at"]
        }

        return {"success": True, "application": app_detail}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching application detail {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not load application details.")


# --- 8B. Dedicated Application View-Tracking Endpoint (POST / PATCH) ---
@router.post("/applications/{app_id}/view")
@router.patch("/applications/{app_id}/view")
def mark_employer_application_viewed(
    app_id: int,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Marks a single candidate application as viewed by the owning employer.
    - Verifies job ownership before updating.
    - Uses COALESCE(employer_viewed_at, CURRENT_TIMESTAMP) so repeated opens keep the original viewed timestamp.
    - NEVER modifies job_applications.status or candidate-visible status transitions.
    """
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    try:
        rows = _query_db("""
            SELECT a.id, a.job_id, a.status, a.employer_viewed_at, j.company_profile_id, j.employer_user_id
            FROM job_applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = %s;
        """, (app_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Application not found.")

        app_row = rows[0]
        _verify_employer_ownership(app_row, user_id, profile_id)

        updated_rows = _execute_db_returning("""
            UPDATE job_applications
            SET employer_viewed_at = COALESCE(employer_viewed_at, CURRENT_TIMESTAMP)
            WHERE id = %s
            RETURNING id, job_id, status, employer_viewed_at;
        """, (app_id,))

        upd = updated_rows[0] if updated_rows else app_row
        job_id = upd["job_id"]

        # Return updated unread count for this job so dashboard updates immediately
        cnt_rows = _query_db("""
            SELECT COUNT(*) AS unread_count
            FROM job_applications
            WHERE job_id = %s
              AND employer_viewed_at IS NULL
              AND LOWER(COALESCE(status, 'submitted')) IN ('submitted', 'applied');
        """, (job_id,))
        job_unread_count = int(cnt_rows[0]["unread_count"]) if cnt_rows else 0

        return {
            "success": True,
            "application_id": app_id,
            "job_id": job_id,
            "status": (upd.get("status") or "submitted").lower(),
            "employer_viewed_at": upd.get("employer_viewed_at"),
            "is_unread": False,
            "job_unread_applications_count": job_unread_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking application {app_id} as viewed: {e}")
        raise HTTPException(status_code=500, detail="Could not update application view state.")


VALID_APPLICATION_STATUS_TRANSITIONS = {
    "submitted": {"reviewed", "shortlisted", "rejected"},
    "reviewed": {"shortlisted", "rejected"},
    "shortlisted": {"rejected"},
    "rejected": set()
}


@router.put("/applications/{app_id}/status")
def update_employer_application_status(
    app_id: int,
    req: ApplicationStatusUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Explicit employer status transition with server-side validation:
      submitted   -> reviewed, shortlisted, rejected
      reviewed    -> shortlisted, rejected
      shortlisted -> rejected
    """
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    target_status = (req.status or "").strip().lower()
    allowed_target_statuses = ("reviewed", "shortlisted", "rejected")
    if target_status not in allowed_target_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target status '{target_status}'. Must be one of {allowed_target_statuses}"
        )

    try:
        query = """
            SELECT a.id, a.status, j.company_profile_id, j.employer_user_id
            FROM job_applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = %s;
        """
        rows = _query_db(query, (app_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Application not found.")

        app_row = rows[0]
        _verify_employer_ownership(app_row, user_id, profile_id)

        current_status = (app_row.get("status") or "submitted").lower()
        if current_status == "applied":
            current_status = "submitted"

        allowed_next = VALID_APPLICATION_STATUS_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_next and target_status != current_status:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition application status from '{current_status}' to '{target_status}'."
            )

        _execute_db("""
            UPDATE job_applications
            SET status = %s,
                employer_viewed_at = COALESCE(employer_viewed_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (target_status, app_id))

        status_messages = {
            "reviewed": "Application marked as reviewed.",
            "shortlisted": "Candidate shortlisted successfully.",
            "rejected": "Application rejected."
        }

        return {
            "success": True,
            "status": target_status,
            "message": status_messages.get(target_status, f"Status updated to {target_status}.")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating application status {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not update application status.")


@router.get("/jobs/{job_id}/applications")
def get_job_specific_applications(
    job_id: int,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Helper route to fetch applications for a specific job owned by the employer.
    """
    return get_employer_applications(job_id=job_id, status="All", current_user=current_user)


# --- 9. User-Specific Employer Notifications APIs ---

@router.get("/notifications")
def get_employer_notifications(
    limit: int = Query(30, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Returns notifications strictly scoped to the logged-in employer user ID.
    Synchronizes verification and job expiry notifications idempotently before querying.
    """
    user_id = int(current_user["id"])
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        return {"success": True, "unread_count": 0, "notifications": []}

    try:
        _sync_employer_state_notifications(user_id=user_id, profile_id=profile_id, profile=profile)

        rows = _query_db("""
            SELECT
                id, user_id, job_id, application_id, event_type, event_key,
                title, message, target_url, is_read, created_at
            FROM employer_notifications
            WHERE user_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s;
        """, (user_id, limit)) or []

        cnt_rows = _query_db("""
            SELECT COUNT(*) AS unread_count
            FROM employer_notifications
            WHERE user_id = %s AND is_read = FALSE;
        """, (user_id,))
        unread_count = int(cnt_rows[0]["unread_count"]) if cnt_rows else 0

        return {
            "success": True,
            "unread_count": unread_count,
            "notifications": rows
        }
    except Exception as e:
        logger.error(f"Error loading notifications for user {user_id}: {e}")
        return {"success": True, "unread_count": 0, "notifications": []}


@router.post("/notifications/read")
def mark_employer_notifications_read(
    req: NotificationReadRequest = Body(...),
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    """
    Marks a single notification or all notifications as read for the logged-in employer.
    Strictly scoped by WHERE user_id = current_user['id'].
    """
    user_id = int(current_user["id"])

    if not _db_enabled or not _execute_db:
        return {"success": True, "unread_count": 0}

    try:
        if req.mark_all:
            _execute_db("""
                UPDATE employer_notifications
                SET is_read = TRUE
                WHERE user_id = %s AND is_read = FALSE;
            """, (user_id,))
        elif req.notification_id is not None:
            _execute_db("""
                UPDATE employer_notifications
                SET is_read = TRUE
                WHERE id = %s AND user_id = %s;
            """, (int(req.notification_id), user_id))

        cnt_rows = _query_db("""
            SELECT COUNT(*) AS unread_count
            FROM employer_notifications
            WHERE user_id = %s AND is_read = FALSE;
        """, (user_id,))
        unread_count = int(cnt_rows[0]["unread_count"]) if cnt_rows else 0

        return {
            "success": True,
            "unread_count": unread_count
        }
    except Exception as e:
        logger.error(f"Error marking notifications read for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not update notification status.")
