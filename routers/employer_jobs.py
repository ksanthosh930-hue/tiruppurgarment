import os
import re
import uuid
import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Form, File, UploadFile
from pydantic import BaseModel, Field

from routers.public_auth import require_employer_user
from routers.admin_jobs import slugify
from services.extractor import StructuredJobExtractor

logger = logging.getLogger("DigiGarment.EmployerJobs")

router = APIRouter(prefix="/api/employer/jobs", tags=["Employer Jobs"])

# Database helpers injected from app.py
_query_db = None
_execute_db = None
_execute_db_returning = None
_db_enabled = False
_base_dir = ""

def init_employer_jobs_helpers(db_enabled_val, query_fn, exec_fn, exec_ret_fn, base_dir_path):
    global _db_enabled, _query_db, _execute_db, _execute_db_returning, _base_dir
    _db_enabled = db_enabled_val
    _query_db = query_fn
    _execute_db = exec_fn
    _execute_db_returning = exec_ret_fn
    _base_dir = base_dir_path

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
    status: Optional[str] = "pending_review"  # 'draft' or 'pending_review'

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
    status: Optional[str] = None  # 'draft' or 'pending_review'


# --- 1. List Employer's Own Jobs ---
@router.get("")
def get_employer_jobs(current_user: Dict[str, Any] = Depends(require_employer_user)):
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        return {"success": True, "jobs": [], "total": 0}

    try:
        query = """
            SELECT 
                j.id, j.title, j.slug, j.department, j.job_role, j.job_type,
                j.location, j.openings_count, j.experience_min, j.experience_max,
                j.salary_min, j.salary_max, j.salary_text, j.description, j.requirements,
                j.skills, j.qualification, j.gender, j.contact_phone, j.contact_whatsapp,
                j.contact_email, j.poster_image_url, j.status, j.rejection_reason,
                j.published_at, j.created_at, j.updated_at,
                COALESCE(cp.company_name, '') AS company_name,
                COALESCE(cp.verification_status, 'pending') AS employer_verification_status
            FROM jobs j
            LEFT JOIN company_profiles cp ON j.company_profile_id = cp.id
            WHERE (j.company_profile_id = %s OR j.employer_user_id = %s)
            ORDER BY j.id DESC;
        """
        rows = _query_db(query, (profile_id, user_id))
        return {
            "success": True,
            "jobs": rows,
            "total": len(rows),
            "employer_verification_status": profile.get("verification_status", "pending")
        }
    except Exception as e:
        logger.error(f"Error fetching employer jobs: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 2. Create New Job (Draft or Submit for Review) ---
@router.post("")
def create_employer_job(
    req: EmployerJobCreateRequest,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    user_id = current_user["id"]
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

    # Job Role fallback
    if not r_clean:
        r_clean = t_clean

    if not t_clean:
        raise HTTPException(status_code=400, detail="Job Title is required.")
    if not d_clean:
        raise HTTPException(status_code=400, detail="Department is required.")
    if not desc_clean:
        raise HTTPException(status_code=400, detail="Job Description is required.")

    # Status: only 'draft' or 'pending_review' allowed on creation
    target_status = (req.status or "").strip().lower()
    if target_status not in ("draft", "pending_review"):
        target_status = "pending_review"

    # Default contact info to company profile if empty
    phone_clean = _clean_str(req.contact_phone) or profile.get("mobile")
    wa_clean = _clean_str(req.contact_whatsapp) or profile.get("whatsapp") or profile.get("mobile")
    email_clean = _clean_str(req.contact_email) or profile.get("email") or current_user.get("email")
    openings_cnt = max(int(req.vacancies or req.openings_count or 1), 1)

    # Unique slug using existing slugify
    base_slug = slugify(t_clean) or "job"
    slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    if not _db_enabled or not _execute_db_returning:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    try:
        query = """
            INSERT INTO jobs (
                company_profile_id, employer_user_id, title, slug, department, job_role,
                job_type, location, openings_count, experience_min, experience_max,
                salary_min, salary_max, salary_text, description, requirements,
                skills, qualification, gender, contact_phone, contact_whatsapp,
                contact_email, poster_image_url, source_type, source_name,
                status, is_featured, is_archived, verification_status,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, 'employer', 'Employer Direct Posting',
                %s, FALSE, FALSE, %s,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) RETURNING id;
        """
        verif_status = profile.get("verification_status", "pending")
        rows = _execute_db_returning(query, (
            profile_id, user_id, t_clean, slug, d_clean, r_clean,
            req.job_type or "Full Time", loc_clean, openings_cnt,
            int(req.experience_min or 0), _clean_num(req.experience_max),
            _clean_num(req.salary_min), _clean_num(req.salary_max), _clean_str(req.salary_text),
            desc_clean, _clean_str(req.requirements),
            skills_str, _clean_str(req.qualification), _clean_str(req.gender) or "Any",
            phone_clean, wa_clean, email_clean, _clean_str(req.poster_image_url),
            target_status, verif_status
        ))

        job_id = rows[0]["id"]
        msg = (
            "Job saved as draft." if target_status == "draft"
            else "Job submitted successfully. Your job is now pending DigiGarment review."
        )
        return {
            "success": True,
            "job_id": job_id,
            "slug": slug,
            "status": target_status,
            "job": {
                "id": job_id,
                "slug": slug,
                "status": target_status
            },
            "message": msg
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating employer job: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 3. Get Single Job Details (Ownership Enforced) ---
@router.get("/{job_id}")
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

        # Server-side ownership check: must match current employer's company_profile_id or employer_user_id
        if job.get("company_profile_id") != profile_id and job.get("employer_user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied. You do not own this job posting.")

        return {"success": True, "job": job}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 4. Update Existing Job (Draft / Rejected jobs only) ---
@router.put("/{job_id}")
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
        # Check ownership and current status
        rows = _query_db("SELECT id, status, company_profile_id, employer_user_id FROM jobs WHERE id = %s;", (job_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found.")

        job = rows[0]
        if job.get("company_profile_id") != profile_id and job.get("employer_user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied. You do not own this job posting.")

        current_status = (job.get("status") or "").lower()
        if current_status in ("published", "pending_review"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot edit a job with status '{current_status}'. Please contact admin if urgent changes are needed."
            )

        t_clean = (req.title or "").strip()
        d_clean = (req.department or "").strip()
        r_clean = (req.job_role or "").strip() or t_clean
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

        if not t_clean or not d_clean or not desc_clean:
            raise HTTPException(status_code=400, detail="Title, Department, and Description are required.")

        # Determine target status
        target_status = (req.status or "").strip().lower()
        if target_status not in ("draft", "pending_review"):
            target_status = "pending_review" if current_status == "rejected" else current_status

        # Clear rejection reason if resubmitting for review
        clear_rejection = (target_status == "pending_review")

        query = """
            UPDATE jobs
            SET title = %s, department = %s, job_role = %s, job_type = %s,
                location = %s, openings_count = %s, experience_min = %s, experience_max = %s,
                salary_min = %s, salary_max = %s, salary_text = %s, description = %s,
                requirements = %s, skills = %s, qualification = %s, gender = %s,
                contact_phone = %s, contact_whatsapp = %s, contact_email = %s,
                poster_image_url = %s, status = %s,
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
            clear_rejection, job_id
        ))

        msg = (
            "Job submitted for review." if target_status == "pending_review"
            else "Job draft updated successfully."
        )
        return {
            "success": True,
            "status": target_status,
            "job": {
                "id": job_id,
                "status": target_status
            },
            "message": msg
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 5. Submit Draft/Rejected Job for Admin Review ---
@router.post("/{job_id}/submit")
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
        rows = _query_db("SELECT id, status, company_profile_id, employer_user_id FROM jobs WHERE id = %s;", (job_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found.")

        job = rows[0]
        if job.get("company_profile_id") != profile_id and job.get("employer_user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied. You do not own this job.")

        current_status = (job.get("status") or "").lower()
        if current_status not in ("draft", "rejected"):
            raise HTTPException(status_code=400, detail=f"Job is already in '{current_status}' status.")

        _execute_db("""
            UPDATE jobs
            SET status = 'pending_review', rejection_reason = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """, (job_id,))

        return {
            "success": True,
            "status": "pending_review",
            "job": {
                "id": job_id,
                "status": "pending_review"
            },
            "message": "Job submitted successfully. Your job is now pending DigiGarment review."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 6. Delete Draft Job Only (Strict State Protection) ---
@router.delete("/{job_id}")
def delete_employer_draft_job(
    job_id: int,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    user_id = current_user["id"]
    profile = current_user.get("profile", {})
    profile_id = profile.get("id")

    if not _db_enabled or not _query_db:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    try:
        rows = _query_db("SELECT id, status, company_profile_id, employer_user_id FROM jobs WHERE id = %s;", (job_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Job not found.")

        job = rows[0]
        if job.get("company_profile_id") != profile_id and job.get("employer_user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied. You do not own this job.")

        current_status = (job.get("status") or "").lower()
        if current_status != "draft":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete a job with status '{current_status}'. Only 'draft' jobs may be deleted."
            )

        _execute_db("DELETE FROM jobs WHERE id = %s;", (job_id,))
        return {"success": True, "message": "Draft job deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting draft job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 7. Poster AI / OCR Extraction Assistant (Reusing Existing Pipeline) ---
@router.post("/extract-poster")
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

        # Read file with size check (5 MB limit)
        content = await file.read()
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Poster file size must be less than 5 MB.")

        image_bytes = content
        image_mime = file.content_type

        # Save to source_vault securely
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
