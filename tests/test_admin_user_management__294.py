"""Tests for issue #294: admin user management controls with safeguards.

POST /api/admin/users/{id}/reset-password  — reset password (admin-gated)
POST /api/admin/users/{id}/toggle-admin    — toggle is_admin (admin-gated)
POST /api/admin/users/{id}/disable         — disable account (admin-gated)
POST /api/admin/users/{id}/enable          — re-enable account (admin-gated)
DELETE /api/admin/users/{id}               — delete user (admin-gated)
POST /api/auth/login                       — disabled user blocked with 403

Server under test: http://127.0.0.1:9001
"""
import os
import time
import uuid

import httpx
import pytest
from backend.auth import create_admin_cookie, hash_password, verify_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session

BASE = "http://127.0.0.1:9001"
_RUN = uuid.uuid4().hex[:8]
_ADMIN_COOKIE_NAME = "admin_session"


def _admin_client():
    admin_secret = os.getenv("ADMIN_SECRET_UAT") or os.getenv("ADMIN_SECRET_PRD")
    if not admin_secret:
        pytest.skip("No ADMIN_SECRET env var set — admin tests require it")
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


def _create_test_user(session, name, password="hunter2hunter2", is_admin=False, is_active=True):
    u = User(name=name, password_hash=hash_password(password), is_admin=is_admin, is_active=is_active)
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _delete_user_by_name(name):
    with Session(engine) as db:
        u = db.query(User).filter(User.name == name).first()
        if u:
            db.delete(u)
            db.commit()


# ── Auth guards ───────────────────────────────────────────────────────────────

def test_reset_password_no_session_returns_401(anon):
    fake_id = str(uuid.uuid4())
    res = anon.post(f"/api/admin/users/{fake_id}/reset-password", json={"new_password": "hunter2hunter2"})
    assert res.status_code == 401


def test_toggle_admin_no_session_returns_401(anon):
    fake_id = str(uuid.uuid4())
    res = anon.post(f"/api/admin/users/{fake_id}/toggle-admin")
    assert res.status_code == 401


def test_disable_no_session_returns_401(anon):
    fake_id = str(uuid.uuid4())
    res = anon.post(f"/api/admin/users/{fake_id}/disable")
    assert res.status_code == 401


def test_enable_no_session_returns_401(anon):
    fake_id = str(uuid.uuid4())
    res = anon.post(f"/api/admin/users/{fake_id}/enable")
    assert res.status_code == 401


def test_delete_no_session_returns_401(anon):
    fake_id = str(uuid.uuid4())
    res = anon.delete(f"/api/admin/users/{fake_id}")
    assert res.status_code == 401


# ── 404 for unknown user ──────────────────────────────────────────────────────

def test_reset_password_unknown_user_returns_404(admin):
    fake_id = str(uuid.uuid4())
    res = admin.post(f"/api/admin/users/{fake_id}/reset-password", json={"new_password": "hunter2hunter2"})
    assert res.status_code == 404


def test_toggle_admin_unknown_user_returns_404(admin):
    fake_id = str(uuid.uuid4())
    res = admin.post(f"/api/admin/users/{fake_id}/toggle-admin")
    assert res.status_code == 404


def test_disable_unknown_user_returns_404(admin):
    fake_id = str(uuid.uuid4())
    res = admin.post(f"/api/admin/users/{fake_id}/disable")
    assert res.status_code == 404


def test_delete_unknown_user_returns_404(admin):
    fake_id = str(uuid.uuid4())
    res = admin.delete(f"/api/admin/users/{fake_id}")
    assert res.status_code == 404


# ── Reset Password ────────────────────────────────────────────────────────────

def test_reset_password_ok(admin):
    name = f"mgmt-{_RUN}-resetpw"
    with Session(engine) as db:
        u = _create_test_user(db, name, password="oldpassword")
        uid = str(u.id)

    res = admin.post(f"/api/admin/users/{uid}/reset-password", json={"new_password": "newpassword1"})
    assert res.status_code == 200, res.text
    assert res.json().get("ok") is True

    with Session(engine) as db:
        u = db.query(User).filter(User.name == name).first()
        assert u is not None
        assert verify_password("newpassword1", u.password_hash)
        db.delete(u)
        db.commit()


def test_reset_password_short_returns_422(admin):
    name = f"mgmt-{_RUN}-shortpw"
    with Session(engine) as db:
        u = _create_test_user(db, name)
        uid = str(u.id)

    res = admin.post(f"/api/admin/users/{uid}/reset-password", json={"new_password": "short"})
    assert res.status_code == 422

    _delete_user_by_name(name)


