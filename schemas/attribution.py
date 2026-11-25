"""
DigiGarment – Phase 1D-4B Marketing Attribution Schema & Persistence Engine
Authoritative, Zero-PII deterministic attribution tracking for Job Seekers and Employers.
Remediated in Phase 1D-4B-2:
  - SEC-01: Strict domain boundary matching (_is_matching_domain)
  - PRIV-01: Formatted Indian phone PII detection (_contains_phone_pii)
  - DATA-01: Disambiguation of missing attribution (untracked) vs explicit direct
  - DATA-02: Android app intent referrers (Instagram, Facebook, WhatsApp, Google)
"""

import re
import json
import logging
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field, validator

logger = logging.getLogger("marketing_attribution")

# Maximum field length constraints
MAX_SOURCE_LEN = 100
MAX_MEDIUM_LEN = 50
MAX_CAMPAIGN_LEN = 150
MAX_CONTENT_LEN = 150
MAX_TERM_LEN = 150
MAX_URL_LEN = 2048
MAX_VISITOR_ID_LEN = 64

# Strict PII detection patterns
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
SCRIPT_TAG_PATTERN = re.compile(r"<script.*?>.*?</script>", re.IGNORECASE | re.DOTALL)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
VISITOR_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{4,64}$")

INTERNAL_HOSTS = {
    "tirupurgarment.in",
    "www.tirupurgarment.in",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "testserver"
}


def _is_matching_domain(host: Optional[str], target_domain: str) -> bool:
    """
    SEC-01 Fix: Strict domain boundary matching to prevent domain spoofing.
    Matches host == target_domain OR host ending with '.' + target_domain.
    Rejects 'attacker-google.com', 'fake-instagram.com', 'google.com.attacker.com'.
    """
    if not host or not target_domain:
        return False
    h = host.lower().strip()
    t = target_domain.lower().strip()
    return h == t or h.endswith("." + t)


def _is_google_domain(host: Optional[str]) -> bool:
    """Matches legitimate Google search domains."""
    return any(_is_matching_domain(host, d) for d in ("google.com", "google.co.in", "google.in"))


def _contains_phone_pii(text: str) -> bool:
    """
    PRIV-01 Fix: Formatted phone PII detection.
    Detects Indian mobile numbers across formatting variations:
    spaces ('98421 98421'), hyphens ('98421-98421'), dots ('98421.98421'),
    parentheses ('(98421) 98421'), country codes ('+91-98421-98421', '09842198421').
    """
    if not text:
        return False
    for match in re.finditer(r"(?:\+?91|0)?[\s\-\.\(\)]*[6-9](?:[\s\-\.\(\)]*\d){9}", text):
        cleaned = re.sub(r"[\s\-\.\(\)]", "", match.group(0))
        if cleaned.startswith("+91"):
            cleaned = cleaned[3:]
        elif cleaned.startswith("91") and len(cleaned) == 12:
            cleaned = cleaned[2:]
        elif cleaned.startswith("0") and len(cleaned) == 11:
            cleaned = cleaned[1:]
        if len(cleaned) == 10 and cleaned[0] in "6789" and cleaned.isdigit():
            return True
    return False


