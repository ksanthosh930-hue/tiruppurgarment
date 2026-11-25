"""
Phase 1D-4B-2 Marketing Attribution Remediation Test Suite
Comprehensive tests covering:
  A. Schema Validation & Sanitization (lengths, PII, visitor_id, timestamps)
  B. SEC-01: Domain Spoofing Defense & Strict Domain Boundary Matching
  C. PRIV-01: Formatted Indian Phone PII Redaction
  D. DATA-01: Missing Attribution Disambiguation (untracked vs direct)
  E. DATA-02: Android App Intent Referrers
  F. Channel Classification Precedence Rules
  G. Persistence Engine & 1:1 Constraints (individual, company)
  H. Backward Compatibility & Non-Breaking Registration
"""

import os
import sys
import json
import unittest
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Ensure project root is on sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from schemas.attribution import (
    TouchAttributionPayload,
    MarketingAttributionPayload,
    classify_marketing_channel,
    persist_user_marketing_attribution,
    _sanitize_string,
    _parse_timestamp,
    _extract_domain,
    _is_matching_domain,
    _is_google_domain,
    _contains_phone_pii
)


class TestMarketingAttributionSchema(unittest.TestCase):
    """A. Schema Validation, Sanitization, PII Redaction, and Limits"""

    def test_01_valid_full_attribution_payload(self):
        payload_data = {
            "visitor_id": "v_abc123_456-xyz",
            "first_touch": {
                "source": "instagram",
                "medium": "paid_social",
                "campaign": "garment_workers_nov",
                "content": "video_reel_1",
                "term": "tailor hiring",
                "landing_page": "https://tirupurgarment.in/hire?ref=insta",
                "referrer": "https://l.instagram.com/",
                "visit_at": "2026-11-20T10:00:00Z"
            },
            "last_touch": {
                "source": "google",
                "medium": "cpc",
                "campaign": "search_tirupur_jobs",
                "landing_page": "https://tirupurgarment.in/signup?gclid=12345",
                "referrer": "https://www.google.co.in/",
                "visit_at": "2026-11-25T09:30:00+05:30"
            }
        }
        obj = MarketingAttributionPayload(**payload_data)
        self.assertEqual(obj.visitor_id, "v_abc123_456-xyz")
        self.assertEqual(obj.first_touch.source, "instagram")
        self.assertEqual(obj.first_touch.medium, "paid_social")
        self.assertEqual(obj.last_touch.source, "google")
        self.assertEqual(obj.last_touch.medium, "cpc")

    def test_02_empty_and_missing_payload(self):
        obj = MarketingAttributionPayload()
        self.assertIsNone(obj.visitor_id)
        self.assertIsNone(obj.first_touch)
        self.assertIsNone(obj.last_touch)

        obj2 = MarketingAttributionPayload(**{})
        self.assertIsNone(obj2.visitor_id)

    def test_03_invalid_visitor_id(self):
        obj1 = MarketingAttributionPayload(visitor_id="bad visitor id with spaces!")
        self.assertIsNone(obj1.visitor_id)

        obj2 = MarketingAttributionPayload(visitor_id="ab")
        self.assertIsNone(obj2.visitor_id)

        obj3 = MarketingAttributionPayload(visitor_id="a" * 100)
        self.assertIsNone(obj3.visitor_id)

        obj4 = MarketingAttributionPayload(visitor_id="valid_id-123.456")
        self.assertEqual(obj4.visitor_id, "valid_id-123.456")

    def test_04_oversized_values_truncated(self):
        long_val = "x" * 500
        touch = TouchAttributionPayload(
            source=long_val,
            campaign=long_val,
            content=long_val
        )
        self.assertLessEqual(len(touch.source), 100)
        self.assertLessEqual(len(touch.campaign), 150)
        self.assertLessEqual(len(touch.content), 150)

    def test_05_malformed_timestamps_handled_safely(self):
        dt = _parse_timestamp("not-a-timestamp")
        self.assertIsInstance(dt, datetime)
        self.assertIsNotNone(dt.tzinfo)

        dt_valid = _parse_timestamp("2026-11-20T12:00:00Z")
        self.assertEqual(dt_valid.year, 2026)
        self.assertEqual(dt_valid.month, 11)
        self.assertEqual(dt_valid.day, 20)

    def test_06_email_and_script_sanitization(self):
        self.assertIsNone(_sanitize_string("contact user@example.com for info", 100))
        sanitized = _sanitize_string("summer_campaign<script>alert('xss')</script>", 100)
        self.assertEqual(sanitized, "summer_campaign")


