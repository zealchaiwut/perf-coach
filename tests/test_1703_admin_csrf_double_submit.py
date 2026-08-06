"""Tests for issue #1703: Admin-only mutating endpoints must enforce CSRF double-submit check.

Acceptance Criteria verified here:
- AC1: Mutating request with admin_session cookie but no X-CSRF-Token → 403 from middleware.
- AC2: Mutating request with admin_session + matching X-CSRF-Token → passes CSRF check (not 403).
- AC3: GET requests with admin_session cookie are not CSRF-blocked (safe methods exempt).
- AC4: POST /api/admin/login response sets a csrf-token cookie alongside admin_session.
- AC5: Requests with no auth cookies are not blocked by CSRF middleware (auth layer handles 401).
- AC6: Regression — regular session CSRF protection continues to block requests without CSRF token.
"""
import time

from fastapi.testclient import TestClient

from backend.auth import (
    ADMIN_COOKIE_NAME,
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    create_admin_cookie,
    create_session_cookie,
)
from backend.main import app

_CSRF_VALUE = "test-csrf-token-abc123"


def _admin_token() -> str:
    return create_admin_cookie(time.time())


def _session_token() -> str:
    return create_session_cookie("00000000-0000-0000-0000-000000001703", time.time())


# AC1 — admin_session present, no CSRF token → 403
def test_admin_mutating_without_csrf_token_is_rejected():
    """_csrf_protect blocks POST when admin_session cookie is present but CSRF header is missing."""
    client = TestClient(app, cookies={ADMIN_COOKIE_NAME: _admin_token()})
    # Use a simple admin endpoint; body details don't matter — middleware rejects first.
    resp = client.post("/api/admin/users", json={"username": "x", "password": "xxxxxxxx"})
    assert resp.status_code == 403
    assert "csrf" in resp.json().get("detail", "").lower()


# AC1 — wrong CSRF token → 403
def test_admin_mutating_with_wrong_csrf_token_is_rejected():
    """_csrf_protect blocks POST when X-CSRF-Token header doesn't match the csrf-token cookie."""
    client = TestClient(
        app,
        cookies={
            ADMIN_COOKIE_NAME: _admin_token(),
            CSRF_COOKIE_NAME: "correct-token",
        },
    )
    resp = client.post(
        "/api/admin/users",
        json={"username": "x", "password": "xxxxxxxx"},
        headers={"X-CSRF-Token": "wrong-token"},
    )
    assert resp.status_code == 403
    assert "csrf" in resp.json().get("detail", "").lower()


# AC2 — admin_session + matching CSRF token → passes middleware (not 403)
def test_admin_mutating_with_correct_csrf_token_passes_middleware():
    """_csrf_protect allows POST through when admin_session + matching CSRF token are present."""
    client = TestClient(
        app,
        cookies={
            ADMIN_COOKIE_NAME: _admin_token(),
            CSRF_COOKIE_NAME: _CSRF_VALUE,
        },
    )
    resp = client.post(
        "/api/admin/users",
        json={"username": "x", "password": "xxxxxxxx"},
        headers={"X-CSRF-Token": _CSRF_VALUE},
    )
    # Must NOT be a CSRF rejection; may be 422 (validation), 400, 201, etc.
    assert resp.status_code != 403, (
        f"Expected CSRF middleware to pass, got 403: {resp.json()}"
    )


# AC3 — GET with admin_session cookie is safe-method-exempt
def test_admin_get_request_not_csrf_blocked():
    """GET requests carrying admin_session are not blocked by CSRF middleware."""
    client = TestClient(app, cookies={ADMIN_COOKIE_NAME: _admin_token()})
    resp = client.get("/api/admin/users", headers={"accept": "application/json"})
    # Any response except 403 is acceptable here; 401 means auth (not CSRF).
    assert resp.status_code != 403