def _sanitize_string(val: Optional[Any], max_len: int) -> Optional[str]:
    """
    Sanitizes, strips, redacts PII, and truncates text metadata.
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None

    # Strip script blocks and HTML tags
    s = SCRIPT_TAG_PATTERN.sub("", s)
    s = HTML_TAG_PATTERN.sub("", s).strip()
    if not s:
        return None

    # Redact / reject if PII patterns detected (Email or Formatted Phone)
    if EMAIL_PATTERN.search(s) or _contains_phone_pii(s):
        logger.warning("PII detected in attribution field; redacting value.")
        return None

    # Truncate to maximum length safely
    return s[:max_len]


def _parse_timestamp(val: Optional[Any]) -> datetime:
    """
    Parses timestamp into a timezone-aware UTC datetime.
    Falls back to current UTC time if invalid or missing.
    """
    if val is None:
        return datetime.now(timezone.utc)
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    try:
        s = str(val).strip()
        # Handle trailing 'Z'
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _extract_domain(url_str: Optional[str]) -> Optional[str]:
    """
    Extracts the clean host/domain from a URL string, supporting web and android-app URLs.
    """
    if not url_str:
        return None
    try:
        parsed = urlparse(url_str.strip())
        host = parsed.netloc or parsed.path.split("/")[0]
        host = host.split(":")[0].lower().strip()
        return host or None
    except Exception:
        return None


class TouchAttributionPayload(BaseModel):
    source: Optional[str] = Field(None, max_length=MAX_SOURCE_LEN)
    medium: Optional[str] = Field(None, max_length=MAX_MEDIUM_LEN)
    campaign: Optional[str] = Field(None, max_length=MAX_CAMPAIGN_LEN)
    content: Optional[str] = Field(None, max_length=MAX_CONTENT_LEN)
    term: Optional[str] = Field(None, max_length=MAX_TERM_LEN)
    landing_page: Optional[str] = Field(None, max_length=MAX_URL_LEN)
    referrer: Optional[str] = Field(None, max_length=MAX_URL_LEN)
    visit_at: Optional[Union[datetime, str]] = None

    @validator("source", pre=True)
    def sanitize_source(cls, v):
        return _sanitize_string(v, MAX_SOURCE_LEN)

    @validator("medium", pre=True)
    def sanitize_medium(cls, v):
        return _sanitize_string(v, MAX_MEDIUM_LEN)

    @validator("campaign", "content", "term", pre=True)
    def sanitize_campaign_fields(cls, v):
        return _sanitize_string(v, MAX_CAMPAIGN_LEN)

    @validator("landing_page", "referrer", pre=True)
    def sanitize_urls(cls, v):
        if v is None:
            return None
        return _sanitize_string(v, MAX_URL_LEN)


class MarketingAttributionPayload(BaseModel):
    visitor_id: Optional[str] = Field(None, max_length=MAX_VISITOR_ID_LEN)
    first_touch: Optional[TouchAttributionPayload] = None
    last_touch: Optional[TouchAttributionPayload] = None

    @validator("visitor_id", pre=True)
    def validate_visitor_id_field(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        if not s or not VISITOR_ID_PATTERN.match(s):
            return None
        return s[:MAX_VISITOR_ID_LEN]


def classify_marketing_channel(
    source: Optional[str] = None,
    medium: Optional[str] = None,
    referrer: Optional[str] = None,
    landing_page: Optional[str] = None,
    campaign: Optional[str] = None
) -> Dict[str, Optional[str]]:
    """
    Enforces deterministic channel classification following Phase 1D-4A audit precedence rules.
    Remediated with SEC-01 domain boundary checks and DATA-02 Android app referrers.
    Returns normalized dict: {'source': ..., 'medium': ..., 'campaign': ...}
    """
    src = (source or "").lower().strip()
    med = (medium or "").lower().strip()
    ref = (referrer or "").strip()
    ref_host = (_extract_domain(ref) or "").lower()
    lp = (landing_page or "").lower()

    # Rule 1: Google Ads (gclid in landing page or referrer, or google + cpc/ppc)
    if "gclid=" in lp or "gclid=" in ref.lower():
        return {
            "source": "google",
            "medium": "cpc",
            "campaign": campaign or "(google_ads)"
        }
    if src == "google" and med in ("cpc", "ppc", "paidsearch", "paid_search", "adwords"):
        return {
            "source": "google",
            "medium": "cpc",
            "campaign": campaign or "(google_ads)"
        }

    # Rule 2: Google Organic (SEC-01 & DATA-02)
    # Strict Google domain matching or Android Google quicksearchbox app
    is_google_ref = _is_google_domain(ref_host) or ref_host == "com.google.android.googlequicksearchbox"
    if med == "organic" or (is_google_ref and not any(k in lp for k in ("gclid=", "fbclid="))):
        return {
            "source": "google",
            "medium": "organic",
            "campaign": campaign or "(organic)"
        }

    # Rule 3: Instagram (SEC-01 & DATA-02)
    is_insta_ref = _is_matching_domain(ref_host, "instagram.com") or ref_host == "com.instagram.android"
    if src == "instagram" or is_insta_ref:
        norm_med = med if med in ("paid_social", "story", "reel", "cpc", "ad") else "social"
        return {
            "source": "instagram",
            "medium": norm_med,
            "campaign": campaign
        }

    # Rule 4: Facebook (SEC-01 & DATA-02)
    is_fb_ref = _is_matching_domain(ref_host, "facebook.com") or ref_host in ("com.facebook.katana", "com.facebook.orca")
    if "fbclid=" in lp or src == "facebook" or is_fb_ref:
        norm_med = med if med in ("paid_social", "cpc", "ad") else "social"
        return {
            "source": "facebook",
            "medium": norm_med,
            "campaign": campaign
        }

    # Rule 5: WhatsApp (SEC-01 & DATA-02)
    is_wa_ref = _is_matching_domain(ref_host, "whatsapp.com") or ref_host == "com.whatsapp"
    if src == "whatsapp" or is_wa_ref:
        norm_med = med if med in ("chat_share", "job_alert", "broadcast", "cpc") else "chat_share"
        return {
            "source": "whatsapp",
            "medium": norm_med,
            "campaign": campaign
        }

    # Rule 6: Referral (external, non-internal, non-search/social)
    if ref_host and ref_host not in INTERNAL_HOSTS:
        return {
            "source": ref_host[:MAX_SOURCE_LEN],
            "medium": med or "referral",
            "campaign": campaign
        }

    # Rule 7: Direct (or Internal Navigation)
    if not src and not med:
        return {
            "source": "direct",
            "medium": "(none)",
            "campaign": None
        }

    # Default fallback: preserve valid explicit UTM parameters
    return {
        "source": src or "direct",
        "medium": med or "(none)",
        "campaign": campaign
    }


def persist_user_marketing_attribution(
    exec_fn,
    user_id: int,
    account_type: str,
    attribution_payload: Optional[MarketingAttributionPayload] = None,
    request: Optional[Any] = None,
    raw_metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Persists deterministic first-touch and last-touch attribution for newly registered public users.
    Guaranteed:
      - 1:1 foreign key binding to public_users(id).
      - Server-side referrer fallback if client-side payload is missing or blocked.
      - DATA-01: Disambiguates missing/blocked attribution ('untracked') from explicit 'direct'.
      - Never breaks user registration on attribution parsing failures.
    """
    if not exec_fn or not user_id:
        return False

    try:
        server_referrer = None
        server_landing_page = None
        if request is not None:
            try:
                server_referrer = request.headers.get("referer") or request.headers.get("referrer")
                server_landing_page = str(request.url)
            except Exception:
                pass

        visitor_id = None
        first_payload = None
        last_payload = None

        if attribution_payload:
            visitor_id = _sanitize_string(attribution_payload.visitor_id, MAX_VISITOR_ID_LEN)
            first_payload = attribution_payload.first_touch
            last_payload = attribution_payload.last_touch

        attribution_supplied = attribution_payload is not None and (
            first_payload is not None or last_payload is not None
        )

        if not attribution_supplied:
            # DATA-01 Fix: Client attribution is absent/blocked.
            # Inspect server referrer to distinguish untracked internal navigation from external referrers.
            server_ref_host = _extract_domain(server_referrer)
            if not server_referrer or not server_ref_host or server_ref_host in INTERNAL_HOSTS:
                first_source = "untracked"
                first_medium = "(none)"
                first_campaign = None
            else:
                f_classified = classify_marketing_channel(
                    referrer=server_referrer,
                    landing_page=server_landing_page
                )
                first_source = f_classified["source"]
                first_medium = f_classified["medium"]
                first_campaign = f_classified["campaign"]

            f_cnt = None
            f_trm = None
            f_lp = _sanitize_string(server_landing_page, MAX_URL_LEN)
            f_ref = _sanitize_string(server_referrer, MAX_URL_LEN)
            f_visit = datetime.now(timezone.utc)

            # Last touch mirrors first touch in server fallback mode
            last_source = first_source
            last_medium = first_medium
            last_campaign = first_campaign
            l_cnt, l_trm, l_lp, l_ref, l_visit = (
                f_cnt, f_trm, f_lp, f_ref, f_visit
            )
        else:
            # Client attribution payload is supplied!
            # Process First Touch
            f_src = _sanitize_string(first_payload.source if first_payload else None, MAX_SOURCE_LEN)
            f_med = _sanitize_string(first_payload.medium if first_payload else None, MAX_MEDIUM_LEN)
            f_cmp = _sanitize_string(first_payload.campaign if first_payload else None, MAX_CAMPAIGN_LEN)
            f_cnt = _sanitize_string(first_payload.content if first_payload else None, MAX_CONTENT_LEN)
            f_trm = _sanitize_string(first_payload.term if first_payload else None, MAX_TERM_LEN)
            f_lp = _sanitize_string(first_payload.landing_page if first_payload else server_landing_page, MAX_URL_LEN)
            f_ref = _sanitize_string(first_payload.referrer if first_payload else server_referrer, MAX_URL_LEN)
            f_visit = _parse_timestamp(first_payload.visit_at if first_payload else None)

            f_classified = classify_marketing_channel(
                source=f_src,
                medium=f_med,
                referrer=f_ref,
                landing_page=f_lp,
                campaign=f_cmp
            )
            first_source = f_classified["source"]
            first_medium = f_classified["medium"]
            first_campaign = f_classified["campaign"]

            # Process Last Touch
            if last_payload:
                l_src = _sanitize_string(last_payload.source, MAX_SOURCE_LEN)
                l_med = _sanitize_string(last_payload.medium, MAX_MEDIUM_LEN)
                l_cmp = _sanitize_string(last_payload.campaign, MAX_CAMPAIGN_LEN)
                l_cnt = _sanitize_string(last_payload.content, MAX_CONTENT_LEN)
                l_trm = _sanitize_string(last_payload.term, MAX_TERM_LEN)
                l_lp = _sanitize_string(last_payload.landing_page or server_landing_page, MAX_URL_LEN)
                l_ref = _sanitize_string(last_payload.referrer or server_referrer, MAX_URL_LEN)
                l_visit = _parse_timestamp(last_payload.visit_at)
            else:
                l_src, l_med, l_cmp, l_cnt, l_trm, l_lp, l_ref, l_visit = (
                    f_src, f_med, f_cmp, f_cnt, f_trm, f_lp, f_ref, f_visit
                )

            l_classified = classify_marketing_channel(
                source=l_src,
                medium=l_med,
                referrer=l_ref,
                landing_page=l_lp,
                campaign=l_cmp
            )
            last_source = l_classified["source"]
            last_medium = l_classified["medium"]
            last_campaign = l_classified["campaign"]

        # Prepare metadata JSON with explicit attribution tracking state
        meta_dict = raw_metadata.copy() if raw_metadata and isinstance(raw_metadata, dict) else {}
        meta_dict["attribution_supplied"] = attribution_supplied
        meta_dict["server_fallback"] = not attribution_supplied
        meta_dict["classified_first_channel"] = first_source
        meta_dict["classified_last_channel"] = last_source
        meta_json = json.dumps(meta_dict)

        sql = """
            INSERT INTO user_marketing_attributions (
                user_id, account_type,
                first_utm_source, first_utm_medium, first_utm_campaign, first_utm_content, first_utm_term,
                first_landing_page, first_referrer, first_visit_at,
                last_utm_source, last_utm_medium, last_utm_campaign, last_utm_content, last_utm_term,
                last_landing_page, last_referrer, last_visit_at,
                visitor_id, registration_at, raw_metadata, created_at
            )
            VALUES (
                %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, CURRENT_TIMESTAMP, %s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (user_id) DO NOTHING;
        """

        params = (
            user_id,
            account_type,
            first_source, first_medium, first_campaign, f_cnt, f_trm,
            f_lp, f_ref, f_visit,
            last_source, last_medium, last_campaign, l_cnt, l_trm,
            l_lp, l_ref, l_visit,
            visitor_id,
            meta_json
        )

        exec_fn(sql, params)
        logger.info(
            f"Successfully recorded marketing attribution for user_id={user_id} ({account_type}): "
            f"first={first_source}/{first_medium}, last={last_source}/{last_medium}, "
            f"supplied={attribution_supplied}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to persist marketing attribution for user_id={user_id}: {e}", exc_info=True)
        # Never break registration on attribution failure
        return False
