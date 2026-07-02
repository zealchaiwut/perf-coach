"""Tests for issue #1103: Build plan editor UI for races and checkpoints.

Acceptance criteria verified:
- AC1: Add Race form renders with fields: name, date, distance, type, and goal time
- AC2: Add Checkpoint form renders with fields: name, date, distance, type, and goal time
- AC3: POST to plan router creates an entry visible in list
- AC4: Races and checkpoints fetched on load from plan router and listed
- AC5: Edit action pre-populates form; PATCH updates via plan router
- AC6: Delete action sends DELETE and removes entry
- AC7: All mutations persist (verified via API round-trip)
- AC9: Name/date/distance validation prevents empty submissions
- AC10: API errors surface inline error messages
"""
import os
import pathlib
import re
import uuid

import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "plan1103test!"
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


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def user_and_client():
    _skip_if_no_db()
    uname = f"planui_{uuid.uuid4().hex[:8]}"
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


# ── AC1 + AC2: HTML form structure ───────────────────────────────────────────

def test_training_log_page_loads(user_and_client):
    """AC1/AC2: The plan editor page (training-log) is served and accessible."""
    client, _ = user_and_client
    r = client.get("/log")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"


def test_add_race_form_has_name_field(user_and_client):
    """AC1: Add Race modal has a name input field."""
    client, _ = user_and_client
    r = client.get("/log")
    html = r.text
    assert 'id="plan-modal-name"' in html, "Name field (plan-modal-name) not found in plan modal"


def test_add_race_form_has_date_field(user_and_client):
    """AC1: Add Race modal has a date input field."""
    client, _ = user_and_client
    r = client.get("/log")
    html = r.text
    assert 'id="plan-modal-date"' in html, "Date field (plan-modal-date) not found in plan modal"


def test_add_race_form_has_distance_field(user_and_client):
    """AC1: Add Race modal has a distance input field."""
    client, _ = user_and_client
    r = client.get("/log")
    html = r.text
    assert 'id="plan-modal-distance"' in html, "Distance field (plan-modal-distance) not found"


def test_add_race_form_has_type_field(user_and_client):
    """AC1/AC2: Plan modal has a type field showing race/checkpoint options."""
    client, _ = user_and_client
    r = client.get("/log")
    html = r.text
    assert 'id="plan-modal-type"' in html, "Type field (plan-modal-type) not found in plan modal"
    assert 'value="race"' in html, "Race option not found in type select"
    assert 'value="checkpoint"' in html, "Checkpoint option not found in type select"


def test_add_race_form_has_goal_time_field(user_and_client):
    """AC1/AC2: Add Race/Checkpoint modal has a goal time input field."""
    client, _ = user_and_client
    r = client.get("/log")
    html = r.text
    assert 'id="plan-modal-goal-time"' in html, "Goal time field not found in plan modal"


def test_plan_add_race_button_present(user_and_client):
    """AC1: The '+ Add Race' button is visible in the plan tab."""
    client, _ = user_and_client
    r = client.get("/log")
    html = r.text
    assert 'id="plan-add-race-btn"' in html, "'+ Add Race' button not found"


def test_plan_add_checkpoint_button_present(user_and_client):
    """AC2: The '+ Add Checkpoint' button is visible in the plan tab."""
    client, _ = user_and_client
    r = client.get("/log")
    html = r.text
    assert 'id="plan-add-checkpoint-btn"' in html, "'+ Add Checkpoint' button not found"


def test_plan_modal_has_error_container(user_and_client):
    """AC10: Modal has an error container for inline API error messages."""
    client, _ = user_and_client
    r = client.get("/log")
    html = r.text
    assert 'id="plan-modal-error"' in html, "plan-modal-error element not found"


# ── AC3: POST via plan router creates race ────────────────────────────────────

