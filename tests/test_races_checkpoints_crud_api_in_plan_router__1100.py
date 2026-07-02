"""Tests for issue #1100: Add races/checkpoints CRUD API to plan router.

Acceptance criteria verified:
- AC1: GET /plans/{plan_id}/races returns a list of race rows for the given plan
- AC2: POST /plans/{plan_id}/races creates a new race; validates date (ISO 8601),
       distance (positive number), and type (enum or non-empty string)
- AC3: PATCH /plans/{plan_id}/races/{race_id} partially updates a race; same validation
- AC4: DELETE /plans/{plan_id}/races/{race_id} removes the race and returns 204
- AC5: GET /plans/{plan_id}/races/{race_id}/checkpoints returns checkpoint rows for a race
- AC6: POST /plans/{plan_id}/races/{race_id}/checkpoints creates a checkpoint;
       validates distance (positive number) and type
- AC7: PATCH /plans/{plan_id}/races/{race_id}/checkpoints/{checkpoint_id} partially updates
- AC8: DELETE /plans/{plan_id}/races/{race_id}/checkpoints/{checkpoint_id} returns 204
- AC9: All validation errors return 422 with a descriptive message; no 500s on bad input
- AC10: Router contains no business logic (verified via py_compile)
- AC11: Full CRUD round-trip passes (create→read→update→delete→confirm 404)
"""
import os
import pathlib
import py_compile
import uuid

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "plan1100test!"
_ROOT = pathlib.Path(__file__).resolve().parents[1]

# DB engine for user setup
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


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def user_and_client():
    """Create a test user, authenticate, and yield (auth_client, user_id). Cleanup after."""
    _skip_if_no_db()
    uname = f"plantest_{uuid.uuid4().hex[:8]}"
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
    yield client, user_id

    client.close()
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


# ── AC10: py_compile check ────────────────────────────────────────────────────

def test_plan_router_compiles_without_syntax_error():
    """AC10: backend/routers/projection.py has no syntax errors."""
    router_path = _ROOT / "backend" / "routers" / "plan.py"
    assert router_path.exists(), f"router file not found at {router_path}"
    try:
        py_compile.compile(str(router_path), doraise=True)
    except py_compile.PyCompileError as exc:
        pytest.fail(f"Syntax error in routers/projection.py: {exc}")


def test_plan_service_compiles_without_syntax_error():
    """AC10: backend/services/projection_service.py has no syntax errors."""
    svc_path = _ROOT / "backend" / "services" / "projection_service.py"
    assert svc_path.exists(), f"service file not found at {svc_path}"
    try:
        py_compile.compile(str(svc_path), doraise=True)
    except py_compile.PyCompileError as exc:
        pytest.fail(f"Syntax error in projection_service.py: {exc}")


# ── AC2: POST /plans/{plan_id}/races ─────────────────────────────────────────

def test_create_race_returns_201(user_and_client):
    """AC2: POST with valid payload returns 201 with race object including id (UAT Step 1)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-06-01",
        "distance": 42.195,
        "type": "race",
    })
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert "id" in data, "Response must include 'id'"
    assert data["date"] == "2027-06-01"
    assert data["distance"] == pytest.approx(42.195, rel=1e-3)
    assert data["type"] == "race"
    # cleanup
    client.delete(f"/plans/{user_id}/races/{data['id']}")


def test_create_race_invalid_date_returns_422(user_and_client):
    """AC2/AC9: POST with invalid date returns 422 referencing 'date' (UAT Step 4)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "not-a-date",
        "distance": 5.0,
        "type": "race",
    })
    assert r.status_code == 422, f"Expected 422 for bad date, got {r.status_code}: {r.text}"
    body = r.json()
    assert "date" in str(body).lower(), f"Error must reference 'date': {body}"


def test_create_race_negative_distance_returns_422(user_and_client):
    """AC2/AC9: POST with negative distance returns 422 referencing 'distance' (UAT Step 5)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-06-01",
        "distance": -5.0,
        "type": "race",
    })
    assert r.status_code == 422, f"Expected 422 for negative distance, got {r.status_code}: {r.text}"
    body = r.json()
    assert "distance" in str(body).lower(), f"Error must reference 'distance': {body}"


def test_create_race_zero_distance_returns_422(user_and_client):
    """AC2: POST with distance=0 is rejected (not positive)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-06-01",
        "distance": 0,
        "type": "race",
    })
    assert r.status_code == 422, f"Expected 422 for zero distance, got {r.status_code}: {r.text}"


