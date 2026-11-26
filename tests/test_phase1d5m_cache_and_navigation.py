"""
Phase 1D-5M Cache Hardening & Responsive Subtab Navigation Test Suite
Validates:
- Admin HTML route cache-busting headers (no-cache, no-store, must-revalidate, max-age=0)
- Preservation of authentication & authorization on /admin
- Non-leakage of admin cache headers onto public routes
- Fallback admin session cache header delivery
- Database authenticated session cache header delivery
"""

import os
import sys
import datetime
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, ADMIN_NO_CACHE_HEADERS, FALLBACK_ADMIN_SESSIONS


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


class TestPhase1D5MCacheHardening:
    """Verifies that Admin HTML routes strictly emit non-cacheable headers."""

    def test_01_admin_no_cache_headers_definition(self):
        """Verify the exact required cache control headers dictionary."""
        assert isinstance(ADMIN_NO_CACHE_HEADERS, dict)
        assert ADMIN_NO_CACHE_HEADERS.get("Cache-Control") == "no-cache, no-store, must-revalidate, max-age=0"
        assert ADMIN_NO_CACHE_HEADERS.get("Pragma") == "no-cache"
        assert ADMIN_NO_CACHE_HEADERS.get("Expires") == "0"

    def test_02_unauthenticated_admin_redirect_preserved(self, client):
        """Unauthenticated request to /admin must redirect to /admin/login without serving admin.html."""
        res = client.get("/admin")
        assert res.status_code == 307
        assert res.headers["location"] == "/admin/login"

    def test_03_fallback_admin_receives_cache_hardening_headers(self, client):
        """Authenticated fallback admin session receives admin.html with explicit cache headers."""
        test_session_id = "test-fallback-session-token-12345"
        FALLBACK_ADMIN_SESSIONS[test_session_id] = {
            "expires_at": datetime.datetime.now() + datetime.timedelta(hours=2)
        }

        try:
            client.cookies.set("session_id", test_session_id)
            res = client.get("/admin")
            assert res.status_code == 200
            assert "text/html" in res.headers.get("content-type", "")
            
            # Assert all 3 cache hardening headers are present
            assert res.headers.get("cache-control") == "no-cache, no-store, must-revalidate, max-age=0"
            assert res.headers.get("pragma") == "no-cache"
            assert res.headers.get("expires") == "0"
        finally:
            FALLBACK_ADMIN_SESSIONS.pop(test_session_id, None)

    @patch("app.query_db")
    @patch("app._ensure_db_connected")
    def test_04_db_authenticated_admin_receives_cache_hardening_headers(self, mock_ensure_db, mock_query_db, client):
        """Authenticated database session receives admin.html with explicit cache headers."""
        mock_query_db.return_value = [{"token": "valid-db-token"}]

        with patch("app.db_enabled", True):
            client.cookies.set("session_id", "valid-db-token")
            res = client.get("/admin")
            assert res.status_code == 200
            assert "text/html" in res.headers.get("content-type", "")

            # Assert cache hardening headers
            assert res.headers.get("cache-control") == "no-cache, no-store, must-revalidate, max-age=0"
            assert res.headers.get("pragma") == "no-cache"
            assert res.headers.get("expires") == "0"

    def test_05_public_routes_do_not_inherit_admin_cache_headers(self, client):
        """Verify public routes do not inherit the Admin-specific no-store/must-revalidate headers."""
        res_login = client.get("/admin/login")
        # /admin/login serves login.html or redirect; should NOT have the admin dashboard no-store header
        cache_ctrl = res_login.headers.get("cache-control", "")
        assert "must-revalidate, max-age=0" not in cache_ctrl
