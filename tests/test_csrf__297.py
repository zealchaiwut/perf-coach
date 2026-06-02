"""Tests for issue #297: CSRF protection for cookie-based auth."""
import hmac
import pytest
from fastapi.testclient import TestClient

from backend.auth import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    SESSION_SECRET,
    create_session_cookie,
    generate_csrf_token,
    set_csrf_cookie,
    set_session,
)
from backend.main import app

import time


def _make_session_headers(user_id: str = "00000000-0000-0000-0000-000000000001"):
    """Return (session_cookie_value, csrf_token) for a fake in-memory user."""
    session_token = create_session_cookie(user_id, time.time())
    csrf_token = generate_csrf_token()
    return session_token, csrf_token


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _with_session(client, session_token: str, csrf_token: str):
    """Return a client that sends both cookies."""
    client.cookies.set(COOKIE_NAME, session_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    return client


# ── GET requests are exempt ──────────────────────────────────────────────────

def test_get_exempt_no_csrf_cookie(client):
    """GET with a session cookie but no CSRF cookie must not be blocked."""
    session_token = create_session_cookie("00000000-0000-0000-0000-000000000001", time.time())
    client.cookies.set(COOKIE_NAME, session_token)
    resp = client.get("/api/health")
    assert resp.status_code != 403


def test_get_exempt_no_session(client):
    """GET with no cookies at all must not be blocked by CSRF."""
    resp = client.get("/api/health")
    assert resp.status_code != 403


# ── POST without session — CSRF not enforced (no privileged session to abuse) ──

def test_post_without_session_no_csrf_required(client):
    """POST with no session cookie: CSRF middleware does not block (no session = no privilege)."""
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "wrongpass"})
    # May return 401/429 from auth logic, but NOT 403 from CSRF
    assert resp.status_code != 403


# ── POST with session — CSRF enforced ────────────────────────────────────────

def test_post_with_session_missing_csrf_header_returns_403(client):
    """POST with valid session but no X-CSRF-Token header → 403."""
    session_token, csrf_token = _make_session_headers()
    client.cookies.set(COOKIE_NAME, session_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    resp = client.post("/api/weight", json={"weight_kg": 70.0, "recorded_date": "2026-01-01"})
    assert resp.status_code == 403
    assert "csrf" in resp.json()["detail"].lower()


def test_post_with_session_wrong_csrf_header_returns_403(client):
    """POST with valid session but incorrect X-CSRF-Token value → 403."""
    session_token, csrf_token = _make_session_headers()
    client.cookies.set(COOKIE_NAME, session_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    resp = client.post(
        "/api/weight",
        json={"weight_kg": 70.0, "recorded_date": "2026-01-01"},
        headers={"X-CSRF-Token": "invalid-token-value"},
    )
    assert resp.status_code == 403


def test_patch_with_session_missing_csrf_returns_403(client):
    """PATCH with session but no CSRF header → 403."""
    session_token, csrf_token = _make_session_headers()
    client.cookies.set(COOKIE_NAME, session_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    resp = client.patch(
        "/api/habits/00000000-0000-0000-0000-000000000099",
        json={"name": "test"},
    )
    assert resp.status_code == 403


def test_delete_with_session_missing_csrf_returns_403(client):
    """DELETE with session but no CSRF header → 403."""
    session_token, csrf_token = _make_session_headers()
    client.cookies.set(COOKIE_NAME, session_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    resp = client.delete("/api/weight/00000000-0000-0000-0000-000000000099")
    assert resp.status_code == 403


def test_post_with_session_and_correct_csrf_passes_middleware(client):
    """POST with valid session + matching X-CSRF-Token header passes CSRF check."""
    session_token, csrf_token = _make_session_headers()
    client.cookies.set(COOKIE_NAME, session_token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    # Will fail auth (user not in DB) or validation, but NOT 403 from CSRF
    resp = client.post(
        "/api/weight",
        json={"weight_kg": 70.0, "recorded_date": "2026-01-01"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code != 403


# ── Logout clears CSRF cookie ────────────────────────────────────────────────

def test_csrf_cookie_set_on_login_response():
    """set_session() must return a CSRF token and set it as a readable cookie."""
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    csrf = set_session(resp, "00000000-0000-0000-0000-000000000001")
    assert csrf  # non-empty string
    all_set_cookie = resp.headers.getlist("set-cookie")
    csrf_header = next((h for h in all_set_cookie if h.startswith(CSRF_COOKIE_NAME + "=")), None)
    assert csrf_header is not None, f"csrf-token cookie not found in Set-Cookie headers: {all_set_cookie}"
    # The csrf-token cookie must NOT be httponly so JS can read it
    directives = [d.strip().lower() for d in csrf_header.split(";")[1:]]
    assert "httponly" not in directives


def test_clear_session_removes_csrf_cookie():
    """clear_session() must delete both session and CSRF cookies."""
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    clear_from_backend = __import__("backend.auth", fromlist=["clear_session"]).clear_session
    clear_from_backend(resp)
    headers = resp.headers.getlist("set-cookie")
    cookie_names = [h.split("=")[0].strip() for h in headers]
    assert CSRF_COOKIE_NAME in cookie_names
    assert COOKIE_NAME in cookie_names


# ── /api/csrf-token endpoint ─────────────────────────────────────────────────

def test_csrf_token_endpoint_returns_existing_cookie(client):
    """GET /api/csrf-token returns the value already in the cookie."""
    existing = "abc123existingtoken"
    client.cookies.set(CSRF_COOKIE_NAME, existing)
    resp = client.get("/api/csrf-token")
    assert resp.status_code == 200
    assert resp.json()["csrf_token"] == existing


def test_csrf_token_endpoint_sets_new_cookie_when_absent(client):
    """GET /api/csrf-token sets a fresh CSRF cookie when none exists."""
    client.cookies.clear()
    resp = client.get("/api/csrf-token")
    assert resp.status_code == 200
    data = resp.json()
    assert "csrf_token" in data
    assert len(data["csrf_token"]) == 64  # 32 hex bytes
