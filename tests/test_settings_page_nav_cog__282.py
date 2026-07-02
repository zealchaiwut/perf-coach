"""Tests for issue #282: Settings page and nav cog-wheel button."""
import uuid

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9003"
_TEST_PASSWORD = "hunter2-settings-test"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth_user(client):
    name = f"settings-test-{uuid.uuid4().hex[:8]}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201, f"Failed to create user: {res.text}"
    user_id = res.json()["id"]

    pw_hash = hash_password(_TEST_PASSWORD)
    with Session(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        user.password_hash = pw_hash
        session.commit()

    yield {"id": user_id, "name": name, "password": _TEST_PASSWORD}

    client.delete(f"/api/users/{user_id}", cookies=_admin_cookies())


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


# ── Auth gate ─────────────────────────────────────────────────────────────────

def test_settings_unauthenticated_redirects_to_login(client):
    res = client.get("/settings")
    assert res.status_code == 302
    assert res.headers.get("location") == "/login"


def test_settings_unauthenticated_json_accept_returns_401(client):
    res = client.get("/settings", headers={"Accept": "application/json"})
    assert res.status_code == 401


# ── Page renders when authenticated ──────────────────────────────────────────

def test_settings_authenticated_returns_200(client, session_cookie):
    res = client.get("/settings", cookies={"session": session_cookie})
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


def test_settings_page_contains_three_section_headings(client, session_cookie):
    res = client.get("/settings", cookies={"session": session_cookie})
    body = res.text
    assert "<h2>Profile</h2>" in body
    assert "<h2>Security</h2>" in body
    assert "<h2>Integrations</h2>" in body


def test_settings_page_each_section_has_placeholder_content(client, session_cookie):
    res = client.get("/settings", cookies={"session": session_cookie})
    body = res.text
    assert "coming soon" in body.lower()


def test_settings_page_has_no_functional_forms(client, session_cookie):
    """Scaffold only — no form submission elements expected."""
    res = client.get("/settings", cookies={"session": session_cookie})
    body = res.text
    assert "<form" not in body.lower()


# ── Nav cog-wheel button ──────────────────────────────────────────────────────

def test_nav_js_contains_settings_link(client):
    res = client.get("/js/nav.js")
    assert res.status_code == 200
    assert 'href="/settings"' in res.text


def test_nav_js_settings_link_uses_anchor_tag(client):
    """Settings is now the avatar (single entry); it is an <a> to /settings."""
    res = client.get("/js/nav.js")
    assert res.status_code == 200
    assert "gn-avatar" in res.text and 'href="/settings"' in res.text


def test_nav_js_settings_link_has_aria_label(client):
    res = client.get("/js/nav.js")
    assert "settings" in res.text.lower() and "aria-label" in res.text


def test_nav_js_settings_uses_cog_icon(client):
    """The standalone cog was merged into the avatar; there is one settings entry
    (the avatar), and no separate ti-settings gear."""
    res = client.get("/js/nav.js")
    assert "ti-settings" not in res.text and "gn-avatar" in res.text


def test_nav_js_settings_link_placed_after_avatar(client):
    """Settings is the avatar itself now; verify the avatar (settings entry) is present."""
    res = client.get("/js/nav.js")
    body = res.text
    assert body.find("gn-avatar") != -1 and 'href="/settings"' in body


def test_nav_js_settings_link_placed_before_logout(client):
    """The avatar (settings entry) appears before the logout button."""
    res = client.get("/js/nav.js")
    body = res.text
    avatar_pos = body.find("gn-avatar")
    logout_pos = body.find("gn-logout")
    assert avatar_pos != -1 and logout_pos != -1
    assert avatar_pos < logout_pos, "Avatar/settings must appear before logout in nav"


def test_nav_js_settings_active_state_on_settings_path(client):
    """/settings path should produce active class on the cog link."""
    res = client.get("/js/nav.js")
    body = res.text
    assert "active" in body
    assert "/settings" in body


# ── No regression on existing nav / auth ─────────────────────────────────────

def test_existing_pages_still_auth_gated():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=False) as fresh:
        for path in ("/home", "/weight", "/log"):
            res = fresh.get(path)
            assert res.status_code == 302, f"{path} should still redirect unauthenticated"
            assert res.headers.get("location") == "/login"


def test_nav_js_still_has_logout_button(client):
    res = client.get("/js/nav.js")
    assert "nav-logout" in res.text
    assert "/api/auth/logout" in res.text


def test_settings_html_alias_works(client, session_cookie):
    res = client.get("/settings.html", cookies={"session": session_cookie})
    assert res.status_code == 200
