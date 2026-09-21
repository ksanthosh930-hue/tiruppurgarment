import os
import time
import uuid
import logging
import datetime
from typing import Dict, Any, Optional
import re
from fastapi import APIRouter, HTTPException, Cookie, Depends, Response, Form, Request
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
    cleaned = (mobile or "").strip()
    # Remove leading +91, 91, or 0 if present
    cleaned = re.sub(r"^(?:\+91|91|0)", "", cleaned)
    cleaned = re.sub(r"[\s\-\(\)]", "", cleaned)
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


# --- 1. Direct Employee (Job Seeker) Registration ---
class EmployeeRegisterRequest(BaseModel):
    full_name: str
    mobile: str
    email: str
    password: str
    confirm_password: str
    location: Optional[str] = None

@router.post("/register/employee")
@router.post("/register/individual")
def register_employee(req_data: EmployeeRegisterRequest, response: Response, request: Request):
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
        # Check duplicate email
        existing_email = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if existing_email:
            raise HTTPException(status_code=400, detail="This email is already registered. Please sign in.")
            
        # Check duplicate mobile in individual profiles
        existing_mobile = _query_db("SELECT id FROM individual_profiles WHERE mobile = %s;", (mobile,))
        if existing_mobile:
            raise HTTPException(status_code=400, detail="This mobile number is already registered with another account.")
            
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
    confirm_password: str
    whatsapp: Optional[str] = None
    area: Optional[str] = None
    location: Optional[str] = None

@router.post("/register/employer")
@router.post("/register/company")
def register_employer(req_data: EmployerRegisterRequest, response: Response, request: Request):
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
        # Check duplicate email
        existing_email = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if existing_email:
            raise HTTPException(status_code=400, detail="This email is already registered. Please sign in.")
            
        # Check duplicate mobile in company profiles
        existing_mobile = _query_db("SELECT id FROM company_profiles WHERE mobile = %s;", (mobile,))
        if existing_mobile:
            raise HTTPException(status_code=400, detail="This mobile number is already registered with another company account.")
            
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
        cleaned_mobile = re.sub(r"^(?:\+91|91|0)", "", raw_ident)
        cleaned_mobile = re.sub(r"[\s\-\(\)]", "", cleaned_mobile)
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
            
        if not check_password_hash(user["password_hash"], password):
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
    job_title: Optional[str] = None
    experience_years: Optional[float] = 0.0
    skills: Optional[str] = None
    expected_salary: Optional[str] = None

@router.get("/employee/profile")
def get_employee_profile(current_user: Dict[str, Any] = Depends(require_employee_user)):
    user_id = current_user["id"]
    p_rows = _query_db("SELECT * FROM individual_profiles WHERE user_id = %s;", (user_id,))
    if not p_rows:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return {"success": True, "profile": p_rows[0]}

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
    job_title = (req_data.job_title or "").strip() or None
    skills = (req_data.skills or "").strip() or None
    expected_salary = (req_data.expected_salary or "").strip() or None
    
    try:
        # Check if mobile is used by another individual
        if mobile:
            dup = _query_db("SELECT id FROM individual_profiles WHERE mobile = %s AND user_id != %s;", (mobile, user_id))
            if dup:
                raise HTTPException(status_code=400, detail="This mobile number is registered to another account.")
                
        _execute_db("""
            UPDATE individual_profiles
            SET full_name = %s, mobile = %s, location = %s, job_title = %s,
                experience_years = %s, skills = %s, expected_salary = %s, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s;
        """, (full_name, mobile, location, job_title, req_data.experience_years or 0.0, skills, expected_salary, user_id))
        
        return {"success": True, "message": "Profile updated successfully."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating employee profile: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


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

@router.post("/register/send-otp")
def register_send_otp(req_data: SendOtpRequest, request: Request):
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
            SELECT created_at FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'registration' AND created_at > (CURRENT_TIMESTAMP - INTERVAL '60 seconds')
            ORDER BY created_at DESC LIMIT 1;
        """, (email,))
        if recent_otp:
            raise HTTPException(status_code=429, detail="Please wait 60 seconds before requesting another verification code.")
            
        _execute_db("DELETE FROM email_otp_verifications WHERE email = %s AND purpose = 'registration';", (email,))
        
        otp = generate_6digit_otp()
        otp_hashed = hash_otp(otp)
        
        _execute_db("""
            INSERT INTO email_otp_verifications (email, otp_hash, purpose, expires_at, attempts, created_at)
            VALUES (%s, %s, 'registration', CURRENT_TIMESTAMP + INTERVAL '5 minutes', 0, CURRENT_TIMESTAMP);
        """, (email, otp_hashed))
        
        send_otp_email(to_email=email, otp_code=otp, purpose="registration")
        
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
def register_verify_otp(req_data: VerifyOtpRequest, request: Request):
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
        
        return {
            "success": True,
            "message": "Email verified successfully.",
            "verification_token": temp_token,
            "email": email
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during register verify OTP: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")

class CompleteRegistrationRequest(BaseModel):
    verification_token: str
    account_type: str
    password: str
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    location: Optional[str] = None
    company_name: Optional[str] = None
    contact_person: Optional[str] = None
    whatsapp: Optional[str] = None
    area: Optional[str] = None

@router.post("/register/complete")
def register_complete(req_data: CompleteRegistrationRequest, response: Response):
    is_valid, token_payload, err_msg = verify_signed_temp_token(req_data.verification_token, expected_purpose="registration")
    if not is_valid or not token_payload:
        raise HTTPException(status_code=400, detail=err_msg or "Invalid or expired verification token.")
        
    email = token_payload["email"].strip().lower()
    nonce = token_payload["nonce"]
    account_type = req_data.account_type.strip().lower()
    if account_type not in ("individual", "company"):
        raise HTTPException(status_code=400, detail="Invalid account type.")
        
    password = _validate_password_strength(req_data.password)
    
    if account_type == "individual":
        full_name = (req_data.full_name or "").strip()
        if not full_name:
            raise HTTPException(status_code=400, detail="Full name is required.")
    else:
        company_name = (req_data.company_name or "").strip()
        contact_person = (req_data.contact_person or "").strip()
        if not company_name:
            raise HTTPException(status_code=400, detail="Company name is required.")
        if not contact_person:
            raise HTTPException(status_code=400, detail="HR / Recruiter name is required.")
            
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        otp_records = _query_db("""
            SELECT id, is_consumed, verified_at 
            FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'registration' AND token_nonce = %s;
        """, (email, nonce))
        
        if not otp_records or otp_records[0]["is_consumed"] or not otp_records[0]["verified_at"]:
            raise HTTPException(status_code=400, detail="Verification token is invalid or has already been used.")
            
        otp_rec_id = otp_records[0]["id"]
        
        existing_user = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if existing_user:
            raise HTTPException(status_code=400, detail="This email is already registered. Please sign in.")
            
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
                INSERT INTO individual_profiles (user_id, full_name, email, mobile, location, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """, (new_user_id, req_data.full_name, email, req_data.mobile, req_data.location))
        else:
            _execute_db("""
                INSERT INTO company_profiles (user_id, company_name, contact_person, email, mobile, whatsapp, area, verification_status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """, (new_user_id, req_data.company_name, req_data.contact_person, email, req_data.mobile, req_data.whatsapp, req_data.area))
            
        _execute_db("UPDATE email_otp_verifications SET is_consumed = TRUE WHERE id = %s;", (otp_rec_id,))
        
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
