"""
Integration tests for issue #864: Add CRUD endpoints for user weight plan.

Each test is anchored to a specific acceptance criterion from the issue.
Tests run against a live UAT server at http://127.0.0.1:9001.
"""
import os
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import CSRF_COOKIE_NAME, hash_password as _hash_pw
from backend.models import User as _UserModel
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test864pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _make_auth_client(base_client: httpx.Client) -> tuple[httpx.Client, str]:
    """Create a test user, set password, login, return (auth_client, user_id)."""
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set")

    user_name = f"wp_test_{uuid.uuid4().hex[:8]}"
    r = base_client.post("/api/users", json={"name": user_name}, cookies=_admin_cookies())
    assert r.status_code == 201, f"Failed to create user: {r.text}"
    user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r = bare.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    bare.close()
    assert r.status_code == 200, f"Login failed: {r.text}"

    session_cookie = r.cookies.get("session")
    csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    auth = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return auth, user_id


def _cleanup_user(user_id: str) -> None:
    if _engine is None:
        return
    with _OrmSess(_engine) as sess:
        user = sess.get(_UserModel, uuid.UUID(user_id))
        if user:
            sess.delete(user)
            sess.commit()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_client(client):
    auth, user_id = _make_auth_client(client)
    yield auth
    auth.close()
    _cleanup_user(user_id)


@pytest.fixture
def two_auth_clients(client):
    """Two distinct authenticated users for cross-user access tests."""
    auth1, uid1 = _make_auth_client(client)
    auth2, uid2 = _make_auth_client(client)
    yield auth1, auth2
    auth1.close()
    auth2.close()
    _cleanup_user(uid1)
    _cleanup_user(uid2)


_CUT_PLAN = {
    "start_weight": 90.0,
    "goal_weight": 80.0,
    "start_date": "2026-06-01",
    "goal_date": "2026-12-01",
    "phase": "cut",
}


# ── AC1: POST /weight-plans creates a plan and marks it active ────────────────

def test_ac1_create_plan_returns_201(auth_client):
    """AC1: POST /api/weight-plans returns 201 with active=true."""
    r = auth_client.post("/api/weight-plans", json=_CUT_PLAN)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["active"] is True
    assert "id" in data


def test_ac1_create_plan_deactivates_previous(auth_client):
    """AC1: Creating a second plan atomically deactivates the first one."""
    r1 = auth_client.post("/api/weight-plans", json=_CUT_PLAN)
    assert r1.status_code == 201, r1.text
    plan1_id = r1.json()["id"]

    second = {**_CUT_PLAN, "goal_weight": 82.0}
    r2 = auth_client.post("/api/weight-plans", json=second)
    assert r2.status_code == 201, r2.text
    plan2_id = r2.json()["id"]
    assert plan2_id != plan1_id

    # Active endpoint returns the new plan
    r_active = auth_client.get("/api/weight-plans/active")
    assert r_active.status_code == 200
    assert r_active.json()["id"] == plan2_id


# ── AC2: GET /weight-plans/active returns active plan or 404 ─────────────────

def test_ac2_get_active_when_none_returns_404(auth_client):
    """AC2: GET /api/weight-plans/active returns 404 when no active plan."""
    r = auth_client.get("/api/weight-plans/active")
    assert r.status_code == 404, r.text


def test_ac2_get_active_returns_plan(auth_client):
    """AC2: GET /api/weight-plans/active returns 200 with the active plan."""
    r = auth_client.post("/api/weight-plans", json=_CUT_PLAN)
    assert r.status_code == 201
    plan_id = r.json()["id"]

    r2 = auth_client.get("/api/weight-plans/active")
    assert r2.status_code == 200
    assert r2.json()["id"] == plan_id


# ── AC3: PATCH /weight-plans/:id updates mutable fields ─────────────────────

def test_ac3_patch_updates_goal_weight(auth_client):
    """AC3: PATCH /api/weight-plans/:id updates goal_weight and leaves other fields unchanged."""
    r = auth_client.post("/api/weight-plans", json=_CUT_PLAN)
    assert r.status_code == 201
    plan = r.json()
    plan_id = plan["id"]

    r2 = auth_client.patch(f"/api/weight-plans/{plan_id}", json={"goal_weight": 78.0})
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["goal_weight"] == 78.0
    assert data["start_weight"] == plan["start_weight"]  # unchanged