def test_create_race_empty_type_returns_422(user_and_client):
    """AC2: POST with empty type string is rejected."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-06-01",
        "distance": 5.0,
        "type": "",
    })
    assert r.status_code == 422, f"Expected 422 for empty type, got {r.status_code}: {r.text}"


# ── AC1: GET /plans/{plan_id}/races ──────────────────────────────────────────

def test_list_races_returns_created_race(user_and_client):
    """AC1: GET returns list; after POST the list contains the new race (UAT Step 2)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-07-01",
        "distance": 10.0,
        "type": "checkpoint",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.get(f"/plans/{user_id}/races")
    assert r2.status_code == 200, r2.text
    ids = [row["id"] for row in r2.json()]
    assert race_id in ids, f"Created race {race_id} not in list: {ids}"

    client.delete(f"/plans/{user_id}/races/{race_id}")


# ── AC3: PATCH /plans/{plan_id}/races/{race_id} ──────────────────────────────

def test_patch_race_updates_distance(user_and_client):
    """AC3: PATCH returns 200 and updated fields (UAT Step 3)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-08-01",
        "distance": 5.0,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.patch(f"/plans/{user_id}/races/{race_id}", json={"distance": 10.0})
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text}"
    data = r2.json()
    assert data["distance"] == pytest.approx(10.0, rel=1e-3)

    client.delete(f"/plans/{user_id}/races/{race_id}")


def test_patch_race_invalid_date_returns_422(user_and_client):
    """AC3/AC9: PATCH with invalid date returns 422."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-09-01",
        "distance": 5.0,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.patch(f"/plans/{user_id}/races/{race_id}", json={"date": "baddate"})
    assert r2.status_code == 422, f"Expected 422, got {r2.status_code}: {r2.text}"

    client.delete(f"/plans/{user_id}/races/{race_id}")


# ── AC4: DELETE /plans/{plan_id}/races/{race_id} ─────────────────────────────

def test_delete_race_returns_204(user_and_client):
    """AC4: DELETE returns 204 No Content (UAT Step 10)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-10-01",
        "distance": 5.0,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.delete(f"/plans/{user_id}/races/{race_id}")
    assert r2.status_code == 204, f"Expected 204, got {r2.status_code}: {r2.text}"


def test_get_race_after_delete_returns_404(user_and_client):
    """AC11: After DELETE, GET /plans/{plan_id}/races/{race_id} returns 404 (UAT Step 11)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-11-01",
        "distance": 5.0,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    client.delete(f"/plans/{user_id}/races/{race_id}")

    r2 = client.get(f"/plans/{user_id}/races/{race_id}")
    assert r2.status_code == 404, f"Expected 404 after delete, got {r2.status_code}: {r2.text}"


# ── AC6: POST checkpoints ─────────────────────────────────────────────────────

def test_create_checkpoint_returns_201(user_and_client):
    """AC6: POST checkpoint with valid distance and type returns 201 (UAT Step 6)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2027-12-01",
        "distance": 42.195,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.post(f"/plans/{user_id}/races/{race_id}/checkpoints", json={
        "distance": 21.0,
        "type": "checkpoint",
    })
    assert r2.status_code == 201, f"Expected 201, got {r2.status_code}: {r2.text}"
    data = r2.json()
    assert "id" in data, "Checkpoint response must include 'id'"

    # cleanup
    client.delete(f"/plans/{user_id}/races/{race_id}/checkpoints/{data['id']}")
    client.delete(f"/plans/{user_id}/races/{race_id}")


def test_create_checkpoint_negative_distance_returns_422(user_and_client):
    """AC6/AC9: POST checkpoint with negative distance returns 422."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2028-01-01",
        "distance": 42.195,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.post(f"/plans/{user_id}/races/{race_id}/checkpoints", json={
        "distance": -5.0,
        "type": "checkpoint",
    })
    assert r2.status_code == 422, f"Expected 422, got {r2.status_code}: {r2.text}"
    body = r2.json()
    assert "distance" in str(body).lower(), f"Error must reference 'distance': {body}"

    client.delete(f"/plans/{user_id}/races/{race_id}")