class TestSec01DomainSpoofingDefense(unittest.TestCase):
    """B. SEC-01: Domain Spoofing Defense & Strict Domain Boundary Matching"""

    def test_01_is_matching_domain_helper(self):
        # Exact match
        self.assertTrue(_is_matching_domain("google.com", "google.com"))
        # Legitimate subdomains
        self.assertTrue(_is_matching_domain("www.google.com", "google.com"))
        self.assertTrue(_is_matching_domain("news.google.co.in", "google.co.in"))
        self.assertTrue(_is_matching_domain("l.instagram.com", "instagram.com"))
        self.assertTrue(_is_matching_domain("m.facebook.com", "facebook.com"))
        self.assertTrue(_is_matching_domain("web.whatsapp.com", "whatsapp.com"))

        # Adversarial spoofed domains must FAIL
        self.assertFalse(_is_matching_domain("attacker-google.com", "google.com"))
        self.assertFalse(_is_matching_domain("fakegoogle.com", "google.com"))
        self.assertFalse(_is_matching_domain("google.com.attacker.com", "google.com"))
        self.assertFalse(_is_matching_domain("fake-instagram.com", "instagram.com"))
        self.assertFalse(_is_matching_domain("instagram.com.evil.org", "instagram.com"))
        self.assertFalse(_is_matching_domain("malicious-facebook.com", "facebook.com"))
        self.assertFalse(_is_matching_domain("spoofed-whatsapp.com", "whatsapp.com"))

        # Empty and None cases
        self.assertFalse(_is_matching_domain(None, "google.com"))
        self.assertFalse(_is_matching_domain("", "google.com"))

    def test_02_spoofed_google_domains_rejected(self):
        # Spoofed Google domain must NOT be classified as google organic; should fall to referral
        res1 = classify_marketing_channel(referrer="https://attacker-google.com/search")
        self.assertEqual(res1["source"], "attacker-google.com")
        self.assertEqual(res1["medium"], "referral")

        res2 = classify_marketing_channel(referrer="https://google.com.attacker.com/results")
        self.assertEqual(res2["source"], "google.com.attacker.com")
        self.assertEqual(res2["medium"], "referral")

        # Legitimate Google domains MUST be classified as google organic
        res_legit1 = classify_marketing_channel(referrer="https://www.google.com/")
        self.assertEqual(res_legit1["source"], "google")
        self.assertEqual(res_legit1["medium"], "organic")

        res_legit2 = classify_marketing_channel(referrer="https://www.google.co.in/")
        self.assertEqual(res_legit2["source"], "google")
        self.assertEqual(res_legit2["medium"], "organic")

    def test_03_spoofed_social_domains_rejected(self):
        # Spoofed Instagram
        res_fake_insta = classify_marketing_channel(referrer="https://fake-instagram.com/p/123")
        self.assertEqual(res_fake_insta["source"], "fake-instagram.com")
        self.assertEqual(res_fake_insta["medium"], "referral")

        # Legitimate Instagram
        res_legit_insta = classify_marketing_channel(referrer="https://l.instagram.com/")
        self.assertEqual(res_legit_insta["source"], "instagram")
        self.assertEqual(res_legit_insta["medium"], "social")

        # Spoofed Facebook
        res_fake_fb = classify_marketing_channel(referrer="https://evil-facebook.com/share")
        self.assertEqual(res_fake_fb["source"], "evil-facebook.com")
        self.assertEqual(res_fake_fb["medium"], "referral")

        # Legitimate Facebook
        res_legit_fb = classify_marketing_channel(referrer="https://m.facebook.com/")
        self.assertEqual(res_legit_fb["source"], "facebook")
        self.assertEqual(res_legit_fb["medium"], "social")

        # Spoofed WhatsApp
        res_fake_wa = classify_marketing_channel(referrer="https://phishing-whatsapp.com/chat")
        self.assertEqual(res_fake_wa["source"], "phishing-whatsapp.com")
        self.assertEqual(res_fake_wa["medium"], "referral")

        # Legitimate WhatsApp
        res_legit_wa = classify_marketing_channel(referrer="https://web.whatsapp.com/")
        self.assertEqual(res_legit_wa["source"], "whatsapp")
        self.assertEqual(res_legit_wa["medium"], "chat_share")


