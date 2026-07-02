"""Tests for issue #284: avatar upload and display."""
import io
import uuid

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.db import engine
from backend.models import User
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9003"
_TEST_PASSWORD = "hunter2-avatar-test"

# Minimal valid JPEG bytes (SOI + APP0 marker stub)
_TINY_JPEG = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
    0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xD9,
])

_TINY_PNG = bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
    0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
    0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
    0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
    0x00, 0x00, 0x02, 0x00, 0x01, 0xE2, 0x21, 0xBC,
    0x33, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,
    0x44, 0xAE, 0x42, 0x60, 0x82,
])


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth_user(client):
    name = f"avatar-test-{uuid.uuid4().hex[:8]}"
    res = client.post("/api/users", json={"name": name}, cookies=_admin_cookies())
    assert res.status_code == 201, f"Failed to create user: {res.text}"
    user_id = res.json()["id"]

    with Session(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        user.password_hash = hash_password(_TEST_PASSWORD)
        session.commit()

    yield {"id": user_id, "name": name}

    # Cleanup
    client.delete(f"/api/users/{user_id}", cookies=_admin_cookies())


@pytest.fixture(scope="module")
def session_cookie(client, auth_user):
    res = client.post(
        "/api/auth/login",
        json={"username": auth_user["name"], "password": _TEST_PASSWORD},
    )
    assert res.status_code == 200, f"Login failed: {res.text}"
    cookie = res.cookies.get("session")
    assert cookie, "Login must set a session cookie"
    return cookie


# ── GET avatar — no avatar set ────────────────────────────────────────────────

def test_get_avatar_no_avatar_returns_404(client, auth_user):
    res = client.get(f"/api/users/{auth_user['id']}/avatar")
    assert res.status_code == 404


def test_get_avatar_invalid_user_id_returns_400(client):
    res = client.get("/api/users/not-a-uuid/avatar")
    assert res.status_code == 400


def test_get_avatar_unknown_user_returns_404(client):
    res = client.get(f"/api/users/{uuid.uuid4()}/avatar")
    assert res.status_code == 404


# ── POST upload — unauthenticated ─────────────────────────────────────────────

def test_upload_avatar_unauthenticated_returns_401(client):
    res = client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.jpg", _TINY_JPEG, "image/jpeg")},
    )
    assert res.status_code == 401


# ── POST upload — wrong MIME type ─────────────────────────────────────────────

def test_upload_avatar_gif_returns_415(client, session_cookie):
    res = client.post(
        "/api/users/me/avatar",
        files={"file": ("anim.gif", b"GIF89a", "image/gif")},
        cookies={"session": session_cookie},
    )
    assert res.status_code == 415


def test_upload_avatar_svg_returns_415(client, session_cookie):
    res = client.post(
        "/api/users/me/avatar",
        files={"file": ("icon.svg", b"<svg/>", "image/svg+xml")},
        cookies={"session": session_cookie},
    )
    assert res.status_code == 415


# ── POST upload — file too large ──────────────────────────────────────────────

def test_upload_avatar_too_large_returns_413(client, session_cookie):
    big = b"x" * (2 * 1024 * 1024 + 1)
    res = client.post(
        "/api/users/me/avatar",
        files={"file": ("big.jpg", big, "image/jpeg")},
        cookies={"session": session_cookie},
    )
    assert res.status_code == 413


# ── POST upload — success ─────────────────────────────────────────────────────

def test_upload_avatar_jpeg_returns_200(client, session_cookie):
    res = client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.jpg", _TINY_JPEG, "image/jpeg")},
        cookies={"session": session_cookie},
    )
    assert res.status_code == 200
    assert res.json().get("ok") is True


def test_upload_avatar_png_accepted(client, session_cookie):
    res = client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.png", _TINY_PNG, "image/png")},
        cookies={"session": session_cookie},
    )
    assert res.status_code == 200


def test_upload_avatar_webp_accepted(client, session_cookie):
    webp_stub = b"RIFF\x00\x00\x00\x00WEBP"
    res = client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.webp", webp_stub, "image/webp")},
        cookies={"session": session_cookie},
    )
    assert res.status_code == 200


# ── GET avatar — after upload ─────────────────────────────────────────────────

def test_get_avatar_after_upload_returns_image(client, auth_user, session_cookie):
    client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.jpg", _TINY_JPEG, "image/jpeg")},
        cookies={"session": session_cookie},
    )
    res = client.get(f"/api/users/{auth_user['id']}/avatar")
    assert res.status_code == 200