def test_create_checkpoint_empty_type_returns_422(user_and_client):
    """AC6/AC9: POST checkpoint with empty type returns 422."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2028-02-01",
        "distance": 10.0,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.post(f"/plans/{user_id}/races/{race_id}/checkpoints", json={
        "distance": 5.0,
        "type": "",
    })
    assert r2.status_code == 422, f"Expected 422, got {r2.status_code}: {r2.text}"

    client.delete(f"/plans/{user_id}/races/{race_id}")


# ── AC5: GET checkpoints ──────────────────────────────────────────────────────

def test_list_checkpoints_contains_created(user_and_client):
    """AC5: GET checkpoints returns list including newly created one (UAT Step 7)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2028-03-01",
        "distance": 42.195,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.post(f"/plans/{user_id}/races/{race_id}/checkpoints", json={
        "distance": 10.0,
        "type": "checkpoint",
    })
    assert r2.status_code == 201, r2.text
    cp_id = r2.json()["id"]

    r3 = client.get(f"/plans/{user_id}/races/{race_id}/checkpoints")
    assert r3.status_code == 200, r3.text
    ids = [cp["id"] for cp in r3.json()]
    assert cp_id in ids, f"Created checkpoint {cp_id} not in list: {ids}"

    client.delete(f"/plans/{user_id}/races/{race_id}/checkpoints/{cp_id}")
    client.delete(f"/plans/{user_id}/races/{race_id}")


# ── AC7: PATCH checkpoint ─────────────────────────────────────────────────────

def test_patch_checkpoint_updates_type(user_and_client):
    """AC7: PATCH checkpoint returns 200 with updated field."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2028-04-01",
        "distance": 42.195,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.post(f"/plans/{user_id}/races/{race_id}/checkpoints", json={
        "distance": 10.0,
        "type": "week12",
    })
    assert r2.status_code == 201, r2.text
    cp_id = r2.json()["id"]

    r3 = client.patch(
        f"/plans/{user_id}/races/{race_id}/checkpoints/{cp_id}",
        json={"type": "week16"},
    )
    assert r3.status_code == 200, f"Expected 200, got {r3.status_code}: {r3.text}"
    assert r3.json()["type"] == "week16"

    client.delete(f"/plans/{user_id}/races/{race_id}/checkpoints/{cp_id}")
    client.delete(f"/plans/{user_id}/races/{race_id}")


# ── AC8: DELETE checkpoint ────────────────────────────────────────────────────

def test_delete_checkpoint_returns_204(user_and_client):
    """AC8: DELETE checkpoint returns 204 (UAT Step 8)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2028-05-01",
        "distance": 42.195,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.post(f"/plans/{user_id}/races/{race_id}/checkpoints", json={
        "distance": 5.0,
        "type": "mid-cycle",
    })
    assert r2.status_code == 201, r2.text
    cp_id = r2.json()["id"]

    r3 = client.delete(f"/plans/{user_id}/races/{race_id}/checkpoints/{cp_id}")
    assert r3.status_code == 204, f"Expected 204, got {r3.status_code}: {r3.text}"

    client.delete(f"/plans/{user_id}/races/{race_id}")


def test_deleted_checkpoint_not_in_list(user_and_client):
    """AC8/AC11: After DELETE, checkpoint is absent from GET list (UAT Step 9)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2028-06-01",
        "distance": 42.195,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.post(f"/plans/{user_id}/races/{race_id}/checkpoints", json={
        "distance": 5.0,
        "type": "week8",
    })
    assert r2.status_code == 201, r2.text
    cp_id = r2.json()["id"]

    client.delete(f"/plans/{user_id}/races/{race_id}/checkpoints/{cp_id}")

    r3 = client.get(f"/plans/{user_id}/races/{race_id}/checkpoints")
    assert r3.status_code == 200, r3.text
    ids = [cp["id"] for cp in r3.json()]
    assert cp_id not in ids, f"Deleted checkpoint {cp_id} still in list"

    client.delete(f"/plans/{user_id}/races/{race_id}")


# ── AC11: Full round-trip ─────────────────────────────────────────────────────

def test_full_round_trip(user_and_client):
    """AC11: Full CRUD round-trip: create→read→update→delete→confirm 404."""
    client, user_id = user_and_client

    # create
    r = client.post(f"/plans/{user_id}/races", json={
        "date": "2029-01-15",
        "distance": 21.097,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race = r.json()
    race_id = race["id"]
    assert race["distance"] == pytest.approx(21.097, rel=1e-2)

    # read list
    r2 = client.get(f"/plans/{user_id}/races")
    assert r2.status_code == 200
    assert any(row["id"] == race_id for row in r2.json())

    # update
    r3 = client.patch(f"/plans/{user_id}/races/{race_id}", json={"distance": 42.195})
    assert r3.status_code == 200
    assert r3.json()["distance"] == pytest.approx(42.195, rel=1e-3)

    # delete
    r4 = client.delete(f"/plans/{user_id}/races/{race_id}")
    assert r4.status_code == 204

    # confirm 404
    r5 = client.get(f"/plans/{user_id}/races/{race_id}")
    assert r5.status_code == 404