def test_ac3_patch_updates_goal_date(auth_client):
    """AC3: PATCH updates goal_date."""
    r = auth_client.post("/api/weight-plans", json=_CUT_PLAN)
    assert r.status_code == 201
    plan_id = r.json()["id"]

    r2 = auth_client.patch(f"/api/weight-plans/{plan_id}", json={"goal_date": "2027-01-01"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["goal_date"] == "2027-01-01"


# ── AC4: DELETE /weight-plans/:id deactivates (no hard-delete) ───────────────

def test_ac4_delete_deactivates_plan(auth_client):
    """AC4: DELETE /api/weight-plans/:id deactivates the plan; row still exists."""
    r = auth_client.post("/api/weight-plans", json=_CUT_PLAN)
    assert r.status_code == 201
    plan_id = r.json()["id"]

    r2 = auth_client.delete(f"/api/weight-plans/{plan_id}")
    assert r2.status_code == 200, r2.text
    assert r2.json()["active"] is False

    # Active plan no longer found
    r3 = auth_client.get("/api/weight-plans/active")
    assert r3.status_code == 404


# ── AC7: goal_weight + goal_date without rate → no derived rate stored ────────

def test_ac7_no_rate_derived_when_not_provided(auth_client):
    """AC7: When goal_weight and goal_date are given but rate is omitted, rate stays null."""
    body = {
        "start_weight": 90.0,
        "goal_weight": 80.0,
        "start_date": "2026-06-01",
        "goal_date": "2026-12-01",
        "phase": "cut",
    }
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data.get("rate") is None


# ── AC8: rate provided, goal_date optional ────────────────────────────────────

def test_ac8_rate_provided_goal_date_optional(auth_client):
    """AC8: When rate is given without goal_date, 201 with goal_date null."""
    body = {
        "start_weight": 90.0,
        "goal_weight": 80.0,
        "start_date": "2026-06-01",
        "rate": 0.5,
        "phase": "cut",
    }
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data.get("goal_date") is None
    assert data.get("rate") == 0.5


# ── AC9: Non-positive weight values rejected ──────────────────────────────────

def test_ac9_zero_start_weight_rejected(auth_client):
    """AC9: start_weight=0 returns 422."""
    body = {**_CUT_PLAN, "start_weight": 0.0}
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 422, r.text


def test_ac9_negative_start_weight_rejected(auth_client):
    """AC9: start_weight=-70 returns 422 referencing start_weight."""
    body = {**_CUT_PLAN, "start_weight": -70.0}
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 422, r.text
    assert "start_weight" in r.text


def test_ac9_zero_goal_weight_rejected(auth_client):
    """AC9: goal_weight=0 returns 422."""
    body = {**_CUT_PLAN, "goal_weight": 0.0}
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 422, r.text


def test_ac9_negative_rate_rejected(auth_client):
    """AC9: rate=-0.5 returns 422."""
    body = {**_CUT_PLAN, "rate": -0.5}
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 422, r.text
    assert "rate" in r.text


def test_ac9_zero_rate_rejected(auth_client):
    """AC9: rate=0 returns 422."""
    body = {**_CUT_PLAN, "rate": 0.0}
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 422, r.text


# ── AC10: goal_weight direction must match phase ──────────────────────────────

def test_ac10_cut_with_goal_above_start_rejected(auth_client):
    """AC10: cut phase with goal_weight > start_weight returns 422."""
    body = {
        "start_weight": 80.0,
        "goal_weight": 90.0,   # wrong: goal > start for a cut
        "start_date": "2026-06-01",
        "goal_date": "2026-12-01",
        "phase": "cut",
    }
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 422, r.text


def test_ac10_bulk_with_goal_below_start_rejected(auth_client):
    """AC10: bulk phase with goal_weight < start_weight returns 422."""
    body = {
        "start_weight": 80.0,
        "goal_weight": 70.0,   # wrong: goal < start for a bulk
        "start_date": "2026-06-01",
        "goal_date": "2026-12-01",
        "phase": "bulk",
    }
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 422, r.text


# ── AC11: start_date after goal_date rejected ─────────────────────────────────

def test_ac11_start_date_after_goal_date_rejected(auth_client):
    """AC11: start_date after goal_date returns 422 referencing date range."""
    body = {
        "start_weight": 90.0,
        "goal_weight": 80.0,
        "start_date": "2026-12-01",
        "goal_date": "2026-06-01",
        "phase": "cut",
    }
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 422, r.text


# ── AC12: validation errors return 422 with structured body ──────────────────

def test_ac12_validation_error_structured(auth_client):
    """AC12: validation errors return 422 with a structured JSON error body."""
    body = {**_CUT_PLAN, "start_weight": -10.0}
    r = auth_client.post("/api/weight-plans", json=body)
    assert r.status_code == 422
    data = r.json()
    # Must be a JSON object (not raw text)
    assert isinstance(data, dict)
    # Must identify the failing field
    text = r.text
    assert "start_weight" in text


# ── AC13: cross-user access denied ───────────────────────────────────────────

def test_ac13_patch_another_users_plan_returns_403(two_auth_clients):
    """AC13: User B cannot PATCH user A's plan — 403."""
    user_a, user_b = two_auth_clients

    r = user_a.post("/api/weight-plans", json=_CUT_PLAN)
    assert r.status_code == 201
    plan_id = r.json()["id"]

    r2 = user_b.patch(f"/api/weight-plans/{plan_id}", json={"goal_weight": 75.0})
    assert r2.status_code == 403, r2.text


def test_ac13_delete_another_users_plan_returns_403(two_auth_clients):
    """AC13: User B cannot DELETE/deactivate user A's plan — 403."""
    user_a, user_b = two_auth_clients

    r = user_a.post("/api/weight-plans", json=_CUT_PLAN)
    assert r.status_code == 201
    plan_id = r.json()["id"]

    r2 = user_b.delete(f"/api/weight-plans/{plan_id}")
    assert r2.status_code == 403, r2.text
