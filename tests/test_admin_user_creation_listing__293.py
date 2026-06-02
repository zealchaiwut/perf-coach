"""Tests for issue #293: admin user creation and listing endpoints.

POST /api/admin/users  — create a user (admin-gated)
GET  /api/admin/users  — list all users with integration_count (admin-gated)

Server under test: http://127.0.0.1:9001
"""
import os
import uuid

import httpx
import pytest
from backend.auth import create_admin_cookie, hash_password
from backend.db import engine
from backend.models import User
from sqlalchemy.orm import Session

BASE = "http://127.0.0.1:9001"
_RUN = uuid.uuid4().hex[:8]
_ADMIN_COOKIE_NAME = "admin_session"


def _admin_client():
    """Return an httpx client with a valid admin session cookie."""
    admin_secret = os.getenv("ADMIN_SECRET_UAT") or os.getenv("ADMIN_SECRET_PRD")
    if not admin_secret:
        pytest.skip("No ADMIN_SECRET env var set — admin tests require it")
    import time
    token = create_admin_cookie(time.time())
    client = httpx.Client(
        base_url=BASE,
        timeout=10,
        follow_redirects=False,
        cookies={_ADMIN_COOKIE_NAME: token},
        headers={"Accept": "application/json"},
    )
    return client


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


# ── Auth guards ───────────────────────────────────────────────────────────────

def test_create_user_no_session_returns_401(anon):
    res = anon.post("/api/admin/users", json={"username": "x", "password": "password123"})
    assert res.status_code == 401


def test_list_users_no_session_returns_401(anon):
    res = anon.get("/api/admin/users")
    assert res.status_code == 401


# ── POST /api/admin/users ─────────────────────────────────────────────────────

def test_create_user_returns_201(admin):
    name = f"admusr-{_RUN}-a"
    res = admin.post("/api/admin/users", json={"username": name, "password": "hunter2hunter2"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["username"] == name
    assert body["is_admin"] is False
    assert "id" in body
    assert "created_at" in body
    assert "password_hash" not in body
    # cleanup
    with Session(engine) as db:
        u = db.query(User).filter(User.name == name).first()
        if u:
            db.delete(u)
            db.commit()


def test_create_user_is_admin_true(admin):
    name = f"admusr-{_RUN}-admin"
    res = admin.post(
        "/api/admin/users",
        json={"username": name, "password": "hunter2hunter2", "is_admin": True},
    )
    assert res.status_code == 201, res.text
    assert res.json()["is_admin"] is True
    with Session(engine) as db:
        u = db.query(User).filter(User.name == name).first()
        if u:
            db.delete(u)
            db.commit()


def test_create_user_password_hashed(admin):
    """Plaintext password must not be stored in the DB."""
    name = f"admusr-{_RUN}-hashchk"
    plain = "hunter2hunter2"
    res = admin.post("/api/admin/users", json={"username": name, "password": plain})
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]
    with Session(engine) as db:
        u = db.get(User, uuid.UUID(user_id))
        assert u is not None
        assert u.password_hash != plain
        assert len(u.password_hash) > 20
        db.delete(u)
        db.commit()


def test_create_user_duplicate_returns_409(admin):
    name = f"admusr-{_RUN}-dup"
    admin.post("/api/admin/users", json={"username": name, "password": "hunter2hunter2"})
    res = admin.post("/api/admin/users", json={"username": name, "password": "hunter2hunter2"})
    assert res.status_code == 409, res.text
    assert "already exists" in res.json().get("detail", "").lower()
    with Session(engine) as db:
        u = db.query(User).filter(User.name == name).first()
        if u:
            db.delete(u)
            db.commit()


def test_create_user_short_password_returns_422(admin):
    res = admin.post("/api/admin/users", json={"username": f"x-{_RUN}", "password": "short"})
    assert res.status_code == 422


def test_create_user_empty_username_returns_422(admin):
    res = admin.post("/api/admin/users", json={"username": "  ", "password": "hunter2hunter2"})
    assert res.status_code in (400, 422)


# ── GET /api/admin/users ──────────────────────────────────────────────────────

def test_list_users_returns_array(admin):
    res = admin.get("/api/admin/users")
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body, list)
    assert len(body) >= 1


def test_list_users_fields(admin):
    res = admin.get("/api/admin/users")
    assert res.status_code == 200, res.text
    user = res.json()[0]
    for field in ("id", "username", "is_admin", "integration_count", "created_at"):
        assert field in user, f"Missing field: {field}"


def test_list_users_integration_count_is_int(admin):
    res = admin.get("/api/admin/users")
    assert res.status_code == 200
    for u in res.json():
        assert isinstance(u["integration_count"], int)
        assert u["integration_count"] >= 0


def test_newly_created_user_appears_in_list(admin):
    name = f"admusr-{_RUN}-listchk"
    create_res = admin.post("/api/admin/users", json={"username": name, "password": "hunter2hunter2"})
    assert create_res.status_code == 201, create_res.text

    list_res = admin.get("/api/admin/users")
    assert list_res.status_code == 200
    names = [u["username"] for u in list_res.json()]
    assert name in names

    with Session(engine) as db:
        u = db.query(User).filter(User.name == name).first()
        if u:
            db.delete(u)
            db.commit()
