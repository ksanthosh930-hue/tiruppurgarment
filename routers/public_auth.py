import os
import time
import uuid
import json
import logging
import datetime
import secrets
from typing import Dict, Any, Optional, Tuple
import re
from fastapi import APIRouter, HTTPException, Cookie, Depends, Response, Form, Request, UploadFile, File
from pydantic import BaseModel, Field
from werkzeug.security import generate_password_hash, check_password_hash

from services.email_service import send_otp_email
from services.otp_service import (
    generate_6digit_otp,
    hash_otp,
    check_rate_limit,
    generate_signed_temp_token,
    verify_signed_temp_token,
    OTP_MAX_ATTEMPTS,
    OTP_RESEND_COOLDOWN_SECONDS
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Public Authentication"])

# Database helpers injected from app.py
_query_db = None
_execute_db = None
_execute_db_returning = None
_db_enabled = False

def init_public_auth_helpers(db_enabled_val, query_fn, exec_fn, exec_ret_fn):
    global _db_enabled, _query_db, _execute_db, _execute_db_returning
    _db_enabled = db_enabled_val
    _query_db = query_fn
    _execute_db = exec_fn
    _execute_db_returning = exec_ret_fn

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"

# --- Validation Helpers ---

def _validate_email_format(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if not cleaned or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", cleaned):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    return cleaned

def _validate_indian_mobile(mobile: str) -> str:
    cleaned = re.sub(r"[\s\-\(\)]", "", (mobile or "").strip())
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif len(cleaned) == 12 and cleaned.startswith("91"):
        cleaned = cleaned[2:]
    elif len(cleaned) == 11 and cleaned.startswith("0"):
        cleaned = cleaned[1:]
    if not cleaned or not re.match(r"^[6-9]\d{9}$", cleaned):
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit Indian mobile number.")
    return cleaned

def _validate_optional_mobile(mobile: Optional[str]) -> Optional[str]:
    if not mobile or not mobile.strip():
        return None
    return _validate_indian_mobile(mobile)

def _validate_password_strength(password: str, confirm_password: Optional[str] = None) -> str:
    pwd = (password or "").strip()
    if len(pwd) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")
    if confirm_password is not None:
        if pwd != confirm_password.strip():
            raise HTTPException(status_code=400, detail="Passwords do not match. Please re-enter.")
    return pwd

# --- Dependency: Current Public User ---
async def get_current_public_user(public_session_id: Optional[str] = Cookie(None)):
    if not public_session_id:
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        query = """
            SELECT s.token, s.expires_at, u.id, u.account_type, u.email, u.email_verified, u.is_active, u.created_at
            FROM public_user_sessions s
            JOIN public_users u ON s.user_id = u.id
            WHERE s.token = %s AND s.expires_at > CURRENT_TIMESTAMP AND u.is_active = TRUE;
        """
        rows = _query_db(query, (public_session_id,))
        if not rows:
            raise HTTPException(status_code=401, detail="Session expired or invalid. Please sign in again.")
            
        user = rows[0]
        user_id = user["id"]
        account_type = user["account_type"]
        
        # Determine application role
        role = "employee" if account_type == "individual" else "employer"
        user["role"] = role
        
        # Load profile
        profile = {}
        if account_type == "individual":
            p_rows = _query_db("SELECT * FROM individual_profiles WHERE user_id = %s;", (user_id,))
            if p_rows:
                profile = p_rows[0]
        elif account_type == "company":
            p_rows = _query_db("SELECT * FROM company_profiles WHERE user_id = %s;", (user_id,))
            if p_rows:
                profile = p_rows[0]
                
        user["profile"] = profile
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching current public user: {e}")
        raise HTTPException(status_code=401, detail="Authentication verification error.")

# --- Role-Based Server-Side Authorization Guards ---

async def require_employee_user(user: Dict[str, Any] = Depends(get_current_public_user)) -> Dict[str, Any]:
    """Ensures the authenticated user has employee (individual) role."""
    if user.get("account_type") != "individual":
        raise HTTPException(
            status_code=403, 
            detail="Access denied. This section is strictly for Job Seekers / Employees."
        )
    return user

async def require_employer_user(user: Dict[str, Any] = Depends(get_current_public_user)) -> Dict[str, Any]:
    """Ensures the authenticated user has employer (company) role."""
    if user.get("account_type") != "company":
        raise HTTPException(
            status_code=403, 
            detail="Access denied. This section is strictly for Employers / Garment Companies."
        )
    return user


PENDING_REG_COOKIE_NAME = "dg_reg_verify"
PENDING_REG_MAX_AGE = 600  # 10 minutes (matches TEMP_TOKEN_EXPIRY_MINUTES)


def _is_secure_request(request: Optional[Request] = None) -> bool:
    if os.getenv("ENVIRONMENT", "").strip().lower() == "production":
        return True
    if request:
        if request.url.scheme == "https":
            return True
        if request.headers.get("x-forwarded-proto", "").strip().lower() == "https":
            return True
    return False


def _verify_registration_otp_token_or_400(
    expected_email: Optional[str],
    cookie_token: Optional[str] = None
) -> Tuple[int, str]:
    """
    Enforces that any endpoint creating a verified account (email_verified = TRUE)
    presents a valid, unconsumed, non-expired Email OTP verification credential exclusively
    via the HttpOnly cookie `dg_reg_verify` bound to `purpose='registration'` and `expected_email`.
    Request-body bearer tokens are never accepted.
    Returns (email_otp_verifications.id, verified_email).
    """
    raw_token = (cookie_token or "").strip()
    if not raw_token:
        raise HTTPException(
            status_code=400,
            detail="Email OTP verification is required before completing registration. Please verify your email code first."
        )
    is_valid, token_payload, err_msg = verify_signed_temp_token(raw_token, expected_purpose="registration")
    if not is_valid or not token_payload:
        raise HTTPException(status_code=400, detail=err_msg or "Invalid or expired verification token.")
    token_email = (token_payload.get("email") or "").strip().lower()
    if expected_email and expected_email.strip():
        if token_email != expected_email.strip().lower():
            raise HTTPException(status_code=400, detail="Verification token does not match the provided email address.")
    nonce = token_payload.get("nonce")
    otp_records = _query_db("""
        SELECT id, is_consumed, verified_at,
               (verified_at IS NULL OR verified_at < (CURRENT_TIMESTAMP - INTERVAL '10 minutes')) AS is_token_expired
        FROM email_otp_verifications
        WHERE email = %s AND purpose = 'registration' AND token_nonce = %s;
    """, (token_email, nonce))
    if not otp_records or otp_records[0]["is_consumed"] or not otp_records[0]["verified_at"]:
        raise HTTPException(status_code=400, detail="Verification token is invalid or has already been used.")
    if otp_records[0].get("is_token_expired"):
        raise HTTPException(status_code=400, detail="Verification token has expired (valid for 10 minutes). Please verify your email again.")
    return otp_records[0]["id"], token_email


def _consume_registration_otp_or_400(otp_rec_id: int, response: Optional[Response] = None) -> None:
    """
    Atomically marks the verified OTP record consumed and clears token_nonce so it is strictly single-use,
    and deletes the pending registration HttpOnly cookie.
    """
    updated = _execute_db_returning("""
        UPDATE email_otp_verifications
        SET is_consumed = TRUE, token_nonce = NULL
        WHERE id = %s AND is_consumed = FALSE
        RETURNING id;
    """, (otp_rec_id,))
    if not updated:
        raise HTTPException(status_code=400, detail="Verification token has already been used.")
    if response is not None:
        response.delete_cookie(key=PENDING_REG_COOKIE_NAME, path="/", samesite="lax")


# --- 1. Direct Employee (Job Seeker) Registration ---
class EmployeeRegisterRequest(BaseModel):
    full_name: str
    mobile: str
    email: str
    password: str
    confirm_password: Optional[str] = None
    location: Optional[str] = None
    visitor_id: Optional[str] = None

@router.post("/register/employee")
@router.post("/register/individual")
def register_employee(
    req_data: EmployeeRegisterRequest,
    response: Response,
    request: Request,
    dg_reg_verify: Optional[str] = Cookie(None)
):
    ip = _get_client_ip(request)
    if not check_rate_limit(f"reg_emp_ip:{ip}", max_requests=8, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Please wait a few minutes.")
        
    full_name = (req_data.full_name or "").strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Full Name is required.")
        
    mobile = _validate_indian_mobile(req_data.mobile)
    email = _validate_email_format(req_data.email)
    password = _validate_password_strength(req_data.password, req_data.confirm_password)
    location = (req_data.location or "").strip() or None
    
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        # Enforce mandatory Email OTP verification exclusively via HttpOnly cookie `dg_reg_verify`
        otp_rec_id, _ = _verify_registration_otp_token_or_400(email, dg_reg_verify)

        # Check duplicate email
        existing_email = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if existing_email:
            raise HTTPException(status_code=400, detail="This email is already registered. Please sign in.")
            
        # Check duplicate mobile in individual profiles
        existing_mobile = _query_db("SELECT id FROM individual_profiles WHERE mobile = %s;", (mobile,))
        if existing_mobile:
            raise HTTPException(status_code=400, detail="This mobile number is already registered with another account.")

        # Atomically consume OTP token before account creation (single-use)
        _consume_registration_otp_or_400(otp_rec_id, response)
            
        password_hash = generate_password_hash(password, method="scrypt")
        
        # Create public_users record (account_type = 'individual')
        create_user_query = """
            INSERT INTO public_users (account_type, email, password_hash, email_verified, is_active, created_at, updated_at)
            VALUES ('individual', %s, %s, TRUE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id;
        """
        user_rows = _execute_db_returning(create_user_query, (email, password_hash))
        new_user_id = user_rows[0]["id"]
        
        # Create individual profile record
        _execute_db("""
            INSERT INTO individual_profiles (user_id, full_name, email, mobile, location, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
        """, (new_user_id, full_name, email, mobile, location))
        
        # Auto-login: Create public session
        session_token = str(uuid.uuid4())
        _execute_db("""
            INSERT INTO public_user_sessions (token, user_id, expires_at, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '30 days', CURRENT_TIMESTAMP);
        """, (session_token, new_user_id))
        
        response.set_cookie(
            key="public_session_id",
            value=session_token,
            httponly=True,
            expires=30 * 24 * 3600,
            samesite="lax"
        )

        try:
            vid = (req_data.visitor_id or "").strip()[:64] or None
            _execute_db("""
                INSERT INTO job_analytics_events (event_type, visitor_id, user_id, session_id, metadata)
                VALUES ('registration_complete', %s, %s, %s, %s);
            """, (vid, new_user_id, session_token, json.dumps({"account_type": "individual", "source": "register_employee"})))
        except Exception as ae:
            logger.warning(f"Could not track registration_complete event: {ae}")
        
        return {
            "success": True,
            "message": "Employee registration successful.",
            "role": "employee",
            "account_type": "individual",
            "redirect_url": "/dashboard/individual"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during employee registration: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 2. Direct Employer Registration ---
class EmployerRegisterRequest(BaseModel):
    company_name: str
    contact_person: str  # HR / Recruiter Name
    mobile: str
    email: str
    password: str
    confirm_password: Optional[str] = None
    whatsapp: Optional[str] = None
    area: Optional[str] = None
    location: Optional[str] = None
    visitor_id: Optional[str] = None

@router.post("/register/employer")
@router.post("/register/company")
def register_employer(
    req_data: EmployerRegisterRequest,
    response: Response,
    request: Request,
    dg_reg_verify: Optional[str] = Cookie(None)
):
    ip = _get_client_ip(request)
    if not check_rate_limit(f"reg_empr_ip:{ip}", max_requests=8, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Please wait a few minutes.")
        
    company_name = (req_data.company_name or "").strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="Company Name is required.")
        
    contact_person = (req_data.contact_person or "").strip()
    if not contact_person:
        raise HTTPException(status_code=400, detail="HR / Recruiter Name is required.")
        
    mobile = _validate_indian_mobile(req_data.mobile)
    email = _validate_email_format(req_data.email)
    password = _validate_password_strength(req_data.password, req_data.confirm_password)
    whatsapp = _validate_optional_mobile(req_data.whatsapp)
    area = (req_data.area or "").strip() or None
    location = (req_data.location or req_data.area or "").strip() or None
    
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        # Enforce mandatory Email OTP verification exclusively via HttpOnly cookie `dg_reg_verify`
        otp_rec_id, _ = _verify_registration_otp_token_or_400(email, dg_reg_verify)

        # Check duplicate email
        existing_email = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if existing_email:
            raise HTTPException(status_code=400, detail="This email is already registered. Please sign in.")
            
        # Check duplicate mobile in company profiles
        existing_mobile = _query_db("SELECT id FROM company_profiles WHERE mobile = %s;", (mobile,))
        if existing_mobile:
            raise HTTPException(status_code=400, detail="This mobile number is already registered with another company account.")

        # Atomically consume OTP token before account creation (single-use)
        _consume_registration_otp_or_400(otp_rec_id, response)
            
        password_hash = generate_password_hash(password, method="scrypt")
        
        # Create public_users record (account_type = 'company')
        create_user_query = """
            INSERT INTO public_users (account_type, email, password_hash, email_verified, is_active, created_at, updated_at)
            VALUES ('company', %s, %s, TRUE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id;
        """
        user_rows = _execute_db_returning(create_user_query, (email, password_hash))
        new_user_id = user_rows[0]["id"]
        
        # Create company profile record with verification_status = 'pending'
        _execute_db("""
            INSERT INTO company_profiles (
                user_id, company_name, contact_person, email, mobile, whatsapp, area, location, verification_status, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
        """, (new_user_id, company_name, contact_person, email, mobile, whatsapp, area, location))
        
        # Auto-login: Create public session
        session_token = str(uuid.uuid4())
        _execute_db("""
            INSERT INTO public_user_sessions (token, user_id, expires_at, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '30 days', CURRENT_TIMESTAMP);
        """, (session_token, new_user_id))
        
        response.set_cookie(
            key="public_session_id",
            value=session_token,
            httponly=True,
            expires=30 * 24 * 3600,
            samesite="lax"
        )

        try:
            vid = (req_data.visitor_id or "").strip()[:64] or None
            _execute_db("""
                INSERT INTO job_analytics_events (event_type, visitor_id, user_id, session_id, metadata)
                VALUES ('registration_complete', %s, %s, %s, %s);
            """, (vid, new_user_id, session_token, json.dumps({"account_type": "company", "source": "register_employer"})))
        except Exception as ae:
            logger.warning(f"Could not track registration_complete event: {ae}")
        
        return {
            "success": True,
            "message": "Employer registration successful. Verification is pending.",
            "role": "employer",
            "account_type": "company",
            "verification_status": "pending",
            "redirect_url": "/dashboard/company"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during employer registration: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 3. Unified Public Login (Email or Mobile + Password) ---
class LoginRequest(BaseModel):
    email: str  # Can be email or 10-digit mobile
    password: str
    visitor_id: Optional[str] = None

@router.post("/login")
def public_login(req_data: LoginRequest, response: Response, request: Request):
    ip = _get_client_ip(request)
    raw_ident = (req_data.email or "").strip()
    password = (req_data.password or "").strip()
    
    if not raw_ident or not password:
        raise HTTPException(status_code=400, detail="Please enter your email or mobile number and password.")
        
    if not check_rate_limit(f"login_ip:{ip}", max_requests=12, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Please wait a few minutes.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        target_email = None
        
        # Check if input is a mobile number (10 digits)
        cleaned_mobile = re.sub(r"[\s\-\(\)]", "", raw_ident)
        if cleaned_mobile.startswith("+91"):
            cleaned_mobile = cleaned_mobile[3:]
        elif len(cleaned_mobile) == 12 and cleaned_mobile.startswith("91"):
            cleaned_mobile = cleaned_mobile[2:]
        elif len(cleaned_mobile) == 11 and cleaned_mobile.startswith("0"):
            cleaned_mobile = cleaned_mobile[1:]
        if re.match(r"^[6-9]\d{9}$", cleaned_mobile):
            # Look up by mobile in individual_profiles or company_profiles
            m_rows = _query_db("SELECT email FROM individual_profiles WHERE mobile = %s LIMIT 1;", (cleaned_mobile,))
            if not m_rows:
                m_rows = _query_db("SELECT email FROM company_profiles WHERE mobile = %s LIMIT 1;", (cleaned_mobile,))
            if m_rows and m_rows[0].get("email"):
                target_email = m_rows[0]["email"].strip().lower()
            else:
                raise HTTPException(status_code=401, detail="Invalid mobile number or password.")
        else:
            target_email = _validate_email_format(raw_ident)
            
        # Fetch user
        rows = _query_db("""
            SELECT id, account_type, email, password_hash, is_active 
            FROM public_users 
            WHERE email = %s;
        """, (target_email,))
        
        if not rows:
            raise HTTPException(status_code=401, detail="Invalid email/mobile or password.")
            
        user = rows[0]
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Your account has been deactivated. Please contact support.")
            
        current_hash = user.get("password_hash") or ""
        if current_hash.startswith("!google_oauth_"):
            raise HTTPException(
                status_code=400,
                detail="This account was registered using Google Sign-In. Please sign in by clicking 'Continue with Google', or click 'Forgot password?' below to establish a password."
            )

        if not check_password_hash(current_hash, password):
            raise HTTPException(status_code=401, detail="Invalid email/mobile or password.")
            
        # Create public session
        session_token = str(uuid.uuid4())
        _execute_db("""
            INSERT INTO public_user_sessions (token, user_id, expires_at, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '30 days', CURRENT_TIMESTAMP);
        """, (session_token, user["id"]))
        
        # Set session cookie
        response.set_cookie(
            key="public_session_id",
            value=session_token,
            httponly=True,
            expires=30 * 24 * 3600,
            samesite="lax"
        )
        
        account_type = user["account_type"]
        role = "employee" if account_type == "individual" else "employer"
        redirect_url = "/dashboard/individual" if account_type == "individual" else "/dashboard/company"

        # Track login analytics event
        try:
            vid = (req_data.visitor_id or "").strip()[:64] or None
            _execute_db("""
                INSERT INTO job_analytics_events (event_type, visitor_id, user_id, session_id, metadata)
                VALUES ('login', %s, %s, %s, %s);
            """, (vid, user["id"], session_token, json.dumps({"account_type": account_type, "role": role})))
        except Exception as ae:
            logger.warning(f"Could not track login event: {ae}")
        
        return {
            "success": True,
            "message": "Signed in successfully.",
            "role": role,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "account_type": account_type,
                "role": role
            },
            "redirect_url": redirect_url
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during public login: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 4. Session Validation & Current User Info ---
@router.get("/me")
def get_auth_me(current_user: Dict[str, Any] = Depends(get_current_public_user)):
    return {
        "logged_in": True,
        "role": current_user.get("role", "employee"),
        "user": current_user
    }


# --- 5. Employee Profile Foundation APIs ---
class EmployeeProfileUpdateRequest(BaseModel):
    full_name: str
    mobile: Optional[str] = None
    location: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    experience_years: Optional[float] = 0.0
    expected_salary: Optional[str] = None
    preferred_job_role: Optional[str] = None
    preferred_department: Optional[str] = None
    preferred_location: Optional[str] = None
    qualification: Optional[str] = None
    course: Optional[str] = None
    institution: Optional[str] = None
    passing_year: Optional[str] = None
    skills: Optional[str] = None

def calculate_profile_completion(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic field-level profile completion calculation (5 sections x 20% = 100%).
    """
    # 1. Personal (20%): full_name (7%), mobile (7%), location/city (6%)
    personal_score = 0
    if (profile.get("full_name") or "").strip(): personal_score += 7
    if (profile.get("mobile") or "").strip(): personal_score += 7
    if (profile.get("location") or profile.get("city") or "").strip(): personal_score += 6
    
    # 2. Professional (20%): job_title (7%), department (7%), experience_years (6%)
    prof_score = 0
    if (profile.get("job_title") or "").strip(): prof_score += 7
    if (profile.get("department") or "").strip(): prof_score += 7
    if profile.get("experience_years") is not None and float(profile.get("experience_years") or 0) > 0: prof_score += 6
    
    # 3. Preferences (20%): preferred_job_role (7%), expected_salary (7%), preferred_location (6%)
    pref_score = 0
    if (profile.get("preferred_job_role") or "").strip(): pref_score += 7
    if (profile.get("expected_salary") or "").strip(): pref_score += 7
    if (profile.get("preferred_location") or "").strip(): pref_score += 6
    
    # 4. Education (20%): qualification (10%), course/institution (10%)
    edu_score = 0
    if (profile.get("qualification") or "").strip(): edu_score += 10
    if (profile.get("course") or profile.get("institution") or "").strip(): edu_score += 10
    
    # 5. Resume & Skills (20%): skills (10%), resume_url (10%)
    skills_resume_score = 0
    if (profile.get("skills") or "").strip(): skills_resume_score += 10
    if (profile.get("resume_url") or "").strip(): skills_resume_score += 10
    
    total = personal_score + prof_score + pref_score + edu_score + skills_resume_score
    return {
        "percentage": min(total, 100),
        "sections": {
            "personal": {"score": personal_score, "complete": personal_score == 20},
            "professional": {"score": prof_score, "complete": prof_score == 20},
            "preferences": {"score": pref_score, "complete": pref_score == 20},
            "education": {"score": edu_score, "complete": edu_score == 20},
            "resume_skills": {"score": skills_resume_score, "complete": skills_resume_score == 20}
        }
    }

@router.get("/employee/profile")
def get_employee_profile(current_user: Dict[str, Any] = Depends(require_employee_user)):
    user_id = current_user["id"]
    p_rows = _query_db("SELECT * FROM individual_profiles WHERE user_id = %s;", (user_id,))
    if not p_rows:
        raise HTTPException(status_code=404, detail="Profile not found.")
    profile = p_rows[0]
    completion = calculate_profile_completion(profile)
    return {
        "success": True,
        "profile": profile,
        "completion": completion
    }

@router.put("/employee/profile")
def update_employee_profile(
    req_data: EmployeeProfileUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_employee_user)
):
    user_id = current_user["id"]
    full_name = (req_data.full_name or "").strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Full Name is required.")
        
    mobile = _validate_optional_mobile(req_data.mobile)
    location = (req_data.location or "").strip() or None
    city = (req_data.city or "").strip() or None
    district = (req_data.district or "").strip() or None
    job_title = (req_data.job_title or "").strip() or None
    department = (req_data.department or "").strip() or None
    expected_salary = (req_data.expected_salary or "").strip() or None
    preferred_job_role = (req_data.preferred_job_role or "").strip() or None
    preferred_department = (req_data.preferred_department or "").strip() or None
    preferred_location = (req_data.preferred_location or "").strip() or None
    qualification = (req_data.qualification or "").strip() or None
    course = (req_data.course or "").strip() or None
    institution = (req_data.institution or "").strip() or None
    passing_year = (req_data.passing_year or "").strip() or None
    skills = (req_data.skills or "").strip() or None
    
    try:
        # Check if mobile is used by another individual
        if mobile:
            dup = _query_db("SELECT id FROM individual_profiles WHERE mobile = %s AND user_id != %s;", (mobile, user_id))
            if dup:
                raise HTTPException(status_code=400, detail="This mobile number is registered to another account.")
                
        _execute_db("""
            UPDATE individual_profiles
            SET full_name = %s, mobile = %s, location = %s, city = %s, district = %s,
                job_title = %s, department = %s, experience_years = %s, expected_salary = %s,
                preferred_job_role = %s, preferred_department = %s, preferred_location = %s,
                qualification = %s, course = %s, institution = %s, passing_year = %s,
                skills = %s, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s;
        """, (
            full_name, mobile, location, city, district,
            job_title, department, req_data.experience_years or 0.0, expected_salary,
            preferred_job_role, preferred_department, preferred_location,
            qualification, course, institution, passing_year,
            skills, user_id
        ))
        
        # Load updated profile and completion
        p_rows = _query_db("SELECT * FROM individual_profiles WHERE user_id = %s;", (user_id,))
        updated_profile = p_rows[0] if p_rows else {}
        completion = calculate_profile_completion(updated_profile)
        
        return {
            "success": True,
            "message": "Profile updated successfully.",
            "profile": updated_profile,
            "completion": completion
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating employee profile: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")

@router.post("/employee/resume")
async def upload_employee_resume(
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(require_employee_user)
):
    """
    Validates and stores candidate resume in existing /assets/uploads/resumes directory.
    Updates candidate's individual_profiles.resume_url.
    """
    user_id = current_user["id"]
    ext = os.path.splitext(file.filename or "")[1].lower()
    allowed_exts = [".pdf", ".doc", ".docx"]
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF, DOC, and DOCX files are allowed.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Resume file size must be less than 10MB.")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    resume_dir = os.path.join(base_dir, "assets", "uploads", "resumes")
    os.makedirs(resume_dir, exist_ok=True)

    base = re.sub(r'[^a-zA-Z0-9_\-]', '_', os.path.splitext(file.filename or "resume")[0])
    safe_name = f"candidate_resume_{user_id}_{base[:30]}_{uuid.uuid4().hex[:6]}{ext}"
    dest_path = os.path.join(resume_dir, safe_name)

    with open(dest_path, "wb") as f:
        f.write(content)

    rel_path = f"/assets/uploads/resumes/{safe_name}"
    _execute_db("UPDATE individual_profiles SET resume_url = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s;", (rel_path, user_id))

    p_rows = _query_db("SELECT * FROM individual_profiles WHERE user_id = %s;", (user_id,))
    updated_profile = p_rows[0] if p_rows else {}
    completion = calculate_profile_completion(updated_profile)

    return {
        "success": True,
        "resume_url": rel_path,
        "filename": file.filename,
        "completion": completion,
        "message": "Resume uploaded successfully."
    }

@router.delete("/employee/resume")
def delete_employee_resume(current_user: Dict[str, Any] = Depends(require_employee_user)):
    """
    Removes candidate resume reference from individual_profiles.
    """
    user_id = current_user["id"]
    _execute_db("UPDATE individual_profiles SET resume_url = NULL, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s;", (user_id,))
    p_rows = _query_db("SELECT * FROM individual_profiles WHERE user_id = %s;", (user_id,))
    updated_profile = p_rows[0] if p_rows else {}
    completion = calculate_profile_completion(updated_profile)
    return {
        "success": True,
        "completion": completion,
        "message": "Resume deleted successfully."
    }


# --- 6. Employer Company Profile Foundation APIs ---
class EmployerProfileUpdateRequest(BaseModel):
    company_name: str
    contact_person: str
    mobile: Optional[str] = None
    whatsapp: Optional[str] = None
    area: Optional[str] = None
    location: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    company_description: Optional[str] = None
    business_type: Optional[str] = None

@router.get("/employer/profile")
def get_employer_profile(current_user: Dict[str, Any] = Depends(require_employer_user)):
    user_id = current_user["id"]
    p_rows = _query_db("SELECT * FROM company_profiles WHERE user_id = %s;", (user_id,))
    if not p_rows:
        raise HTTPException(status_code=404, detail="Company profile not found.")
    profile = p_rows[0]
    return {
        "success": True, 
        "profile": profile,
        "verification_status": profile.get("verification_status", "pending")
    }

@router.put("/employer/profile")
def update_employer_profile(
    req_data: EmployerProfileUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_employer_user)
):
    user_id = current_user["id"]
    company_name = (req_data.company_name or "").strip()
    contact_person = (req_data.contact_person or "").strip()
    
    if not company_name:
        raise HTTPException(status_code=400, detail="Company Name is required.")
    if not contact_person:
        raise HTTPException(status_code=400, detail="HR / Recruiter Name is required.")
        
    mobile = _validate_optional_mobile(req_data.mobile)
    whatsapp = _validate_optional_mobile(req_data.whatsapp)
    area = (req_data.area or "").strip() or None
    location = (req_data.location or req_data.area or "").strip() or None
    address = (req_data.address or "").strip() or None
    website = (req_data.website or "").strip() or None
    company_description = (req_data.company_description or "").strip() or None
    business_type = (req_data.business_type or "").strip() or None
    
    try:
        # Check duplicate mobile with other companies
        if mobile:
            dup = _query_db("SELECT id FROM company_profiles WHERE mobile = %s AND user_id != %s;", (mobile, user_id))
            if dup:
                raise HTTPException(status_code=400, detail="This mobile number is registered to another company account.")
                
        _execute_db("""
            UPDATE company_profiles
            SET company_name = %s, contact_person = %s, mobile = %s, whatsapp = %s,
                area = %s, location = %s, address = %s, website = %s,
                company_description = %s, business_type = %s, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s;
        """, (company_name, contact_person, mobile, whatsapp, area, location, address, website, company_description, business_type, user_id))
        
        return {"success": True, "message": "Company profile updated successfully."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating employer profile: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- 7. Logout ---
@router.post("/logout")
def public_logout(response: Response, public_session_id: Optional[str] = Cookie(None)):
    if public_session_id and _db_enabled:
        try:
            _execute_db("DELETE FROM public_user_sessions WHERE token = %s;", (public_session_id,))
        except Exception as e:
            logger.error(f"Error removing public user session: {e}")
            
    response.delete_cookie(key="public_session_id", samesite="lax")
    return {"success": True, "message": "Logged out successfully."}


# --- 8. Preserved OTP Endpoints (Registration & Password Reset) ---

class SendOtpRequest(BaseModel):
    email: str
    visitor_id: Optional[str] = None
    account_type: Optional[str] = None

@router.post("/register/send-otp")
def register_send_otp(req_data: SendOtpRequest, request: Request, response: Response):
    ip = _get_client_ip(request)
    email = _validate_email_format(req_data.email)
    
    if not check_rate_limit(f"reg_otp_ip:{ip}", max_requests=5, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many verification requests. Please wait a few minutes.")
    if not check_rate_limit(f"reg_otp_email:{email}", max_requests=3, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many verification requests for this email. Please wait a few minutes.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        existing_user = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if existing_user:
            raise HTTPException(status_code=400, detail="This email is already registered. Please sign in instead.")
            
        recent_otp = _query_db("""
            SELECT created_at, GREATEST(1, 60 - EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at))::int) AS remaining_seconds
            FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'registration' AND created_at > (CURRENT_TIMESTAMP - INTERVAL '60 seconds')
            ORDER BY created_at DESC LIMIT 1;
        """, (email,))
        if recent_otp:
            rem_sec = int(recent_otp[0].get("remaining_seconds") or 60)
            raise HTTPException(status_code=429, detail=f"Please wait {rem_sec} seconds before requesting another verification code.")
            
        _execute_db("DELETE FROM email_otp_verifications WHERE email = %s AND purpose = 'registration';", (email,))
        
        otp = generate_6digit_otp()
        otp_hashed = hash_otp(otp)
        pending_nonce = uuid.uuid4().hex
        
        _execute_db("""
            INSERT INTO email_otp_verifications (email, otp_hash, purpose, expires_at, attempts, token_nonce, is_consumed, created_at)
            VALUES (%s, %s, 'registration', CURRENT_TIMESTAMP + INTERVAL '5 minutes', 0, %s, FALSE, CURRENT_TIMESTAMP);
        """, (email, otp_hashed, pending_nonce))
        
        send_otp_email(to_email=email, otp_code=otp, purpose="registration")

        # Bind Step 2 pending OTP countdown to an HttpOnly cookie (purpose='registration_pending')
        pending_token = generate_signed_temp_token(email=email, purpose="registration_pending", nonce=pending_nonce)
        response.set_cookie(
            key=PENDING_REG_COOKIE_NAME,
            value=pending_token,
            httponly=True,
            max_age=300,
            expires=300,
            samesite="lax",
            secure=_is_secure_request(request),
            path="/"
        )

        try:
            vid = (req_data.visitor_id or "").strip()[:64] or None
            acct_type = (req_data.account_type or "individual").strip().lower()
            if acct_type not in ("individual", "company"):
                acct_type = "individual"
            _execute_db("""
                INSERT INTO job_analytics_events (event_type, visitor_id, metadata)
                VALUES ('registration_start', %s, %s);
            """, (vid, json.dumps({"account_type": acct_type, "source": "send_otp"})))
        except Exception as ae:
            logger.warning(f"Could not track registration_start event: {ae}")
        
        return {
            "success": True,
            "message": "Verification code has been sent to your email.",
            "cooldown_seconds": OTP_RESEND_COOLDOWN_SECONDS,
            "expires_in_seconds": 300
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during register send OTP: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")

class VerifyOtpRequest(BaseModel):
    email: str
    otp: str

@router.post("/register/verify-otp")
def register_verify_otp(req_data: VerifyOtpRequest, request: Request, response: Response):
    ip = _get_client_ip(request)
    email = _validate_email_format(req_data.email)
    otp = req_data.otp.strip()
    
    if len(otp) != 6 or not otp.isdigit():
        raise HTTPException(status_code=400, detail="Verification code must be exactly 6 digits.")
        
    if not check_rate_limit(f"reg_verify_ip:{ip}", max_requests=10, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many verification attempts. Please wait a few minutes.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        rows = _query_db("""
            SELECT id, otp_hash, expires_at, attempts, verified_at, is_consumed, (expires_at < CURRENT_TIMESTAMP) AS is_expired 
            FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'registration'
            ORDER BY created_at DESC LIMIT 1;
        """, (email,))
        
        if not rows:
            raise HTTPException(status_code=400, detail="No verification request found. Please request a new code.")
            
        otp_rec = rows[0]
        if otp_rec["is_consumed"]:
            raise HTTPException(status_code=400, detail="This verification code has already been used.")
        if otp_rec["is_expired"]:
            raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new code.")
        if otp_rec["attempts"] >= OTP_MAX_ATTEMPTS:
            raise HTTPException(status_code=400, detail="Maximum verification attempts exceeded. Please request a new code.")
            
        entered_hash = hash_otp(otp)
        if entered_hash != otp_rec["otp_hash"]:
            _execute_db("UPDATE email_otp_verifications SET attempts = attempts + 1 WHERE id = %s;", (otp_rec["id"],))
            remaining = OTP_MAX_ATTEMPTS - (otp_rec["attempts"] + 1)
            if remaining <= 0:
                raise HTTPException(status_code=400, detail="Maximum attempts exceeded. Please request a new code.")
            raise HTTPException(status_code=400, detail=f"Invalid verification code. {remaining} attempt(s) remaining.")
            
        token_nonce = uuid.uuid4().hex
        _execute_db("""
            UPDATE email_otp_verifications 
            SET verified_at = CURRENT_TIMESTAMP, token_nonce = %s, is_consumed = FALSE
            WHERE id = %s;
        """, (token_nonce, otp_rec["id"]))
        
        temp_token = generate_signed_temp_token(email=email, purpose="registration", nonce=token_nonce)

        # Deliver verification credential in an HttpOnly cookie (never persisted in sessionStorage/localStorage)
        response.set_cookie(
            key=PENDING_REG_COOKIE_NAME,
            value=temp_token,
            httponly=True,
            max_age=PENDING_REG_MAX_AGE,
            expires=PENDING_REG_MAX_AGE,
            samesite="lax",
            secure=_is_secure_request(request),
            path="/"
        )
        
        return {
            "success": True,
            "message": "Email verified successfully.",
            "email": email,
            "expires_in_seconds": PENDING_REG_MAX_AGE
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during register verify OTP: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


@router.get("/register/pending-status")
def register_pending_status(
    request: Request,
    email: Optional[str] = None,
    dg_reg_verify: Optional[str] = Cookie(None)
):
    """
    Checks whether the caller has an active, valid, unconsumed HttpOnly pending registration
    session (`dg_reg_verify` cookie) for Step 3 (`purpose='registration'`) or Step 2 (`purpose='registration_pending'`).
    Strictly requires the caller's signed HttpOnly cookie matching the server-side `token_nonce` to prevent
    email enumeration and unauthorized registration status disclosure.
    """
    ip = _get_client_ip(request)
    if not check_rate_limit(f"reg_pending_ip:{ip}", max_requests=30, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")

    if not dg_reg_verify or not _db_enabled:
        return {"verified": False, "otp_pending": False, "email": None}

    raw_cookie = dg_reg_verify.strip()
    target_email = (email or "").strip().lower()

    # 1. Check for verified Step 3 session cookie (purpose='registration')
    is_valid_ver, payload_ver, _ = verify_signed_temp_token(raw_cookie, expected_purpose="registration")
    if is_valid_ver and payload_ver:
        token_email = (payload_ver.get("email") or "").strip().lower()
        nonce = payload_ver.get("nonce")
        if token_email and nonce and (not target_email or token_email == target_email):
            rows = _query_db("""
                SELECT id, is_consumed, verified_at,
                       GREATEST(0, 600 - EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - verified_at))::int) AS rem_sec
                FROM email_otp_verifications
                WHERE email = %s AND purpose = 'registration' AND token_nonce = %s
                  AND is_consumed = FALSE AND verified_at IS NOT NULL
                  AND verified_at >= (CURRENT_TIMESTAMP - INTERVAL '10 minutes')
                LIMIT 1;
            """, (token_email, nonce))
            if rows:
                return {
                    "verified": True,
                    "otp_pending": False,
                    "email": token_email,
                    "expires_in_seconds": int(rows[0].get("rem_sec") or 600)
                }

    # 2. Check for unverified Step 2 OTP countdown cookie (purpose='registration_pending')
    is_valid_pend, payload_pend, _ = verify_signed_temp_token(raw_cookie, expected_purpose="registration_pending")
    if is_valid_pend and payload_pend:
        token_email = (payload_pend.get("email") or "").strip().lower()
        nonce = payload_pend.get("nonce")
        if token_email and nonce and (not target_email or token_email == target_email):
            otp_rows = _query_db("""
                SELECT id, is_consumed, verified_at,
                       GREATEST(0, 60 - EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at))::int) AS cooldown_sec,
                       GREATEST(0, EXTRACT(EPOCH FROM (expires_at - CURRENT_TIMESTAMP))::int) AS exp_sec
                FROM email_otp_verifications
                WHERE email = %s AND purpose = 'registration' AND token_nonce = %s
                  AND is_consumed = FALSE AND verified_at IS NULL AND expires_at > CURRENT_TIMESTAMP
                ORDER BY created_at DESC LIMIT 1;
            """, (token_email, nonce))
            if otp_rows and not otp_rows[0].get("verified_at"):
                return {
                    "verified": False,
                    "otp_pending": True,
                    "email": token_email,
                    "cooldown_seconds": int(otp_rows[0].get("cooldown_sec") or 0),
                    "expires_in_seconds": int(otp_rows[0].get("exp_sec") or 0)
                }

    return {"verified": False, "otp_pending": False, "email": None}


class CompleteRegistrationRequest(BaseModel):
    email: Optional[str] = None
    account_type: str
    password: str
    confirm_password: Optional[str] = None
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    location: Optional[str] = None
    department: Optional[str] = None
    company_name: Optional[str] = None
    contact_person: Optional[str] = None
    whatsapp: Optional[str] = None
    area: Optional[str] = None
    visitor_id: Optional[str] = None

@router.post("/register/complete")
def register_complete(
    req_data: CompleteRegistrationRequest,
    response: Response,
    dg_reg_verify: Optional[str] = Cookie(None)
):
    account_type = req_data.account_type.strip().lower()
    if account_type not in ("individual", "company"):
        raise HTTPException(status_code=400, detail="Invalid account type.")
        
    password = _validate_password_strength(req_data.password, req_data.confirm_password)
    
    mobile_clean = _validate_optional_mobile(req_data.mobile)
    whatsapp_clean = _validate_optional_mobile(req_data.whatsapp)

    full_name_clean = (req_data.full_name or "").strip()
    location_clean = (req_data.location or "").strip() or None
    department_clean = (req_data.department or "").strip() or None
    company_name_clean = (req_data.company_name or "").strip()
    contact_person_clean = (req_data.contact_person or "").strip()
    area_clean = (req_data.area or "").strip() or None

    if account_type == "individual":
        if not full_name_clean:
            raise HTTPException(status_code=400, detail="Full name is required.")
        if not mobile_clean:
            raise HTTPException(status_code=400, detail="Please enter a valid 10-digit mobile number.")
    else:
        if not company_name_clean:
            raise HTTPException(status_code=400, detail="Company name is required.")
        if not contact_person_clean:
            raise HTTPException(status_code=400, detail="HR / Recruiter name is required.")
        if not mobile_clean:
            raise HTTPException(status_code=400, detail="Please enter a valid 10-digit official mobile number.")
            
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        otp_rec_id, email = _verify_registration_otp_token_or_400(
            req_data.email,
            dg_reg_verify
        )
        
        existing_user = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if existing_user:
            raise HTTPException(status_code=400, detail="This email is already registered. Please sign in.")

        if account_type == "individual":
            existing_mobile = _query_db("SELECT id FROM individual_profiles WHERE mobile = %s;", (mobile_clean,))
            if existing_mobile:
                raise HTTPException(status_code=400, detail="This mobile number is already registered with another account. Please sign in.")
        else:
            existing_mobile = _query_db("SELECT id FROM company_profiles WHERE mobile = %s;", (mobile_clean,))
            if existing_mobile:
                raise HTTPException(status_code=400, detail="This mobile number is already registered with another company account. Please sign in.")

        # Atomically consume OTP token before account creation (single-use) and clear dg_reg_verify cookie
        _consume_registration_otp_or_400(otp_rec_id, response)
            
        password_hash = generate_password_hash(password, method="scrypt")
        
        create_user_query = """
            INSERT INTO public_users (account_type, email, password_hash, email_verified, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, TRUE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id;
        """
        user_rows = _execute_db_returning(create_user_query, (account_type, email, password_hash))
        new_user_id = user_rows[0]["id"]
        
        if account_type == "individual":
            _execute_db("""
                INSERT INTO individual_profiles (user_id, full_name, email, mobile, location, department, preferred_department, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """, (new_user_id, full_name_clean, email, mobile_clean, location_clean, department_clean, department_clean))
        else:
            _execute_db("""
                INSERT INTO company_profiles (user_id, company_name, contact_person, email, mobile, whatsapp, area, verification_status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """, (new_user_id, company_name_clean, contact_person_clean, email, mobile_clean, whatsapp_clean, area_clean))
        
        session_token = str(uuid.uuid4())
        _execute_db("""
            INSERT INTO public_user_sessions (token, user_id, expires_at, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '30 days', CURRENT_TIMESTAMP);
        """, (session_token, new_user_id))
        
        response.set_cookie(
            key="public_session_id",
            value=session_token,
            httponly=True,
            expires=30 * 24 * 3600,
            samesite="lax"
        )
        
        redirect_url = "/dashboard/individual" if account_type == "individual" else "/dashboard/company"

        # Track registration_complete analytics event
        try:
            vid = (req_data.visitor_id or "").strip()[:64] or None
            _execute_db("""
                INSERT INTO job_analytics_events (event_type, visitor_id, user_id, session_id, metadata)
                VALUES ('registration_complete', %s, %s, %s, %s);
            """, (vid, new_user_id, session_token, json.dumps({"account_type": account_type, "source": "register_complete"})))
        except Exception as ae:
            logger.warning(f"Could not track registration_complete event: {ae}")

        return {
            "success": True,
            "message": "Account created successfully.",
            "user": {"id": new_user_id, "email": email, "account_type": account_type},
            "redirect_url": redirect_url
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during registration complete: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")

# --- 9. Forgot Password Endpoints ---
@router.post("/forgot-password/send-otp")
def forgot_password_send_otp(req_data: SendOtpRequest, request: Request):
    ip = _get_client_ip(request)
    email = _validate_email_format(req_data.email)
    
    if not check_rate_limit(f"forgot_otp_ip:{ip}", max_requests=5, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many reset requests. Please wait a few minutes.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        user_rows = _query_db("SELECT id FROM public_users WHERE email = %s AND is_active = TRUE;", (email,))
        if not user_rows:
            return {
                "success": True,
                "message": "If an account exists with this email, a password reset code has been sent.",
                "cooldown_seconds": OTP_RESEND_COOLDOWN_SECONDS,
                "expires_in_seconds": 300
            }
            
        recent_otp = _query_db("""
            SELECT created_at FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'forgot_password' AND created_at > (CURRENT_TIMESTAMP - INTERVAL '60 seconds')
            ORDER BY created_at DESC LIMIT 1;
        """, (email,))
        if recent_otp:
            raise HTTPException(status_code=429, detail="Please wait 60 seconds before requesting another reset code.")
            
        _execute_db("DELETE FROM email_otp_verifications WHERE email = %s AND purpose = 'forgot_password';", (email,))
        
        otp = generate_6digit_otp()
        otp_hashed = hash_otp(otp)
        
        _execute_db("""
            INSERT INTO email_otp_verifications (email, otp_hash, purpose, expires_at, attempts, created_at)
            VALUES (%s, %s, 'forgot_password', CURRENT_TIMESTAMP + INTERVAL '5 minutes', 0, CURRENT_TIMESTAMP);
        """, (email, otp_hashed))
        
        send_otp_email(to_email=email, otp_code=otp, purpose="forgot_password")
        
        return {
            "success": True,
            "message": "If an account exists with this email, a password reset code has been sent.",
            "cooldown_seconds": OTP_RESEND_COOLDOWN_SECONDS,
            "expires_in_seconds": 300
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during forgot password send OTP: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")

@router.post("/forgot-password/verify-otp")
def forgot_password_verify_otp(req_data: VerifyOtpRequest, request: Request):
    ip = _get_client_ip(request)
    email = _validate_email_format(req_data.email)
    otp = req_data.otp.strip()
    
    if len(otp) != 6 or not otp.isdigit():
        raise HTTPException(status_code=400, detail="Reset code must be exactly 6 digits.")
        
    if not check_rate_limit(f"forgot_verify_ip:{ip}", max_requests=10, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many reset attempts. Please wait a few minutes.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        rows = _query_db("""
            SELECT id, otp_hash, expires_at, attempts, verified_at, is_consumed, (expires_at < CURRENT_TIMESTAMP) AS is_expired 
            FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'forgot_password'
            ORDER BY created_at DESC LIMIT 1;
        """, (email,))
        
        if not rows:
            raise HTTPException(status_code=400, detail="No active reset request found. Please request a new code.")
            
        otp_rec = rows[0]
        if otp_rec["is_consumed"]:
            raise HTTPException(status_code=400, detail="This reset code has already been used.")
        if otp_rec["is_expired"]:
            raise HTTPException(status_code=400, detail="Reset code has expired. Please request a new code.")
        if otp_rec["attempts"] >= OTP_MAX_ATTEMPTS:
            raise HTTPException(status_code=400, detail="Maximum verification attempts exceeded.")
            
        entered_hash = hash_otp(otp)
        if entered_hash != otp_rec["otp_hash"]:
            _execute_db("UPDATE email_otp_verifications SET attempts = attempts + 1 WHERE id = %s;", (otp_rec["id"],))
            remaining = OTP_MAX_ATTEMPTS - (otp_rec["attempts"] + 1)
            if remaining <= 0:
                raise HTTPException(status_code=400, detail="Maximum attempts exceeded.")
            raise HTTPException(status_code=400, detail=f"Invalid reset code. {remaining} attempt(s) remaining.")
            
        token_nonce = uuid.uuid4().hex
        _execute_db("""
            UPDATE email_otp_verifications 
            SET verified_at = CURRENT_TIMESTAMP, token_nonce = %s, is_consumed = FALSE
            WHERE id = %s;
        """, (token_nonce, otp_rec["id"]))
        
        temp_token = generate_signed_temp_token(email=email, purpose="forgot_password", nonce=token_nonce)
        return {"success": True, "message": "Reset code verified.", "reset_token": temp_token}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during forgot password verify OTP: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")

class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str

@router.post("/reset-password")
def reset_password(req_data: ResetPasswordRequest):
    is_valid, token_payload, err_msg = verify_signed_temp_token(req_data.reset_token, expected_purpose="forgot_password")
    if not is_valid or not token_payload:
        raise HTTPException(status_code=400, detail=err_msg or "Invalid or expired reset token.")
        
    email = token_payload["email"].strip().lower()
    nonce = token_payload["nonce"]
    new_password = _validate_password_strength(req_data.new_password)
    
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        otp_records = _query_db("""
            SELECT id, is_consumed, verified_at 
            FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'forgot_password' AND token_nonce = %s;
        """, (email, nonce))
        
        if not otp_records or otp_records[0]["is_consumed"] or not otp_records[0]["verified_at"]:
            raise HTTPException(status_code=400, detail="Reset token is invalid or has already been used.")
            
        otp_rec_id = otp_records[0]["id"]
        
        user_rows = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if not user_rows:
            raise HTTPException(status_code=404, detail="User account not found.")
            
        user_id = user_rows[0]["id"]
        new_hash = generate_password_hash(new_password, method="scrypt")
        
        _execute_db("UPDATE public_users SET password_hash = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (new_hash, user_id))
        _execute_db("DELETE FROM public_user_sessions WHERE user_id = %s;", (user_id,))
        _execute_db("UPDATE email_otp_verifications SET is_consumed = TRUE WHERE id = %s;", (otp_rec_id,))
        
        return {
            "success": True,
            "message": "Your password has been reset successfully. Please sign in with your new password."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during reset password: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# ==============================================================================
# --- 7. GOOGLE SIGN-IN INTEGRATION (HARDENED SECURITY ARCHITECTURE) ---
# ==============================================================================

OAUTH_PASSWORD_SENTINEL_PREFIX = "!google_oauth_"
GOOGLE_TICKET_COOKIE_NAME = "dg_oauth_ticket"
GOOGLE_TICKET_EXPIRY_SECONDS = 600  # 10 minutes

# Thread-safe in-memory ticket store for local development/testing: {jti: dict}
_LOCAL_OAUTH_TICKETS: Dict[str, Dict[str, Any]] = {}
import threading
_ticket_lock = threading.Lock()

def generate_oauth_sentinel_hash() -> str:
    """Generates an unguessable sentinel password string with 32 bytes (256 bits) of cryptographic entropy."""
    return f"{OAUTH_PASSWORD_SENTINEL_PREFIX}{secrets.token_hex(32)}"

def _classify_email_trust_tier(id_info: Dict[str, Any]) -> Tuple[int, str]:
    """
    Tier 1 (Consumer Gmail): domain in ['gmail.com', 'googlemail.com'] AND email_verified == True.
    Tier 2 (Google Workspace): email_verified == True AND claim.get('hd') matches email domain strictly.
    Tier 3 (Third-Party / Non-Authoritative): Yahoo, Outlook, Zoho, or domain mismatch. Mandatory Email OTP required.
    Tier 4 (Untrusted): email_verified is False or missing.
    Returns: (tier: int, reason: str)
    """
    if not id_info.get("email_verified"):
        return 4, "Google email address is not verified."

    email = (id_info.get("email") or "").strip().lower()
    if "@" not in email:
        return 4, "Invalid email address format."

    email_domain = email.split("@")[1].strip().lower()
    if email_domain in ["gmail.com", "googlemail.com"]:
        return 1, "Authoritative Consumer Gmail"

    hd = (id_info.get("hd") or "").strip().lower()
    if hd and hd == email_domain:
        return 2, "Authoritative Google Workspace Enterprise Domain"

    return 3, "Third-Party Non-Authoritative Domain (Email OTP Mandatory)"

def _verify_google_id_token(id_token_str: str) -> Dict[str, Any]:
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()

    # Development stub for testing without external Google Cloud dependency
    if (not client_id or os.getenv("ENVIRONMENT") != "production") and id_token_str.startswith("mock_token_"):
        parts = id_token_str.split(":")
        # format: mock_token_valid:email:name:sub:hd:verified
        email = parts[1] if len(parts) > 1 else "test@gmail.com"
        name = parts[2] if len(parts) > 2 else "Test User"
        sub = parts[3] if len(parts) > 3 else "sub_mock_123"
        hd = parts[4] if len(parts) > 4 and parts[4] != "none" else None
        verified = (parts[5].lower() != "false") if len(parts) > 5 else True
        if parts[0] == "mock_token_invalid_sig":
            raise HTTPException(status_code=401, detail="Invalid token signature.")
        if parts[0] == "mock_token_wrong_aud":
            raise HTTPException(status_code=401, detail="Audience mismatch.")
        if parts[0] == "mock_token_wrong_iss":
            raise HTTPException(status_code=401, detail="Invalid token issuer.")
        if parts[0] == "mock_token_expired":
            raise HTTPException(status_code=401, detail="Token has expired.")
        if not sub:
            raise HTTPException(status_code=400, detail="Missing Google identity identifier.")
        return {
            "email": email,
            "name": name,
            "sub": sub,
            "hd": hd,
            "email_verified": verified,
            "aud": client_id or "mock_client_id",
            "iss": "https://accounts.google.com"
        }

    if not client_id:
        raise HTTPException(status_code=500, detail="Google Client ID is not configured on the server.")

    try:
        id_info = id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            client_id
        )
        if id_info.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
            raise HTTPException(status_code=401, detail="Invalid token issuer.")
        if not id_info.get("sub"):
            raise HTTPException(status_code=400, detail="Missing Google identity identifier.")
        return id_info
    except ValueError as ve:
        raise HTTPException(status_code=401, detail=f"Invalid Google ID token: {str(ve)}")
    except Exception as e:
        logger.error(f"Google ID token verification error: {e}")
        raise HTTPException(status_code=401, detail="Google authentication verification failed.")

def _store_pending_oauth_ticket(jti: str, google_sub: str, email: str, role: str, expires_at: datetime.datetime):
    with _ticket_lock:
        _LOCAL_OAUTH_TICKETS[jti] = {
            "jti": jti,
            "google_sub": google_sub,
            "email": email,
            "role": role,
            "is_consumed": False,
            "expires_at": expires_at.timestamp() if hasattr(expires_at, "timestamp") else time.time() + 600,
            "created_at": time.time()
        }
    if _db_enabled:
        try:
            _execute_db("""
                INSERT INTO pending_oauth_tickets (jti, google_sub, email, role, is_consumed, expires_at)
                VALUES (%s, %s, %s, %s, FALSE, %s);
            """, (jti, google_sub, email, role, expires_at))
        except Exception as e:
            logger.info(f"Using in-memory pending ticket store fallback: {e}")

def _get_pending_oauth_ticket(jti: str, expected_role: str) -> Dict[str, Any]:
    """
    Validates ticket existence, expiry, consumption status, and role binding WITHOUT consuming it.
    Uses database-side timestamp comparison (expires_at < CURRENT_TIMESTAMP) to avoid host/container clock skew.
    """
    with _ticket_lock:
        ticket = _LOCAL_OAUTH_TICKETS.get(jti)
        if _db_enabled:
            try:
                rows = _query_db("""
                    SELECT jti, google_sub, email, role, is_consumed,
                           (expires_at < CURRENT_TIMESTAMP) AS is_expired
                    FROM pending_oauth_tickets
                    WHERE jti = %s;
                """, (jti,))
                if rows:
                    r = rows[0]
                    ticket = {
                        "jti": r["jti"],
                        "google_sub": r["google_sub"],
                        "email": r["email"],
                        "role": r["role"],
                        "is_consumed": r["is_consumed"],
                        "is_expired": r["is_expired"]
                    }
            except Exception as e:
                logger.warning(f"Database query for pending ticket failed: {e}")

        if not ticket:
            raise HTTPException(status_code=400, detail="Registration session not found or expired. Please sign in again.")

        if ticket.get("is_consumed"):
            raise HTTPException(status_code=400, detail="This registration session has already been used.")

        # Check expiry via database flag or fallback to timestamp
        if ticket.get("is_expired"):
            raise HTTPException(status_code=400, detail="Registration session expired. Please sign in again.")
        if "expires_at" in ticket and ticket["expires_at"] < time.time():
            raise HTTPException(status_code=400, detail="Registration session expired. Please sign in again.")

        if ticket.get("role") != expected_role:
            raise HTTPException(status_code=400, detail=f"Role mismatch error: Expected {ticket.get('role')}, got {expected_role}.")

        return ticket

def _consume_pending_oauth_ticket(jti: str, expected_role: str) -> Dict[str, Any]:
    ticket = _get_pending_oauth_ticket(jti, expected_role=expected_role)
    with _ticket_lock:
        ticket["is_consumed"] = True
        _LOCAL_OAUTH_TICKETS[jti] = ticket
    if _db_enabled:
        updated = _execute_db_returning("""
            UPDATE pending_oauth_tickets
            SET is_consumed = TRUE
            WHERE jti = %s AND is_consumed = FALSE AND expires_at > CURRENT_TIMESTAMP
            RETURNING jti;
        """, (jti,))
        if not updated:
            raise HTTPException(status_code=400, detail="This registration session has already been used or expired.")
    return ticket


class GoogleVerifyRequest(BaseModel):
    id_token: str
    role: str = "individual"  # 'individual' or 'company'
    visitor_id: Optional[str] = None

class GoogleCompleteRegistrationRequest(BaseModel):
    full_name: Optional[str] = None
    mobile: str
    location: Optional[str] = None
    company_name: Optional[str] = None
    contact_person: Optional[str] = None
    area: Optional[str] = None
    otp_code: Optional[str] = None
    visitor_id: Optional[str] = None

class GoogleLinkAccountRequest(BaseModel):
    method: str = "password"  # 'password' or 'otp'
    password: Optional[str] = None
    otp_code: Optional[str] = None
    visitor_id: Optional[str] = None


@router.get("/google/config")
def get_google_oauth_config():
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    enabled = bool(os.getenv("GOOGLE_OAUTH_ENABLED", "true").lower() in ("true", "1") and client_id)
    return {
        "enabled": enabled,
        "client_id": client_id
    }


@router.post("/google/verify")
def google_verify(
    req_data: GoogleVerifyRequest,
    response: Response,
    request: Request
):
    ip = _get_client_ip(request)
    if not check_rate_limit(f"g_verify_ip:{ip}", max_requests=15, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many verification attempts. Please wait a few minutes.")

    target_role = "company" if req_data.role in ("company", "employer") else "individual"
    id_info = _verify_google_id_token(req_data.id_token)

    tier, tier_msg = _classify_email_trust_tier(id_info)
    if tier == 4:
        raise HTTPException(status_code=400, detail="Google account email is not verified.")

    email = id_info["email"].strip().lower()
    google_sub = id_info["sub"]
    name = id_info.get("name", "")

    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    # 1. Check if user already exists
    existing_user_rows = _query_db("""
        SELECT id, account_type, email, google_sub, is_active
        FROM public_users
        WHERE email = %s;
    """, (email,))

    if existing_user_rows:
        user = existing_user_rows[0]

        # Enforce account active status
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Your account has been deactivated. Please contact support.")

        # Enforce strict role matching (prevent cross-role account linking/takeover)
        if user["account_type"] != target_role:
            existing_role_title = "Employer" if user["account_type"] == "company" else "Job Seeker"
            requested_role_title = "Employer" if target_role == "company" else "Job Seeker"
            raise HTTPException(
                status_code=400,
                detail=f"This email is already registered as a {existing_role_title} account. Cannot link with {requested_role_title} portal."
            )

        # Case A: Already linked to this Google ID -> Instant Login
        if user.get("google_sub") == google_sub:
            session_token = str(uuid.uuid4())
            _execute_db("""
                INSERT INTO public_user_sessions (token, user_id, expires_at, created_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '30 days', CURRENT_TIMESTAMP);
            """, (session_token, user["id"]))

            response.set_cookie(
                key="public_session_id",
                value=session_token,
                httponly=True,
                expires=30 * 24 * 3600,
                samesite="lax",
                secure=_is_secure_request(request)
            )

            redirect_url = "/dashboard/individual" if target_role == "individual" else "/dashboard/company"
            return {
                "success": True,
                "action": "login",
                "role": target_role,
                "email": email,
                "redirect_url": redirect_url
            }

        # Case B: Already linked to a DIFFERENT Google ID -> Identity Conflict
        if user.get("google_sub") and user["google_sub"] != google_sub:
            raise HTTPException(
                status_code=403,
                detail="Security Conflict: This account is already linked to a different Google account."
            )

        # Case C: Existing account with google_sub IS NULL -> Verification Challenge Required
        jti = str(uuid.uuid4())
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=GOOGLE_TICKET_EXPIRY_SECONDS)
        _store_pending_oauth_ticket(jti, google_sub, email, target_role, expires_at)

        response.set_cookie(
            key=GOOGLE_TICKET_COOKIE_NAME,
            value=jti,
            httponly=True,
            max_age=GOOGLE_TICKET_EXPIRY_SECONDS,
            samesite="lax",
            path="/api/auth/google",
            secure=_is_secure_request(request)
        )

        return {
            "success": True,
            "action": "link_challenge_required",
            "email": email,
            "role": target_role,
            "message": "An existing account with this email was found. Please enter your password or verify via email code to link your Google account."
        }

    # 2. Check if this google_sub is already linked to another email
    sub_conflict = _query_db("SELECT id FROM public_users WHERE google_sub = %s;", (google_sub,))
    if sub_conflict:
        raise HTTPException(
            status_code=400,
            detail="This Google account is already linked to another DigiGarment account."
        )

    # 3. New User Registration Ticket
    jti = str(uuid.uuid4())
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=GOOGLE_TICKET_EXPIRY_SECONDS)
    _store_pending_oauth_ticket(jti, google_sub, email, target_role, expires_at)

    response.set_cookie(
        key=GOOGLE_TICKET_COOKIE_NAME,
        value=jti,
        httponly=True,
        max_age=GOOGLE_TICKET_EXPIRY_SECONDS,
        samesite="lax",
        path="/api/auth/google",
        secure=_is_secure_request(request)
    )

    # Tier 3 Third-Party Domain: Trigger mandatory 6-digit Email OTP
    if tier == 3:
        otp = generate_6digit_otp()
        otp_h = hash_otp(otp)
        otp_nonce = jti
        otp_purpose = f"google_oauth:{jti}"

        # Invalidate any prior pending OTPs for this email and purpose
        _execute_db("DELETE FROM email_otp_verifications WHERE email = %s AND purpose = %s;", (email, otp_purpose))

        _execute_db("""
            INSERT INTO email_otp_verifications (email, otp_hash, purpose, expires_at, token_nonce, attempts, is_consumed, created_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '5 minutes', %s, 0, FALSE, CURRENT_TIMESTAMP);
        """, (email, otp_h, otp_purpose, otp_nonce))

        # Send Email OTP via Resend
        send_otp_email(to_email=email, otp_code=otp, purpose="registration")

        return {
            "success": True,
            "action": "otp_verification_required",
            "email": email,
            "role": target_role,
            "prefilled_name": name,
            "trust_tier": tier,
            "message": f"Verification code sent to {email}. Please enter the 6-digit code to complete registration."
        }

    # Tier 1 & 2: Authoritative Gmail / Google Workspace -> Proceed to Profile Completion
    return {
        "success": True,
        "action": "needs_profile",
        "email": email,
        "role": target_role,
        "prefilled_name": name,
        "trust_tier": tier
    }


@router.post("/google/complete-registration")
def google_complete_registration(
    req_data: GoogleCompleteRegistrationRequest,
    response: Response,
    request: Request,
    dg_oauth_ticket: Optional[str] = Cookie(None)
):
    ip = _get_client_ip(request)
    if not check_rate_limit(f"g_comp_ip:{ip}", max_requests=10, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Please wait a few minutes.")

    jti = (dg_oauth_ticket or "").strip()
    if not jti:
        raise HTTPException(status_code=400, detail="Missing registration ticket. Please sign in with Google again.")

    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    # 1. Role determination & field validation
    is_employer = bool(req_data.company_name or req_data.contact_person)
    expected_role = "company" if is_employer else "individual"

    # 2. Validate ticket existence, role, and expiry WITHOUT consuming it (Fix B)
    ticket = _get_pending_oauth_ticket(jti, expected_role=expected_role)
    email = ticket["email"]
    google_sub = ticket["google_sub"]
    role = ticket["role"]

    # 3. Mobile Format Validation (preserves ticket on invalid mobile)
    mobile = _validate_indian_mobile(req_data.mobile)

    # 4. If Tier 3 Email OTP was required, verify OTP without consuming registration ticket (Fix A & B)
    otp_purpose = f"google_oauth:{jti}"
    otp_records = _query_db("""
        SELECT id, otp_hash, attempts, is_consumed, (expires_at < CURRENT_TIMESTAMP) AS is_expired
        FROM email_otp_verifications
        WHERE email = %s AND purpose = %s;
    """, (email, otp_purpose))

    otp_rec = None
    if otp_records:
        otp_rec = otp_records[0]
        submitted_otp = (req_data.otp_code or "").strip()
        if not submitted_otp:
            raise HTTPException(status_code=400, detail="Email verification code is required.")
        if otp_rec["is_consumed"]:
            raise HTTPException(status_code=400, detail="Email verification code has already been used.")
        if otp_rec["is_expired"]:
            raise HTTPException(status_code=400, detail="Email verification code has expired. Please try again.")
        if otp_rec["attempts"] >= OTP_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Maximum OTP verification attempts exceeded.")

        expected_hash = hash_otp(submitted_otp)
        if otp_rec["otp_hash"] != expected_hash:
            _execute_db("UPDATE email_otp_verifications SET attempts = attempts + 1 WHERE id = %s;", (otp_rec["id"],))
            remaining = OTP_MAX_ATTEMPTS - (otp_rec["attempts"] + 1)
            raise HTTPException(status_code=400, detail=f"Invalid verification code. {max(0, remaining)} attempt(s) remaining.")

    # 5. Mobile Uniqueness & Profile Field Validation (preserves ticket on duplicate mobile or missing field)
    if role == "individual":
        existing_mob = _query_db("SELECT id FROM individual_profiles WHERE mobile = %s;", (mobile,))
        if existing_mob:
            raise HTTPException(status_code=400, detail="This mobile number is already registered with another account.")
        full_name = (req_data.full_name or "").strip()
        if not full_name:
            raise HTTPException(status_code=400, detail="Full Name is required.")
        location = (req_data.location or "").strip() or None
    else:
        existing_mob = _query_db("SELECT id FROM company_profiles WHERE mobile = %s;", (mobile,))
        if existing_mob:
            raise HTTPException(status_code=400, detail="This mobile number is already registered with another company account.")
        company_name = (req_data.company_name or "").strip()
        if not company_name:
            raise HTTPException(status_code=400, detail="Company Name is required.")
        contact_person = (req_data.contact_person or "").strip()
        if not contact_person:
            raise HTTPException(status_code=400, detail="Contact Person / HR Name is required.")
        area = (req_data.area or "").strip() or None
        if not area:
            raise HTTPException(status_code=400, detail="Industrial Area / Cluster is required.")
        location = (req_data.location or req_data.area or "").strip() or None

    # 6. Final Atomic Transaction: Lock & Consume Ticket and OTP + Create User & Profile
    # Use atomic conditional update to lock and consume the ticket (concurrency safe)
    # Only one concurrent request can successfully update is_consumed from FALSE to TRUE
    if _db_enabled:
        consumed_ticket = _execute_db_returning("""
            UPDATE pending_oauth_tickets
            SET is_consumed = TRUE
            WHERE jti = %s AND is_consumed = FALSE AND expires_at > CURRENT_TIMESTAMP
            RETURNING jti;
        """, (jti,))
        if not consumed_ticket:
            raise HTTPException(status_code=400, detail="This registration session has already been used or expired.")

    with _ticket_lock:
        if jti in _LOCAL_OAUTH_TICKETS:
            _LOCAL_OAUTH_TICKETS[jti]["is_consumed"] = True

    # Mark OTP consumed atomically
    if otp_rec:
        _execute_db("UPDATE email_otp_verifications SET is_consumed = TRUE, verified_at = CURRENT_TIMESTAMP WHERE id = %s;", (otp_rec["id"],))

    sentinel_hash = generate_oauth_sentinel_hash()
    try:
        user_rows = _execute_db_returning("""
            INSERT INTO public_users (account_type, email, google_sub, password_hash, auth_provider, email_verified, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'google', TRUE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id;
        """, (role, email, google_sub, sentinel_hash))
        new_user_id = user_rows[0]["id"]

        if role == "individual":
            _execute_db("""
                INSERT INTO individual_profiles (user_id, full_name, email, mobile, location, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """, (new_user_id, full_name, email, mobile, location))
        else:
            _execute_db("""
                INSERT INTO company_profiles (user_id, company_name, contact_person, email, mobile, area, location, verification_status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """, (new_user_id, company_name, contact_person, email, mobile, area, location))

        # Create session
        session_token = str(uuid.uuid4())
        _execute_db("""
            INSERT INTO public_user_sessions (token, user_id, expires_at, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '30 days', CURRENT_TIMESTAMP);
        """, (session_token, new_user_id))

        # Set session cookie and clear ticket cookie
        response.set_cookie(
            key="public_session_id",
            value=session_token,
            httponly=True,
            expires=30 * 24 * 3600,
            samesite="lax",
            secure=_is_secure_request(request)
        )
        response.delete_cookie(key=GOOGLE_TICKET_COOKIE_NAME, path="/api/auth/google")

        redirect_url = "/dashboard/individual" if role == "individual" else "/dashboard/company"
        return {
            "success": True,
            "message": "Registration completed successfully.",
            "role": role,
            "redirect_url": redirect_url
        }
    except Exception as e:
        logger.error(f"Error during Google complete registration: {e}")
        # Roll back ticket consumption in case of failure so user/session is not bricked
        try:
            if 'new_user_id' in locals() and new_user_id:
                _execute_db("DELETE FROM public_users WHERE id = %s;", (new_user_id,))
            _execute_db("UPDATE pending_oauth_tickets SET is_consumed = FALSE WHERE jti = %s;", (jti,))
            if otp_rec:
                _execute_db("UPDATE email_otp_verifications SET is_consumed = FALSE WHERE id = %s;", (otp_rec["id"],))
            with _ticket_lock:
                if jti in _LOCAL_OAUTH_TICKETS:
                    _LOCAL_OAUTH_TICKETS[jti]["is_consumed"] = False
        except Exception as rb_err:
            logger.error(f"Rollback failed: {rb_err}")
        raise HTTPException(status_code=500, detail="Failed to create account. Please try again.")


@router.post("/google/link-account")
def google_link_account(
    req_data: GoogleLinkAccountRequest,
    response: Response,
    request: Request,
    dg_oauth_ticket: Optional[str] = Cookie(None)
):
    jti = (dg_oauth_ticket or "").strip()
    if not jti:
        raise HTTPException(status_code=400, detail="Missing linking ticket. Please sign in with Google again.")

    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")

    # Retrieve ticket from store without consuming yet (consumed on success)
    with _ticket_lock:
        ticket = _LOCAL_OAUTH_TICKETS.get(jti)
    if not ticket and _db_enabled:
        rows = _query_db("SELECT jti, google_sub, email, role, is_consumed, expires_at FROM pending_oauth_tickets WHERE jti = %s;", (jti,))
        if rows:
            r = rows[0]
            ticket = {
                "jti": r["jti"],
                "google_sub": r["google_sub"],
                "email": r["email"],
                "role": r["role"],
                "is_consumed": r["is_consumed"],
                "expires_at": r["expires_at"].timestamp() if hasattr(r["expires_at"], "timestamp") else time.time() + 600
            }

    if not ticket or ticket["is_consumed"] or ticket["expires_at"] < time.time():
        raise HTTPException(status_code=400, detail="Linking session expired or invalid. Please sign in with Google again.")

    email = ticket["email"]
    google_sub = ticket["google_sub"]
    role = ticket["role"]

    # Verify existing user
    user_rows = _query_db("""
        SELECT id, account_type, email, password_hash, google_sub, is_active
        FROM public_users
        WHERE email = %s;
    """, (email,))

    if not user_rows:
        raise HTTPException(status_code=404, detail="Account not found.")

    user = user_rows[0]
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Your account has been deactivated.")

    if user["account_type"] != role:
        raise HTTPException(status_code=400, detail="Role mismatch error.")

    if user.get("google_sub"):
        raise HTTPException(status_code=403, detail="This account is already linked to a Google account.")

    # Verification Challenge: Password or Email OTP
    if req_data.method == "password":
        pwd = (req_data.password or "").strip()
        if not pwd:
            raise HTTPException(status_code=400, detail="Password is required to link account.")
        current_hash = user.get("password_hash") or ""
        if current_hash.startswith("!google_oauth_") or not check_password_hash(current_hash, pwd):
            raise HTTPException(status_code=401, detail="Incorrect account password.")
    elif req_data.method == "otp":
        otp_code = (req_data.otp_code or "").strip()
        if not otp_code:
            raise HTTPException(status_code=400, detail="Verification code is required.")
        otp_purpose = f"google_link:{jti}"
        otp_records = _query_db("""
            SELECT id, otp_hash, attempts, is_consumed, (expires_at < CURRENT_TIMESTAMP) AS is_expired
            FROM email_otp_verifications
            WHERE email = %s AND purpose = %s;
        """, (email, otp_purpose))
        if not otp_records or otp_records[0]["is_consumed"] or otp_records[0]["is_expired"]:
            raise HTTPException(status_code=400, detail="Verification code expired or invalid.")
        if otp_records[0]["attempts"] >= OTP_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Maximum attempts exceeded.")
        if otp_records[0]["otp_hash"] != hash_otp(otp_code):
            _execute_db("UPDATE email_otp_verifications SET attempts = attempts + 1 WHERE id = %s;", (otp_records[0]["id"],))
            raise HTTPException(status_code=400, detail="Invalid verification code.")
        _execute_db("UPDATE email_otp_verifications SET is_consumed = TRUE WHERE id = %s;", (otp_records[0]["id"],))
    else:
        raise HTTPException(status_code=400, detail="Invalid verification method.")

    # Atomically Link Account (verifying exactly 1 row updated)
    updated_rows = _execute_db_returning("""
        UPDATE public_users
        SET google_sub = %s, auth_provider = 'google_linked', updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND google_sub IS NULL
        RETURNING id;
    """, (google_sub, user["id"]))

    if not updated_rows:
        raise HTTPException(status_code=400, detail="Failed to link account. It may already be linked.")

    # Mark ticket consumed
    with _ticket_lock:
        if jti in _LOCAL_OAUTH_TICKETS:
            _LOCAL_OAUTH_TICKETS[jti]["is_consumed"] = True
    if _db_enabled:
        try:
            _execute_db("UPDATE pending_oauth_tickets SET is_consumed = TRUE WHERE jti = %s;", (jti,))
        except Exception:
            pass

    # Create session
    session_token = str(uuid.uuid4())
    _execute_db("""
        INSERT INTO public_user_sessions (token, user_id, expires_at, created_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '30 days', CURRENT_TIMESTAMP);
    """, (session_token, user["id"]))

    response.set_cookie(
        key="public_session_id",
        value=session_token,
        httponly=True,
        expires=30 * 24 * 3600,
        samesite="lax",
        secure=_is_secure_request(request)
    )
    response.delete_cookie(key=GOOGLE_TICKET_COOKIE_NAME, path="/api/auth/google")

    redirect_url = "/dashboard/individual" if role == "individual" else "/dashboard/company"
    return {
        "success": True,
        "message": "Google account linked successfully.",
        "role": role,
        "redirect_url": redirect_url
    }


@router.post("/google/send-link-otp")
def google_send_link_otp(
    response: Response,
    request: Request,
    dg_oauth_ticket: Optional[str] = Cookie(None)
):
    ip = _get_client_ip(request)
    if not check_rate_limit(f"g_link_otp:{ip}", max_requests=5, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many code requests. Please wait a few minutes.")

    jti = (dg_oauth_ticket or "").strip()
    if not jti:
        raise HTTPException(status_code=400, detail="Missing linking ticket.")

    with _ticket_lock:
        ticket = _LOCAL_OAUTH_TICKETS.get(jti)
    if not ticket and _db_enabled:
        rows = _query_db("SELECT jti, email, role, is_consumed, expires_at FROM pending_oauth_tickets WHERE jti = %s;", (jti,))
        if rows:
            r = rows[0]
            ticket = {"jti": r["jti"], "email": r["email"], "role": r["role"], "is_consumed": r["is_consumed"], "expires_at": r["expires_at"].timestamp() if hasattr(r["expires_at"], "timestamp") else time.time() + 600}

    if not ticket or ticket["is_consumed"] or ticket["expires_at"] < time.time():
        raise HTTPException(status_code=400, detail="Linking session expired. Please sign in with Google again.")

    email = ticket["email"]
    otp = generate_6digit_otp()
    otp_h = hash_otp(otp)
    otp_purpose = f"google_link:{jti}"

    _execute_db("DELETE FROM email_otp_verifications WHERE email = %s AND purpose = %s;", (email, otp_purpose))
    _execute_db("""
        INSERT INTO email_otp_verifications (email, otp_hash, purpose, expires_at, token_nonce, attempts, is_consumed, created_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '5 minutes', %s, 0, FALSE, CURRENT_TIMESTAMP);
    """, (email, otp_h, otp_purpose, jti))

    send_otp_email(to_email=email, otp_code=otp, purpose="registration")
    return {
        "success": True,
        "message": f"Verification code sent to {email}."
    }
