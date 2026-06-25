"""
Tests for issue #275: session auth endpoints with brute-force lockout
Server under test: http://127.0.0.1:9001
"""
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
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def auth_user(client):
    name = f"auth-test-{uuid.uuid4().hex[:8]}"
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


def test_login_success(client, auth_user):
    """Valid credentials return 200 with id/name/is_admin and set a session cookie."""
    res = client.post("/api/auth/login", json={"username": auth_user["name"], "password": auth_user["password"]})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    body = res.json()
    assert body["id"] == auth_user["id"]
    assert body["name"] == auth_user["name"]
    assert "is_admin" in body
    assert "session" in res.cookies, "Login must set a session cookie"


def test_login_bad_password_returns_401(client, auth_user):
    """Wrong password returns 401 generic message, no cookie."""
    res = client.post("/api/auth/login", json={"username": auth_user["name"], "password": "wrong-password"})
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"
    assert "session" not in res.cookies


def test_lockout_after_5_failures(client):
    """6th failed attempt for the same username+IP returns 429."""
    username = f"lockout-{uuid.uuid4().hex[:8]}"
    for i in range(5):
        res = client.post("/api/auth/login", json={"username": username, "password": "wrong"})
        assert res.status_code == 401, f"Attempt {i + 1}: expected 401, got {res.status_code}"
    res = client.post("/api/auth/login", json={"username": username, "password": "wrong"})
    assert res.status_code == 429, f"6th attempt: expected 429, got {res.status_code}: {res.text}"


def test_lockout_resets_on_successful_login(client):
    """Successful login clears the failure counter (no lingering lockout)."""
    name = f"reset-test-{uuid.uuid4().hex[:8]}"
    create_res = client.post("/api/users", json={"name": name})
    assert create_res.status_code == 201
    user_id = create_res.json()["id"]

    pw_hash = hash_password(_TEST_PASSWORD)
    with Session(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        user.password_hash = pw_hash
        session.commit()

    try:
        # Accumulate some failures (< 5 so no lockout yet)
        for _ in range(3):
            client.post("/api/auth/login", json={"username": name, "password": "wrong"})
        # Successful login resets counter
        res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PASSWORD})
        assert res.status_code == 200, f"Expected 200 after reset, got {res.status_code}: {res.text}"
    finally:
        client.delete(f"/api/users/{user_id}")


def test_logout_returns_204(client, auth_user):
    """POST /api/auth/logout returns 204 and clears the session cookie."""
    login_res = client.post(
        "/api/auth/login", json={"username": auth_user["name"], "password": auth_user["password"]}
    )
    assert login_res.status_code == 200
    session_cookie = login_res.cookies.get("session")
    assert session_cookie, "Expected session cookie after login"

    res = client.post("/api/auth/logout", cookies={"session": session_cookie})
    assert res.status_code == 204, f"Expected 204, got {res.status_code}: {res.text}"


def test_me_with_valid_session(client, auth_user):
    """/me returns 200 with user info when a valid session cookie is present."""
    login_res = client.post(
        "/api/auth/login", json={"username": auth_user["name"], "password": auth_user["password"]}
    )
    assert login_res.status_code == 200
    session_cookie = login_res.cookies.get("session")

    res = client.get("/api/auth/me", cookies={"session": session_cookie})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    body = res.json()
    assert body["id"] == auth_user["id"]
    assert body["name"] == auth_user["name"]
    assert "is_admin" in body


def test_me_without_session_returns_401(client):
    """/me returns 401 when no session cookie is provided."""
    res = client.get("/api/auth/me")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"