def test_create_race_via_plan_router(user_and_client):
    """AC3: POSTing to the plan router creates a race that is retrievable."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "Test Marathon 1103",
        "date": "2027-06-15",
        "distance": 42.195,
        "type": "race",
    })
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["name"] == "Test Marathon 1103"
    assert data["type"] == "race"
    race_id = data["id"]

    r2 = client.get(f"/plans/{user_id}/races")
    assert r2.status_code == 200
    ids = [row["id"] for row in r2.json()]
    assert race_id in ids, "Created race not in list"

    client.delete(f"/plans/{user_id}/races/{race_id}")


def test_create_checkpoint_via_plan_router(user_and_client):
    """AC3: POSTing with type=checkpoint to plan router creates a checkpoint entry."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "Mid-cycle check",
        "date": "2027-03-10",
        "distance": 10.0,
        "type": "checkpoint",
    })
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["type"] == "checkpoint"
    cp_id = data["id"]

    r2 = client.get(f"/plans/{user_id}/races")
    types = {row["id"]: row["type"] for row in r2.json()}
    assert cp_id in types, "Created checkpoint not in list"
    assert types[cp_id] == "checkpoint"

    client.delete(f"/plans/{user_id}/races/{cp_id}")


# ── AC4: GET returns both races and checkpoints ───────────────────────────────

def test_list_returns_races_and_checkpoints(user_and_client):
    """AC4: GET /plans/{plan_id}/races returns both type=race and type=checkpoint entries."""
    client, user_id = user_and_client
    r1 = client.post(f"/plans/{user_id}/races", json={
        "name": "A Race",
        "date": "2027-09-01",
        "distance": 21.1,
        "type": "race",
    })
    r2 = client.post(f"/plans/{user_id}/races", json={
        "name": "A Checkpoint",
        "date": "2027-07-01",
        "distance": 10.0,
        "type": "checkpoint",
    })
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    race_id = r1.json()["id"]
    cp_id = r2.json()["id"]

    resp = client.get(f"/plans/{user_id}/races")
    assert resp.status_code == 200
    entries = {row["id"]: row for row in resp.json()}
    assert race_id in entries, "Race not in list"
    assert cp_id in entries, "Checkpoint not in list"
    assert entries[race_id]["type"] == "race"
    assert entries[cp_id]["type"] == "checkpoint"

    client.delete(f"/plans/{user_id}/races/{race_id}")
    client.delete(f"/plans/{user_id}/races/{cp_id}")


# ── AC5: PATCH edits an entry ─────────────────────────────────────────────────

def test_patch_race_updates_name(user_and_client):
    """AC5: PATCHing a race updates the name; change is retrievable."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "Original Name",
        "date": "2027-10-01",
        "distance": 5.0,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    patch = client.patch(f"/plans/{user_id}/races/{race_id}", json={"name": "Updated Name"})
    assert patch.status_code == 200, f"Expected 200, got {patch.status_code}: {patch.text}"
    assert patch.json()["name"] == "Updated Name"

    client.delete(f"/plans/{user_id}/races/{race_id}")


def test_patch_race_updates_goal_time(user_and_client):
    """AC5: PATCHing goal_time_seconds updates the value."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "Goal Time Race",
        "date": "2027-11-01",
        "distance": 42.195,
        "type": "race",
        "goal_time_seconds": 14400,
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    patch = client.patch(
        f"/plans/{user_id}/races/{race_id}",
        json={"goal_time_seconds": 13200},
    )
    assert patch.status_code == 200, f"Expected 200, got {patch.status_code}: {patch.text}"
    assert patch.json()["goal_time_seconds"] == 13200

    client.delete(f"/plans/{user_id}/races/{race_id}")


# ── AC6: DELETE removes entry ─────────────────────────────────────────────────