# ── Toggle Admin ──────────────────────────────────────────────────────────────

def test_toggle_admin_promotes_user(admin):
    name = f"mgmt-{_RUN}-toggle-up"
    with Session(engine) as db:
        u = _create_test_user(db, name, is_admin=False)
        uid = str(u.id)

    res = admin.post(f"/api/admin/users/{uid}/toggle-admin")
    assert res.status_code == 200, res.text
    assert res.json()["is_admin"] is True

    _delete_user_by_name(name)


def test_toggle_admin_demotes_admin_when_others_exist(admin):
    name = f"mgmt-{_RUN}-toggle-down"
    with Session(engine) as db:
        u = _create_test_user(db, name, is_admin=True)
        uid = str(u.id)

    # Ensure there's at least one other admin in the DB so demotion is allowed.
    admin_count_res = admin.get("/api/admin/users")
    admins = [u for u in admin_count_res.json() if u["is_admin"] and u["id"] != uid]
    if not admins:
        _delete_user_by_name(name)
        pytest.skip("No other admin exists to test demotion")

    res = admin.post(f"/api/admin/users/{uid}/toggle-admin")
    assert res.status_code == 200, res.text
    assert res.json()["is_admin"] is False

    _delete_user_by_name(name)


def test_toggle_admin_last_admin_returns_409(admin):
    """If only one admin exists, toggling it off must return 409."""
    # Count current admins
    users_res = admin.get("/api/admin/users")
    all_users = users_res.json()
    admins = [u for u in all_users if u["is_admin"]]
    if len(admins) != 1:
        pytest.skip("Test requires exactly 1 admin in DB; skipping")

    the_admin = admins[0]
    res = admin.post(f"/api/admin/users/{the_admin['id']}/toggle-admin")
    assert res.status_code == 409, res.text
    assert "admin" in res.json().get("detail", "").lower()


# ── Disable / Enable ──────────────────────────────────────────────────────────

def test_disable_user_blocks_login(admin, anon):
    name = f"mgmt-{_RUN}-disable"
    pw = "hunter2hunter2"
    with Session(engine) as db:
        u = _create_test_user(db, name, password=pw)
        uid = str(u.id)

    # Confirm login works before disable
    login_res = anon.post("/api/auth/login", json={"username": name, "password": pw})
    assert login_res.status_code == 200, "Setup: login should succeed before disabling"

    res = admin.post(f"/api/admin/users/{uid}/disable")
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is False

    login_res2 = anon.post("/api/auth/login", json={"username": name, "password": pw})
    assert login_res2.status_code == 403, login_res2.text
    assert "disabled" in login_res2.json().get("detail", "").lower()

    _delete_user_by_name(name)


def test_enable_user_restores_login(admin, anon):
    name = f"mgmt-{_RUN}-enable"
    pw = "hunter2hunter2"
    with Session(engine) as db:
        u = _create_test_user(db, name, password=pw, is_active=False)
        uid = str(u.id)

    # Login should fail for disabled user
    login_res = anon.post("/api/auth/login", json={"username": name, "password": pw})
    assert login_res.status_code == 403

    res = admin.post(f"/api/admin/users/{uid}/enable")
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is True

    login_res2 = anon.post("/api/auth/login", json={"username": name, "password": pw})
    assert login_res2.status_code == 200, login_res2.text

    _delete_user_by_name(name)


def test_list_users_includes_is_active(admin):
    res = admin.get("/api/admin/users")
    assert res.status_code == 200
    for u in res.json():
        assert "is_active" in u, "Missing is_active field"
        assert isinstance(u["is_active"], bool)


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_user_removes_from_list(admin):
    name = f"mgmt-{_RUN}-del"
    with Session(engine) as db:
        u = _create_test_user(db, name, is_admin=False)
        uid = str(u.id)

    res = admin.delete(f"/api/admin/users/{uid}")
    assert res.status_code == 204, res.text

    list_res = admin.get("/api/admin/users")
    ids = [u["id"] for u in list_res.json()]
    assert uid not in ids


def test_delete_last_admin_returns_409(admin):
    users_res = admin.get("/api/admin/users")
    all_users = users_res.json()
    admins = [u for u in all_users if u["is_admin"]]
    if len(admins) != 1:
        pytest.skip("Test requires exactly 1 admin in DB; skipping")

    the_admin = admins[0]
    res = admin.delete(f"/api/admin/users/{the_admin['id']}")
    assert res.status_code == 409, res.text
    assert "last admin" in res.json().get("detail", "").lower()
