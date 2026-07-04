"""Tests for issue #1136: _check_plan_access equates plan_id with user_id.

Acceptance criteria verified:
- AC1: _check_plan_access fetches TrainingPlan by plan_id and compares plan.user_id == user.id
        (no longer plan_id == user.id)
- AC2: A valid plan UUID from POST /api/plans passes race/checkpoint endpoints for the plan owner (200)
- AC3: A plan UUID belonging to a different user returns 403
- AC4: A non-existent plan UUID returns 404
- AC5: Implementation mirrors the existing pattern in get_plan_projection
"""
import ast
import os
import pathlib
import uuid

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "plan1136test!"
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


# ── AC1: Static code check — no plan_id == user.id in _check_plan_access ──────

def test_check_plan_access_uses_db_lookup_not_id_equality():
    """AC1: _check_plan_access must not compare plan_id directly to user.id."""
    router_path = _ROOT / "backend" / "routers" / "projection.py"
    source = router_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_check_plan_access":
            func_src = ast.get_source_segment(source, node)
            assert func_src is not None, "_check_plan_access function not found"
            # The old broken pattern compared plan_id directly to user.id
            assert "plan_id != user.id" not in func_src, (
                "_check_plan_access still uses 'plan_id != user.id' — must use DB lookup"
            )
            assert "plan_id == user.id" not in func_src, (
                "_check_plan_access still uses 'plan_id == user.id' — must use DB lookup"
            )
            # Must contain a DB lookup for TrainingPlan
            assert "TrainingPlan" in func_src or "_TrainingPlan" in func_src, (
                "_check_plan_access must look up TrainingPlan from DB"
            )
            return

    pytest.fail("_check_plan_access function not found in projection.py")


def test_check_plan_access_returns_404_for_nonexistent_plan_source():
    """AC4: _check_plan_access source must raise 404 when plan is not found."""
    router_path = _ROOT / "backend" / "routers" / "projection.py"
    source = router_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_check_plan_access":
            func_src = ast.get_source_segment(source, node)
            assert "404" in func_src, (
                "_check_plan_access must raise 404 for non-existent plan"
            )
            return

    pytest.fail("_check_plan_access function not found in projection.py")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def owner_client_and_plan():
    """Create a user + plan, yield (client, plan_id, user_id). Cleanup after."""
    _skip_if_no_db()
    uname = f"plan1136a_{uuid.uuid4().hex[:8]}"
    client, user_id = _make_user_client(uname)

    r = client.post("/api/plans", json={
        "name": "Test Plan 1136",
        "ramp_rate": 5.0,
    })
    assert r.status_code == 201, f"create plan failed: {r.text}"
    plan_id = r.json()["id"]

    yield client, plan_id, user_id

    client.close()
    _delete_user(user_id)


@pytest.fixture(scope="module")
def other_client():
    """Create a second user who does not own the plan, yield (client, user_id). Cleanup after."""
    _skip_if_no_db()
    uname = f"plan1136b_{uuid.uuid4().hex[:8]}"
    client, user_id = _make_user_client(uname)
    yield client, user_id
    client.close()
    _delete_user(user_id)


# ── AC2: Valid plan UUID from POST /api/plans passes race endpoint (200) ──────

def test_owner_can_list_races_with_real_plan_id(owner_client_and_plan):
    """AC2: Plan owner using the real plan UUID gets 200 from GET /plans/{plan_id}/races."""
    client, plan_id, _ = owner_client_and_plan
    r = client.get(f"/plans/{plan_id}/races")
    assert r.status_code == 200, (
        f"Expected 200 for owner using real plan_id, got {r.status_code}: {r.text}"
    )


def test_owner_can_create_race_with_real_plan_id(owner_client_and_plan):
    """AC2: Plan owner using the real plan UUID gets 201 from POST /plans/{plan_id}/races."""
    client, plan_id, _ = owner_client_and_plan
    r = client.post(f"/plans/{plan_id}/races", json={
        "date": "2027-09-01",
        "distance": 21.097,
        "type": "race",
    })
    assert r.status_code == 201, (
        f"Expected 201 for owner using real plan_id, got {r.status_code}: {r.text}"
    )
    race_id = r.json()["id"]
    client.delete(f"/plans/{plan_id}/races/{race_id}")


def test_user_uuid_as_plan_id_no_longer_grants_access(owner_client_and_plan):
    """AC2/UAT2: Using own user UUID as plan_id should return 404 (plan doesn't exist at that id)."""
    client, _, user_id = owner_client_and_plan
    r = client.get(f"/plans/{user_id}/races")
    assert r.status_code == 404, (
        f"Expected 404 when using user UUID as plan_id, got {r.status_code}: {r.text}"
    )


# ── AC3: Cross-user access returns 403 ────────────────────────────────────────

def test_other_user_cannot_list_races_on_foreign_plan(owner_client_and_plan, other_client):
    """AC3: User B cannot access User A's plan races — expects 403."""
    _, plan_id, _ = owner_client_and_plan
    client_b, _ = other_client
    r = client_b.get(f"/plans/{plan_id}/races")
    assert r.status_code == 403, (
        f"Expected 403 for cross-user access, got {r.status_code}: {r.text}"
    )


def test_other_user_cannot_create_race_on_foreign_plan(owner_client_and_plan, other_client):
    """AC3: User B POST to User A's plan races returns 403."""
    _, plan_id, _ = owner_client_and_plan
    client_b, _ = other_client
    r = client_b.post(f"/plans/{plan_id}/races", json={
        "date": "2027-10-01",
        "distance": 5.0,
        "type": "race",
    })
    assert r.status_code == 403, (
        f"Expected 403 for cross-user create, got {r.status_code}: {r.text}"
    )


# ── AC4: Non-existent plan UUID returns 404 ───────────────────────────────────

def test_nonexistent_plan_uuid_returns_404_on_list_races(owner_client_and_plan):
    """AC4: A randomly generated UUID that is not in the DB returns 404."""
    client, _, _ = owner_client_and_plan
    random_id = str(uuid.uuid4())
    r = client.get(f"/plans/{random_id}/races")
    assert r.status_code == 404, (
        f"Expected 404 for non-existent plan UUID, got {r.status_code}: {r.text}"
    )


def test_nonexistent_plan_uuid_returns_404_on_create_race(owner_client_and_plan):
    """AC4: POST to a non-existent plan UUID returns 404."""
    client, _, _ = owner_client_and_plan
    random_id = str(uuid.uuid4())
    r = client.post(f"/plans/{random_id}/races", json={
        "date": "2027-11-01",
        "distance": 10.0,
        "type": "race",
    })
    assert r.status_code == 404, (
        f"Expected 404 for non-existent plan UUID, got {r.status_code}: {r.text}"
    )
