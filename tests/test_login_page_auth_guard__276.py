"""Tests for issue #276: /login page, page-level auth guard, logout nav control."""
import uuid

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.db import engine
from backend.models import User

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="module")
def client():
    """HTTP client that does NOT follow redirects so we can assert 302."""
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth_user(client):
    name = f"guard-test-{uuid.uuid4().hex[:8]}"
    res = client.post("/api/users", json={"name": name})
    assert res.status_code == 201, f"Failed to create test user: {res.text}"
    user_id = res.json()["id"]

    pw_hash = hash_password(_TEST_PASSWORD)
    with Session(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        user.password_hash = pw_hash
        session.commit()

    yield {"id": user_id, "name": name, "password": _TEST_PASSWORD}

    client.delete(f"/api/users/{user_id}")


@pytest.fixture(scope="module")
def session_cookie(client, auth_user):
    res = client.post(
        "/api/auth/login",
        json={"username": auth_user["name"], "password": auth_user["password"]},
    )
    assert res.status_code == 200, f"Login failed: {res.text}"
    cookie = res.cookies.get("session")
    assert cookie, "Login must set a session cookie"
    return cookie


# ── /login page ───────────────────────────────────────────────────────────────

def test_login_page_returns_200_html(client):
    res = client.get("/login")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


def test_login_page_html_contains_form(client):
    res = client.get("/login")
    assert res.status_code == 200
    body = res.text
    assert 'id="username"' in body
    assert 'id="password"' in body
    assert 'id="submit-btn"' in body


def test_login_dot_html_alias_works(client):
    res = client.get("/login.html")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


# ── Auth guard: exempt routes ─────────────────────────────────────────────────

def test_login_page_exempt_from_guard(client):
    """/login must be reachable without a session cookie."""
    res = client.get("/login")
    assert res.status_code == 200


def test_css_exempt_from_guard(client):
    """/css/* assets must be served without authentication."""
    res = client.get("/css/styles.css")
    assert res.status_code == 200


def test_js_exempt_from_guard(client):
    """/js/* assets must be served without authentication."""
    res = client.get("/js/nav.js")
    assert res.status_code == 200


def test_api_auth_login_exempt_from_guard(client):
    """POST /api/auth/login must be callable without a session cookie."""
    res = client.post(
        "/api/auth/login",
        json={"username": "nonexistent", "password": "wrong"},
    )
    assert res.status_code in (401, 429), f"Expected 401/429, got {res.status_code}"


# ── Auth guard: browser requests redirect ─────────────────────────────────────

def test_unauthenticated_home_redirects_to_login(client):
    res = client.get("/home")
    assert res.status_code == 302
    assert res.headers.get("location") == "/login"


def test_unauthenticated_root_redirects(client):
    """GET / without session is guarded and redirects to /login."""
    res = client.get("/")
    assert res.status_code == 302
    assert res.headers.get("location") == "/login"


def test_unauthenticated_weight_page_redirects(client):
    res = client.get("/weight")
    assert res.status_code == 302
    assert res.headers.get("location") == "/login"


# ── Auth guard: JSON clients get 401 not redirect ─────────────────────────────

def test_unauthenticated_page_with_json_accept_returns_401(client):
    res = client.get("/home", headers={"Accept": "application/json"})
    assert res.status_code == 401


def test_unauthenticated_html_page_via_json_accept_returns_401(client):
    res = client.get("/weight", headers={"Accept": "application/json"})
    assert res.status_code == 401


# ── Auth guard: authenticated requests pass through ───────────────────────────

def test_authenticated_home_returns_200(client, session_cookie):
    res = client.get("/home", cookies={"session": session_cookie})
    assert res.status_code == 200


def test_authenticated_weight_page_returns_200(client, session_cookie):
    res = client.get("/weight", cookies={"session": session_cookie})
    assert res.status_code == 200


# ── Logout ────────────────────────────────────────────────────────────────────

def test_logout_returns_204_and_clears_cookie(client, auth_user):
    login_res = client.post(
        "/api/auth/login",
        json={"username": auth_user["name"], "password": auth_user["password"]},
    )
    assert login_res.status_code == 200
    cookie = login_res.cookies.get("session")
    assert cookie

    res = client.post("/api/auth/logout", cookies={"session": cookie})
    assert res.status_code == 204

    # After logout the session cookie should be cleared
    assert "session" not in res.cookies or res.cookies.get("session") == ""


def test_after_logout_guarded_page_redirects(client, auth_user):
    """Session cleared after logout → next guarded page request redirects to /login."""
    login_res = client.post(
        "/api/auth/login",
        json={"username": auth_user["name"], "password": auth_user["password"]},
    )
    cookie = login_res.cookies.get("session")

    client.post("/api/auth/logout", cookies={"session": cookie})

    res = client.get("/home")
    assert res.status_code == 302
    assert res.headers.get("location") == "/login"


# ── nav.js contains logout button ─────────────────────────────────────────────

def test_nav_js_contains_logout_button(client):
    res = client.get("/js/nav.js")
    assert res.status_code == 200
    assert "nav-logout" in res.text
    assert "/api/auth/logout" in res.text
