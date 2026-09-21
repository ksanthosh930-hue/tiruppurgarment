import os
import re
import uuid
import shutil
import mimetypes
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Form, UploadFile, File, Query

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
            "(LOWER(j.status) = 'published' OR j.status = 'ACTIVE')",
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
              AND (LOWER(j.status) = 'published' OR j.status = 'ACTIVE')
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

@router.post("/jobs/{job_id}/apply")
def submit_job_application(
    job_id: int,
    applicant_name: str = Form(...),
    applicant_phone: str = Form(...),
    applicant_email: Optional[str] = Form(None),
    resume_url: Optional[str] = Form(None),
    cover_letter: Optional[str] = Form(None)
):
    """
    Submits a direct application for a published job.
    """
    app_name = str(applicant_name).strip() if applicant_name else ""
    raw_phone = str(applicant_phone).strip() if applicant_phone else ""
    app_phone = re.sub(r'[^0-9+]', '', raw_phone)
    if not app_phone or len(app_phone) < 10:
        raise HTTPException(status_code=400, detail="Please provide a valid applicant phone number.")

    app_email = _clean_str(applicant_email)
    app_resume = _clean_str(resume_url)
    app_letter = _clean_str(cover_letter)

    if not db_helpers["db_enabled"] or not db_helpers["execute_db"]:
        FALLBACK_APPLICATIONS.append({
            "id": len(FALLBACK_APPLICATIONS) + 1,
            "job_id": job_id,
            "applicant_name": app_name,
            "applicant_phone": app_phone,
            "applicant_email": app_email,
            "resume_url": app_resume,
            "cover_letter": app_letter,
            "status": "applied"
        })
        return {"success": True, "message": "Thank you! Your application has been submitted successfully."}

    try:
        # Check job existence
        job_rows = db_helpers["query_db"]("SELECT id, status FROM jobs WHERE id = %s AND COALESCE(is_archived, FALSE) = FALSE;", (job_id,))
        if not job_rows or job_rows[0]["status"] != "published":
            raise HTTPException(status_code=400, detail="This job is currently not accepting applications.")

        # Find profile id if candidate already registered
        prof_rows = db_helpers["query_db"]("SELECT id, user_id FROM job_seeker_profiles WHERE mobile = %s;", (app_phone,))
        profile_id = prof_rows[0]["id"] if prof_rows else None
        user_id = prof_rows[0]["user_id"] if prof_rows else None

        query = """
            INSERT INTO job_applications (
                job_id, user_id, job_seeker_profile_id, applicant_name,
                applicant_phone, applicant_email, resume_url, cover_letter,
                status, applied_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, 'applied', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) RETURNING id;
        """
        rows = db_helpers["execute_db_returning"](query, (
            job_id, user_id, profile_id, app_name, app_phone,
            app_email, app_resume, app_letter
        ))
        app_id = rows[0]["id"] if rows else None

        return {
            "success": True,
            "application_id": app_id,
            "message": "Thank you! Your application has been submitted successfully."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting job application: {e}")
        raise HTTPException(status_code=500, detail=f"Database error submitting application: {e}")
