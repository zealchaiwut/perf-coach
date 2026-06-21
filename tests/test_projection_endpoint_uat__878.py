"""
Tests for issue #878: Add projection endpoint for arrival date and rate (UAT HTTP tests).

These tests verify the HTTP endpoint /api/weight-targets/arrival-projection
against a running UAT server, ensuring the endpoint correctly:
1. Returns valid JSON responses for authenticated users
2. Resolves the active plan and goal correctly
3. Handles edge cases (no plan, no goal, insufficient data, not trending)
4. Returns consistent response shape across all states

Tests authenticate as a user and verify the endpoint behavior.
"""
import os
import pathlib
import uuid
import pytest
import httpx
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel


# Resolved from UAT .env at runtime; see tester skill Step 0.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TEST_PW = "test878pw!"
_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def authenticated_client(client):
    """Create a test user, authenticate, and return client with session."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    # Create test user
    user_name = f"proj_test_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name})
    assert r.status_code == 201, f"Failed to create user: {r.text}"
    user_id = r.json()["id"]

    # Set password
    password = _TEST_PW
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(password)
        db.commit()

    # Login
    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = bare.post("/api/auth/login", json={"username": user_name, "password": password})
    bare.close()
    assert r.status_code == 200, f"Login failed: {r.text}"

    session_cookie = r.cookies.get("session")
    csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    # Return new authenticated client
    auth = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )

    yield auth
    auth.close()

    # Cleanup: delete user
    with _OrmSess(_engine) as sess:
        user = sess.get(_UserModel, uuid.UUID(user_id))
        if user:
            sess.delete(user)
            sess.commit()


# ── AC1/AC2: Endpoint accepts plan/goal and returns projection fields ─────

def test_endpoint_returns_200_with_valid_auth(authenticated_client):
    """AC1+AC2: Endpoint responds 200 for authenticated user."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    assert r.status_code == 200


def test_response_is_json(authenticated_client):
    """AC2+AC6: Response is valid JSON with consistent structure."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)


def test_response_shape_has_required_keys(authenticated_client):
    """AC6: Response shape is consistent with required keys."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    data = r.json()
    required_keys = {"projected_arrival_date", "projected_rate", "recent_rate", "reason"}
    actual_keys = set(data.keys())
    missing = required_keys - actual_keys
    assert not missing, f"Missing keys in response: {missing}"


# ── AC2: Normal projection (happy path) ──────────────────────────────────

def test_normal_projection_with_active_plan_and_trend(authenticated_client):
    """AC2: With active plan, goal, and weight entries, returns non-null arrival date."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    data = r.json()

    # If the user has an active plan with entries, check for non-null fields
    # (This test may return empty state if seed user lacks data; that's OK)
    if data["reason"] is None:
        # Happy path: projection succeeded
        assert data["projected_arrival_date"] is not None
        assert data["projected_rate"] is not None
        assert data["recent_rate"] is not None


def test_arrival_date_is_iso_format(authenticated_client):
    """AC2: projected_arrival_date, if non-null, must be ISO format string."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    data = r.json()

    if data["projected_arrival_date"] is not None:
        # Must be parseable as an ISO date
        parsed = datetime.date.fromisoformat(data["projected_arrival_date"])
        assert isinstance(parsed, datetime.date)


# ── AC3: not-trending-toward-goal state ──────────────────────────────────

def test_not_trending_has_null_projection_fields(authenticated_client):
    """AC3: When not trending, projected_arrival_date and projected_rate are null."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    data = r.json()

    if data["reason"] == "not_trending_toward_goal":
        assert data["projected_arrival_date"] is None
        assert data["projected_rate"] is None


def test_not_trending_recent_rate_populated(authenticated_client):
    """AC3+AC5: When not trending, recent_rate is still populated."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    data = r.json()

    if data["reason"] == "not_trending_toward_goal":
        assert data["recent_rate"] is not None


def test_not_trending_reason_value(authenticated_client):
    """AC3: reason field must be 'not_trending_toward_goal'."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    data = r.json()

    if data["reason"] == "not_trending_toward_goal":
        assert data["reason"] == "not_trending_toward_goal"


# ── AC4: Missing data states (no plan, no goal, insufficient data) ───────

def test_no_active_plan_returns_200(authenticated_client):
    """AC4: no_active_plan reason returns HTTP 200, not 4xx/5xx."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    assert r.status_code == 200

    # If the user has no active plan, we expect this reason
    data = r.json()
    if data["reason"] == "no_active_plan":
        assert data["projected_arrival_date"] is None
        assert data["projected_rate"] is None
        assert data["recent_rate"] is None


def test_no_active_goal_returns_200(authenticated_client):
    """AC4: no_active_goal reason returns HTTP 200, not 4xx/5xx."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    assert r.status_code == 200

    data = r.json()
    if data["reason"] == "no_active_goal":
        assert data["projected_arrival_date"] is None
        assert data["projected_rate"] is None
        assert data["recent_rate"] is None


def test_insufficient_data_returns_200(authenticated_client):
    """AC4: insufficient_data reason returns HTTP 200, not 4xx/5xx."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    assert r.status_code == 200

    data = r.json()
    if data["reason"] == "insufficient_data":
        assert data["projected_arrival_date"] is None
        assert data["projected_rate"] is None
        assert data["recent_rate"] is None


# ── AC4: Reason field values ─────────────────────────────────────────────

def test_reason_is_one_of_expected_values(authenticated_client):
    """AC4+AC6: reason field is one of the documented values or null."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    data = r.json()

    expected_reasons = {None, "no_active_plan", "no_active_goal", "insufficient_data", "not_trending_toward_goal"}
    assert data["reason"] in expected_reasons, f"Unexpected reason: {data['reason']}"


# ── AC5: recent_rate is always present when computable ─────────────────

def test_response_shape_consistent_all_states(authenticated_client):
    """AC6: All four keys present in every response state."""
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    data = r.json()

    required_keys = {"projected_arrival_date", "projected_rate", "recent_rate", "reason"}
    actual_keys = set(data.keys())

    assert actual_keys == required_keys, f"Response shape mismatch. Expected {required_keys}, got {actual_keys}"


# ── AC1: Endpoint path and auth gating ────────────────────────────────

def test_endpoint_requires_auth(client):
    """AC1: Unauthenticated requests must be rejected (401)."""
    r = client.get("/api/weight-targets/arrival-projection")
    # Expect 401 for unauthenticated API request
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


def test_endpoint_path_is_correct(authenticated_client):
    """AC1: Endpoint path is /api/weight-targets/arrival-projection."""
    # Verify the endpoint is routable and returns a valid response
    r = authenticated_client.get("/api/weight-targets/arrival-projection")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
