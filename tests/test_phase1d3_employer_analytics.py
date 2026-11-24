"""
Phase 1D-3A Employer Acquisition & Activation Analytics Test Suite
Tests for GET /api/admin/growth-analytics/employers/deep-dive
"""

import os
import sys
import unittest
from datetime import datetime
from dotenv import load_dotenv

# Ensure root directory is on sys.path and environment loaded
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv(os.path.join(ROOT_DIR, ".env"))

from fastapi.testclient import TestClient
from app import app
import routers.admin_growth_analytics as raga


class TestEmployerDeepDiveAnalytics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Auth override for admin
        cls.admin_user = {"username": "test_admin", "role": "admin"}
        app.dependency_overrides[raga.require_admin] = lambda: cls.admin_user

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_01_admin_auth_required(self):
        """Test that missing admin authentication raises 401"""
        # Temporarily clear override to test real require_admin dependency
        del app.dependency_overrides[raga.require_admin]
        try:
            res = self.client.get("/api/admin/growth-analytics/employers/deep-dive")
            self.assertEqual(res.status_code, 401)
        finally:
            app.dependency_overrides[raga.require_admin] = lambda: self.admin_user

    def test_02_default_range_30d(self):
        """Test default invocation uses 30d range and returns 200 with ground truth structure"""
        res = self.client.get("/api/admin/growth-analytics/employers/deep-dive?refresh=true")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("range"), "30d")
        self.assertEqual(data.get("reporting_timezone"), "Asia/Kolkata (IST)")

        # Verify key top-level keys
        self.assertIn("kpis", data)
        self.assertIn("funnel", data)
        self.assertIn("activation_velocity", data)
        self.assertIn("job_distribution", data)
        self.assertIn("profile_completeness", data)
        self.assertIn("acquisition", data)
        self.assertIn("trends", data)
        self.assertIn("methodology", data)
        self.assertIn("data_quality_warnings", data)

    def test_03_all_supported_ranges(self):
        """Test each standard range (today, 7d, 30d, 90d, all)"""
        ranges_expected_days = {
            "today": 1,
            "7d": 7,
            "30d": 30,
            "90d": 90
        }
        for r_name, expected_days in ranges_expected_days.items():
            res = self.client.get(f"/api/admin/growth-analytics/employers/deep-dive?range={r_name}&refresh=true")
            self.assertEqual(res.status_code, 200, f"Failed for range {r_name}")
            data = res.json()
            self.assertEqual(data.get("range"), r_name)
            trends = data.get("trends", [])
            self.assertEqual(len(trends), expected_days, f"Trend days mismatch for {r_name}")

        # Test 'all' range
        res_all = self.client.get("/api/admin/growth-analytics/employers/deep-dive?range=all&refresh=true")
        self.assertEqual(res_all.status_code, 200)
        data_all = res_all.json()
        self.assertEqual(data_all.get("range"), "all")
        self.assertGreaterEqual(len(data_all.get("trends", [])), 30)

    def test_04_custom_range_valid(self):
        """Test valid custom date range with 11 days (2026-11-10 to 2026-11-20)"""
        res = self.client.get(
            "/api/admin/growth-analytics/employers/deep-dive?range=custom&start_date=2026-11-10&end_date=2026-11-20&refresh=true"
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("range"), "custom")
        self.assertEqual(data.get("start_date"), "2026-11-10")
        self.assertEqual(data.get("end_date"), "2026-11-20")
        trends = data.get("trends", [])
        self.assertEqual(len(trends), 11)
        self.assertEqual(trends[0]["date"], "2026-11-10")
        self.assertEqual(trends[-1]["date"], "2026-11-20")

    def test_05_custom_range_inverted_dates_graceful_swap(self):
        """Test inverted custom dates (start > end) are gracefully handled"""
        res = self.client.get(
            "/api/admin/growth-analytics/employers/deep-dive?range=custom&start_date=2026-11-20&end_date=2026-11-10&refresh=true"
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("start_date"), "2026-11-10")
        self.assertEqual(data.get("end_date"), "2026-11-20")
        self.assertEqual(len(data.get("trends", [])), 11)

    def test_06_custom_range_missing_dates(self):
        """Test that missing start_date or end_date for custom range returns HTTP 400"""
        res1 = self.client.get("/api/admin/growth-analytics/employers/deep-dive?range=custom")
        self.assertEqual(res1.status_code, 400)
        self.assertIn("start_date and end_date are required", res1.json().get("detail", ""))

        res2 = self.client.get("/api/admin/growth-analytics/employers/deep-dive?range=custom&start_date=2026-11-10")
        self.assertEqual(res2.status_code, 400)

    def test_07_custom_range_invalid_format(self):
        """Test that malformed date returns HTTP 400"""
        res = self.client.get(
            "/api/admin/growth-analytics/employers/deep-dive?range=custom&start_date=10-11-2026&end_date=2026-11-20"
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid date format", res.json().get("detail", ""))

    def test_08_invalid_range_pattern(self):
        """Test invalid range argument triggers FastAPI 422 regex pattern validation"""
        res = self.client.get("/api/admin/growth-analytics/employers/deep-dive?range=yearly")
        self.assertEqual(res.status_code, 422)

    def test_09_cache_hit_and_refresh_bypass(self):
        """Test in-memory cache hit and refresh=true cache bypass"""
        res1 = self.client.get("/api/admin/growth-analytics/employers/deep-dive?range=30d")
        self.assertEqual(res1.status_code, 200)
        ts1 = res1.json().get("last_updated")

        res2 = self.client.get("/api/admin/growth-analytics/employers/deep-dive?range=30d")
        self.assertEqual(res2.status_code, 200)
        ts2 = res2.json().get("last_updated")
        self.assertEqual(ts1, ts2, "Cache hit should return identical timestamp")

        res3 = self.client.get("/api/admin/growth-analytics/employers/deep-dive?range=30d&refresh=true")
        self.assertEqual(res3.status_code, 200)
        ts3 = res3.json().get("last_updated")
        self.assertTrue(datetime.fromisoformat(ts3) >= datetime.fromisoformat(ts1))

    def test_10_zero_pii_compliance(self):
        """Test that no sensitive PII fields exist in the response payload"""
        res = self.client.get("/api/admin/growth-analytics/employers/deep-dive?range=all&refresh=true")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Check raw string representation does not contain actual PII patterns
        text_payload = res.text.lower()
        forbidden_pii_patterns = [
            "password", "hashed_password", "salt", "session_id",
            "@gmail.com", "@yahoo.com"
        ]
        for pattern in forbidden_pii_patterns:
            self.assertNotIn(pattern, text_payload, f"Forbidden PII token found: {pattern}")

        # Check that individual record identifiers are not exposed in metrics or trends
        for t in data.get("trends", []):
            self.assertNotIn("user_id", t)
            self.assertNotIn("email", t)
            self.assertNotIn("mobile", t)
            self.assertNotIn("company_name", t)

    def test_11_metric_integrity_rules(self):
        """Test the 12 metric integrity rules against the response structure"""
        res = self.client.get("/api/admin/growth-analytics/employers/deep-dive?range=all&refresh=true")
        data = res.json()
        kpis = data.get("kpis", {})
        totals = kpis.get("all_time_totals", {})

        # Rule 1 & 2: Active accounts <= total registered
        self.assertLessEqual(totals.get("active_accounts"), totals.get("total_registered_employers"))

        # Rule 3: Activated employers <= total registered
        self.assertLessEqual(totals.get("activated_employers"), totals.get("total_registered_employers"))

        # Rule 4: Published employers <= activated employers
        self.assertLessEqual(totals.get("published_employers"), totals.get("activated_employers"))

        # Rule 5: Repeat employers <= activated employers
        self.assertLessEqual(totals.get("repeat_job_posting_employers"), totals.get("activated_employers"))

        # Rule 6: Repeat posting rate is between 0 and 100
        self.assertGreaterEqual(totals.get("repeat_posting_rate_pct"), 0.0)
        self.assertLessEqual(totals.get("repeat_posting_rate_pct"), 100.0)

        # Rule 7: Pre-registration funnel note & cohort_conversion_tracked is False
        funnel_pre = data.get("funnel", {}).get("pre_registration", {})
        self.assertFalse(funnel_pre.get("cohort_conversion_tracked"))
        self.assertIn("unmeasured in database", funnel_pre.get("note", "").lower())

        # Rule 8: Velocity buckets sum to total measured
        vel = data.get("activation_velocity", {})
        tot_meas = vel.get("total_activated_measured", 0)
        sum_buckets = (
            vel.get("under_5_mins", {}).get("count", 0) +
            vel.get("mins_5_to_15", {}).get("count", 0) +
            vel.get("mins_15_to_60", {}).get("count", 0) +
            vel.get("hours_1_to_24", {}).get("count", 0) +
            vel.get("over_24_hours", {}).get("count", 0)
        )
        self.assertEqual(tot_meas, sum_buckets)

        # Rule 9: Job distribution sum matches total posting employers
        dist = data.get("job_distribution", {})
        tot_posting = dist.get("total_posting_employers", 0)
        sum_dist = (
            dist.get("employers_with_1_job", {}).get("count", 0) +
            dist.get("employers_with_2_jobs", {}).get("count", 0) +
            dist.get("employers_with_3_jobs", {}).get("count", 0) +
            dist.get("employers_with_4_plus_jobs", {}).get("count", 0)
        )
        self.assertEqual(tot_posting, sum_dist)

        # Rule 10: Marketing attribution status is unmeasured_in_database
        mkt = data.get("acquisition", {}).get("marketing_attribution", {})
        self.assertEqual(mkt.get("status"), "unmeasured_in_database")
        self.assertFalse(mkt.get("source_tracking_column_present"))

        # Rule 11: Warnings contain Job 631 and cohort size
        warnings = data.get("data_quality_warnings", [])
        self.assertTrue(any("631" in w for w in warnings))
        self.assertTrue(any("cohort is currently" in w for w in warnings))

        # Rule 12: Methodology definitions exist
        meth = data.get("methodology", {})
        self.assertIn("registered_employer", meth)
        self.assertIn("activated_employer", meth)
        self.assertIn("timezone", meth)

    def test_12_regression_existing_growth_endpoints(self):
        """Ensure all pre-existing Growth Analytics endpoints continue to operate without regression"""
        endpoints = [
            "/api/admin/growth-analytics/overview",
            "/api/admin/growth-analytics/jobseekers",
            "/api/admin/growth-analytics/employers",
            "/api/admin/growth-analytics/jobs",
            "/api/admin/growth-analytics/trends?granularity=daily"
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Regression detected in endpoint: {ep}")
            self.assertTrue(res.json().get("success"), f"Success not true in: {ep}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
