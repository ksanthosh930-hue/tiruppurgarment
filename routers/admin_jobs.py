import re
import uuid
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Form, Query, Body, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin Jobs CMS"])

# Database and Auth helper injectors
db_helpers = {
    "db_enabled": False,
    "query_db": None,
    "execute_db": None,
    "execute_db_returning": None,
    "get_current_admin": None
}

def init_admin_helpers(enabled: bool, query_fn, exec_fn, exec_ret_fn, auth_fn):
    db_helpers["db_enabled"] = enabled
    db_helpers["query_db"] = query_fn
    db_helpers["execute_db"] = exec_fn
    db_helpers["execute_db_returning"] = exec_ret_fn
    db_helpers["get_current_admin"] = auth_fn

async def require_admin(admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)):
    return admin

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text[:180]

# --- 1. JOBS STATS ---

@router.get("/jobs/dashboard-stats")
def get_jobs_dashboard_stats(admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)):
    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        from routers.jobs import FALLBACK_JOBS
        total = len(FALLBACK_JOBS)
        published = len([j for j in FALLBACK_JOBS if (j.get("status") or "").lower() == "published" and not j.get("is_archived")])
        draft = len([j for j in FALLBACK_JOBS if (j.get("status") or "").lower() == "draft" and not j.get("is_archived")])
        pending = len([j for j in FALLBACK_JOBS if (j.get("status") or "").lower() in ("pending_review", "pending") and not j.get("is_archived")])
        closed = len([j for j in FALLBACK_JOBS if (j.get("status") or "").lower() == "closed" and not j.get("is_archived")])
        expired = len([j for j in FALLBACK_JOBS if (j.get("status") or "").lower() == "expired" and not j.get("is_archived")])
        archived = len([j for j in FALLBACK_JOBS if j.get("is_archived") or (j.get("status") or "").lower() == "archived"])
        featured = len([j for j in FALLBACK_JOBS if j.get("is_featured") and not j.get("is_archived")])
        return {
            "total_jobs": total,
            "published": published,
            "draft": draft,
            "pending_review": pending,
            "closed": closed,
            "expired": expired,
            "archived": archived,
            "featured": featured
        }

    try:
        rows = db_helpers["query_db"]("""
            SELECT 
                COUNT(*) AS total_jobs,
                COUNT(*) FILTER (WHERE LOWER(status) = 'published' AND COALESCE(is_archived, FALSE) = FALSE) AS published,
                COUNT(*) FILTER (WHERE LOWER(status) = 'draft' AND COALESCE(is_archived, FALSE) = FALSE) AS draft,
                COUNT(*) FILTER (WHERE LOWER(status) IN ('pending_review', 'pending') AND COALESCE(is_archived, FALSE) = FALSE) AS pending_review,
                COUNT(*) FILTER (WHERE LOWER(status) = 'closed' AND COALESCE(is_archived, FALSE) = FALSE) AS closed,
                COUNT(*) FILTER (WHERE LOWER(status) = 'expired' AND COALESCE(is_archived, FALSE) = FALSE) AS expired,
                COUNT(*) FILTER (WHERE COALESCE(is_archived, FALSE) = TRUE OR LOWER(status) = 'archived') AS archived,
                COUNT(*) FILTER (WHERE is_featured = TRUE AND COALESCE(is_archived, FALSE) = FALSE) AS featured
            FROM jobs;
        """)
        return rows[0] if rows else {}
    except Exception as e:
        logger.error(f"Error fetching jobs stats: {e}")
        raise HTTPException(status_code=500, detail=f"Database error loading stats: {e}")

# --- 2. ADMIN JOBS CRUD ---

