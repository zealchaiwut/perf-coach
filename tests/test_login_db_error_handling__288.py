"""Tests for issue #288: error handling in login endpoint DB query."""
import uuid
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.db import engine
from backend.main import app
from backend.models import User

BASE = "http://127.0.0.1:9004"
_TEST_PASSWORD = "test-pass-288"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=False) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    name = f"login288-{uuid.uuid4().hex[:8]}"
    res = client.post("/api/users", json={"name": name})
    assert res.status_code == 201, f"Create user failed: {res.text}"
    user_id = res.json()["id"]

    with Session(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        user.password_hash = hash_password(_TEST_PASSWORD)
        session.commit()

    yield {"id": user_id, "name": name}

    client.delete(f"/api/users/{user_id}")


def test_login_success_returns_user_and_cookie(client, test_user):
    res = client.post(
        "/api/auth/login",
        json={"username": test_user["name"], "password": _TEST_PASSWORD},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == test_user["id"]
    assert body["name"] == test_user["name"]
    assert "is_admin" in body
    assert res.cookies.get("session"), "Login must set session cookie"


def test_login_wrong_password_returns_401(client, test_user):
    res = client.post(
        "/api/auth/login",
        json={"username": test_user["name"], "password": "wrong-password"},
    )
    assert res.status_code == 401


def test_login_unknown_user_returns_401(client):
    res = client.post(
        "/api/auth/login",
        json={"username": f"no-such-user-{uuid.uuid4().hex}", "password": "x"},
    )
    assert res.status_code == 401


def test_login_db_error_returns_500():
    import subprocess
    import sys

    coder_path = str(__import__("pathlib").Path(__file__).parent.parent.parent / "coder")
    script = f"""
import sys
sys.path.insert(0, {coder_path!r})
from unittest.mock import patch
from sqlalchemy import exc as sa_exc
from fastapi.testclient import TestClient
from backend.main import app

tc = TestClient(app, raise_server_exceptions=False)
with patch("backend.main.Session", side_effect=sa_exc.SQLAlchemyError("db down")):
    res = tc.post("/api/auth/login", json={{"username": "anyuser", "password": "anypass"}})

assert res.status_code == 500, f"Expected 500, got {{res.status_code}}: {{res.text}}"
assert res.json()["detail"] == "Database error", f"Unexpected body: {{res.text}}"
print("OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=coder_path,
    )
    assert result.returncode == 0, f"DB error test failed:\n{result.stdout}\n{result.stderr}"
