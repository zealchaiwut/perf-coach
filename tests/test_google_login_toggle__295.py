"""Tests for issue #295: Google login toggle via env var and admin UI.

GET  /api/auth/google-status           — public, returns enabled flag
GET  /api/admin/config/google-login    — admin-gated, returns full config state
POST /api/admin/config/google-login    — admin-gated, sets DB toggle
GET  /auth/google                      — 404 when feature disabled
GET  /auth/google/callback             — 404 when feature disabled

Server under test: http://127.0.0.1:9001
"""
import os
import uuid

import httpx
import pytest
from backend.auth import create_admin_cookie
from backend.db import engine
from backend.models import AppConfig
from sqlalchemy.orm import Session

BASE = "http://127.0.0.1:9001"
_ADMIN_COOKIE_NAME = "admin_session"
_APP_CONFIG_GOOGLE_LOGIN = "google_login_enabled"


def _admin_client():
    admin_secret = os.getenv("ADMIN_SECRET_UAT") or os.getenv("ADMIN_SECRET_PRD")
    if not admin_secret:
        pytest.skip("No ADMIN_SECRET env var set — admin tests require it")
    import time
    token = create_admin_cookie(time.time())
    return httpx.Client(
        base_url=BASE,
        timeout=10,
        follow_redirects=False,
        cookies={_ADMIN_COOKIE_NAME: token},
        headers={"Accept": "application/json"},
    )


@pytest.fixture(scope="module")
def admin():
    client = _admin_client()
    yield client
    client.close()


@pytest.fixture(scope="module")
def anon():
    with httpx.Client(
        base_url=BASE,
        timeout=10,
        follow_redirects=False,
        headers={"Accept": "application/json"},
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_db_toggle():
    """Remove any test-written toggle row so tests are independent."""
    yield
    with Session(engine) as db:
        row = db.get(AppConfig, _APP_CONFIG_GOOGLE_LOGIN)
        if row:
            db.delete(row)
            db.commit()


# ── GET /api/auth/google-status ───────────────────────────────────────────────

def test_google_status_returns_200(anon):
    res = anon.get("/api/auth/google-status")
    assert res.status_code == 200


def test_google_status_has_enabled_field(anon):
    res = anon.get("/api/auth/google-status")
    body = res.json()
    assert "enabled" in body
    assert isinstance(body["enabled"], bool)


def test_google_status_disabled_when_env_unset(anon, monkeypatch):
    monkeypatch.delenv("GOOGLE_LOGIN_ENABLED", raising=False)
    res = anon.get("/api/auth/google-status")
    assert res.json()["enabled"] is False


# ── GET /api/admin/config/google-login ────────────────────────────────────────

def test_admin_google_config_requires_auth(anon):
    res = anon.get("/api/admin/config/google-login")
    assert res.status_code == 401


def test_admin_google_config_returns_fields(admin):
    res = admin.get("/api/admin/config/google-login")
    assert res.status_code == 200
    body = res.json()
    for field in ("env_enabled", "credentials_present", "toggle_enabled", "active"):
        assert field in body, f"Missing field: {field}"
    assert isinstance(body["env_enabled"], bool)
    assert isinstance(body["credentials_present"], bool)
    assert isinstance(body["toggle_enabled"], bool)
    assert isinstance(body["active"], bool)


def test_admin_google_config_warning_when_env_true_no_creds(admin, monkeypatch):
    monkeypatch.setenv("GOOGLE_LOGIN_ENABLED", "true")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    res = admin.get("/api/admin/config/google-login")
    assert res.status_code == 200
    body = res.json()
    assert body["env_enabled"] is True
    assert body["credentials_present"] is False
    assert body["warning"] is not None
    assert "GOOGLE_CLIENT" in body["warning"]


# ── POST /api/admin/config/google-login ───────────────────────────────────────

def test_admin_set_google_toggle_requires_auth(anon):
    res = anon.post("/api/admin/config/google-login", json={"enabled": False})
    assert res.status_code == 401


def test_admin_set_google_toggle_false(admin):
    res = admin.post("/api/admin/config/google-login", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["toggle_enabled"] is False


def test_admin_set_google_toggle_true(admin):
    res = admin.post("/api/admin/config/google-login", json={"enabled": True})
    assert res.status_code == 200
    assert res.json()["toggle_enabled"] is True


def test_admin_toggle_persists_in_db(admin):
    admin.post("/api/admin/config/google-login", json={"enabled": False})
    with Session(engine) as db:
        row = db.get(AppConfig, _APP_CONFIG_GOOGLE_LOGIN)
        assert row is not None
        assert row.value == "false"


def test_admin_toggle_reflected_in_get(admin):
    admin.post("/api/admin/config/google-login", json={"enabled": False})
    res = admin.get("/api/admin/config/google-login")
    assert res.json()["toggle_enabled"] is False

    admin.post("/api/admin/config/google-login", json={"enabled": True})
    res = admin.get("/api/admin/config/google-login")
    assert res.json()["toggle_enabled"] is True


# ── /auth/google routes return 404 when disabled ──────────────────────────────

def test_google_signin_initiate_disabled_when_env_unset(anon, monkeypatch):
    monkeypatch.delenv("GOOGLE_LOGIN_ENABLED", raising=False)
    res = anon.get("/auth/google")
    assert res.status_code in (404, 403)


def test_google_signin_callback_disabled_when_env_unset(anon, monkeypatch):
    monkeypatch.delenv("GOOGLE_LOGIN_ENABLED", raising=False)
    res = anon.get("/auth/google/callback", params={"code": "x", "state": "y"})
    assert res.status_code in (404, 403)


def test_google_signin_disabled_via_db_toggle(admin, anon, monkeypatch):
    monkeypatch.setenv("GOOGLE_LOGIN_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    admin.post("/api/admin/config/google-login", json={"enabled": False})
    res = anon.get("/auth/google")
    assert res.status_code in (404, 403)
