"""Tests for issue #1705: HTTP security headers middleware.

Acceptance Criteria verified here:
- AC1: Every response includes X-Content-Type-Options: nosniff.
- AC2: Every response includes X-Frame-Options: DENY.
- AC3: Every response includes a Content-Security-Policy header with frame-ancestors 'none'.
- AC4: Every response includes Strict-Transport-Security.
- AC5: Headers are present on both API endpoints and static/page responses.
"""
from fastapi.testclient import TestClient

from backend.main import app


def test_api_response_has_x_content_type_options_nosniff():
    """AC1: X-Content-Type-Options: nosniff is set on API responses."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"


def test_api_response_has_x_frame_options_deny():
    """AC2: X-Frame-Options: DENY is set on API responses."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/health")
    assert resp.headers.get("x-frame-options") == "DENY"


def test_api_response_has_csp_frame_ancestors():
    """AC3: Content-Security-Policy includes frame-ancestors 'none' on API responses."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/health")
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp, f"frame-ancestors missing from CSP: {csp!r}"
    assert "'none'" in csp, f"frame-ancestors 'none' missing from CSP: {csp!r}"


def test_api_response_has_strict_transport_security():
    """AC4: Strict-Transport-Security header is set on API responses."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/health")
    hsts = resp.headers.get("strict-transport-security", "")
    assert "max-age=" in hsts, f"HSTS header missing or malformed: {hsts!r}"


def test_security_headers_present_on_login_page():
    """AC5: Security headers are present on the login page (non-API route)."""
    client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    resp = client.get("/login")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp
    assert resp.headers.get("strict-transport-security", "") != ""


def test_security_headers_present_on_api_auth_endpoint():
    """AC5: Security headers are present on POST /api/auth/login (auth endpoint)."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/auth/login", json={"username": "noexist", "password": "x"})
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp
