import os
import re
import uuid
import shutil
import mimetypes
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Form, UploadFile, File, Query, Request, Body
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["Public Jobs"])

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESUME_DIR = os.path.join(BASE_DIR, "assets", "uploads", "resumes")
os.makedirs(RESUME_DIR, exist_ok=True)

# Database helper injectors (will be configured by app.py)
db_helpers = {
    "db_enabled": False,
    "query_db": None,
    "execute_db": None,
    "execute_db_returning": None
}

def init_db_helpers(enabled: bool, query_fn, exec_fn, exec_ret_fn):
    db_helpers["db_enabled"] = enabled
    db_helpers["query_db"] = query_fn
    db_helpers["execute_db"] = exec_fn
    db_helpers["execute_db_returning"] = exec_ret_fn

# --- FALLBACK DATASETS (Ensures offline resilience) ---
FALLBACK_COMPANIES = [
    {
        "id": 1,
        "name": "[DEMO] Test Garments India",
        "slug": "demo-test-garments-india",
        "logo_url": "/assets/images/logo-dark.png",
        "description": "DEMO TEST RECORD: Sample garment exporter for development testing.",
        "location": "Angeripalayam, Tiruppur",
        "website": "https://example.com",
        "contact_email": "demo.contact@example.com",
        "contact_phone": "+91 99999 00001",
        "is_verified": False,
        "status": "ACTIVE"
    },
    {
        "id": 2,
        "name": "[DEMO] Sample Knitwear Corp",
        "slug": "demo-sample-knitwear-corp",
        "logo_url": "/assets/images/logo-light.png",
        "description": "DEMO TEST RECORD: Sample spinning and knitting unit.",
        "location": "Veerapandi, Tiruppur",
        "website": "https://example.com",
        "contact_email": "demo.hr@example.com",
        "contact_phone": "+91 99999 00002",
        "is_verified": False,
        "status": "ACTIVE"
    }
]

FALLBACK_JOBS = [
    {
        "id": 1,
        "company_id": 1,
        "company_name": "[DEMO] Test Garments India",
        "company_logo": "/assets/images/logo-dark.png",
        "company_is_verified": False,
        "title": "[DEMO] Senior Merchandiser (Woven & Knits)",
        "slug": "demo-senior-merchandiser-woven-knits",
        "department": "Merchandising",
        "job_role": "Senior Merchandiser",
        "job_type": "Full Time",
        "location": "Angeripalayam, Tiruppur",
        "experience_min": 4,
        "experience_max": 8,
        "salary_min": 35000,
        "salary_max": 50000,
        "salary_text": "₹35,000 - ₹50,000 / month",
        "description": "DEMO TEST VACANCY ONLY: Responsible for buyer communication, sample follow-ups, costing, order execution, and production coordination across cutting, printing, and sewing departments.",
        "requirements": "Candidate must have relevant experience in Tiruppur export houses handling US/European buyers with strong communication skills.",
        "skills": "Sampling, Costing, TNA, Buyer Communication, ERP",
        "qualification": "Degree / Diploma in Fashion Tech or Garment Manufacturing",
        "gender": "Any",
        "contact_phone": "+91 99999 00001",
        "contact_whatsapp": "+91 99999 00001",
        "contact_email": "demo.jobs@example.com",
        "application_url": "",
        "source_type": "manual",
        "source_name": "Direct Admin Entry",
        "poster_image_url": "",
        "status": "published",
        "is_featured": True,
        "is_archived": False,
        "verification_status": "verified",
        "published_at": "2026-08-27T10:00:00"
    },
    {
        "id": 2,
        "company_id": 2,
        "company_name": "[DEMO] Sample Knitwear Corp",
        "company_logo": "/assets/images/logo-light.png",
        "company_is_verified": False,
        "title": "[DEMO] Quality Control Supervisor",
        "slug": "demo-quality-control-supervisor",
        "department": "Quality",
        "job_role": "Quality Supervisor",
        "job_type": "Full Time",
        "location": "Veerapandi, Tiruppur",
        "experience_min": 2,
        "experience_max": 5,
        "salary_min": 20000,
        "salary_max": 28000,
        "salary_text": "₹20,000 - ₹28,000 / month",
        "description": "DEMO TEST VACANCY ONLY: In-line and end-line garment inspection, AQL standards compliance, sewing defects auditing and line balancing.",
        "requirements": "Floor supervision experience in circular knitting and sewing units with understanding of 4-point fabric inspection.",
        "skills": "AQL 2.5/4.0, Sewing Defects Identification, Measurement Checking",
        "qualification": "Diploma in Textile Technology / Higher Secondary",
        "gender": "Any",
        "contact_phone": "+91 99999 00002",
        "contact_whatsapp": "+91 99999 00002",
        "contact_email": "",
        "application_url": "",
        "source_type": "manual",
        "source_name": "Direct Admin Entry",
        "poster_image_url": "",
        "status": "published",
        "is_featured": False,
        "is_archived": False,
        "verification_status": "unverified",
        "published_at": "2026-08-27T11:00:00"
    },
    {
        "id": 3,
        "company_id": 1,
        "company_name": "[DEMO] Test Garments India",
        "company_logo": "/assets/images/logo-dark.png",
        "company_is_verified": False,
        "title": "[DEMO] Pattern Master (CAD & Manual)",
        "slug": "demo-pattern-master-cad-manual",
        "department": "Cutting",
        "job_role": "Pattern Master",
        "job_type": "Full Time",
        "location": "Avinashi Road, Tiruppur",
        "experience_min": 5,
        "experience_max": 10,
        "salary_min": 30000,
        "salary_max": 45000,
        "salary_text": "₹30,000 - ₹45,000 / month",
        "description": "DEMO TEST VACANCY ONLY: Creating accurate master patterns, shrinkage calculations, marker planning, and fitting adjustments for knitted apparel.",
        "requirements": "Proficiency in manual grading and CAD software (Optitex / Gerber / Lectra).",
        "skills": "Optitex, Pattern Grading, Marker Planning, Shrinkage Calculation",
        "qualification": "Diploma in Apparel Pattern Making / Equivalent Experience",
        "gender": "Any",
        "contact_phone": "+91 99999 00001",
        "contact_whatsapp": "",
        "contact_email": "demo.jobs@example.com",
        "application_url": "",
        "source_type": "manual",
        "source_name": "Direct Admin Entry",
        "poster_image_url": "",
        "status": "published",
        "is_featured": False,
        "is_archived": False,
        "verification_status": "verified",
        "published_at": "2026-08-27T12:00:00"
    }
]

# In-memory candidate storage for offline mode
FALLBACK_CANDIDATES = []
FALLBACK_APPLICATIONS = []
FALLBACK_SAVED_JOBS = []

# --- PUBLIC ENDPOINTS ---

