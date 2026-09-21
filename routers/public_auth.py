import os
import time
import uuid
import logging
import datetime
from typing import Dict, Any, Optional
import re
from fastapi import APIRouter, HTTPException, Cookie, Depends, Response, Form, Request
from pydantic import BaseModel
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

# --- Dependency: Current Public User ---
async def get_current_public_user(public_session_id: Optional[str] = Cookie(None)):
    if not public_session_id:
        raise HTTPException(status_code=401, detail="Authentication required: No active session.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        # Check active session
        query = """
            SELECT s.token, s.expires_at, u.id, u.account_type, u.email, u.email_verified, u.is_active, u.created_at
            FROM public_user_sessions s
            JOIN public_users u ON s.user_id = u.id
            WHERE s.token = %s AND s.expires_at > CURRENT_TIMESTAMP AND u.is_active = TRUE;
        """
        rows = _query_db(query, (public_session_id,))
        if not rows:
            raise HTTPException(status_code=401, detail="Session invalid or expired. Please sign in again.")
            
        user = rows[0]
        user_id = user["id"]
        account_type = user["account_type"]
        
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

# --- Email validation helper ---
def _validate_email_format(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if not cleaned or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", cleaned):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    return cleaned

# --- 1. Registration: Send OTP ---
class SendOtpRequest(BaseModel):
    email: str

@router.post("/register/send-otp")
def register_send_otp(req_data: SendOtpRequest, request: Request):
    ip = _get_client_ip(request)
    email = _validate_email_format(req_data.email)
    
    # Rate limit check: 5 requests per 5 minutes per IP, and 3 per 5 minutes per email
    if not check_rate_limit(f"reg_otp_ip:{ip}", max_requests=5, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many verification requests from your network. Please wait a few minutes.")
    if not check_rate_limit(f"reg_otp_email:{email}", max_requests=3, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many verification requests for this email. Please wait a few minutes.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        # Check if email is already registered
        existing_user = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if existing_user:
            raise HTTPException(status_code=400, detail="This email is already registered. Please sign in instead.")
            
        # Check cooldown (60 seconds)
        recent_otp = _query_db("""
            SELECT created_at FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'registration' AND created_at > (CURRENT_TIMESTAMP - INTERVAL '60 seconds')
            ORDER BY created_at DESC LIMIT 1;
        """, (email,))
        if recent_otp:
            raise HTTPException(status_code=429, detail="Please wait 60 seconds before requesting another verification code.")
            
        # Invalidate prior active OTPs for registration
        _execute_db("DELETE FROM email_otp_verifications WHERE email = %s AND purpose = 'registration';", (email,))
        
        # Generate 6-digit OTP and secure hash
        otp = generate_6digit_otp()
        otp_hashed = hash_otp(otp)
        
        # Store in DB (5 minute expiration)
        _execute_db("""
            INSERT INTO email_otp_verifications (email, otp_hash, purpose, expires_at, attempts, created_at)
            VALUES (%s, %s, 'registration', CURRENT_TIMESTAMP + INTERVAL '5 minutes', 0, CURRENT_TIMESTAMP);
        """, (email, otp_hashed))
        
        # Send via Resend (fails closed in production)
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
        raise HTTPException(status_code=500, detail="Unable to send verification email. Please try again later.")

# --- 2. Registration: Verify OTP ---
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
            raise HTTPException(status_code=400, detail="This verification code has already been used. Please request a new code.")
            
        if otp_rec["is_expired"]:
            raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new code.")
            
        if otp_rec["attempts"] >= OTP_MAX_ATTEMPTS:
            raise HTTPException(status_code=400, detail="Maximum verification attempts exceeded. Please request a new code.")
            
        # Verify hash
        entered_hash = hash_otp(otp)
        if entered_hash != otp_rec["otp_hash"]:
            _execute_db("UPDATE email_otp_verifications SET attempts = attempts + 1 WHERE id = %s;", (otp_rec["id"],))
            remaining = OTP_MAX_ATTEMPTS - (otp_rec["attempts"] + 1)
            if remaining <= 0:
                raise HTTPException(status_code=400, detail="Maximum attempts exceeded. Please request a new code.")
            raise HTTPException(status_code=400, detail=f"Invalid verification code. {remaining} attempt(s) remaining.")
            
        # Success: Generate single-use nonce & signed temporary verification token (10 min expiry)
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
        raise HTTPException(status_code=500, detail="Verification failed due to a server error. Please try again.")

# --- 3. Registration: Complete Account Creation ---
class CompleteRegistrationRequest(BaseModel):
    verification_token: str
    account_type: str
    password: str
    
    # Individual Profile Fields
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    location: Optional[str] = None
    job_title: Optional[str] = None
    experience_years: Optional[float] = 0.0
    skills: Optional[str] = None
    expected_salary: Optional[str] = None
    
    # Company Profile Fields
    company_name: Optional[str] = None
    contact_person: Optional[str] = None
    business_type: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    company_description: Optional[str] = None

@router.post("/register/complete")
def register_complete(req_data: CompleteRegistrationRequest, response: Response):
    # 1. Validate signed temporary verification token
    is_valid, token_payload, err_msg = verify_signed_temp_token(req_data.verification_token, expected_purpose="registration")
    if not is_valid or not token_payload:
        raise HTTPException(status_code=400, detail=err_msg or "Invalid or expired verification token.")
        
    email = token_payload["email"].strip().lower()
    nonce = token_payload["nonce"]
    
    # 2. Validate account type
    account_type = req_data.account_type.strip().lower()
    if account_type not in ("individual", "company"):
        raise HTTPException(status_code=400, detail="Invalid account type. Must be 'individual' or 'company'.")
        
    # 3. Validate password strength
    password = req_data.password.strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long.")
        
    # 4. Validate profile required fields
    if account_type == "individual":
        full_name = (req_data.full_name or "").strip()
        if not full_name:
            raise HTTPException(status_code=400, detail="Full name is required for individual registration.")
    elif account_type == "company":
        company_name = (req_data.company_name or "").strip()
        contact_person = (req_data.contact_person or "").strip()
        if not company_name:
            raise HTTPException(status_code=400, detail="Company name is required for company registration.")
        if not contact_person:
            raise HTTPException(status_code=400, detail="Contact person name is required for company registration.")
            
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        # 5. Validate that token nonce exists in DB and has not been consumed
        otp_records = _query_db("""
            SELECT id, is_consumed, verified_at 
            FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'registration' AND token_nonce = %s;
        """, (email, nonce))
        
        if not otp_records or otp_records[0]["is_consumed"] or not otp_records[0]["verified_at"]:
            raise HTTPException(status_code=400, detail="Verification token is invalid or has already been used.")
            
        otp_rec_id = otp_records[0]["id"]
        
        # 6. Check if email is already registered in public_users
        existing_user = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if existing_user:
            raise HTTPException(status_code=400, detail="This email is already registered. Please sign in.")
            
        # 7. Hash password securely
        password_hash = generate_password_hash(password, method="scrypt")
        
        # 8. Create public_users record (without name field, pure authentication identity)
        create_user_query = """
            INSERT INTO public_users (account_type, email, password_hash, email_verified, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, TRUE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id;
        """
        user_rows = _execute_db_returning(create_user_query, (account_type, email, password_hash))
        new_user_id = user_rows[0]["id"]
        
        # 9. Create profile record
        if account_type == "individual":
            _execute_db("""
                INSERT INTO individual_profiles (user_id, full_name, email, mobile, location, job_title, experience_years, skills, expected_salary, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """, (
                new_user_id,
                (req_data.full_name or "").strip(),
                email,
                (req_data.mobile or "").strip(),
                (req_data.location or "").strip(),
                (req_data.job_title or "").strip(),
                req_data.experience_years or 0.0,
                (req_data.skills or "").strip(),
                (req_data.expected_salary or "").strip()
            ))
        elif account_type == "company":
            _execute_db("""
                INSERT INTO company_profiles (user_id, company_name, contact_person, email, mobile, business_type, location, address, website, company_description, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """, (
                new_user_id,
                (req_data.company_name or "").strip(),
                (req_data.contact_person or "").strip(),
                email,
                (req_data.mobile or "").strip(),
                (req_data.business_type or "").strip(),
                (req_data.location or "").strip(),
                (req_data.address or "").strip(),
                (req_data.website or "").strip(),
                (req_data.company_description or "").strip()
            ))
            
        # 10. Mark OTP verification token as consumed
        _execute_db("UPDATE email_otp_verifications SET is_consumed = TRUE WHERE id = %s;", (otp_rec_id,))
        
        # 11. Create distinct public login session
        session_token = str(uuid.uuid4())
        _execute_db("""
            INSERT INTO public_user_sessions (token, user_id, expires_at, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '30 days', CURRENT_TIMESTAMP);
        """, (session_token, new_user_id))
        
        # 12. Set HttpOnly public session cookie
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
            "user": {
                "id": new_user_id,
                "email": email,
                "account_type": account_type
            },
            "redirect_url": redirect_url
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during registration complete: {e}")
        raise HTTPException(status_code=500, detail="Failed to create account due to a database error. Please try again.")

# --- 4. Public Login ---
class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/login")
def public_login(req_data: LoginRequest, response: Response, request: Request):
    ip = _get_client_ip(request)
    email = _validate_email_format(req_data.email)
    password = req_data.password.strip()
    
    if not check_rate_limit(f"login_ip:{ip}", max_requests=10, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Please wait a few minutes.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        rows = _query_db("""
            SELECT id, account_type, email, password_hash, is_active 
            FROM public_users 
            WHERE email = %s;
        """, (email,))
        
        if not rows:
            raise HTTPException(status_code=401, detail="Invalid email or password.")
            
        user = rows[0]
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Your account has been deactivated. Please contact support.")
            
        if not check_password_hash(user["password_hash"], password):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
            
        # Create public session
        session_token = str(uuid.uuid4())
        _execute_db("""
            INSERT INTO public_user_sessions (token, user_id, expires_at, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '30 days', CURRENT_TIMESTAMP);
        """, (session_token, user["id"]))
        
        # Set public session cookie
        response.set_cookie(
            key="public_session_id",
            value=session_token,
            httponly=True,
            expires=30 * 24 * 3600,
            samesite="lax"
        )
        
        account_type = user["account_type"]
        redirect_url = "/dashboard/individual" if account_type == "individual" else "/dashboard/company"
        
        return {
            "success": True,
            "message": "Signed in successfully.",
            "user": {
                "id": user["id"],
                "email": user["email"],
                "account_type": account_type
            },
            "redirect_url": redirect_url
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during public login: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed due to a server error.")

# --- 5. Public Logout ---
@router.post("/logout")
def public_logout(response: Response, public_session_id: Optional[str] = Cookie(None)):
    if public_session_id and _db_enabled:
        try:
            _execute_db("DELETE FROM public_user_sessions WHERE token = %s;", (public_session_id,))
        except Exception as e:
            logger.error(f"Error deleting public session during logout: {e}")
            
    response.delete_cookie(key="public_session_id")
    return {"success": True, "message": "Logged out successfully."}

# --- 6. Get Current Authenticated User (Me) ---
@router.get("/me")
def get_me(user = Depends(get_current_public_user)):
    return {
        "logged_in": True,
        "user": user
    }

# --- 7. Forgot Password: Send OTP ---
@router.post("/forgot-password/send-otp")
def forgot_password_send_otp(req_data: SendOtpRequest, request: Request):
    ip = _get_client_ip(request)
    email = _validate_email_format(req_data.email)
    
    if not check_rate_limit(f"forgot_otp_ip:{ip}", max_requests=5, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many password reset requests. Please wait a few minutes.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        # Check if user exists
        user_rows = _query_db("SELECT id FROM public_users WHERE email = %s AND is_active = TRUE;", (email,))
        if not user_rows:
            # Prevent account enumeration: return standard generic message without sending email
            return {
                "success": True,
                "message": "If an account exists with this email, a password reset code has been sent.",
                "cooldown_seconds": OTP_RESEND_COOLDOWN_SECONDS
            }
            
        # Check cooldown
        recent_otp = _query_db("""
            SELECT created_at FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'forgot_password' AND created_at > (CURRENT_TIMESTAMP - INTERVAL '60 seconds')
            ORDER BY created_at DESC LIMIT 1;
        """, (email,))
        if recent_otp:
            raise HTTPException(status_code=429, detail="Please wait 60 seconds before requesting another reset code.")
            
        # Invalidate prior active OTPs for forgot_password
        _execute_db("DELETE FROM email_otp_verifications WHERE email = %s AND purpose = 'forgot_password';", (email,))
        
        # Generate 6-digit OTP
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
        raise HTTPException(status_code=500, detail="Unable to process password reset request. Please try again later.")

# --- 8. Forgot Password: Verify OTP ---
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
            raise HTTPException(status_code=400, detail="Maximum verification attempts exceeded. Please request a new code.")
            
        entered_hash = hash_otp(otp)
        if entered_hash != otp_rec["otp_hash"]:
            _execute_db("UPDATE email_otp_verifications SET attempts = attempts + 1 WHERE id = %s;", (otp_rec["id"],))
            remaining = OTP_MAX_ATTEMPTS - (otp_rec["attempts"] + 1)
            if remaining <= 0:
                raise HTTPException(status_code=400, detail="Maximum attempts exceeded. Please request a new code.")
            raise HTTPException(status_code=400, detail=f"Invalid reset code. {remaining} attempt(s) remaining.")
            
        token_nonce = uuid.uuid4().hex
        _execute_db("""
            UPDATE email_otp_verifications 
            SET verified_at = CURRENT_TIMESTAMP, token_nonce = %s, is_consumed = FALSE
            WHERE id = %s;
        """, (token_nonce, otp_rec["id"]))
        
        temp_token = generate_signed_temp_token(email=email, purpose="forgot_password", nonce=token_nonce)
        
        return {
            "success": True,
            "message": "Reset code verified.",
            "reset_token": temp_token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during forgot password verify OTP: {e}")
        raise HTTPException(status_code=500, detail="Verification failed due to a server error.")

# --- 9. Forgot Password: Reset Password ---
class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str

@router.post("/reset-password")
def reset_password(req_data: ResetPasswordRequest):
    # Validate token
    is_valid, token_payload, err_msg = verify_signed_temp_token(req_data.reset_token, expected_purpose="forgot_password")
    if not is_valid or not token_payload:
        raise HTTPException(status_code=400, detail=err_msg or "Invalid or expired reset token.")
        
    email = token_payload["email"].strip().lower()
    nonce = token_payload["nonce"]
    new_password = req_data.new_password.strip()
    
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long.")
        
    if not _db_enabled:
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.")
        
    try:
        # Check nonce validity
        otp_records = _query_db("""
            SELECT id, is_consumed, verified_at 
            FROM email_otp_verifications 
            WHERE email = %s AND purpose = 'forgot_password' AND token_nonce = %s;
        """, (email, nonce))
        
        if not otp_records or otp_records[0]["is_consumed"] or not otp_records[0]["verified_at"]:
            raise HTTPException(status_code=400, detail="Reset token is invalid or has already been used.")
            
        otp_rec_id = otp_records[0]["id"]
        
        # Fetch user
        user_rows = _query_db("SELECT id FROM public_users WHERE email = %s;", (email,))
        if not user_rows:
            raise HTTPException(status_code=404, detail="User account not found.")
            
        user_id = user_rows[0]["id"]
        new_hash = generate_password_hash(new_password, method="scrypt")
        
        # Update password
        _execute_db("UPDATE public_users SET password_hash = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (new_hash, user_id))
        
        # Invalidate all active public sessions for this user
        _execute_db("DELETE FROM public_user_sessions WHERE user_id = %s;", (user_id,))
        
        # Mark token as consumed
        _execute_db("UPDATE email_otp_verifications SET is_consumed = TRUE WHERE id = %s;", (otp_rec_id,))
        
        return {
            "success": True,
            "message": "Your password has been reset successfully. Please sign in with your new password."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during reset password: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset password due to a server error.")