@router.get("/jobs")
def get_admin_jobs(
    status: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)
):
    """
    Paginated jobs list for Admin table.
    """
    status_str = str(status).strip() if isinstance(status, str) and status.strip() else None
    dept_str = str(department).strip() if isinstance(department, str) and department.strip() else None
    search_str = str(search).strip() if isinstance(search, str) and search.strip() else None
    page_num = page if isinstance(page, int) and page >= 1 else 1
    limit_num = limit if isinstance(limit, int) and limit >= 1 else 20

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        from routers.jobs import FALLBACK_JOBS
        filtered = list(FALLBACK_JOBS)
        if status_str and status_str != "All":
            if status_str.lower() == "archived":
                filtered = [j for j in filtered if j.get("is_archived") or (j.get("status") or "").lower() == "archived"]
            else:
                filtered = [j for j in filtered if (j.get("status") or "").lower() == status_str.lower() and not j.get("is_archived")]
        if dept_str and dept_str != "All":
            filtered = [j for j in filtered if (j.get("department") or "").lower() == dept_str.lower()]
        if search_str:
            term = search_str.lower()
            filtered = [j for j in filtered if term in (j.get("title") or "").lower() or term in (j.get("company_name") or "").lower() or term in (j.get("job_role") or "").lower()]
            
        total = len(filtered)
        start = (page_num - 1) * limit_num
        paginated = filtered[start:start + limit_num]
        total_pages = max(1, (total + limit_num - 1) // limit_num)
        return {
            "success": True,
            "jobs": paginated,
            "page": page_num,
            "limit": limit_num,
            "total": total,
            "total_pages": total_pages
        }

    try:
        conditions = []
        params = []

        if status_str and status_str != "All":
            if status_str.lower() == "archived":
                conditions.append("(COALESCE(j.is_archived, FALSE) = TRUE OR LOWER(j.status) = 'archived')")
            else:
                conditions.append("LOWER(j.status) = LOWER(%s) AND COALESCE(j.is_archived, FALSE) = FALSE")
                params.append(status_str)
        else:
            # By default show non-archived unless specifically requested
            conditions.append("COALESCE(j.is_archived, FALSE) = FALSE")

        if dept_str and dept_str != "All":
            conditions.append("j.department ILIKE %s")
            params.append(dept_str)

        if search_str:
            conditions.append("(j.title ILIKE %s OR j.job_role ILIKE %s OR c.name ILIKE %s OR j.location ILIKE %s)")
            params.extend([f"%{search_str}%"] * 4)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        # Total count
        count_q = f"SELECT COUNT(*) FROM jobs j LEFT JOIN companies c ON j.company_id = c.id {where_clause};"
        total = db_helpers["query_db"](count_q, tuple(params) if params else None)[0]["count"]

        offset = (page_num - 1) * limit_num
        data_q = f"""
            SELECT 
                j.id, j.company_id, j.title, j.slug, j.department, j.job_role, j.job_type,
                j.location, j.openings_count, j.experience_min, j.experience_max, j.salary_min, j.salary_max,
                j.salary_text, j.description, j.requirements, j.skills, j.qualification,
                j.gender, j.contact_phone, j.contact_whatsapp, j.contact_email, j.application_url,
                j.source_type, j.source_name, j.poster_image_url, j.status, j.is_featured,
                j.is_archived, j.verification_status, j.published_at, j.expires_at, j.created_at,
                c.name AS company_name, c.logo_url AS company_logo
            FROM jobs j
            LEFT JOIN companies c ON j.company_id = c.id
            {where_clause}
            ORDER BY j.created_at DESC
            LIMIT %s OFFSET %s;
        """
        p_list = list(params)
        p_list.extend([limit_num, offset])
        rows = db_helpers["query_db"](data_q, tuple(p_list))
        total_pages = max(1, (total + limit_num - 1) // limit_num)

        return {
            "success": True,
            "jobs": rows,
            "page": page_num,
            "limit": limit_num,
            "total": total,
            "total_pages": total_pages
        }
    except Exception as e:
        logger.error(f"Error loading admin jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Database error loading jobs: {e}")

@router.get("/jobs/{job_id}")
def get_admin_job(job_id: int, admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)):
    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        from routers.jobs import FALLBACK_JOBS
        match = next((j for j in FALLBACK_JOBS if j["id"] == job_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Job not found.")
        return {"success": True, "job": match}

    try:
        rows = db_helpers["query_db"]("""
            SELECT j.*, c.name AS company_name 
            FROM jobs j 
            LEFT JOIN companies c ON j.company_id = c.id 
            WHERE j.id = %s;
        """, (job_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found.")
        return {"success": True, "job": rows[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

def _clean_str(val):
    if isinstance(val, str):
        v = val.strip()
        return v if v else None
    return None

def _clean_num(val, default=None):
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return val
    try:
        if isinstance(val, str) and val.strip():
            return float(val.strip()) if '.' in val else int(val.strip())
    except Exception:
        pass
    return default

def _clean_bool(val, default=False):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "on")
    return default

@router.post("/jobs")
def create_admin_job(
    title: str = Form(...),
    department: str = Form(...),
    job_role: str = Form(...),
    company_id: Optional[int] = Form(None),
    job_type: str = Form("Full Time"),
    location: str = Form(...),
    openings_count: int = Form(1),
    experience_min: int = Form(0),
    experience_max: Optional[int] = Form(None),
    salary_min: Optional[float] = Form(None),
    salary_max: Optional[float] = Form(None),
    salary_text: Optional[str] = Form(None),
    description: str = Form(...),
    requirements: Optional[str] = Form(None),
    skills: Optional[str] = Form(None),
    qualification: Optional[str] = Form(None),
    gender: Optional[str] = Form("Any"),
    contact_phone: Optional[str] = Form(None),
    contact_whatsapp: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    application_url: Optional[str] = Form(None),
    source_type: str = Form("manual"),
    source_name: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    poster_image_url: Optional[str] = Form(None),
    status: str = Form("draft"),
    is_featured: bool = Form(False),
    verification_status: str = Form("unverified"),
    admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)
):
    """
    Creates a new job vacancy. Generates unique slug.
    """
    t_clean = str(title).strip() if title else ""
    d_clean = str(department).strip() if department else ""
    r_clean = str(job_role).strip() if job_role else ""
    cid_clean = _clean_num(company_id)
    type_clean = _clean_str(job_type) or "Full Time"
    loc_clean = str(location).strip() if location else ""
    openings_cnt_clean = max(int(_clean_num(openings_count, 1) or 1), 1)
    exp_min_clean = _clean_num(experience_min, 0)
    exp_max_clean = _clean_num(experience_max)
    sal_min_clean = _clean_num(salary_min)
    sal_max_clean = _clean_num(salary_max)
    sal_text_clean = _clean_str(salary_text)
    desc_clean = str(description).strip() if description else ""
    req_clean = _clean_str(requirements)
    skills_clean = _clean_str(skills)
    qual_clean = _clean_str(qualification)
    gender_clean = _clean_str(gender) or "Any"
    phone_clean = _clean_str(contact_phone)
    wa_clean = _clean_str(contact_whatsapp)
    email_clean = _clean_str(contact_email)
    app_url_clean = _clean_str(application_url)
    src_type_clean = _clean_str(source_type) or "manual"
    src_name_clean = _clean_str(source_name) or "Direct Admin Entry"
    src_url_clean = _clean_str(source_url)
    poster_clean = _clean_str(poster_image_url)
    status_clean = _clean_str(status) or "draft"
    featured_clean = _clean_bool(is_featured, False)
    verif_clean = _clean_str(verification_status) or "unverified"

    base_slug = slugify(t_clean)
    unique_suffix = uuid.uuid4().hex[:6]
    slug = f"{base_slug}-{unique_suffix}"

    published_at_clause = "CURRENT_TIMESTAMP" if status_clean == "published" else "NULL"

    if not db_helpers["db_enabled"] or not db_helpers["execute_db_returning"]:
        from routers.jobs import FALLBACK_JOBS
        new_job = {
            "id": len(FALLBACK_JOBS) + 1,
            "company_id": cid_clean or 1,
            "company_name": "[DEMO] Test Garments India",
            "title": t_clean,
            "slug": slug,
            "department": d_clean,
            "job_role": r_clean,
            "job_type": type_clean,
            "location": loc_clean,
            "openings_count": openings_cnt_clean,
            "experience_min": exp_min_clean,
            "experience_max": exp_max_clean,
            "salary_min": sal_min_clean,
            "salary_max": sal_max_clean,
            "salary_text": sal_text_clean,
            "description": desc_clean,
            "requirements": req_clean,
            "skills": skills_clean,
            "qualification": qual_clean,
            "gender": gender_clean,
            "contact_phone": phone_clean,
            "contact_whatsapp": wa_clean,
            "contact_email": email_clean,
            "application_url": app_url_clean,
            "source_type": src_type_clean,
            "source_name": src_name_clean,
            "poster_image_url": poster_clean,
            "status": status_clean,
            "is_featured": featured_clean,
            "is_archived": False,
            "verification_status": verif_clean,
            "published_at": "2026-08-27T12:00:00" if status_clean == "published" else None
        }
        FALLBACK_JOBS.insert(0, new_job)
        return {"success": True, "job_id": new_job["id"], "slug": slug, "message": "Job created successfully (offline mode)."}

    try:
        query = f"""
            INSERT INTO jobs (
                company_id, title, slug, department, job_role, job_type, location,
                openings_count, experience_min, experience_max, salary_min, salary_max, salary_text,
                description, requirements, skills, qualification, gender,
                contact_phone, contact_whatsapp, contact_email, application_url,
                source_type, source_name, source_url, poster_image_url, status,
                is_featured, is_archived, verification_status, published_at,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, FALSE, %s, {published_at_clause},
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) RETURNING id;
        """
        rows = db_helpers["execute_db_returning"](query, (
            cid_clean, t_clean, slug, d_clean, r_clean, type_clean, loc_clean,
            openings_cnt_clean, exp_min_clean, exp_max_clean, sal_min_clean, sal_max_clean, sal_text_clean,
            desc_clean, req_clean, skills_clean, qual_clean, gender_clean,
            phone_clean, wa_clean, email_clean, app_url_clean,
            src_type_clean, src_name_clean, src_url_clean, poster_clean, status_clean,
            featured_clean, verif_clean
        ))
        job_id = rows[0]["id"]
        return {"success": True, "job_id": job_id, "slug": slug, "message": "Job created successfully."}
    except Exception as e:
        logger.error(f"Error creating job: {e}")
        raise HTTPException(status_code=500, detail=f"Database error creating job: {e}")

@router.put("/jobs/{job_id}")
def update_admin_job(
    job_id: int,
    title: str = Form(...),
    department: str = Form(...),
    job_role: str = Form(...),
    company_id: Optional[int] = Form(None),
    job_type: str = Form("Full Time"),
    location: str = Form(...),
    openings_count: int = Form(1),
    experience_min: int = Form(0),
    experience_max: Optional[int] = Form(None),
    salary_min: Optional[float] = Form(None),
    salary_max: Optional[float] = Form(None),
    salary_text: Optional[str] = Form(None),
    description: str = Form(...),
    requirements: Optional[str] = Form(None),
    skills: Optional[str] = Form(None),
    qualification: Optional[str] = Form(None),
    gender: Optional[str] = Form("Any"),
    contact_phone: Optional[str] = Form(None),
    contact_whatsapp: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    application_url: Optional[str] = Form(None),
    source_type: str = Form("manual"),
    source_name: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    poster_image_url: Optional[str] = Form(None),
    status: str = Form("draft"),
    is_featured: bool = Form(False),
    verification_status: str = Form("unverified"),
    admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)
):
    """
    Updates an existing job.
    """
    t_clean = str(title).strip() if title else ""
    d_clean = str(department).strip() if department else ""
    r_clean = str(job_role).strip() if job_role else ""
    cid_clean = _clean_num(company_id)
    type_clean = _clean_str(job_type) or "Full Time"
    loc_clean = str(location).strip() if location else ""
    openings_cnt_clean = max(int(_clean_num(openings_count, 1) or 1), 1)
    exp_min_clean = _clean_num(experience_min, 0)
    exp_max_clean = _clean_num(experience_max)
    sal_min_clean = _clean_num(salary_min)
    sal_max_clean = _clean_num(salary_max)
    sal_text_clean = _clean_str(salary_text)
    desc_clean = str(description).strip() if description else ""
    req_clean = _clean_str(requirements)
    skills_clean = _clean_str(skills)
    qual_clean = _clean_str(qualification)
    gender_clean = _clean_str(gender) or "Any"
    phone_clean = _clean_str(contact_phone)
    wa_clean = _clean_str(contact_whatsapp)
    email_clean = _clean_str(contact_email)
    app_url_clean = _clean_str(application_url)
    src_type_clean = _clean_str(source_type) or "manual"
    src_name_clean = _clean_str(source_name) or "Direct Admin Entry"
    src_url_clean = _clean_str(source_url)
    poster_clean = _clean_str(poster_image_url)
    status_clean = _clean_str(status) or "draft"
    featured_clean = _clean_bool(is_featured, False)
    verif_clean = _clean_str(verification_status) or "unverified"

    if not db_helpers["db_enabled"] or not db_helpers["execute_db"]:
        from routers.jobs import FALLBACK_JOBS
        match = next((j for j in FALLBACK_JOBS if j["id"] == job_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Job not found.")
        match.update({
            "title": t_clean,
            "department": d_clean,
            "job_role": r_clean,
            "company_id": cid_clean,
            "job_type": type_clean,
            "location": loc_clean,
            "openings_count": openings_cnt_clean,
            "experience_min": exp_min_clean,
            "experience_max": exp_max_clean,
            "salary_min": sal_min_clean,
            "salary_max": sal_max_clean,
            "salary_text": sal_text_clean,
            "description": desc_clean,
            "requirements": req_clean,
            "skills": skills_clean,
            "qualification": qual_clean,
            "gender": gender_clean,
            "contact_phone": phone_clean,
            "contact_whatsapp": wa_clean,
            "contact_email": email_clean,
            "application_url": app_url_clean,
            "source_type": src_type_clean,
            "source_name": src_name_clean,
            "poster_image_url": poster_clean,
            "status": status_clean,
            "is_featured": featured_clean,
            "verification_status": verif_clean
        })
        return {"success": True, "message": "Job updated successfully."}

    try:
        query = """
            UPDATE jobs
            SET company_id = %s, title = %s, department = %s, job_role = %s, job_type = %s,
                location = %s, openings_count = %s, experience_min = %s, experience_max = %s, salary_min = %s,
                salary_max = %s, salary_text = %s, description = %s, requirements = %s,
                skills = %s, qualification = %s, gender = %s, contact_phone = %s,
                contact_whatsapp = %s, contact_email = %s, application_url = %s,
                source_type = %s, source_name = %s, source_url = %s, poster_image_url = %s,
                status = %s, is_featured = %s, verification_status = %s,
                published_at = CASE WHEN %s = 'published' AND published_at IS NULL THEN CURRENT_TIMESTAMP ELSE published_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """
        db_helpers["execute_db"](query, (
            cid_clean, t_clean, d_clean, r_clean, type_clean, loc_clean,
            openings_cnt_clean, exp_min_clean, exp_max_clean, sal_min_clean, sal_max_clean, sal_text_clean,
            desc_clean, req_clean, skills_clean, qual_clean, gender_clean,
            phone_clean, wa_clean, email_clean, app_url_clean,
            src_type_clean, src_name_clean, src_url_clean, poster_clean, status_clean,
            featured_clean, verif_clean, status_clean, job_id
        ))
        return {"success": True, "message": "Job updated successfully."}
    except Exception as e:
        logger.error(f"Error updating job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error updating job: {e}")

@router.put("/jobs/{job_id}/status")
def update_job_status(
    job_id: int,
    status: str = Form(...),
    admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)
):
    """
    Quick status toggle (e.g. published, closed, expired, draft, archived).
    Normalizes status string and ensures is_archived is properly set/unset.
    """
    clean_status = (str(status) or "").lower().strip()
    allowed_statuses = ["draft", "pending_review", "published", "closed", "expired", "archived"]
    if clean_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status '{status}'. Must be one of {allowed_statuses}")

    if not db_helpers["db_enabled"] or not db_helpers["execute_db"]:
        from routers.jobs import FALLBACK_JOBS
        match = next((j for j in FALLBACK_JOBS if j["id"] == job_id), None)
        if match:
            match["status"] = clean_status
            match["is_archived"] = (clean_status == "archived")
            if clean_status == "published":
                match["published_at"] = "2026-08-27T12:00:00"
        return {"success": True, "message": f"Job status updated to {clean_status}."}

    try:
        query = """
            UPDATE jobs 
            SET status = %s,
                is_archived = CASE WHEN %s = 'archived' THEN TRUE ELSE FALSE END,
                published_at = CASE WHEN %s = 'published' AND published_at IS NULL THEN CURRENT_TIMESTAMP ELSE published_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """
        db_helpers["execute_db"](query, (clean_status, clean_status, clean_status, job_id))
        return {"success": True, "message": f"Job status updated to {clean_status}."}
    except Exception as e:
        logger.error(f"Error updating status for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error updating status: {e}")

@router.delete("/jobs/bulk")
@router.post("/jobs/bulk-delete")
async def bulk_delete_admin_jobs(
    request: Request = None,
    payload: Optional[Dict[str, Any]] = Body(None),
    admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)
):
    """
    BULK DELETE JOBS
    Deletes multiple selected jobs transactionally.
    Accepts JSON body: {"job_ids": [1, 2, 3]}
    """
    job_ids = []
    if payload and isinstance(payload, dict) and "job_ids" in payload:
        job_ids = payload.get("job_ids", [])
    elif request:
        try:
            body = await request.json()
            if isinstance(body, dict):
                job_ids = body.get("job_ids", [])
            elif isinstance(body, list):
                job_ids = body
        except Exception:
            pass

    # Clean & validate integer IDs
    clean_ids = []
    for jid in job_ids:
        try:
            val = int(jid)
            if val > 0:
                clean_ids.append(val)
        except (ValueError, TypeError):
            continue

    clean_ids = list(set(clean_ids)) # Deduplicate

    if not clean_ids:
        raise HTTPException(status_code=400, detail="No valid job IDs provided for bulk deletion.")

    if not db_helpers["db_enabled"] or not db_helpers["execute_db"]:
        from routers.jobs import FALLBACK_JOBS
        initial_len = len(FALLBACK_JOBS)
        FALLBACK_JOBS[:] = [j for j in FALLBACK_JOBS if j["id"] not in clean_ids]
        deleted_cnt = initial_len - len(FALLBACK_JOBS)
        return {
            "success": True,
            "message": f"{deleted_cnt} job(s) deleted successfully.",
            "deleted_count": deleted_cnt,
            "deleted_ids": clean_ids
        }

    try:
        # Check how many exist and how many are currently published
        records = db_helpers["query_db"](
            "SELECT id, status, is_archived FROM jobs WHERE id = ANY(%s);",
            (clean_ids,)
        )
        if not records:
            return {
                "success": True,
                "message": "0 jobs deleted (none of the provided IDs were found).",
                "deleted_count": 0,
                "deleted_ids": []
            }

        valid_ids = [r["id"] for r in records]
        published_count = sum(1 for r in records if (r.get("status") or "").lower() == "published" and not r.get("is_archived"))

        # Transactionally nullify / delete FK references for all valid IDs
        db_helpers["execute_db"]("UPDATE raw_job_ingestions SET matched_job_id = NULL WHERE matched_job_id = ANY(%s);", (valid_ids,))
        db_helpers["execute_db"]("UPDATE jobs SET duplicate_of_job_id = NULL WHERE duplicate_of_job_id = ANY(%s);", (valid_ids,))
        db_helpers["execute_db"]("DELETE FROM job_sources WHERE job_id = ANY(%s);", (valid_ids,))
        db_helpers["execute_db"]("DELETE FROM job_applications WHERE job_id = ANY(%s);", (valid_ids,))
        db_helpers["execute_db"]("DELETE FROM jobs WHERE id = ANY(%s);", (valid_ids,))

        return {
            "success": True,
            "message": f"{len(valid_ids)} job(s) deleted successfully.",
            "deleted_count": len(valid_ids),
            "deleted_ids": valid_ids,
            "published_deleted_count": published_count
        }
    except Exception as e:
        logger.error(f"Error performing bulk job deletion: {e}")
        raise HTTPException(status_code=500, detail=f"Database error deleting jobs: {e}")

@router.delete("/jobs/{job_id}")
def archive_admin_job(
    job_id: int,
    admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)
):
    """
    SOFT DELETE / ARCHIVE JOB
    Safely marks job as is_archived = TRUE and status = 'archived' without deleting record.
    """
    if not db_helpers["db_enabled"] or not db_helpers["execute_db"]:
        from routers.jobs import FALLBACK_JOBS
        match = next((j for j in FALLBACK_JOBS if j["id"] == job_id), None)
        if match:
            match["is_archived"] = True
            match["status"] = "archived"
        return {"success": True, "message": "Job archived successfully (soft deleted)."}

    try:
        query = """
            UPDATE jobs 
            SET is_archived = TRUE, status = 'archived', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """
        db_helpers["execute_db"](query, (job_id,))
        return {"success": True, "message": "Job archived successfully (soft deleted)."}
    except Exception as e:
        logger.error(f"Error archiving job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error archiving job: {e}")

@router.delete("/jobs/{job_id}/delete")
def delete_single_admin_job(
    job_id: int,
    admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)
):
    """
    PERMANENT / HARD DELETE SINGLE JOB
    Removes job and transactionally cleans up foreign key references.
    """
    if not db_helpers["db_enabled"] or not db_helpers["execute_db"]:
        from routers.jobs import FALLBACK_JOBS
        idx = next((i for i, j in enumerate(FALLBACK_JOBS) if j["id"] == job_id), None)
        if idx is not None:
            FALLBACK_JOBS.pop(idx)
            return {"success": True, "message": "Job deleted successfully."}
        raise HTTPException(status_code=404, detail="Job not found.")

    try:
        # Check existence
        check = db_helpers["query_db"]("SELECT id, status, is_archived FROM jobs WHERE id = %s;", (job_id,))
        if not check:
            raise HTTPException(status_code=404, detail=f"Job #{job_id} not found.")

        # Transactionally nullify / delete FK references
        db_helpers["execute_db"]("UPDATE raw_job_ingestions SET matched_job_id = NULL WHERE matched_job_id = %s;", (job_id,))
        db_helpers["execute_db"]("UPDATE jobs SET duplicate_of_job_id = NULL WHERE duplicate_of_job_id = %s;", (job_id,))
        db_helpers["execute_db"]("DELETE FROM job_sources WHERE job_id = %s;", (job_id,))
        db_helpers["execute_db"]("DELETE FROM job_applications WHERE job_id = %s;", (job_id,))
        db_helpers["execute_db"]("DELETE FROM jobs WHERE id = %s;", (job_id,))

        return {"success": True, "message": f"Job #{job_id} deleted successfully.", "deleted_id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error deleting job: {e}")

# --- 3. COMPANIES CRUD ---

@router.get("/companies")
def get_admin_companies(admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)):
    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        from routers.jobs import FALLBACK_COMPANIES
        return FALLBACK_COMPANIES

    try:
        query = """
            SELECT c.*, COUNT(j.id) AS active_jobs_count
            FROM companies c
            LEFT JOIN jobs j ON c.id = j.company_id AND j.status = 'published' AND COALESCE(j.is_archived, FALSE) = FALSE
            GROUP BY c.id
            ORDER BY c.name ASC;
        """
        return db_helpers["query_db"](query)
    except Exception as e:
        logger.error(f"Error fetching companies: {e}")
        raise HTTPException(status_code=500, detail=f"Database error fetching companies: {e}")

@router.post("/companies")
def create_admin_company(
    name: str = Form(...),
    logo_url: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    is_verified: bool = Form(False),
    status: str = Form("ACTIVE"),
    admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)
):
    n_clean = str(name).strip() if name else ""
    logo_clean = _clean_str(logo_url)
    desc_clean = _clean_str(description)
    loc_clean = _clean_str(location)
    web_clean = _clean_str(website)
    email_clean = _clean_str(contact_email)
    phone_clean = _clean_str(contact_phone)
    verif_clean = _clean_bool(is_verified, False)
    status_clean = _clean_str(status) or "ACTIVE"

    base_slug = slugify(n_clean)
    slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    if not db_helpers["db_enabled"] or not db_helpers["execute_db_returning"]:
        from routers.jobs import FALLBACK_COMPANIES
        new_comp = {
            "id": len(FALLBACK_COMPANIES) + 1,
            "name": n_clean,
            "slug": slug,
            "logo_url": logo_clean,
            "description": desc_clean,
            "location": loc_clean,
            "website": web_clean,
            "contact_email": email_clean,
            "contact_phone": phone_clean,
            "is_verified": verif_clean,
            "status": status_clean
        }
        FALLBACK_COMPANIES.append(new_comp)
        return {"success": True, "company_id": new_comp["id"], "message": "Company profile created successfully."}

    try:
        query = """
            INSERT INTO companies (name, slug, logo_url, description, location, website, contact_email, contact_phone, is_verified, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id;
        """
        rows = db_helpers["execute_db_returning"](query, (
            n_clean, slug, logo_clean, desc_clean, loc_clean, web_clean, email_clean, phone_clean, verif_clean, status_clean
        ))
        return {"success": True, "company_id": rows[0]["id"], "message": "Company created successfully."}
    except Exception as e:
        logger.error(f"Error creating company: {e}")
        raise HTTPException(status_code=500, detail=f"Database error creating company: {e}")

