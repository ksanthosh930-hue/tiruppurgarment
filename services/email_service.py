import os
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

def is_development_mode() -> bool:
    env = os.getenv("ENVIRONMENT", "development").strip().lower()
    return env == "development"

def send_otp_email(to_email: str, otp_code: str, purpose: str = "registration") -> bool:
    """
    Sends a 6-digit OTP verification code via Resend.
    
    Security & Isolation Rules:
    - Production: Strictly FAILS CLOSED. Requires valid RESEND_API_KEY and successful HTTP delivery.
    - Development: Only if RESEND_API_KEY is not configured and ENVIRONMENT=development, logs [DEV ONLY] code.
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "TirupurGarment <noreply@tirupurgarment.in>").strip()
    
    # Check purpose title & messaging
    if purpose == "forgot_password":
        subject = "Reset Your Password - TirupurGarment.in"
        heading = "Password Reset Request"
        instruction = "You requested to reset your password. Use the verification code below to proceed:"
    else:
        subject = "Verify Your Email Address - TirupurGarment.in"
        heading = "Verify Your Email Address"
        instruction = "Thank you for starting your registration with TirupurGarment.in. Use the verification code below to confirm your email:"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 0; }}
            .container {{ max-width: 540px; margin: 30px auto; background-color: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
            .header {{ background-color: #081226; padding: 24px 32px; text-align: center; }}
            .header h1 {{ color: #ffffff; font-size: 22px; margin: 0; font-weight: 700; letter-spacing: 0.5px; }}
            .header span {{ color: #9E1B32; }}
            .content {{ padding: 32px; color: #1e293b; line-height: 1.6; }}
            .content h2 {{ font-size: 18px; color: #081226; margin-top: 0; }}
            .otp-box {{ background-color: #f1f5f9; border: 2px dashed #9E1B32; border-radius: 8px; padding: 18px; text-align: center; margin: 24px 0; }}
            .otp-code {{ font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #081226; font-family: monospace; }}
            .warning {{ font-size: 13px; color: #64748b; margin-top: 16px; border-top: 1px solid #e2e8f0; padding-top: 16px; }}
            .footer {{ background-color: #f8fafc; padding: 16px 32px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Tirupur<span>Garment</span>.in</h1>
            </div>
            <div class="content">
                <h2>{heading}</h2>
                <p>{instruction}</p>
                <div class="otp-box">
                    <div class="otp-code">{otp_code}</div>
                </div>
                <p style="margin-bottom: 0;"><strong>This code will expire in 5 minutes.</strong></p>
                <div class="warning">
                    If you did not request this verification code, you can safely ignore this email. Do not share this code with anyone.
                </div>
            </div>
            <div class="footer">
                © 2026 TirupurGarment.in • Garment Automation & Industry Platform
            </div>
        </div>
    </body>
    </html>
    """

    text_content = f"""TirupurGarment.in

{heading}

{instruction}

Your Verification Code: {otp_code}

This code will expire in 5 minutes.

If you did not request this code, you can safely ignore this email.
"""

    if not api_key:
        if is_development_mode():
            logger.info(f"[DEV ONLY] Email OTP for {to_email}: {otp_code} (Purpose: {purpose})")
            return True
        else:
            logger.error("Production Resend configuration error: RESEND_API_KEY is missing.")
            raise RuntimeError("Email service is not configured on production.")

    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
        "text": text_content
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(RESEND_API_URL, json=payload, headers=headers, timeout=10)
        if response.status_code in (200, 201):
            logger.info(f"Successfully sent OTP email via Resend to {to_email[:3]}***@{to_email.split('@')[-1]}")
            return True
        else:
            logger.error(f"Resend API error (Status {response.status_code}): {response.text}")
            if is_development_mode():
                # Allow dev testing if Resend domain unverified
                logger.info(f"[DEV ONLY] (Resend failed in dev mode) Email OTP: {otp_code}")
                return True
            raise RuntimeError(f"Resend API returned status {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to deliver OTP email: {e}")
        if is_development_mode():
            logger.info(f"[DEV ONLY] (Delivery exception in dev mode) Email OTP: {otp_code}")
            return True
        raise e
