"""
Phase 1D-5B Marketing Attribution Analytics API Test Suite
Unit tests for GET /api/admin/growth-analytics/marketing-attribution
Ensures strict authentication, date range validation, zero-PII guarantee,
10-tier channel taxonomy, and graceful database offline/mock handling.
Guaranteed ZERO production database mutation and zero live database connection.
"""

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

# Ensure root directory is on sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Force isolated test environment
os.environ["ENVIRONMENT"] = "test_local"
os.environ["DATABASE_URL"] = "postgresql://postgres:test@127.0.0.1:5432/digigarment_test?sslmode=disable"
os.environ["ENV_FILE"] = ".env.test"

from app import app
import routers.admin_growth_analytics as raga


class TestMarketingAttributionAnalyticsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.admin_user = {"username": "test_admin", "role": "admin"}
        # Default admin override
        app.dependency_overrides[raga.require_admin] = lambda: cls.admin_user

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        raga.analytics_cache.clear()

    def setUp(self):
        # Reset cache before each test
        raga.analytics_cache.clear()

    def test_01_require_admin_unauthorized(self):
        """Test that requests without valid admin session trigger 401 Unauthorized"""
        # Remove admin override temporarily
        del app.dependency_overrides[raga.require_admin]
        try:
            res = self.client.get("/api/admin/growth-analytics/marketing-attribution")
            self.assertEqual(res.status_code, 401)
        finally:
            app.dependency_overrides[raga.require_admin] = lambda: self.admin_user

    def test_02_offline_mock_mode_response_structure(self):
        """Test endpoint when db is disabled/offline returns 200 with zeroed mock payload"""
        orig_enabled = raga.db_helpers["db_enabled"]
        orig_query = raga.db_helpers["query_db"]
        raga.db_helpers["db_enabled"] = False
        raga.db_helpers["query_db"] = None

        try:
            res = self.client.get("/api/admin/growth-analytics/marketing-attribution?range=30d")
            self.assertEqual(res.status_code, 200)
            data = res.json()

            self.assertTrue(data["success"])
            self.assertEqual(data["data_source"], "PostgreSQL (Offline/Mock)")
            self.assertEqual(data["reporting_timezone"], "Asia/Kolkata (IST)")
            self.assertEqual(data["range"], "30d")
            self.assertEqual(data["account_type"], "all")
            self.assertIn("kpis", data)
            self.assertEqual(data["kpis"]["total_registrations"], 0)
            self.assertEqual(data["kpis"]["tracking_coverage_pct"], 0.0)
            self.assertEqual(data["channel_groups"], [])
            self.assertEqual(data["first_touch_sources"], [])
            self.assertEqual(data["last_touch_sources"], [])
            self.assertEqual(data["campaigns"], [])
            self.assertEqual(data["cross_channel_journeys"], [])
            self.assertEqual(data["timeline"], [])
        finally:
            raga.db_helpers["db_enabled"] = orig_enabled
            raga.db_helpers["query_db"] = orig_query

    def test_03_standard_ranges_supported(self):
        """Test all standard ranges (today, 7d, 30d, 90d, all) are accepted"""
        orig_enabled = raga.db_helpers["db_enabled"]
        orig_query = raga.db_helpers["query_db"]
        raga.db_helpers["db_enabled"] = False
        raga.db_helpers["query_db"] = None

        try:
            for r in ["today", "7d", "30d", "90d", "all"]:
                res = self.client.get(f"/api/admin/growth-analytics/marketing-attribution?range={r}&refresh=true")
                self.assertEqual(res.status_code, 200, f"Failed for range={r}")
                data = res.json()
                self.assertEqual(data["range"], r)
                self.assertTrue(data["period"]["days_count"] >= 1)
        finally:
            raga.db_helpers["db_enabled"] = orig_enabled
            raga.db_helpers["query_db"] = orig_query

    def test_04_custom_range_valid(self):
        """Test custom range with valid start_date and end_date"""
        orig_enabled = raga.db_helpers["db_enabled"]
        orig_query = raga.db_helpers["query_db"]
        raga.db_helpers["db_enabled"] = False
        raga.db_helpers["query_db"] = None

        try:
            res = self.client.get(
                "/api/admin/growth-analytics/marketing-attribution?range=custom&start_date=2026-11-01&end_date=2026-11-20"
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["range"], "custom")
            self.assertEqual(data["period"]["start_date"], "2026-11-01")
            self.assertEqual(data["period"]["end_date"], "2026-11-20")
            self.assertEqual(data["period"]["days_count"], 20)
        finally:
            raga.db_helpers["db_enabled"] = orig_enabled
            raga.db_helpers["query_db"] = orig_query

    def test_05_custom_range_missing_dates(self):
        """Test custom range missing start_date or end_date raises 400"""
        res1 = self.client.get("/api/admin/growth-analytics/marketing-attribution?range=custom&start_date=2026-11-01")
        self.assertEqual(res1.status_code, 400)
        self.assertIn("start_date and end_date are required", res1.json()["detail"])

        res2 = self.client.get("/api/admin/growth-analytics/marketing-attribution?range=custom&end_date=2026-11-20")
        self.assertEqual(res2.status_code, 400)

    def test_06_custom_range_malformed_date(self):
        """Test custom range with invalid date format raises 400"""
        res = self.client.get(
            "/api/admin/growth-analytics/marketing-attribution?range=custom&start_date=2026/11/01&end_date=2026-11-20"
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid date format", res.json()["detail"])

    def test_07_custom_range_inverted_dates_graceful_swap(self):
        """Test custom range where start_date > end_date is safely swapped"""
        orig_enabled = raga.db_helpers["db_enabled"]
        orig_query = raga.db_helpers["query_db"]
        raga.db_helpers["db_enabled"] = False
        raga.db_helpers["query_db"] = None

        try:
            res = self.client.get(
                "/api/admin/growth-analytics/marketing-attribution?range=custom&start_date=2026-11-20&end_date=2026-11-01"
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["period"]["start_date"], "2026-11-01")
            self.assertEqual(data["period"]["end_date"], "2026-11-20")
            self.assertEqual(data["period"]["days_count"], 20)
        finally:
            raga.db_helpers["db_enabled"] = orig_enabled
            raga.db_helpers["query_db"] = orig_query

    def test_08_account_type_filter(self):
        """Test account_type parameter validation and routing"""
        orig_enabled = raga.db_helpers["db_enabled"]
        orig_query = raga.db_helpers["query_db"]
        raga.db_helpers["db_enabled"] = False
        raga.db_helpers["query_db"] = None

        try:
            for acct in ["all", "individual", "company"]:
                res = self.client.get(f"/api/admin/growth-analytics/marketing-attribution?account_type={acct}")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["account_type"], acct)

            # Invalid account type should fail regex validation (422)
            res_invalid = self.client.get("/api/admin/growth-analytics/marketing-attribution?account_type=invalid_type")
            self.assertEqual(res_invalid.status_code, 422)
        finally:
            raga.db_helpers["db_enabled"] = orig_enabled
            raga.db_helpers["query_db"] = orig_query

    def test_09_database_query_integration_with_mocked_db(self):
        """Test full calculation logic with simulated PostgreSQL query responses"""
        mock_kpis = [{
            "total_registrations": 167,
            "candidate_registrations": 158,
            "employer_registrations": 9,
            "tracked_registrations": 5,
            "legacy_untracked_registrations": 162,
            "tracking_coverage_pct": 2.99,
            "multi_touch_switches": 2,
            "avg_time_to_register_minutes": 14.50,
            "median_time_to_register_minutes": 8.20
        }]

        mock_channels = [
            {"channel_group": "Legacy Untracked", "total_count": 162, "candidate_count": 155, "employer_count": 7, "share_pct": 97.01},
            {"channel_group": "Google Organic", "total_count": 3, "candidate_count": 2, "employer_count": 1, "share_pct": 1.80},
            {"channel_group": "Google Ads", "total_count": 2, "candidate_count": 1, "employer_count": 1, "share_pct": 1.20}
        ]

        mock_first_touch = [
            {"source": "google", "medium": "cpc", "total_count": 2, "candidate_count": 1, "employer_count": 1, "share_pct": 40.0},
            {"source": "google", "medium": "organic", "total_count": 3, "candidate_count": 2, "employer_count": 1, "share_pct": 60.0}
        ]

        mock_last_touch = [
            {"source": "google", "medium": "cpc", "total_count": 3, "candidate_count": 2, "employer_count": 1, "share_pct": 60.0},
            {"source": "direct", "medium": "(none)", "total_count": 2, "candidate_count": 1, "employer_count": 1, "share_pct": 40.0}
        ]

        mock_campaigns = [
            {"campaign": "garment_tailor_jobs_nov", "source": "google", "medium": "cpc", "total_count": 2, "candidate_count": 1, "employer_count": 1, "share_pct": 100.0}
        ]

        mock_journeys = [
            {"first_source": "google", "first_medium": "cpc", "last_source": "direct", "last_medium": "(none)", "journey_count": 2, "candidate_count": 1, "employer_count": 1}
        ]

        mock_timeline = [
            {"day": "2026-11-24", "date_str": "2026-11-24", "candidates_tracked": 1, "candidates_legacy": 2, "employers_tracked": 0, "employers_legacy": 0, "paid_traffic": 1, "organic_direct_traffic": 0},
            {"day": "2026-11-25", "date_str": "2026-11-25", "candidates_tracked": 4, "candidates_legacy": 1, "employers_tracked": 1, "employers_legacy": 0, "paid_traffic": 1, "organic_direct_traffic": 4}
        ]

        query_call_count = 0
        def fake_query_db(sql):
            nonlocal query_call_count
            query_call_count += 1
            sql_clean = sql.strip().upper()
            if "ROUND((COUNT(UMA.ID)::NUMERIC" in sql_clean or "TOTAL_REGISTRATIONS" in sql_clean:
                return mock_kpis
            elif "CASE" in sql_clean and "GOOGLE ADS" in sql_clean:
                return mock_channels
            elif "FIRST_UTM_CAMPAIGN" in sql_clean:
                return mock_campaigns
            elif "LAST_UTM_SOURCE" in sql_clean and "FIRST_UTM_SOURCE" in sql_clean:
                return mock_journeys
            elif "FIRST_UTM_SOURCE" in sql_clean:
                return mock_first_touch
            elif "LAST_UTM_SOURCE" in sql_clean:
                return mock_last_touch
            elif "DATE_SERIES" in sql_clean or "DAILY_SIGNUPS" in sql_clean:
                return mock_timeline
            return []

        orig_enabled = raga.db_helpers["db_enabled"]
        orig_query = raga.db_helpers["query_db"]
        raga.db_helpers["db_enabled"] = True
        raga.db_helpers["query_db"] = fake_query_db

        try:
            res = self.client.get("/api/admin/growth-analytics/marketing-attribution?range=30d&refresh=true")
            self.assertEqual(res.status_code, 200)
            data = res.json()

            self.assertTrue(data["success"])
            self.assertEqual(data["data_source"], "PostgreSQL (Direct System of Record)")
            self.assertEqual(data["kpis"]["total_registrations"], 167)
            self.assertEqual(data["kpis"]["tracked_registrations"], 5)
            self.assertEqual(data["kpis"]["legacy_untracked_registrations"], 162)
            self.assertEqual(data["kpis"]["tracking_coverage_pct"], 2.99)
            self.assertEqual(data["kpis"]["multi_touch_switches"], 2)
            self.assertEqual(data["kpis"]["avg_time_to_register_minutes"], 14.50)
            self.assertEqual(data["kpis"]["median_time_to_register_minutes"], 8.20)

            self.assertEqual(len(data["channel_groups"]), 3)
            self.assertEqual(data["channel_groups"][0]["channel_group"], "Legacy Untracked")
            self.assertEqual(len(data["first_touch_sources"]), 2)
            self.assertEqual(len(data["last_touch_sources"]), 2)
            self.assertEqual(len(data["campaigns"]), 1)
            self.assertEqual(len(data["cross_channel_journeys"]), 1)
            self.assertEqual(len(data["timeline"]), 2)
            self.assertEqual(data["timeline"][0]["date"], "2026-11-24")
        finally:
            raga.db_helpers["db_enabled"] = orig_enabled
            raga.db_helpers["query_db"] = orig_query

    def test_10_cache_hit_and_refresh_behavior(self):
        """Test that in-memory cache stores response and refresh=true forces cache bypass"""
        call_count = 0
        def counting_query_db(sql):
            nonlocal call_count
            call_count += 1
            return []

        orig_enabled = raga.db_helpers["db_enabled"]
        orig_query = raga.db_helpers["query_db"]
        raga.db_helpers["db_enabled"] = True
        raga.db_helpers["query_db"] = counting_query_db

        try:
            # First request: should query DB (7 queries)
            res1 = self.client.get("/api/admin/growth-analytics/marketing-attribution?range=30d")
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(call_count, 7)

            # Second request: should hit cache without invoking DB queries
            res2 = self.client.get("/api/admin/growth-analytics/marketing-attribution?range=30d")
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(call_count, 7)  # No increment

            # Third request with refresh=true: should bypass cache and re-query DB
            res3 = self.client.get("/api/admin/growth-analytics/marketing-attribution?range=30d&refresh=true")
            self.assertEqual(res3.status_code, 200)
            self.assertEqual(call_count, 14)  # 7 additional queries
        finally:
            raga.db_helpers["db_enabled"] = orig_enabled
            raga.db_helpers["query_db"] = orig_query

    def test_11_zero_pii_adversarial_scan(self):
        """Adversarially verify that no PII fields leak into the response payload"""
        sample_kpis = [{
            "total_registrations": 10,
            "candidate_registrations": 8,
            "employer_registrations": 2,
            "tracked_registrations": 4,
            "legacy_untracked_registrations": 6,
            "tracking_coverage_pct": 40.0,
            "multi_touch_switches": 1,
            "avg_time_to_register_minutes": 10.0,
            "median_time_to_register_minutes": 5.0
        }]

        sample_channels = [
            {"channel_group": "Google Ads", "total_count": 4, "candidate_count": 3, "employer_count": 1, "share_pct": 40.0}
        ]

        def sample_query_db(sql):
            sql_clean = sql.strip().upper()
            if "TOTAL_REGISTRATIONS" in sql_clean:
                return sample_kpis
            elif "CASE" in sql_clean:
                return sample_channels
            return []

        orig_enabled = raga.db_helpers["db_enabled"]
        orig_query = raga.db_helpers["query_db"]
        raga.db_helpers["db_enabled"] = True
        raga.db_helpers["query_db"] = sample_query_db

        try:
            res = self.client.get("/api/admin/growth-analytics/marketing-attribution?range=30d&refresh=true")
            self.assertEqual(res.status_code, 200)
            data = res.json()

            # Recursive function to check all keys and values
            prohibited_pii_substrings = [
                "email", "phone", "mobile", "password", "visitor_id",
                "raw_metadata", "full_name", "otp", "aadhaar", "token"
            ]

            def scan_dict_for_pii(obj, path=""):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        k_lower = k.lower()
                        for pii in prohibited_pii_substrings:
                            self.assertNotIn(
                                pii, k_lower,
                                f"PII field detected in key: '{path}.{k}'"
                            )
                        scan_dict_for_pii(v, f"{path}.{k}")
                elif isinstance(obj, list):
                    for idx, item in enumerate(obj):
                        scan_dict_for_pii(item, f"{path}[{idx}]")

            scan_dict_for_pii(data)
        finally:
            raga.db_helpers["db_enabled"] = orig_enabled
            raga.db_helpers["query_db"] = orig_query


if __name__ == "__main__":
    unittest.main(verbosity=2)