class TestPriv01PhonePiiSanitization(unittest.TestCase):
    """C. PRIV-01: Formatted Indian Phone PII Detection & Redaction"""

    def test_01_phone_formats_detected_and_redacted(self):
        # Unbroken 10 digits
        self.assertTrue(_contains_phone_pii("9842198421"))
        self.assertIsNone(_sanitize_string("call 9842198421 now", 100))

        # Space separated
        self.assertTrue(_contains_phone_pii("98421 98421"))
        self.assertIsNone(_sanitize_string("contact: 98421 98421", 100))

        # Hyphen separated
        self.assertTrue(_contains_phone_pii("98421-98421"))
        self.assertIsNone(_sanitize_string("mobile 98421-98421", 100))

        # Dot separated
        self.assertTrue(_contains_phone_pii("98421.98421"))
        self.assertIsNone(_sanitize_string("reach at 98421.98421", 100))

        # Parentheses formatted
        self.assertTrue(_contains_phone_pii("(98421) 98421"))
        self.assertIsNone(_sanitize_string("call (98421) 98421", 100))

        # Country code + hyphens
        self.assertTrue(_contains_phone_pii("+91-98421-98421"))
        self.assertIsNone(_sanitize_string("whatsapp +91-98421-98421", 100))

        # Leading zero
        self.assertTrue(_contains_phone_pii("09842198421"))
        self.assertIsNone(_sanitize_string("09842198421", 100))

    def test_02_legitimate_alphanumeric_not_redacted(self):
        # Non-phone campaign names with numbers must be preserved
        self.assertFalse(_contains_phone_pii("campaign_2026_v1"))
        self.assertEqual(_sanitize_string("campaign_2026_v1", 100), "campaign_2026_v1")

        self.assertFalse(_contains_phone_pii("nov26_hiring"))
        self.assertEqual(_sanitize_string("nov26_hiring", 100), "nov26_hiring")

        self.assertFalse(_contains_phone_pii("tailor_batch_123"))
        self.assertEqual(_sanitize_string("tailor_batch_123", 100), "tailor_batch_123")


