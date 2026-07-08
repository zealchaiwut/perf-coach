"""Tests for issue #1177: Reconcile plan_id convention between race and projection routes.

Acceptance criteria verified:
- AC1: _check_plan_access looks up TrainingPlan by UUID and verifies plan.user_id == user.id
- AC2: All /plans/{plan_id}/* routes pass plan_id as TrainingPlan UUID to _check_plan_access
- AC3: /plans/{plan_id}/races returns 200 for owner's plan UUID; 403 for another user's plan UUID
- AC4: /plans/{plan_id}/projection returns 200 for owner's plan UUID, using same _check_plan_access
- AC5: No route accepts bare user.id as plan_id; passing user.id returns 404 or 403
- AC6: Tests use real TrainingPlan UUIDs in fixtures (no plan_id == user.id shortcut)
"""
from __future__ import annotations

import ast
import os
import pathlib
import uuid

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
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
    """Create user, set password, login; return (client, user_id)."""
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


# ── AC1: Static code check — projection route uses _check_plan_access ──────────

def test_projection_route_calls_check_plan_access():
    """AC1/AC4: get_plan_projection must call _check_plan_access, not its own inline check."""
    router_path = _ROOT / "backend" / "routers" / "projection.py"
    source = router_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_plan_projection":
            func_src = ast.get_source_segment(source, node)
            assert func_src is not None, "get_plan_projection function not found"
            assert "_check_plan_access" in func_src, (
                "get_plan_projection must call _check_plan_access instead of an inline check"
            )
            # Must not duplicate the forbidden inline pattern
            assert "plan.user_id != user.id" not in func_src, (
                "get_plan_projection must not contain its own inline plan.user_id != user.id check"
            )
            return

    pytest.fail("get_plan_projection function not found in projection.py")


def test_projection_route_does_not_inline_access_check():
    """AC2: get_plan_projection must not have a second, redundant access check inline."""
    router_path = _ROOT / "backend" / "routers" / "projection.py"
    source = router_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_plan_projection":
            func_src = ast.get_source_segment(source, node)
            # Count 403 raises in this function — there should be 0 (all handled by _check_plan_access)
            raises_403 = func_src.count("403")
            assert raises_403 == 0, (
                f"get_plan_projection should raise no 403 directly (got {raises_403}); "
                "access control must go through _check_plan_access"
            )
            return

    pytest.fail("get_plan_projection function not found in projection.py")


def test_list_races_call_in_projection_uses_plan_uuid():
    """AC2: get_plan_projection must call list_races with the plan UUID (pid), not user.id."""
    router_path = _ROOT / "backend" / "routers" / "projection.py"
    source = router_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_plan_projection":
            func_src = ast.get_source_segment(source, node)
            # The old (broken) call was list_races(plan.user_id) — must not appear
            assert "list_races(plan.user_id)" not in func_src, (
                "get_plan_projection must not call list_races(plan.user_id); "
                "use list_races(pid) — the plan UUID"
            )
            return

    pytest.fail("get_plan_projection function not found in projection.py")


# ── AC5: No route accepts user.id as plan_id ─────────────────────────────────

@pytest.fixture(scope="module")
def owner_client_and_plan():
    """Create a user + TrainingPlan; yield (client, plan_id, user_id). Cleanup after."""
    _skip_if_no_db()
    uname = f"p1177a_{uuid.uuid4().hex[:8]}"
    client, user_id = _make_user_client(uname)

    r = client.post("/api/plans", json={"name": "Test Plan 1177"})
    assert r.status_code == 201, f"create plan failed: {r.text}"
    plan_id = r.json()["id"]

    yield client, plan_id, user_id

    client.close()
    _delete_user(user_id)


@pytest.fixture(scope="module")
def other_client_and_id():
    """Create a second user (no plan); yield (client, user_id). Cleanup after."""
    _skip_if_no_db()
    uname = f"p1177b_{uuid.uuid4().hex[:8]}"
    client, user_id = _make_user_client(uname)
    yield client, user_id
    client.close()
    _delete_user(user_id)