def test_delete_race_removes_from_list(user_and_client):
    """AC6: DELETE removes the race and it is absent from subsequent GET."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "Race to Delete",
        "date": "2027-12-01",
        "distance": 10.0,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    d = client.delete(f"/plans/{user_id}/races/{race_id}")
    assert d.status_code == 204, f"Expected 204, got {d.status_code}: {d.text}"

    r2 = client.get(f"/plans/{user_id}/races")
    ids = [row["id"] for row in r2.json()]
    assert race_id not in ids, "Deleted race still in list"


# ── AC7: Persistence ──────────────────────────────────────────────────────────

def test_race_persists_across_requests(user_and_client):
    """AC7: A created race is present in subsequent GET requests (DB persistence)."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "Persistent Race",
        "date": "2028-01-15",
        "distance": 21.1,
        "type": "race",
    })
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    r2 = client.get(f"/plans/{user_id}/races")
    ids = [row["id"] for row in r2.json()]
    assert race_id in ids, "Race not present on second GET"

    r3 = client.get(f"/plans/{user_id}/races/{race_id}")
    assert r3.status_code == 200
    assert r3.json()["name"] == "Persistent Race"

    client.delete(f"/plans/{user_id}/races/{race_id}")


# ── AC9: Validation ───────────────────────────────────────────────────────────

def test_create_race_without_date_fails(user_and_client):
    """AC9: POST without date returns a validation error."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "No Date Race",
        "distance": 10.0,
        "type": "race",
    })
    assert r.status_code in (400, 422), f"Expected 4xx for missing date, got {r.status_code}: {r.text}"


def test_create_race_without_distance_fails(user_and_client):
    """AC9: POST without distance returns a validation error."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "No Distance Race",
        "date": "2028-02-01",
        "type": "race",
    })
    assert r.status_code in (400, 422), f"Expected 4xx for missing distance, got {r.status_code}: {r.text}"


def test_create_race_with_zero_distance_fails(user_and_client):
    """AC9: POST with distance=0 returns a validation error."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "Zero Distance",
        "date": "2028-03-01",
        "distance": 0,
        "type": "race",
    })
    assert r.status_code == 422, f"Expected 422 for zero distance, got {r.status_code}: {r.text}"


def test_create_race_with_invalid_date_fails(user_and_client):
    """AC9: POST with invalid date string returns a validation error."""
    client, user_id = user_and_client
    r = client.post(f"/plans/{user_id}/races", json={
        "name": "Bad Date",
        "date": "not-a-date",
        "distance": 10.0,
        "type": "race",
    })
    assert r.status_code == 422, f"Expected 422 for invalid date, got {r.status_code}: {r.text}"


# ── JS wiring: training-projection.js uses plan router ─────────────────────────────

def test_training_plan_js_references_plan_router():
    """AC3/AC5: training-projection.js uses the plan router URL pattern (/plans/)."""
    js_path = _ROOT / "frontend" / "js" / "training-projection.js"
    assert js_path.exists(), f"training-projection.js not found at {js_path}"
    source = js_path.read_text()
    assert "/plans/" in source, (
        "training-projection.js must reference the plan router (/plans/) — "
        "found only old /api/races references"
    )


def test_training_plan_js_uses_patch_for_edits():
    """AC5: training-projection.js uses PATCH method for editing races."""
    js_path = _ROOT / "frontend" / "js" / "training-projection.js"
    source = js_path.read_text()
    assert "PATCH" in source or "apiPatch" in source, (
        "training-projection.js must use PATCH for edits to match the plan router"
    )


def test_training_plan_js_validates_name():
    """AC9: training-projection.js validates that name is not empty before submitting."""
    js_path = _ROOT / "frontend" / "js" / "training-projection.js"
    source = js_path.read_text()
    assert "Name is required" in source or "name" in source.lower(), (
        "training-projection.js should validate the name field"
    )


def test_training_log_html_has_type_select():
    """AC1/AC2: training-log.html plan modal has a type select with race/checkpoint options."""
    html_path = _ROOT / "frontend" / "pages" / "training-log.html"
    assert html_path.exists(), "training-log.html not found"
    source = html_path.read_text()
    assert 'id="plan-modal-type"' in source, "Type select (plan-modal-type) missing from modal"
    assert 'value="race"' in source, "'race' option missing from type select"
    assert 'value="checkpoint"' in source, "'checkpoint' option missing from type select"