class TestData01MissingAttributionDisambiguation(unittest.TestCase):
    """D. DATA-01: Disambiguation of Missing Attribution (untracked) vs Explicit Direct"""

    def test_01_missing_payload_with_internal_referrer_is_untracked(self):
        executed_statements = []

        def mock_exec_fn(sql, params):
            executed_statements.append({"sql": sql, "params": params})
            return 1

        class MockRequest:
            headers = {"referer": "https://tirupurgarment.in/signup"}
            url = "https://tirupurgarment.in/api/v1/public/register/individual"

        success = persist_user_marketing_attribution(
            exec_fn=mock_exec_fn,
            user_id=401,
            account_type="individual",
            attribution_payload=None,
            request=MockRequest()
        )

        self.assertTrue(success)
        self.assertEqual(len(executed_statements), 1)
        params = executed_statements[0]["params"]

        # DATA-01: Must be recorded as 'untracked', NOT 'direct'
        self.assertEqual(params[2], "untracked")   # first_utm_source
        self.assertEqual(params[3], "(none)")      # first_utm_medium
        self.assertIsNone(params[4])               # first_utm_campaign
        self.assertEqual(params[10], "untracked")  # last_utm_source
        self.assertEqual(params[11], "(none)")     # last_utm_medium

        # Verify metadata flags
        meta = json.loads(params[19])
        self.assertFalse(meta["attribution_supplied"])
        self.assertTrue(meta["server_fallback"])
        self.assertEqual(meta["classified_first_channel"], "untracked")

    def test_02_missing_payload_with_external_referrer_uses_server_fallback(self):
        executed_statements = []

        def mock_exec_fn(sql, params):
            executed_statements.append({"sql": sql, "params": params})
            return 1

        class MockRequest:
            headers = {"referer": "https://www.google.co.in/"}
            url = "https://tirupurgarment.in/signup"

        success = persist_user_marketing_attribution(
            exec_fn=mock_exec_fn,
            user_id=402,
            account_type="individual",
            attribution_payload=None,
            request=MockRequest()
        )

        self.assertTrue(success)
        self.assertEqual(len(executed_statements), 1)
        params = executed_statements[0]["params"]

        # External server referrer classified as Google Organic
        self.assertEqual(params[2], "google")
        self.assertEqual(params[3], "organic")
        self.assertEqual(params[10], "google")

        # But metadata still flags server_fallback = True, attribution_supplied = False
        meta = json.loads(params[19])
        self.assertFalse(meta["attribution_supplied"])
        self.assertTrue(meta["server_fallback"])

    def test_03_explicit_direct_from_client_is_direct(self):
        executed_statements = []

        def mock_exec_fn(sql, params):
            executed_statements.append({"sql": sql, "params": params})
            return 1

        payload = MarketingAttributionPayload(
            visitor_id="v_direct_user_001",
            first_touch=TouchAttributionPayload(
                source="direct",
                medium="(none)"
            )
        )

        success = persist_user_marketing_attribution(
            exec_fn=mock_exec_fn,
            user_id=403,
            account_type="company",
            attribution_payload=payload
        )

        self.assertTrue(success)
        self.assertEqual(len(executed_statements), 1)
        params = executed_statements[0]["params"]

        # Explicit direct from client payload
        self.assertEqual(params[2], "direct")
        self.assertEqual(params[3], "(none)")
        self.assertEqual(params[18], "v_direct_user_001")

        meta = json.loads(params[19])
        self.assertTrue(meta["attribution_supplied"])
        self.assertFalse(meta["server_fallback"])


class TestData02AndroidAppReferrers(unittest.TestCase):
    """E. DATA-02: Android App Intent Referrers"""

    def test_01_instagram_android_app(self):
        res = classify_marketing_channel(referrer="android-app://com.instagram.android/")
        self.assertEqual(res["source"], "instagram")
        self.assertEqual(res["medium"], "social")

    def test_02_whatsapp_android_app(self):
        res = classify_marketing_channel(referrer="android-app://com.whatsapp/")
        self.assertEqual(res["source"], "whatsapp")
        self.assertEqual(res["medium"], "chat_share")

    def test_03_facebook_android_app(self):
        res1 = classify_marketing_channel(referrer="android-app://com.facebook.katana/")
        self.assertEqual(res1["source"], "facebook")
        self.assertEqual(res1["medium"], "social")

        res2 = classify_marketing_channel(referrer="android-app://com.facebook.orca/")
        self.assertEqual(res2["source"], "facebook")
        self.assertEqual(res2["medium"], "social")

    def test_04_google_android_searchbox_app(self):
        res = classify_marketing_channel(
            referrer="android-app://com.google.android.googlequicksearchbox/https/www.google.com"
        )
        self.assertEqual(res["source"], "google")
        self.assertEqual(res["medium"], "organic")