@router.put("/companies/{company_id}")
def update_admin_company(
    company_id: int,
    name: str = Form(...),
    logo_url: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    is_verified: bool = Form(False),
    status: str = Form("ACTIVE"),
    admin = Depends(lambda: db_helpers["get_current_admin"]() if db_helpers["get_current_admin"] else None)
):
    n_clean = str(name).strip() if name else ""
    logo_clean = _clean_str(logo_url)
    desc_clean = _clean_str(description)
    loc_clean = _clean_str(location)
    web_clean = _clean_str(website)
    email_clean = _clean_str(contact_email)
    phone_clean = _clean_str(contact_phone)
    verif_clean = _clean_bool(is_verified, False)
    status_clean = _clean_str(status) or "ACTIVE"

    if not db_helpers["db_enabled"] or not db_helpers["execute_db"]:
        from routers.jobs import FALLBACK_COMPANIES
        match = next((c for c in FALLBACK_COMPANIES if c["id"] == company_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Company not found.")
        match.update({
            "name": n_clean,
            "logo_url": logo_clean,
            "description": desc_clean,
            "location": loc_clean,
            "website": web_clean,
            "contact_email": email_clean,
            "contact_phone": phone_clean,
            "is_verified": verif_clean,
            "status": status_clean
        })
        return {"success": True, "message": "Company updated successfully."}

    try:
        query = """
            UPDATE companies
            SET name = %s, logo_url = %s, description = %s, location = %s, website = %s,
                contact_email = %s, contact_phone = %s, is_verified = %s, status = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """
        db_helpers["execute_db"](query, (
            n_clean, logo_clean, desc_clean, loc_clean, web_clean, email_clean, phone_clean, verif_clean, status_clean, company_id
        ))
        return {"success": True, "message": "Company updated successfully."}
    except Exception as e:
        logger.error(f"Error updating company {company_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error updating company: {e}")
