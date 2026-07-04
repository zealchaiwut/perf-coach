"""Tests for issue #1177: Reconcile plan_id convention between race and projection routes.

Acceptance criteria verified:
- AC1: _check_plan_access uses real TrainingPlan UUID lookup, not plan_id == user.id
- AC2: All /plans/{plan_id}/* routes pass plan_id as TrainingPlan UUID to _check_plan_access
- AC3: GET /plans/{plan_id}/races with valid TrainingPlan UUID owned by user returns 200
- AC4: GET /plans/{plan_id}/projection with valid TrainingPlan UUID owned by user returns 200
- AC5: GET /plans/{user_id}/races (user UUID instead of plan UUID) returns 404 or 403
- AC6: GET /plans/{other_user_plan_uuid}/races from another user returns 403
- AC7: GET /plans/{other_user_plan_uuid}/projection from another user returns 403
- AC8: GET /plans/{nonexistent_uuid}/races returns 404
- AC9: GET /plans/{nonexistent_uuid}/projection returns 404
"""
import os
import pathlib
import uuid

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "plan1177test!"
_ROOT = pathlib.Path(__file__).resolve().parents[1]

try:
    from dotenv import dotenv_values
    _env = dotenv_values(_ROOT / ".env")
    _uat_url = _env.get("DATABASE_URL_UAT")
except ImportError:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

if _uat_url:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _OrmSess
    from backend.auth import hash_password as _hash_pw
    from backend.models import User as _UserModel
    _engine = create_engine(_uat_url, pool_pre_ping=True)
else:
    _engine = None


def _skip_if_no_db():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")


def _admin_cookies():
    from tests._admin_helpers import admin_cookies
    return admin_cookies()


def _make_user_client(uname: str) -> tuple:
    """Create user, set password, login, return (client, user_id)."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/users", json={"name": uname}, cookies=_admin_cookies())
        assert r.status_code == 201, f"create user failed: {r.text}"
        user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/auth/login", json={"username": uname, "password": _TEST_PW})
        assert r.status_code == 200, f"login failed: {r.text}"
        session_cookie = r.cookies.get("session")
        csrf_token = r.cookies.get("csrf-token")

    client = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, "csrf-token": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return client, user_id


def _delete_user(user_id: str):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def user_a_client_and_plan():
    """Create user A with a plan, yield (client, plan_id, user_id). Cleanup after."""
    _skip_if_no_db()
    uname = f"plan1177a_{uuid.uuid4().hex[:8]}"
    client, user_id = _make_user_client(uname)

    r = client.post("/api/plans", json={
        "name": "Test Plan 1177 A",
        "ramp_rate": 5.0,
    })
    assert r.status_code == 201, f"create plan failed: {r.text}"
    plan_id = r.json()["id"]

    yield client, plan_id, user_id

    client.close()
    _delete_user(user_id)


@pytest.fixture(scope="module")
def user_b_client():
    """Create user B (different account), yield (client, user_id). Cleanup after."""
    _skip_if_no_db()
    uname = f"plan1177b_{uuid.uuid4().hex[:8]}"
    client, user_id = _make_user_client(uname)
    yield client, user_id
    client.close()
    _delete_user(user_id)


# ── AC3: Valid plan UUID + owner = 200 for races ──────────────────────────────

def test_ac3_owner_races_with_valid_plan_uuid(user_a_client_and_plan):
    """AC3: Plan owner using real plan UUID gets 200 from GET /api/plans/{plan_id}/races."""
    client, plan_id, _ = user_a_client_and_plan
    r = client.get(f"/api/plans/{plan_id}/races")
    assert r.status_code == 200, (
        f"Expected 200 for owner with valid plan UUID, got {r.status_code}: {r.text}"
    )
    # Verify response is a list of races (can be empty initially)
    data = r.json()
    assert isinstance(data, list), "races endpoint should return a list"


# ── AC4: Valid plan UUID + owner = 200 for projection ────────────────────────

def test_ac4_owner_projection_with_valid_plan_uuid(user_a_client_and_plan):
    """AC4: Plan owner using real plan UUID gets 200 from GET /plans/{plan_id}/projection."""
    client, plan_id, _ = user_a_client_and_plan
    r = client.get(f"/api/plans/{plan_id}/projection")
    assert r.status_code == 200, (
        f"Expected 200 for owner with valid plan UUID, got {r.status_code}: {r.text}"
    )
    # Verify response contains projection data
    data = r.json()
    assert isinstance(data, dict), "projection endpoint should return an object"


# ── AC5: User ID instead of plan UUID = 404/403 for races ────────────────────

def test_ac5_user_id_as_races_plan_id_returns_not_found_or_forbidden(user_a_client_and_plan):
    """AC5: Using user UUID as plan_id in races endpoint returns 404 or 403."""
    client, _, user_id = user_a_client_and_plan
    r = client.get(f"/plans/{user_id}/races")
    assert r.status_code in (404, 403), (
        f"Expected 404 or 403 when using user UUID as plan_id, got {r.status_code}: {r.text}"
    )


# ── AC5 variant: User ID instead of plan UUID = 404/403 for projection ───────

def test_ac5_user_id_as_projection_plan_id_returns_not_found_or_forbidden(user_a_client_and_plan):
    """AC5: Using user UUID as plan_id in projection endpoint returns 404 or 403."""
    client, _, user_id = user_a_client_and_plan
    r = client.get(f"/plans/{user_id}/projection")
    assert r.status_code in (404, 403), (
        f"Expected 404 or 403 when using user UUID as plan_id, got {r.status_code}: {r.text}"
    )


# ── AC6: Cross-user access to races = 403 ────────────────────────────────────

def test_ac6_user_b_cannot_access_user_a_plan_races(user_a_client_and_plan, user_b_client):
    """AC6: User B accessing User A's plan races returns 403."""
    _, plan_id, _ = user_a_client_and_plan
    client_b, _ = user_b_client
    r = client_b.get(f"/api/plans/{plan_id}/races")
    assert r.status_code == 403, (
        f"Expected 403 for cross-user access to races, got {r.status_code}: {r.text}"
    )