@router.get("/jobs")
def get_public_jobs(
    q: Optional[str] = Query(None, description="Search keyword in title, role, skills, description"),
    department: Optional[str] = Query(None, description="Filter by department"),
    role: Optional[str] = Query(None, description="Filter by job role"),
    location: Optional[str] = Query(None, description="Filter by location/area"),
    experience: Optional[int] = Query(None, description="Max experience requirement"),
    salary_min: Optional[float] = Query(None, description="Minimum salary filter"),
    job_type: Optional[str] = Query(None, description="Full Time, Part Time, Contract"),
    sort: Optional[str] = Query("latest", description="latest, salary_high"),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50)
):
    """
    Public paginated jobs search & multi-facet filtering.
    Only returns published and non-archived jobs.
    """
    # Parameter normalization for both FastAPI and direct Python invocation
    q_str = str(q).strip() if isinstance(q, str) and q.strip() else None
    dept_str = str(department).strip() if isinstance(department, str) and department.strip() else None
    role_str = str(role).strip() if isinstance(role, str) and role.strip() else None
    loc_str = str(location).strip() if isinstance(location, str) and location.strip() else None
    exp_val = experience if isinstance(experience, (int, float)) and not isinstance(experience, bool) and experience > 0 else None
    sal_val = salary_min if isinstance(salary_min, (int, float)) and not isinstance(salary_min, bool) and salary_min > 0 else None
    type_str = str(job_type).strip() if isinstance(job_type, str) and job_type.strip() else None
    sort_str = str(sort).strip() if isinstance(sort, str) and sort.strip() else "latest"
    page_num = page if isinstance(page, int) and page >= 1 else 1
    limit_num = limit if isinstance(limit, int) and limit >= 1 else 12

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        # Filter fallback in-memory list
        filtered = [j for j in FALLBACK_JOBS if j.get("status") == "published" and not j.get("is_archived", False)]
        
        if q_str:
            term = q_str.lower()
            filtered = [
                j for j in filtered
                if term in j.get("title", "").lower()
                or term in j.get("department", "").lower()
                or term in j.get("job_role", "").lower()
                or term in j.get("skills", "").lower()
                or term in j.get("description", "").lower()
                or term in j.get("company_name", "").lower()
            ]
            
        if dept_str and dept_str != "All":
            filtered = [j for j in filtered if j.get("department", "").lower() == dept_str.lower()]
            
        if role_str and role_str != "All":
            filtered = [j for j in filtered if j.get("job_role", "").lower() == role_str.lower()]
            
        if loc_str and loc_str != "All":
            filtered = [j for j in filtered if loc_str.lower() in j.get("location", "").lower()]
            
        if exp_val is not None and exp_val > 0:
            filtered = [j for j in filtered if j.get("experience_min", 0) <= exp_val]
            
        if sal_val is not None and sal_val > 0:
            filtered = [j for j in filtered if (j.get("salary_max") or j.get("salary_min") or 0) >= sal_val]
            
        if type_str and type_str != "All":
            filtered = [j for j in filtered if j.get("job_type", "").lower() == type_str.lower()]
            
        total = len(filtered)
        start = (page_num - 1) * limit_num
        end = start + limit_num
        paginated_jobs = filtered[start:end]
        total_pages = max(1, (total + limit_num - 1) // limit_num)
        
        return {
            "success": True,
            "jobs": paginated_jobs,
            "page": page_num,
            "limit": limit_num,
            "total": total,
            "total_pages": total_pages
        }

    try:
        conditions = [
            "LOWER(j.status) = 'published'",
            "COALESCE(j.is_archived, FALSE) = FALSE"
        ]
        params = []

        if q_str:
            term = f"%{q_str}%"
            conditions.append("""
                (j.title ILIKE %s 
                 OR j.slug ILIKE %s
                 OR COALESCE(j.department, '') ILIKE %s 
                 OR COALESCE(j.job_role, '') ILIKE %s 
                 OR COALESCE(j.skills, '') ILIKE %s 
                 OR COALESCE(j.description, '') ILIKE %s 
                 OR COALESCE(c.name, '') ILIKE %s)
            """)
            params.extend([term] * 7)

        if dept_str and dept_str != "All":
            conditions.append("j.department = %s")
            params.append(dept_str)

        if role_str and role_str != "All":
            conditions.append("j.job_role = %s")
            params.append(role_str)

        if loc_str and loc_str != "All":
            conditions.append("j.location ILIKE %s")
            params.append(f"%{loc_str}%")

        if exp_val is not None and exp_val > 0:
            conditions.append("j.experience_min <= %s")
            params.append(exp_val)

        if sal_val is not None and sal_val > 0:
            conditions.append("(j.salary_max >= %s OR j.salary_min >= %s)")
            params.extend([sal_val, sal_val])

        if type_str and type_str != "All":
            conditions.append("j.job_type = %s")
            params.append(type_str)

        where_clause = " WHERE " + " AND ".join(conditions)

        # Count total
        count_query = f"""
            SELECT COUNT(*) 
            FROM jobs j 
            LEFT JOIN companies c ON j.company_id = c.id
            {where_clause};
        """
        count_rows = db_helpers["query_db"](count_query, tuple(params) if params else None)
        total = count_rows[0]["count"] if count_rows else 0

        # Sort order
        order_clause = "ORDER BY j.is_featured DESC, j.published_at DESC NULLS LAST, j.id DESC"
        if sort_str == "salary_high":
            order_clause = "ORDER BY j.salary_max DESC NULLS LAST, j.published_at DESC NULLS LAST"

        offset = (page_num - 1) * limit_num
        data_query = f"""
            SELECT 
                j.id, j.company_id, j.title, j.slug, j.department, j.job_role, j.job_type,
                j.location, j.openings_count, j.experience_min, j.experience_max, j.salary_min, j.salary_max,
                j.salary_text, j.description, j.requirements, j.skills, j.qualification,
                j.gender, j.contact_phone, j.contact_whatsapp, j.contact_email, j.application_url,
                j.source_type, j.source_name, j.poster_image_url, j.status, j.is_featured,
                j.verification_status, j.published_at, j.expires_at, j.created_at,
                COALESCE(cp.company_name, c.name, '') AS company_name,
                COALESCE(cp.company_logo, c.logo_url, '') AS company_logo,
                c.slug AS company_slug,
                COALESCE(cp.location, c.location, j.location) AS company_location,
                CASE WHEN cp.verification_status = 'verified' THEN TRUE WHEN c.is_verified = TRUE THEN TRUE ELSE FALSE END AS company_is_verified,
                COALESCE(cp.verification_status, 'pending') AS employer_verification_status
            FROM jobs j
            LEFT JOIN companies c ON j.company_id = c.id
            LEFT JOIN company_profiles cp ON j.company_profile_id = cp.id
            {where_clause}
            {order_clause}
            LIMIT %s OFFSET %s;
        """
        query_params = list(params)
        query_params.extend([limit_num, offset])

        rows = db_helpers["query_db"](data_query, tuple(query_params))
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
        logger.error(f"Error querying public jobs: {e}")
        return {
            "success": False,
            "jobs": [],
            "page": 1,
            "limit": limit_num,
            "total": 0,
            "total_pages": 1,
            "error": "Failed to load jobs."
        }

@router.get("/jobs/{slug}")
def get_public_job_detail(slug: str):
    """
    Fetches full detail of a single active published job by slug or ID.
    """
    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        matches = [j for j in FALLBACK_JOBS if (j.get("slug") == slug or str(j.get("id")) == slug) and (j.get("status") or "").lower() == "published" and not j.get("is_archived")]
        if not matches:
            raise HTTPException(status_code=404, detail="Job posting not found or no longer active.")
        return {"success": True, "job": matches[0]}

    try:
        query = """
            SELECT 
                j.id, j.company_id, j.company_profile_id, j.title, j.slug, j.department, j.job_role, j.job_type,
                j.location, j.openings_count, j.experience_min, j.experience_max, j.salary_min, j.salary_max,
                j.salary_text, j.description, j.requirements, j.skills, j.qualification,
                j.gender, j.contact_phone, j.contact_whatsapp, j.contact_email, j.application_url,
                j.source_type, j.source_name, j.poster_image_url, j.status, j.is_featured,
                j.verification_status, j.published_at, j.expires_at, j.created_at,
                COALESCE(cp.company_name, c.name, '') AS company_name,
                COALESCE(cp.company_logo, c.logo_url, '') AS company_logo,
                c.slug AS company_slug,
                COALESCE(cp.company_description, c.description, '') AS company_description,
                COALESCE(cp.website, c.website, '') AS company_website,
                COALESCE(cp.location, c.location, j.location) AS company_location,
                CASE WHEN cp.verification_status = 'verified' THEN TRUE WHEN c.is_verified = TRUE THEN TRUE ELSE FALSE END AS company_is_verified,
                COALESCE(cp.verification_status, 'pending') AS employer_verification_status
            FROM jobs j
            LEFT JOIN companies c ON j.company_id = c.id
            LEFT JOIN company_profiles cp ON j.company_profile_id = cp.id
            WHERE (j.slug = %s OR CAST(j.id AS VARCHAR) = %s)
              AND LOWER(j.status) = 'published'
              AND COALESCE(j.is_archived, FALSE) = FALSE;
        """
        rows = db_helpers["query_db"](query, (str(slug), str(slug)))
        if not rows:
            raise HTTPException(status_code=404, detail="Job posting not found or no longer active.")
        return {"success": True, "job": rows[0]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching job {slug}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load job details: {e}")

@router.get("/jobs-filters-meta")
def get_filters_meta():
    """
    Returns available departments, roles, and locations for UI filter pills/dropdowns.
    """
    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        departments = sorted(list(set(j["department"] for j in FALLBACK_JOBS)))
        roles = sorted(list(set(j["job_role"] for j in FALLBACK_JOBS)))
        locations = sorted(list(set(j["location"] for j in FALLBACK_JOBS)))
        return {
            "departments": departments,
            "roles": roles,
            "locations": locations,
            "job_types": ["Full Time", "Part Time", "Contract"]
        }

    try:
        dept_rows = db_helpers["query_db"]("SELECT DISTINCT department FROM jobs WHERE status = 'published' AND is_archived = FALSE ORDER BY department ASC;")
        role_rows = db_helpers["query_db"]("SELECT DISTINCT job_role FROM jobs WHERE status = 'published' AND is_archived = FALSE ORDER BY job_role ASC;")
        loc_rows = db_helpers["query_db"]("SELECT DISTINCT location FROM jobs WHERE status = 'published' AND is_archived = FALSE ORDER BY location ASC;")
        
        return {
            "departments": [r["department"] for r in dept_rows if r.get("department")],
            "roles": [r["job_role"] for r in role_rows if r.get("job_role")],
            "locations": [r["location"] for r in loc_rows if r.get("location")],
            "job_types": ["Full Time", "Part Time", "Contract"]
        }
    except Exception as e:
        logger.error(f"Error loading filter metadata: {e}")
        return {
            "departments": ["Cutting", "Merchandising", "Quality", "Sewing", "Finishing", "Printing", "Accounts"],
            "roles": ["Senior Merchandiser", "Quality Supervisor", "Pattern Master", "Line Supervisor", "Production Manager"],
            "locations": ["Angeripalayam, Tiruppur", "Veerapandi, Tiruppur", "Avinashi Road, Tiruppur", "Palladam Road, Tiruppur", "Netaji Apparel Park, Tiruppur"],
            "job_types": ["Full Time", "Part Time", "Contract"]
        }

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

@router.post("/candidates/register")
def register_candidate(
    full_name: str = Form(...),
    mobile: str = Form(...),
    whatsapp_number: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    job_role: Optional[str] = Form(None),
    experience_years: Optional[float] = Form(0.0),
    skills: Optional[str] = Form(None),
    current_company: Optional[str] = Form(None),
    expected_salary: Optional[str] = Form(None),
    preferred_location: Optional[str] = Form(None),
    resume_url: Optional[str] = Form(None)
):
    """
    Registers a job seeker candidate.
    DUPLICATE PREVENTION: Checks existing user by mobile number.
    If mobile exists -> updates profile and reuses existing user record.
    If new -> creates user and creates profile.
    """
    name_clean = str(full_name).strip() if full_name else ""
    raw_mobile = str(mobile).strip() if mobile else ""
    clean_mobile = re.sub(r'[^0-9+]', '', raw_mobile)
    if not clean_mobile or len(clean_mobile) < 10:
        raise HTTPException(status_code=400, detail="Please provide a valid 10-digit mobile phone number.")

    wa_clean = _clean_str(whatsapp_number) or clean_mobile
    loc_clean = _clean_str(location)
    dept_clean = _clean_str(department)
    role_clean = _clean_str(job_role)
    exp_clean = _clean_num(experience_years, 0.0)
    skills_clean = _clean_str(skills)
    comp_clean = _clean_str(current_company)
    sal_clean = _clean_str(expected_salary)
    pref_loc_clean = _clean_str(preferred_location)
    resume_clean = _clean_str(resume_url)

    if not db_helpers["db_enabled"] or not db_helpers["execute_db"]:
        # Offline mock
        existing = next((c for c in FALLBACK_CANDIDATES if c["mobile"] == clean_mobile), None)
        if existing:
            existing.update({
                "full_name": name_clean,
                "whatsapp_number": wa_clean,
                "location": loc_clean,
                "department": dept_clean,
                "job_role": role_clean,
                "experience_years": exp_clean,
                "skills": skills_clean,
                "current_company": comp_clean,
                "expected_salary": sal_clean,
                "preferred_location": pref_loc_clean,
                "resume_url": resume_clean or existing.get("resume_url")
            })
            return {"success": True, "is_existing": True, "message": "Candidate profile updated successfully."}
        else:
            FALLBACK_CANDIDATES.append({
                "id": len(FALLBACK_CANDIDATES) + 1,
                "full_name": name_clean,
                "mobile": clean_mobile,
                "whatsapp_number": wa_clean,
                "location": loc_clean,
                "department": dept_clean,
                "job_role": role_clean,
                "experience_years": exp_clean,
                "skills": skills_clean,
                "current_company": comp_clean,
                "expected_salary": sal_clean,
                "preferred_location": pref_loc_clean,
                "resume_url": resume_clean
            })
            return {"success": True, "is_existing": False, "message": "Candidate profile registered successfully."}

    try:
        # Check if profile with this mobile already exists
        profile_rows = db_helpers["query_db"]("SELECT id, user_id FROM job_seeker_profiles WHERE mobile = %s;", (clean_mobile,))
        
        if profile_rows:
            profile_id = profile_rows[0]["id"]
            user_id = profile_rows[0]["user_id"]
            # Update existing profile
            update_sql = """
                UPDATE job_seeker_profiles
                SET full_name = %s, whatsapp_number = %s, location = %s, department = %s,
                    job_role = %s, experience_years = %s, skills = %s, current_company = %s,
                    expected_salary = %s, preferred_location = %s, 
                    resume_url = COALESCE(%s, resume_url), updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """
            db_helpers["execute_db"](update_sql, (
                name_clean, wa_clean, loc_clean, dept_clean,
                role_clean, exp_clean, skills_clean, comp_clean, sal_clean,
                pref_loc_clean, resume_clean, profile_id
            ))
            return {
                "success": True,
                "profile_id": profile_id,
                "user_id": user_id,
                "is_existing": True,
                "message": "Candidate profile updated successfully."
            }
        else:
            # Check or create user record
            username = f"seeker_{clean_mobile[-10:]}"
            email = f"seeker_{clean_mobile[-10:]}@candidate.digigarment.local"
            user_rows = db_helpers["query_db"]("SELECT id FROM users WHERE username = %s;", (username,))
            
            if user_rows:
                user_id = user_rows[0]["id"]
            else:
                user_insert = """
                    INSERT INTO users (username, email, password_hash, is_active, created_at, updated_at)
                    VALUES (%s, %s, 'UNSET_CANDIDATE_NO_PASSWORD', TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id;
                """
                user_res = db_helpers["execute_db_returning"](user_insert, (username, email))
                user_id = user_res[0]["id"]

            # Create profile
            profile_insert = """
                INSERT INTO job_seeker_profiles (
                    user_id, full_name, mobile, whatsapp_number, location, department,
                    job_role, experience_years, skills, current_company, expected_salary,
                    preferred_location, resume_url, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                ) RETURNING id;
            """
            prof_res = db_helpers["execute_db_returning"](profile_insert, (
                user_id, name_clean, clean_mobile, wa_clean,
                loc_clean, dept_clean, role_clean, exp_clean, skills_clean, comp_clean,
                sal_clean, pref_loc_clean, resume_clean
            ))
            profile_id = prof_res[0]["id"]

            return {
                "success": True,
                "profile_id": profile_id,
                "user_id": user_id,
                "is_existing": False,
                "message": "Candidate profile registered successfully."
            }
    except Exception as e:
        logger.error(f"Candidate registration error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error registering candidate: {e}")

@router.post("/candidates/resume-upload")
def upload_resume(file: UploadFile = File(...)):
    """
    Validates and stores candidate resumes safely.
    Allows: .pdf, .doc, .docx
    Max size: 10MB
    """
    ext = os.path.splitext(file.filename)[1].lower()
    allowed_exts = [".pdf", ".doc", ".docx"]
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF, DOC, and DOCX resumes are allowed.")

    # Size check (10MB)
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Resume file exceeds maximum size limit of 10MB.")

    # Sanitized filename
    base = re.sub(r'[^a-zA-Z0-9_\-]', '_', os.path.splitext(file.filename)[0])
    safe_name = f"resume_{base}_{uuid.uuid4().hex[:8]}{ext}"
    dest_path = os.path.join(RESUME_DIR, safe_name)

    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    filepath = f"assets/uploads/resumes/{safe_name}"
    return {
        "success": True,
        "filename": file.filename,
        "filepath": filepath,
        "file_size": size,
        "message": "Resume uploaded successfully."
    }

class JobApplicationRequest(BaseModel):
    cover_message: Optional[str] = None
    resume_url: Optional[str] = None
    applicant_name: Optional[str] = None
    applicant_phone: Optional[str] = None
    applicant_email: Optional[str] = None

@router.post("/jobs/{job_id}/apply")
async def submit_job_application(
    job_id: int,
    req_body: Optional[JobApplicationRequest] = Body(None),
    applicant_name: Optional[str] = Form(None),
    applicant_phone: Optional[str] = Form(None),
    applicant_email: Optional[str] = Form(None),
    resume_url: Optional[str] = Form(None),
    cover_message: Optional[str] = Form(None),
    cover_letter: Optional[str] = Form(None),
    request: Request = None
):
    """
    Submits a direct application for a published job.
    Enforces candidate authentication, role check, eligibility, and duplicate protection.
    """
    from routers.public_auth import get_current_public_user
    
    # 1. Authenticate candidate
    session_cookie = request.cookies.get("public_session_id") if request else None
    if not session_cookie:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please sign in or register as a Job Seeker to apply."
        )
    
    current_user = await get_current_public_user(public_session_id=session_cookie)
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication session invalid or expired.")
        
    if current_user.get("account_type") != "individual":
        raise HTTPException(
            status_code=403,
            detail="Employers cannot apply for jobs. Please sign in with a Job Seeker account."
        )

    user_id = current_user["id"]
    profile = current_user.get("profile") or {}
    profile_id = profile.get("id")

    # Extract input values (supports both JSON body and multipart form)
    c_message = None
    c_resume = None
    c_name = None
    c_phone = None
    c_email = None

    if req_body:
        c_message = req_body.cover_message
        c_resume = req_body.resume_url
        c_name = req_body.applicant_name
        c_phone = req_body.applicant_phone
        c_email = req_body.applicant_email
    
    c_message = _clean_str(c_message) or _clean_str(cover_message) or _clean_str(cover_letter)
    c_resume = _clean_str(c_resume) or _clean_str(resume_url) or profile.get("resume_url")
    c_name = _clean_str(c_name) or _clean_str(applicant_name) or profile.get("full_name") or current_user.get("email")
    c_phone = _clean_str(c_phone) or _clean_str(applicant_phone) or profile.get("mobile")
    c_email = _clean_str(c_email) or _clean_str(applicant_email) or profile.get("email") or current_user.get("email")

    if not db_helpers["db_enabled"] or not db_helpers["execute_db_returning"]:
        # Fallback in-memory
        for a in FALLBACK_APPLICATIONS:
            if a.get("job_id") == job_id and a.get("candidate_user_id") == user_id:
                raise HTTPException(status_code=400, detail="You have already applied for this job vacancy.")
                
        new_app = {
            "id": len(FALLBACK_APPLICATIONS) + 1,
            "job_id": job_id,
            "candidate_user_id": user_id,
            "individual_profile_id": profile_id,
            "applicant_name": c_name,
            "applicant_phone": c_phone,
            "applicant_email": c_email,
            "resume_url": c_resume,
            "cover_message": c_message,
            "status": "submitted"
        }
        FALLBACK_APPLICATIONS.append(new_app)
        return {
            "success": True,
            "application_id": new_app["id"],
            "status": "submitted",
            "message": "Application submitted successfully."
        }

    try:
        # 2. Check Job Eligibility
        job_rows = db_helpers["query_db"]("""
            SELECT id, status, is_archived, expires_at 
            FROM jobs 
            WHERE id = %s;
        """, (job_id,))
        if not job_rows:
            raise HTTPException(status_code=404, detail="Job vacancy not found.")
            
        job = job_rows[0]
        st = (job.get("status") or "").lower()
        if st != "published" or job.get("is_archived"):
            raise HTTPException(status_code=400, detail="This job vacancy is no longer active or accepting applications.")

        # 3. Duplicate Application Protection
        dup_rows = db_helpers["query_db"]("""
            SELECT id, status FROM job_applications 
            WHERE job_id = %s AND candidate_user_id = %s;
        """, (job_id, user_id))
        if dup_rows:
            raise HTTPException(
                status_code=400,
                detail="You have already submitted an application for this vacancy."
            )

        # 4. Insert Job Application
        insert_query = """
            INSERT INTO job_applications (
                job_id, candidate_user_id, individual_profile_id,
                applicant_name, applicant_phone, applicant_email,
                resume_url, cover_message, cover_letter,
                status, applied_at, updated_at
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                'submitted', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) RETURNING id, status, applied_at;
        """
        rows = db_helpers["execute_db_returning"](insert_query, (
            job_id, user_id, profile_id,
            c_name or "Job Seeker", c_phone or "", c_email,
            c_resume, c_message, c_message
        ))

        app_id = rows[0]["id"]
        return {
            "success": True,
            "application_id": app_id,
            "status": "submitted",
            "message": "Application submitted successfully."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting job application: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong while submitting application. Please try again.")

@router.get("/employee/applications")
async def get_candidate_applications(request: Request):
    """
    Returns all applications submitted by the authenticated job seeker.
    """
    from routers.public_auth import get_current_public_user
    session_cookie = request.cookies.get("public_session_id")
    if not session_cookie:
        raise HTTPException(status_code=401, detail="Authentication required.")
        
    current_user = await get_current_public_user(public_session_id=session_cookie)
    if not current_user or current_user.get("account_type") != "individual":
        raise HTTPException(status_code=403, detail="Access denied.")

    user_id = current_user["id"]

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        my_apps = [a for a in FALLBACK_APPLICATIONS if a.get("candidate_user_id") == user_id]
        return {"success": True, "applications": my_apps, "total": len(my_apps)}

    try:
        query = """
            SELECT 
                a.id, a.job_id, a.status, a.applied_at, a.cover_message, a.resume_url,
                j.title AS job_title, j.slug AS job_slug, j.department AS job_department,
                j.job_type, j.location AS job_location, j.salary_text,
                COALESCE(cp.company_name, c.name, '') AS company_name,
                COALESCE(cp.company_logo, c.logo_url, '') AS company_logo
            FROM job_applications a
            JOIN jobs j ON a.job_id = j.id
            LEFT JOIN companies c ON j.company_id = c.id
            LEFT JOIN company_profiles cp ON j.company_profile_id = cp.id
            WHERE a.candidate_user_id = %s
            ORDER BY a.applied_at DESC;
        """
        rows = db_helpers["query_db"](query, (user_id,))
        return {
            "success": True,
            "applications": rows,
            "total": len(rows)
        }
    except Exception as e:
        logger.error(f"Error fetching candidate applications: {e}")
        raise HTTPException(status_code=500, detail="Could not load your applications.")

@router.get("/jobs/{job_id}/application-status")
async def check_job_application_status(job_id: int, request: Request):
    """
    Checks if the currently authenticated job seeker has already applied for this job.
    """
    session_cookie = request.cookies.get("public_session_id")
    if not session_cookie:
        return {"has_applied": False, "status": None}

    try:
        from routers.public_auth import get_current_public_user
        current_user = await get_current_public_user(public_session_id=session_cookie)
        if not current_user or current_user.get("account_type") != "individual":
            return {"has_applied": False, "status": None}

        user_id = current_user["id"]
        if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
            match = next((a for a in FALLBACK_APPLICATIONS if a.get("job_id") == job_id and a.get("candidate_user_id") == user_id), None)
            return {"has_applied": bool(match), "status": match.get("status") if match else None}

        rows = db_helpers["query_db"]("""
            SELECT id, status, applied_at FROM job_applications 
            WHERE job_id = %s AND candidate_user_id = %s;
        """, (job_id, user_id))

        if rows:
            return {
                "has_applied": True,
                "application_id": rows[0]["id"],
                "status": rows[0]["status"],
                "applied_at": rows[0]["applied_at"]
            }
        return {"has_applied": False, "status": None}
    except Exception:
        return {"has_applied": False, "status": None}


# --- PHASE 4A: SAVED JOBS BACKEND ENDPOINTS ---

@router.post("/jobs/{job_id}/save")
async def save_job(job_id: int, request: Request):
    """
    Saves/bookmarks a published job for the authenticated candidate.
    Enforces employee role, checks job eligibility, and prevents duplicate saves.
    """
    from routers.public_auth import get_current_public_user
    session_cookie = request.cookies.get("public_session_id")
    if not session_cookie:
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in as a Job Seeker to save jobs.")
        
    current_user = await get_current_public_user(public_session_id=session_cookie)
    if not current_user or current_user.get("account_type") != "individual":
        raise HTTPException(status_code=403, detail="Access denied. This action is strictly for Job Seekers / Employees.")

    user_id = current_user["id"]

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        # Fallback in-memory
        matches = [j for j in FALLBACK_JOBS if j.get("id") == job_id and (j.get("status") or "").lower() == "published" and not j.get("is_archived")]
        if not matches:
            raise HTTPException(status_code=400, detail="This job vacancy is not active or cannot be saved.")
        
        existing = next((s for s in FALLBACK_SAVED_JOBS if s.get("user_id") == user_id and s.get("job_id") == job_id), None)
        if not existing:
            FALLBACK_SAVED_JOBS.append({
                "id": len(FALLBACK_SAVED_JOBS) + 1,
                "user_id": user_id,
                "job_id": job_id,
                "created_at": "2026-09-24T12:00:00"
            })
        return {"success": True, "saved": True, "message": "Job saved successfully."}

    try:
        # Check Job Eligibility using existing public visibility rule
        job_rows = db_helpers["query_db"]("""
            SELECT id, status, is_archived, expires_at 
            FROM jobs 
            WHERE id = %s;
        """, (job_id,))
        
        if not job_rows:
            raise HTTPException(status_code=404, detail="Job vacancy not found.")
            
        job = job_rows[0]
        st = (job.get("status") or "").lower()
        if st != "published" or job.get("is_archived"):
            raise HTTPException(status_code=400, detail="This job vacancy is not active or cannot be saved.")

        # Idempotent insert
        insert_query = """
            INSERT INTO saved_jobs (user_id, job_id, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, job_id) DO NOTHING;
        """
        db_helpers["execute_db"](insert_query, (user_id, job_id))

        return {"success": True, "saved": True, "message": "Job saved successfully."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not save job.")


@router.delete("/jobs/{job_id}/save")
async def unsave_job(job_id: int, request: Request):
    """
    Removes a saved job bookmark for the authenticated candidate.
    """
    from routers.public_auth import get_current_public_user
    session_cookie = request.cookies.get("public_session_id")
    if not session_cookie:
        raise HTTPException(status_code=401, detail="Authentication required.")
        
    current_user = await get_current_public_user(public_session_id=session_cookie)
    if not current_user or current_user.get("account_type") != "individual":
        raise HTTPException(status_code=403, detail="Access denied.")

    user_id = current_user["id"]

    if not db_helpers["db_enabled"] or not db_helpers["execute_db"]:
        global FALLBACK_SAVED_JOBS
        FALLBACK_SAVED_JOBS = [s for s in FALLBACK_SAVED_JOBS if not (s.get("user_id") == user_id and s.get("job_id") == job_id)]
        return {"success": True, "saved": False, "message": "Job removed from saved jobs."}

    try:
        delete_query = "DELETE FROM saved_jobs WHERE user_id = %s AND job_id = %s;"
        db_helpers["execute_db"](delete_query, (user_id, job_id))
        return {"success": True, "saved": False, "message": "Job removed from saved jobs."}
    except Exception as e:
        logger.error(f"Error removing saved job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not remove saved job.")


@router.get("/employee/saved-jobs")
async def get_employee_saved_jobs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50)
):
    """
    Returns all jobs bookmarked by the authenticated job seeker with pagination metadata.
    """
    from routers.public_auth import get_current_public_user
    session_cookie = request.cookies.get("public_session_id")
    if not session_cookie:
        raise HTTPException(status_code=401, detail="Authentication required.")
        
    current_user = await get_current_public_user(public_session_id=session_cookie)
    if not current_user or current_user.get("account_type") != "individual":
        raise HTTPException(status_code=403, detail="Access denied.")

    user_id = current_user["id"]
    page_num = page if isinstance(page, int) and page >= 1 else 1
    limit_num = limit if isinstance(limit, int) and limit >= 1 else 10

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        saved_records = [s for s in FALLBACK_SAVED_JOBS if s.get("user_id") == user_id]
        matched_jobs = []
        for s in saved_records:
            j = next((item for item in FALLBACK_JOBS if item.get("id") == s["job_id"]), None)
            if j:
                job_copy = dict(j)
                job_copy["saved_at"] = s.get("created_at")
                matched_jobs.append(job_copy)
                
        total = len(matched_jobs)
        start = (page_num - 1) * limit_num
        end = start + limit_num
        paginated = matched_jobs[start:end]
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
        count_query = """
            SELECT COUNT(*) 
            FROM saved_jobs s
            JOIN jobs j ON s.job_id = j.id
            WHERE s.user_id = %s;
        """
        count_rows = db_helpers["query_db"](count_query, (user_id,))
        total = count_rows[0]["count"] if count_rows else 0

        offset = (page_num - 1) * limit_num
        data_query = """
            SELECT 
                j.id, j.company_id, j.company_profile_id, j.title, j.slug, j.department, j.job_role, j.job_type,
                j.location, j.openings_count, j.experience_min, j.experience_max, j.salary_min, j.salary_max,
                j.salary_text, j.description, j.requirements, j.skills, j.qualification,
                j.gender, j.contact_phone, j.contact_whatsapp, j.contact_email, j.application_url,
                j.source_type, j.source_name, j.poster_image_url, j.status, j.is_featured,
                j.verification_status, j.published_at, j.expires_at, j.created_at,
                s.created_at AS saved_at,
                COALESCE(cp.company_name, c.name, '') AS company_name,
                COALESCE(cp.company_logo, c.logo_url, '') AS company_logo,
                c.slug AS company_slug,
                COALESCE(cp.location, c.location, j.location) AS company_location,
                CASE WHEN cp.verification_status = 'verified' THEN TRUE WHEN c.is_verified = TRUE THEN TRUE ELSE FALSE END AS company_is_verified,
                COALESCE(cp.verification_status, 'pending') AS employer_verification_status
            FROM saved_jobs s
            JOIN jobs j ON s.job_id = j.id
            LEFT JOIN companies c ON j.company_id = c.id
            LEFT JOIN company_profiles cp ON j.company_profile_id = cp.id
            WHERE s.user_id = %s
            ORDER BY s.created_at DESC
            LIMIT %s OFFSET %s;
        """
        rows = db_helpers["query_db"](data_query, (user_id, limit_num, offset))
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
        logger.error(f"Error fetching saved jobs for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not load your saved jobs.")


@router.get("/jobs/{job_id}/saved-status")
async def check_job_saved_status(job_id: int, request: Request):
    """
    Checks if the currently authenticated job seeker has bookmarked this job.
    Safe for guests and non-employees (returns is_saved: False).
    """
    session_cookie = request.cookies.get("public_session_id")
    if not session_cookie:
        return {"success": True, "is_saved": False}

    try:
        from routers.public_auth import get_current_public_user
        current_user = await get_current_public_user(public_session_id=session_cookie)
        if not current_user or current_user.get("account_type") != "individual":
            return {"success": True, "is_saved": False}

        user_id = current_user["id"]
        if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
            match = next((s for s in FALLBACK_SAVED_JOBS if s.get("job_id") == job_id and s.get("user_id") == user_id), None)
            return {"success": True, "is_saved": bool(match)}

        rows = db_helpers["query_db"]("""
            SELECT id FROM saved_jobs 
            WHERE job_id = %s AND user_id = %s;
        """, (job_id, user_id))

        return {
            "success": True,
            "is_saved": bool(rows)
        }
    except Exception:
        return {"success": True, "is_saved": False}


@router.get("/employee/recommended-jobs")
async def get_employee_recommended_jobs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(6, ge=1, le=50)
):
    """
    Returns deterministic, explainable recommended published jobs matching the authenticated
    candidate's profile preferences. Excludes already saved and already applied jobs.
    """
    import re
    from routers.public_auth import get_current_public_user
    session_cookie = request.cookies.get("public_session_id")
    if not session_cookie:
        raise HTTPException(status_code=401, detail="Authentication required.")
        
    current_user = await get_current_public_user(public_session_id=session_cookie)
    if not current_user or current_user.get("account_type") != "individual":
        raise HTTPException(status_code=403, detail="Access denied.")

    user_id = current_user["id"]
    page_num = page if isinstance(page, int) and page >= 1 else 1
    limit_num = limit if isinstance(limit, int) and limit >= 1 else 6

    # 1. Fetch candidate profile
    profile_rows = []
    if db_helpers["db_enabled"] and db_helpers["query_db"]:
        profile_rows = db_helpers["query_db"]("SELECT * FROM individual_profiles WHERE user_id = %s;", (user_id,))
    
    profile = profile_rows[0] if profile_rows else (current_user.get("profile") or {})
    
    # Check if profile has enough information for recommendations
    has_prefs = bool(
        (profile.get("preferred_department") or "").strip() or
        (profile.get("department") or "").strip() or
        (profile.get("preferred_job_role") or "").strip() or
        (profile.get("job_title") or "").strip() or
        (profile.get("preferred_location") or "").strip() or
        (profile.get("location") or "").strip() or
        (profile.get("skills") or "").strip()
    )

    if not has_prefs:
        return {
            "success": True,
            "jobs": [],
            "page": page_num,
            "limit": limit_num,
            "total": 0,
            "total_pages": 1,
            "incomplete_profile": True
        }

    # 2. Fetch candidate eligible active jobs from database
    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        # Fallback in-memory
        saved_job_ids = {s["job_id"] for s in FALLBACK_SAVED_JOBS if s.get("user_id") == user_id}
        applied_job_ids = set()
        candidate_jobs = [
            j for j in FALLBACK_JOBS 
            if (j.get("status") or "").lower() == "published" 
            and not j.get("is_archived")
            and j.get("id") not in saved_job_ids
            and j.get("id") not in applied_job_ids
        ]
    else:
        # Bounded query fetching active published public jobs, excluding saved and applied
        query = """
            SELECT 
                j.id, j.company_id, j.company_profile_id, j.title, j.slug, j.department, j.job_role, j.job_type,
                j.location, j.openings_count, j.experience_min, j.experience_max, j.salary_min, j.salary_max,
                j.salary_text, j.description, j.requirements, j.skills, j.qualification,
                j.gender, j.contact_phone, j.contact_whatsapp, j.contact_email, j.application_url,
                j.source_type, j.source_name, j.poster_image_url, j.status, j.is_featured,
                j.verification_status, j.published_at, j.expires_at, j.created_at,
                COALESCE(cp.company_name, c.name, '') AS company_name,
                COALESCE(cp.company_logo, c.logo_url, '') AS company_logo,
                c.slug AS company_slug,
                COALESCE(cp.location, c.location, j.location) AS company_location,
                CASE WHEN cp.verification_status = 'verified' THEN TRUE WHEN c.is_verified = TRUE THEN TRUE ELSE FALSE END AS company_is_verified
            FROM jobs j
            LEFT JOIN companies c ON j.company_id = c.id
            LEFT JOIN company_profiles cp ON j.company_profile_id = cp.id
            WHERE LOWER(j.status) = 'published'
              AND COALESCE(j.is_archived, FALSE) = FALSE
              AND j.id NOT IN (SELECT job_id FROM saved_jobs WHERE user_id = %s)
              AND j.id NOT IN (SELECT job_id FROM job_applications WHERE candidate_user_id = %s)
            ORDER BY j.published_at DESC NULLS LAST, j.id DESC
            LIMIT 100;
        """
        candidate_jobs = db_helpers["query_db"](query, (user_id, user_id)) or []

    # 3. Deterministic scoring
    cand_dept = (profile.get("preferred_department") or profile.get("department") or "").strip().lower()
    cand_role = (profile.get("preferred_job_role") or profile.get("job_title") or "").strip().lower()
    cand_loc = (profile.get("preferred_location") or profile.get("location") or profile.get("city") or "").strip().lower()
    cand_skills = (profile.get("skills") or "").lower()
    cand_exp = float(profile.get("experience_years") or 0)
    
    # Parse expected salary numeric digits if available
    cand_salary = None
    sal_matches = re.findall(r'\d+', (profile.get("expected_salary") or "").replace(",", ""))
    if sal_matches:
        try:
            cand_salary = float("".join(sal_matches))
        except ValueError:
            cand_salary = None

    skill_tokens = [s.strip() for s in cand_skills.replace(",", " ").split() if len(s.strip()) > 2]
    loc_tokens = [t.strip() for t in cand_loc.replace(",", " ").replace("/", " ").split() if len(t.strip()) > 2]

    scored_jobs = []
    for job in candidate_jobs:
        score = 0
        reasons = []

        job_dept = (job.get("department") or "").strip().lower()
        job_role = (job.get("job_role") or "").strip().lower()
        job_title = (job.get("title") or "").strip().lower()
        job_loc = (job.get("location") or "").strip().lower()
        job_skills = (job.get("skills") or "").lower()
        job_desc = (job.get("description") or "").lower()

        # A. Department match (+30)
        if cand_dept and job_dept:
            if cand_dept in job_dept or job_dept in cand_dept:
                score += 30
                reasons.append("Matches your preferred department")

        # B. Job role match (+30)
        if cand_role:
            if (job_role and (cand_role in job_role or job_role in cand_role)) or (cand_role in job_title or job_title in cand_role):
                score += 30
                reasons.append("Matches your preferred role")
            else:
                # Common keyword match
                role_words = [w for w in cand_role.split() if len(w) > 3]
                if any(w in job_role or w in job_title for w in role_words):
                    score += 20
                    reasons.append("Matches your target role")

        # C. Location match (+20)
        if loc_tokens and job_loc:
            if any(lt in job_loc for lt in loc_tokens):
                score += 20
                reasons.append("Matches your preferred location")

        # D. Skills match (+5 per match, cap +15)
        if skill_tokens:
            job_text = f"{job_skills} {job_title} {job_desc}"
            hits = sum(1 for st in skill_tokens if st in job_text)
            if hits > 0:
                skill_score = min(15, hits * 5)
                score += skill_score
                reasons.append("Skills match")

        # E. Experience match (+10)
        job_exp_min = job.get("experience_min")
        job_exp_max = job.get("experience_max")
        if job_exp_min is not None:
            if job_exp_max is not None:
                if job_exp_min <= cand_exp <= (job_exp_max + 1):
                    score += 10
                    reasons.append("Experience matches")
            else:
                if cand_exp >= job_exp_min:
                    score += 10
                    reasons.append("Experience matches")
        else:
            # Job specifies no explicit experience restriction
            score += 10

        # F. Salary compatibility (+5)
        job_sal_min = job.get("salary_min")
        job_sal_max = job.get("salary_max")
        if cand_salary:
            if job_sal_max and job_sal_max >= cand_salary:
                score += 5
                reasons.append("Salary matches expectations")
            elif job_sal_min and job_sal_min >= (cand_salary * 0.8):
                score += 5
                reasons.append("Salary matches expectations")

        if score > 0:
            job_dict = dict(job)
            job_dict["match_reasons"] = reasons
            # Safe date string serialization
            pub_date = job.get("published_at") or job.get("created_at")
            if hasattr(pub_date, "isoformat"):
                job_dict["published_at"] = pub_date.isoformat()
            if hasattr(job.get("created_at"), "isoformat"):
                job_dict["created_at"] = job["created_at"].isoformat()
            if hasattr(job.get("expires_at"), "isoformat"):
                job_dict["expires_at"] = job["expires_at"].isoformat()

            scored_jobs.append((score, 1 if job.get("is_featured") else 0, str(pub_date or ""), job.get("id", 0), job_dict))

    # Sort deterministically: score desc, is_featured desc, published_date desc, id desc
    scored_jobs.sort(key=lambda item: (-item[0], -item[1], str(item[2]), -item[3]))

    total = len(scored_jobs)
    start = (page_num - 1) * limit_num
    end = start + limit_num
    paginated = [item[4] for item in scored_jobs[start:end]]
    total_pages = max(1, (total + limit_num - 1) // limit_num)

    return {
        "success": True,
        "jobs": paginated,
        "page": page_num,
        "limit": limit_num,
        "total": total,
        "total_pages": total_pages,
        "incomplete_profile": False
    }


# --- PHASE 4G: JOB ALERT PREFERENCES ---

class JobAlertPreferencePayload(BaseModel):
    is_enabled: bool = False
    departments: Optional[List[str]] = []
    job_roles: Optional[List[str]] = []
    locations: Optional[List[str]] = []
    job_types: Optional[List[str]] = []
    experience_min: Optional[float] = None
    experience_max: Optional[float] = None
    salary_min: Optional[float] = None
    frequency: Optional[str] = "daily"

@router.get("/employee/job-alert-preferences")
async def get_job_alert_preferences(request: Request):
    from routers.public_auth import get_current_public_user
    public_session_id = request.cookies.get("public_session_id")
    user = await get_current_public_user(public_session_id=public_session_id)
    if user.get("account_type") != "individual":
        raise HTTPException(
            status_code=403, 
            detail="Access denied. This section is strictly for Job Seekers / Employees."
        )

    user_id = user["id"]

    if not db_helpers["db_enabled"] or not db_helpers["query_db"]:
        return {
            "success": True,
            "preference": {
                "is_enabled": False,
                "departments": [],
                "job_roles": [],
                "locations": [],
                "job_types": [],
                "experience_min": None,
                "experience_max": None,
                "salary_min": None,
                "frequency": "daily",
                "created_at": None,
                "updated_at": None
            }
        }

    try:
        rows = db_helpers["query_db"]("""
            SELECT id, user_id, is_enabled, departments, job_roles, locations,
                   job_types, experience_min, experience_max, salary_min, frequency,
                   created_at, updated_at
            FROM job_alert_preferences
            WHERE user_id = %s;
        """, (user_id,))

        if not rows:
            return {
                "success": True,
                "preference": {
                    "is_enabled": False,
                    "departments": [],
                    "job_roles": [],
                    "locations": [],
                    "job_types": [],
                    "experience_min": None,
                    "experience_max": None,
                    "salary_min": None,
                    "frequency": "daily",
                    "created_at": None,
                    "updated_at": None
                }
            }

        pref = dict(rows[0])
        # Format datetimes & floats safely
        if pref.get("experience_min") is not None:
            pref["experience_min"] = float(pref["experience_min"])
        if pref.get("experience_max") is not None:
            pref["experience_max"] = float(pref["experience_max"])
        if pref.get("salary_min") is not None:
            pref["salary_min"] = float(pref["salary_min"])
        if hasattr(pref.get("created_at"), "isoformat"):
            pref["created_at"] = pref["created_at"].isoformat()
        if hasattr(pref.get("updated_at"), "isoformat"):
            pref["updated_at"] = pref["updated_at"].isoformat()

        # Remove internal user_id to prevent any PII / internal leak
        pref.pop("user_id", None)

        return {
            "success": True,
            "preference": pref
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching job alert preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve job alert preferences.")

@router.put("/employee/job-alert-preferences")
async def update_job_alert_preferences(payload: JobAlertPreferencePayload, request: Request):
    from routers.public_auth import get_current_public_user
    public_session_id = request.cookies.get("public_session_id")
    user = await get_current_public_user(public_session_id=public_session_id)
    if user.get("account_type") != "individual":
        raise HTTPException(
            status_code=403, 
            detail="Access denied. This section is strictly for Job Seekers / Employees."
        )

    user_id = user["id"]

    # Input validations
    freq = (payload.frequency or "daily").strip().lower()
    if freq not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="Invalid alert frequency. Allowed options: 'daily', 'weekly'.")

    if payload.experience_min is not None and payload.experience_min < 0:
        raise HTTPException(status_code=400, detail="Minimum experience cannot be negative.")
    if payload.experience_max is not None and payload.experience_max < 0:
        raise HTTPException(status_code=400, detail="Maximum experience cannot be negative.")
    if payload.experience_min is not None and payload.experience_max is not None:
        if payload.experience_min > payload.experience_max:
            raise HTTPException(status_code=400, detail="Minimum experience cannot exceed maximum experience.")

    if payload.salary_min is not None and payload.salary_min < 0:
        raise HTTPException(status_code=400, detail="Minimum salary cannot be negative.")

    # Sanitize string lists
    depts = [d.strip() for d in (payload.departments or []) if d and d.strip()]
    roles = [r.strip() for r in (payload.job_roles or []) if r and r.strip()]
    locs = [l.strip() for l in (payload.locations or []) if l and l.strip()]
    jtypes = [t.strip() for t in (payload.job_types or []) if t and t.strip()]

    if not db_helpers["db_enabled"] or not db_helpers["execute_db_returning"]:
        return {
            "success": True,
            "message": "Job alert preferences updated successfully (offline mode).",
            "preference": {
                "is_enabled": payload.is_enabled,
                "departments": depts,
                "job_roles": roles,
                "locations": locs,
                "job_types": jtypes,
                "experience_min": payload.experience_min,
                "experience_max": payload.experience_max,
                "salary_min": payload.salary_min,
                "frequency": freq
            }
        }

    try:
        query = """
            INSERT INTO job_alert_preferences (
                user_id, is_enabled, departments, job_roles, locations, job_types,
                experience_min, experience_max, salary_min, frequency, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (user_id) DO UPDATE SET
                is_enabled = EXCLUDED.is_enabled,
                departments = EXCLUDED.departments,
                job_roles = EXCLUDED.job_roles,
                locations = EXCLUDED.locations,
                job_types = EXCLUDED.job_types,
                experience_min = EXCLUDED.experience_min,
                experience_max = EXCLUDED.experience_max,
                salary_min = EXCLUDED.salary_min,
                frequency = EXCLUDED.frequency,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, is_enabled, departments, job_roles, locations, job_types,
                      experience_min, experience_max, salary_min, frequency, created_at, updated_at;
        """
        rows = db_helpers["execute_db_returning"](query, (
            user_id,
            payload.is_enabled,
            depts,
            roles,
            locs,
            jtypes,
            payload.experience_min,
            payload.experience_max,
            payload.salary_min,
            freq
        ))

        pref = dict(rows[0]) if rows else {}
        if pref.get("experience_min") is not None:
            pref["experience_min"] = float(pref["experience_min"])
        if pref.get("experience_max") is not None:
            pref["experience_max"] = float(pref["experience_max"])
        if pref.get("salary_min") is not None:
            pref["salary_min"] = float(pref["salary_min"])
        if hasattr(pref.get("created_at"), "isoformat"):
            pref["created_at"] = pref["created_at"].isoformat()
        if hasattr(pref.get("updated_at"), "isoformat"):
            pref["updated_at"] = pref["updated_at"].isoformat()

        return {
            "success": True,
            "message": "Job alert preferences saved successfully.",
            "preference": pref
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving job alert preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to save job alert preferences.")



