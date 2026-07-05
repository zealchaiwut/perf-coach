"""Tests for issue #679: Add Pydantic validation for race priority and status fields (runs against UAT)"""
import os
import uuid
import pytest
import httpx
from sqlalchemy import create_engine, text


# Build BASE_URL only if UAT_PORT is explicitly set (non-empty).
# "http://localhost:" with empty port is not a valid URL, so guard against that.
_uat_port = os.environ.get("UAT_PORT", "")
BASE_URL = os.environ.get("UAT_BASE_URL") or (f"http://localhost:{_uat_port}" if _uat_port else "")
if not BASE_URL:
    pytest.skip(
        "UAT_BASE_URL / UAT_PORT not set — skipping live-server tests",
        allow_module_level=True,
    )

# Only use DATABASE_URL_UAT — do NOT fall back to DATABASE_URL because
# conftest.py stubs that to sqlite:///./test_perf_coach.db and SQLite has no tables.
_DB_URL = os.environ.get("DATABASE_URL_UAT")
_TEST_PWD = "test679pw!"


@pytest.fixture(scope="module")
def engine():
    if not _DB_URL:
        pytest.skip("DATABASE_URL_UAT not set")
    return create_engine(_DB_URL)


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def _make_user(db_engine, prefix="t679") -> str:
    """Create a test user in the DB."""
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    with db_engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:n) RETURNING id"),
            {"n": name},
        )
        uid = row.scalar_one()
    return uid


def _drop_user(db_engine, uid: str) -> None:
    """Delete a test user from the DB."""
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


def _set_password(db_engine, uid: str, pwd: str) -> None:
    """Set a user's password in the DB."""
    from backend.auth import hash_password
    h = hash_password(pwd)
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET password_hash = :h WHERE id = :uid"),
            {"h": h, "uid": uid},
        )


def _get_username(db_engine, uid: str) -> str:
    """Get a user's username from the DB."""
    with db_engine.begin() as conn:
        row = conn.execute(text("SELECT name FROM users WHERE id = :uid"), {"uid": uid})
        return row.scalar_one()


def _get_csrf_token(client) -> str:
    """Fetch a CSRF token from the API."""
    r = client.get("/api/csrf-token")
    assert r.status_code == 200, f"Failed to get CSRF token: {r.text}"
    data = r.json()
    return data.get("csrf_token", "")


def _login(client, username: str, password: str) -> dict:
    """Log in and return session cookies."""
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return dict(client.cookies)


@pytest.fixture
def authenticated_client(client, engine):
    """Create a test user, log in, and return an authenticated client with CSRF."""
    uid = _make_user(engine)
    try:
        _set_password(engine, uid, _TEST_PWD)
        username = _get_username(engine, uid)

        # Get initial CSRF token
        csrf_token = _get_csrf_token(client)

        # Log in
        cookies = _login(client, username, _TEST_PWD)
        client.cookies.update(cookies)

        # Get fresh CSRF token after login
        csrf_token = _get_csrf_token(client)

        # Set default CSRF header for all requests
        client.headers["X-CSRF-Token"] = csrf_token

        yield client
    finally:
        _drop_user(engine, uid)


@pytest.fixture
def race_id(authenticated_client):
    """Create a test race and return its ID."""
    r = authenticated_client.post(
        "/api/races",
        json={
            "date": "2026-08-15",
            "distance_km": 42.195,
            "goal_time_seconds": 10800,
            "name": "Test Marathon",
            "priority": "A",
            "status": "planned",
        }
    )
    assert r.status_code == 201, f"Failed to create test race: {r.text}"
    return r.json()["id"]


# --- Acceptance Criteria ---

def test_race_priority_status_validation__create_invalid_priority(authenticated_client):
    # AC: `_RaceCreateBody.priority` is typed as `Optional[Literal["A", "B", "C"]]`, rejecting invalid values at request-parsing time
    r = authenticated_client.post(
        "/api/races",
        json={
            "date": "2026-08-15",
            "distance_km": 42.195,
            "goal_time_seconds": 10800,
            "name": "Test Race",
            "priority": "Z",
            "status": "planned",
        }
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    body = r.json()
    assert "detail" in body or "errors" in body, f"No validation error detail in response: {body}"


def test_race_priority_status_validation__create_invalid_status(authenticated_client):
    # AC: `_RaceCreateBody.status` is typed as `Optional[Literal["planned", "done", "abandoned"]]`, rejecting invalid values at request-parsing time
    r = authenticated_client.post(
        "/api/races",
        json={
            "date": "2026-08-15",
            "distance_km": 42.195,
            "goal_time_seconds": 10800,
            "name": "Test Race",
            "priority": "A",
            "status": "invalid",
        }
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    body = r.json()
    assert "detail" in body or "errors" in body, f"No validation error detail in response: {body}"


def test_race_priority_status_validation__update_invalid_priority(authenticated_client, race_id):
    # AC: `_RaceUpdateBody.priority` has the same `Literal` constraints, rejecting invalid values
    r = authenticated_client.put(
        f"/api/races/{race_id}",
        json={
            "priority": "X",
        }
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    body = r.json()
    assert "detail" in body or "errors" in body, f"No validation error detail in response: {body}"


def test_race_priority_status_validation__update_invalid_status(authenticated_client, race_id):
    # AC: `_RaceUpdateBody.status` has the same `Literal` constraints, rejecting invalid values
    r = authenticated_client.put(
        f"/api/races/{race_id}",
        json={
            "status": "running",
        }
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    body = r.json()
    assert "detail" in body or "errors" in body, f"No validation error detail in response: {body}"


def test_race_priority_status_validation__create_valid_values(authenticated_client):
    # AC: Valid values (`"A"`, `"B"`, `"C"` for priority; `"planned"`, `"done"`, `"abandoned"` for status) are accepted and persisted
    r = authenticated_client.post(
        "/api/races",
        json={
            "date": "2026-08-20",
            "distance_km": 5.0,
            "goal_time_seconds": 1500,
            "name": "5K Race",
            "priority": "B",
            "status": "planned",
        }
    )
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["priority"] == "B"
    assert data["status"] == "planned"


def test_race_priority_status_validation__update_valid_values(authenticated_client, race_id):
    # AC: Valid values continue to be accepted and persisted correctly on update
    r = authenticated_client.put(
        f"/api/races/{race_id}",
        json={
            "priority": "C",
            "status": "done",
        }
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["priority"] == "C"
    assert data["status"] == "done"