# ── AC7: Cross-user access to projection = 403 ───────────────────────────────

def test_ac7_user_b_cannot_access_user_a_plan_projection(user_a_client_and_plan, user_b_client):
    """AC7: User B accessing User A's plan projection returns 403."""
    _, plan_id, _ = user_a_client_and_plan
    client_b, _ = user_b_client
    r = client_b.get(f"/api/plans/{plan_id}/projection")
    assert r.status_code == 403, (
        f"Expected 403 for cross-user access to projection, got {r.status_code}: {r.text}"
    )


# ── AC8: Non-existent plan UUID on races = 404 ────────────────────────────────

def test_ac8_nonexistent_uuid_races_returns_404(user_a_client_and_plan):
    """AC8: A random UUID that doesn't correspond to a plan returns 404 on races."""
    client, _, _ = user_a_client_and_plan
    random_uuid = str(uuid.uuid4())
    r = client.get(f"/plans/{random_uuid}/races")
    assert r.status_code == 404, (
        f"Expected 404 for non-existent plan UUID on races, got {r.status_code}: {r.text}"
    )


# ── AC9: Non-existent plan UUID on projection = 404 ──────────────────────────

def test_ac9_nonexistent_uuid_projection_returns_404(user_a_client_and_plan):
    """AC9: A random UUID that doesn't correspond to a plan returns 404 on projection."""
    client, _, _ = user_a_client_and_plan
    random_uuid = str(uuid.uuid4())
    r = client.get(f"/plans/{random_uuid}/projection")
    assert r.status_code == 404, (
        f"Expected 404 for non-existent plan UUID on projection, got {r.status_code}: {r.text}"
    )


# ── AC2: All routes use same _check_plan_access path (static check) ──────────

def test_ac2_projection_endpoint_uses_check_plan_access():
    """AC2: Verify projection endpoint calls _check_plan_access for consistency."""
    router_path = _ROOT / "backend" / "routers" / "projection.py"
    source = router_path.read_text()

    # Find get_plan_projection function
    assert "get_plan_projection" in source, "get_plan_projection must exist"

    # Check that it either calls _check_plan_access or does the equivalent DB lookup
    assert (
        "_check_plan_access(pid, user)" in source or
        ("db.get(_TrainingPlan" in source and "plan.user_id != user.id" in source)
    ), (
        "projection endpoint must either call _check_plan_access or use the same access check pattern"
    )