# ── AC5: user.id as plan_id no longer works ────────────────────────────────────

def test_user_id_as_plan_id_rejected_races(owner_client_and_plan):
    """AC5: GET /plans/{user_id}/races with user's own user ID returns 404 or 403."""
    client, _, user_id = owner_client_and_plan
    r = client.get(f"/api/plans/{user_id}/races")
    assert r.status_code in (403, 404), (
        f"Expected 403 or 404 when using user UUID as plan_id for races, got {r.status_code}: {r.text}"
    )


def test_user_id_as_plan_id_rejected_projection(owner_client_and_plan):
    """AC5: GET /plans/{user_id}/projection with user's own user ID returns 404 or 403."""
    client, _, user_id = owner_client_and_plan
    r = client.get(f"/api/plans/{user_id}/projection")
    assert r.status_code in (403, 404), (
        f"Expected 403 or 404 when using user UUID as plan_id for projection, got {r.status_code}: {r.text}"
    )


# ── AC3: Races endpoint — owner gets 200, other user gets 403 ─────────────────

def test_owner_can_access_races_with_plan_uuid(owner_client_and_plan):
    """AC3: Plan owner calling GET /plans/{plan_uuid}/races gets 200."""
    client, plan_id, _ = owner_client_and_plan
    r = client.get(f"/api/plans/{plan_id}/races")
    assert r.status_code == 200, (
        f"Expected 200 for owner accessing races with real plan UUID, got {r.status_code}: {r.text}"
    )


def test_other_user_forbidden_on_races(owner_client_and_plan, other_client_and_id):
    """AC3: Another user calling GET /plans/{plan_uuid}/races gets 403."""
    _, plan_id, _ = owner_client_and_plan
    client_b, _ = other_client_and_id
    r = client_b.get(f"/api/plans/{plan_id}/races")
    assert r.status_code == 403, (
        f"Expected 403 for cross-user races access, got {r.status_code}: {r.text}"
    )


# ── AC4: Projection endpoint — owner gets 200, other user gets 403 ────────────

def test_owner_can_access_projection_with_plan_uuid(owner_client_and_plan):
    """AC4: Plan owner calling GET /plans/{plan_uuid}/projection gets 200."""
    client, plan_id, _ = owner_client_and_plan
    r = client.get(f"/api/plans/{plan_id}/projection")
    assert r.status_code == 200, (
        f"Expected 200 for owner accessing projection with real plan UUID, got {r.status_code}: {r.text}"
    )


def test_other_user_forbidden_on_projection(owner_client_and_plan, other_client_and_id):
    """AC4/AC5: Another user calling GET /plans/{plan_uuid}/projection gets 403."""
    _, plan_id, _ = owner_client_and_plan
    client_b, _ = other_client_and_id
    r = client_b.get(f"/api/plans/{plan_id}/projection")
    assert r.status_code == 403, (
        f"Expected 403 for cross-user projection access, got {r.status_code}: {r.text}"
    )


# ── AC6: Non-existent plan UUID returns 404 for both routes ──────────────────

def test_nonexistent_uuid_races_returns_404(owner_client_and_plan):
    """AC6: A UUID not in the DB returns 404 for /plans/{plan_id}/races."""
    client, _, _ = owner_client_and_plan
    r = client.get(f"/api/plans/{uuid.uuid4()}/races")
    assert r.status_code == 404, (
        f"Expected 404 for non-existent plan UUID on races, got {r.status_code}: {r.text}"
    )


def test_nonexistent_uuid_projection_returns_404(owner_client_and_plan):
    """AC6: A UUID not in the DB returns 404 for /plans/{plan_id}/projection."""
    client, _, _ = owner_client_and_plan
    r = client.get(f"/api/plans/{uuid.uuid4()}/projection")
    assert r.status_code == 404, (
        f"Expected 404 for non-existent plan UUID on projection, got {r.status_code}: {r.text}"
    )
