import os
import time
import secrets
import hashlib
import hmac
import json
import base64
import datetime
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60
TEMP_TOKEN_EXPIRY_MINUTES = 10

# In-memory rate limiting tracking: {key: [timestamps]}
_RATE_LIMIT_BUCKETS: Dict[str, list] = {}

def get_secret_key() -> str:
    return os.getenv("SECRET_KEY", "digigarment-public-auth-secret-key-2026")

def generate_6digit_otp() -> str:
    """Generates a cryptographically secure 6-digit numeric OTP."""
    return f"{secrets.randbelow(900000) + 100000}"

def hash_otp(otp: str, salt: Optional[str] = None) -> str:
    """Computes a secure SHA-256 hash of the OTP with server salt."""
    if not salt:
        salt = get_secret_key()
    return hashlib.sha256(f"{otp}:{salt}".encode("utf-8")).hexdigest()

def check_rate_limit(key: str, max_requests: int = 5, window_seconds: int = 300) -> bool:
    """
    Checks if a given key (IP or email) has exceeded rate limits.
    Returns True if allowed, False if rate limit exceeded.
    """
    now = time.time()
    timestamps = _RATE_LIMIT_BUCKETS.get(key, [])
    # Filter timestamps within window
    timestamps = [ts for ts in timestamps if now - ts < window_seconds]
    if len(timestamps) >= max_requests:
        _RATE_LIMIT_BUCKETS[key] = timestamps
        return False
    timestamps.append(now)
    _RATE_LIMIT_BUCKETS[key] = timestamps
    return True

def generate_signed_temp_token(email: str, purpose: str, nonce: str) -> str:
    """
    Generates a cryptographically signed, short-lived temporary verification token (HMAC-SHA256).
    Valid for 10 minutes maximum, single-use, tied to email and purpose.
    """
    now = int(time.time())
    expires_at = now + (TEMP_TOKEN_EXPIRY_MINUTES * 60)
    
    payload = {
        "email": email.strip().lower(),
        "purpose": purpose,
        "nonce": nonce,
        "iat": now,
        "exp": expires_at
    }
    
    payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode('utf-8')).decode('utf-8').rstrip('=')
    
    secret = get_secret_key().encode('utf-8')
    sig = hmac.new(secret, payload_b64.encode('utf-8'), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode('utf-8').rstrip('=')
    
    return f"{payload_b64}.{sig_b64}"

def verify_signed_temp_token(token: str, expected_purpose: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Validates the cryptographic signature, expiration, and purpose of a temporary verification token.
    Returns (is_valid, payload, error_message).
    """
    if not token or "." not in token:
        return False, None, "Invalid verification token format."
        
    parts = token.split(".")
    if len(parts) != 2:
        return False, None, "Malformed verification token."
        
    payload_b64, sig_b64 = parts[0], parts[1]
    secret = get_secret_key().encode('utf-8')
    
    expected_sig = hmac.new(secret, payload_b64.encode('utf-8'), hashlib.sha256).digest()
    expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode('utf-8').rstrip('=')
    
    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        return False, None, "Invalid verification token signature."
        
    # Decode payload
    try:
        # Add padding back if necessary
        padded_payload = payload_b64 + '=' * (4 - len(payload_b64) % 4 if len(payload_b64) % 4 != 0 else 0)
        payload_data = json.loads(base64.urlsafe_b64decode(padded_payload).decode('utf-8'))
    except Exception:
        return False, None, "Failed to decode verification token payload."
        
    # Check expiration
    now = int(time.time())
    if payload_data.get("exp", 0) < now:
        return False, None, "Verification token has expired (valid for 10 minutes). Please verify your email again."
        
    # Check purpose
    if payload_data.get("purpose") != expected_purpose:
        return False, None, f"Invalid token purpose (expected {expected_purpose})."
        
    if not payload_data.get("email") or not payload_data.get("nonce"):
        return False, None, "Incomplete verification token metadata."
        
    return True, payload_data, None