# AC3 — DELETE with admin_session + no CSRF is blocked
def test_admin_delete_without_csrf_token_is_rejected():
    """_csrf_protect blocks DELETE when admin_session cookie is present but CSRF is missing."""
    import uuid

    dummy_id = str(uuid.uuid4())
    client = TestClient(app, cookies={ADMIN_COOKIE_NAME: _admin_token()})
    resp = client.delete(f"/api/admin/users/{dummy_id}")
    assert resp.status_code == 403
    assert "csrf" in resp.json().get("detail", "").lower()


# AC4 — admin login sets csrf-token cookie
def test_admin_login_sets_csrf_cookie(monkeypatch):
    """POST /api/admin/login response must include a csrf-token cookie."""
    secret = "super-secret-1703"
    # Set both UAT and PRD vars so the test passes regardless of ENVIRONMENT value.
    monkeypatch.setenv("ADMIN_SECRET_UAT", secret)
    monkeypatch.setenv("ADMIN_SECRET_PRD", secret)
    client = TestClient(app)
    resp = client.post("/api/admin/login", json={"secret": secret})
    assert resp.status_code == 200, f"admin_login returned {resp.status_code}: {resp.json()}"
    assert CSRF_COOKIE_NAME in resp.cookies, (
        f"admin_login must set {CSRF_COOKIE_NAME} cookie; got cookies: {dict(resp.cookies)}"
    )
    csrf_val = resp.cookies[CSRF_COOKIE_NAME]
    assert csrf_val, "csrf-token cookie must be non-empty"


# AC4 — admin login sets admin_session cookie alongside csrf-token
def test_admin_login_sets_both_admin_session_and_csrf_cookie(monkeypatch):
    """POST /api/admin/login must set both admin_session and csrf-token cookies."""
    secret = "super-secret-1703"
    monkeypatch.setenv("ADMIN_SECRET_UAT", secret)
    monkeypatch.setenv("ADMIN_SECRET_PRD", secret)
    client = TestClient(app)
    resp = client.post("/api/admin/login", json={"secret": secret})
    assert resp.status_code == 200, f"admin_login returned {resp.status_code}: {resp.json()}"
    assert ADMIN_COOKIE_NAME in resp.cookies
    assert CSRF_COOKIE_NAME in resp.cookies


# AC5 — request with no auth cookies is not CSRF-blocked
def test_unauthenticated_request_not_csrf_blocked():
    """Requests without any auth cookie are not blocked by CSRF middleware (auth layer handles it)."""
    client = TestClient(app)
    resp = client.post("/api/admin/users", json={"username": "x", "password": "xxxxxxxx"})
    # CSRF middleware must NOT be the one rejecting this (it would return 403 with "csrf" in detail)
    if resp.status_code == 403:
        assert "csrf" not in resp.json().get("detail", "").lower(), (
            "Unauthenticated request should not trigger CSRF check; got CSRF 403"
        )


# AC6 — regression: regular session CSRF still enforced
def test_regular_session_csrf_still_enforced():
    """Regression: session cookie without CSRF token still returns 403 (existing behavior)."""
    client = TestClient(app, cookies={COOKIE_NAME: _session_token()})
    resp = client.post("/api/daily-metrics", json={})
    assert resp.status_code == 403
    assert "csrf" in resp.json().get("detail", "").lower()


# AC6 — regression: regular session + correct CSRF passes
def test_regular_session_with_correct_csrf_passes_middleware():
    """Regression: session cookie + matching CSRF token still passes middleware."""
    client = TestClient(
        app,
        cookies={
            COOKIE_NAME: _session_token(),
            CSRF_COOKIE_NAME: _CSRF_VALUE,
        },
    )
    resp = client.post(
        "/api/daily-metrics",
        json={},
        headers={"X-CSRF-Token": _CSRF_VALUE},
    )
    # Must NOT be a CSRF rejection.
    assert resp.status_code != 403, (
        f"Expected CSRF middleware to pass for regular session, got 403: {resp.json()}"
    )