def test_get_avatar_has_correct_content_type(client, auth_user, session_cookie):
    client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.jpg", _TINY_JPEG, "image/jpeg")},
        cookies={"session": session_cookie},
    )
    res = client.get(f"/api/users/{auth_user['id']}/avatar")
    assert "image/jpeg" in res.headers.get("content-type", "")


def test_get_avatar_has_cache_control_header(client, auth_user, session_cookie):
    client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.jpg", _TINY_JPEG, "image/jpeg")},
        cookies={"session": session_cookie},
    )
    res = client.get(f"/api/users/{auth_user['id']}/avatar")
    cc = res.headers.get("cache-control", "")
    assert "max-age=3600" in cc


def test_get_avatar_returns_uploaded_bytes(client, auth_user, session_cookie):
    client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.jpg", _TINY_JPEG, "image/jpeg")},
        cookies={"session": session_cookie},
    )
    res = client.get(f"/api/users/{auth_user['id']}/avatar")
    assert res.content == _TINY_JPEG


# ── Upload replaces existing avatar ──────────────────────────────────────────

def test_upload_replaces_existing_avatar(client, auth_user, session_cookie):
    client.post(
        "/api/users/me/avatar",
        files={"file": ("first.jpg", _TINY_JPEG, "image/jpeg")},
        cookies={"session": session_cookie},
    )
    client.post(
        "/api/users/me/avatar",
        files={"file": ("second.png", _TINY_PNG, "image/png")},
        cookies={"session": session_cookie},
    )
    res = client.get(f"/api/users/{auth_user['id']}/avatar")
    assert res.status_code == 200
    assert "image/png" in res.headers.get("content-type", "")
    assert res.content == _TINY_PNG


# ── DELETE avatar — unauthenticated ──────────────────────────────────────────

def test_delete_avatar_unauthenticated_returns_401(client):
    res = client.delete("/api/users/me/avatar")
    assert res.status_code == 401


# ── DELETE avatar — success ───────────────────────────────────────────────────

def test_delete_avatar_returns_204(client, auth_user, session_cookie):
    client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.jpg", _TINY_JPEG, "image/jpeg")},
        cookies={"session": session_cookie},
    )
    res = client.delete("/api/users/me/avatar", cookies={"session": session_cookie})
    assert res.status_code == 204


def test_get_avatar_after_delete_returns_404(client, auth_user, session_cookie):
    client.post(
        "/api/users/me/avatar",
        files={"file": ("photo.jpg", _TINY_JPEG, "image/jpeg")},
        cookies={"session": session_cookie},
    )
    client.delete("/api/users/me/avatar", cookies={"session": session_cookie})
    res = client.get(f"/api/users/{auth_user['id']}/avatar")
    assert res.status_code == 404


def test_delete_avatar_when_none_is_idempotent(client, session_cookie):
    # First ensure no avatar exists
    client.delete("/api/users/me/avatar", cookies={"session": session_cookie})
    # Delete again — should not error
    res = client.delete("/api/users/me/avatar", cookies={"session": session_cookie})
    assert res.status_code == 204


# ── Settings page content ─────────────────────────────────────────────────────

def test_settings_page_has_upload_photo_label(client, session_cookie):
    res = client.get("/settings", cookies={"session": session_cookie})
    assert res.status_code == 200
    assert "Upload Photo" in res.text


def test_settings_page_has_file_input(client, session_cookie):
    res = client.get("/settings", cookies={"session": session_cookie})
    assert 'type="file"' in res.text
    assert 'avatar-file-input' in res.text


def test_settings_page_has_remove_button(client, session_cookie):
    res = client.get("/settings", cookies={"session": session_cookie})
    assert "avatar-remove-btn" in res.text


def test_settings_page_has_avatar_circle(client, session_cookie):
    res = client.get("/settings", cookies={"session": session_cookie})
    assert "settings-avatar-circle" in res.text


# ── Nav.js — avatar support ───────────────────────────────────────────────────

def test_nav_js_has_navRefreshAvatar(client):
    res = client.get("/js/nav.js")
    assert res.status_code == 200
    assert "navRefreshAvatar" in res.text


def test_nav_js_gn_avatar_has_overflow_hidden(client):
    res = client.get("/js/nav.js")
    assert "overflow:hidden" in res.text


def test_nav_js_loads_avatar_from_api(client):
    res = client.get("/js/nav.js")
    assert "/api/users/" in res.text
    assert "/avatar" in res.text