class TestChannelClassification(unittest.TestCase):
    """F. Standard Channel Classification & Precedence Rules"""

    def test_01_google_ads_via_gclid(self):
        res = classify_marketing_channel(
            landing_page="https://tirupurgarment.in/hire?gclid=Cj0KCQiA-test123"
        )
        self.assertEqual(res["source"], "google")
        self.assertEqual(res["medium"], "cpc")
        self.assertEqual(res["campaign"], "(google_ads)")

    def test_02_google_ads_via_paid_utm(self):
        res = classify_marketing_channel(
            source="google",
            medium="cpc",
            campaign="tirupur_garments_search"
        )
        self.assertEqual(res["source"], "google")
        self.assertEqual(res["medium"], "cpc")
        self.assertEqual(res["campaign"], "tirupur_garments_search")

    def test_03_external_referral(self):
        res = classify_marketing_channel(
            referrer="https://tirupurtextileassociation.com/news/123"
        )
        self.assertEqual(res["source"], "tirupurtextileassociation.com")
        self.assertEqual(res["medium"], "referral")


class TestAttributionPersistenceEngine(unittest.TestCase):
    """G. Attribution Persistence Engine, Constraints & Fallbacks"""

    def test_01_persist_full_attribution_mock_exec(self):
        executed_statements = []

        def mock_exec_fn(sql, params):
            executed_statements.append({"sql": sql, "params": params})
            return 1

        payload = MarketingAttributionPayload(
            visitor_id="v_test_persist_001",
            first_touch=TouchAttributionPayload(
                source="instagram",
                medium="paid_social",
                campaign="garment_b2b",
                landing_page="https://tirupurgarment.in/hire",
                referrer="https://l.instagram.com/"
            ),
            last_touch=TouchAttributionPayload(
                source="google",
                medium="cpc",
                campaign="hire_workers",
                landing_page="https://tirupurgarment.in/employer/register"
            )
        )

        success = persist_user_marketing_attribution(
            exec_fn=mock_exec_fn,
            user_id=101,
            account_type="company",
            attribution_payload=payload,
            raw_metadata={"flow": "test"}
        )

        self.assertTrue(success)
        self.assertEqual(len(executed_statements), 1)
        params = executed_statements[0]["params"]

        self.assertEqual(params[0], 101)                 # user_id
        self.assertEqual(params[1], "company")             # account_type
        self.assertEqual(params[2], "instagram")           # first_utm_source
        self.assertEqual(params[3], "paid_social")         # first_utm_medium
        self.assertEqual(params[4], "garment_b2b")         # first_utm_campaign
        self.assertEqual(params[10], "google")             # last_utm_source
        self.assertEqual(params[11], "cpc")                # last_utm_medium
        self.assertEqual(params[12], "hire_workers")       # last_utm_campaign
        self.assertEqual(params[18], "v_test_persist_001")  # visitor_id

    def test_02_db_error_does_not_raise(self):
        def mock_broken_exec(sql, params):
            raise RuntimeError("Database connection timed out")

        success = persist_user_marketing_attribution(
            exec_fn=mock_broken_exec,
            user_id=303,
            account_type="individual",
            attribution_payload=None
        )
        self.assertFalse(success)


class TestBackwardCompatibility(unittest.TestCase):
    """H. Request Model Backward Compatibility (No-attribution payloads)"""

    def test_01_models_accept_none_attribution(self):
        from routers.public_auth import (
            EmployeeRegisterRequest,
            EmployerRegisterRequest,
            CompleteRegistrationRequest,
            GoogleCompleteRegistrationRequest
        )

        emp = EmployeeRegisterRequest(
            full_name="Test Seeker",
            mobile="9876543210",
            email="test@example.com",
            password="StrongPassword123!"
        )
        self.assertIsNone(emp.attribution)

        empr = EmployerRegisterRequest(
            company_name="Test Garments",
            contact_person="HR Manager",
            mobile="9876543211",
            email="hr@testgarments.com",
            password="StrongPassword123!"
        )
        self.assertIsNone(empr.attribution)

        comp = CompleteRegistrationRequest(
            account_type="individual",
            password="StrongPassword123!"
        )
        self.assertIsNone(comp.attribution)

        g_comp = GoogleCompleteRegistrationRequest(
            mobile="9876543212"
        )
        self.assertIsNone(g_comp.attribution)


if __name__ == "__main__":
    unittest.main()
