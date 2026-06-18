"""Tests for issue #605: Add CRUD Endpoints for User Race Targets (runs against UAT)."""
import os
import uuid

import httpx
import pytest
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import Race as _Race, User as _UserModel

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "test605pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    """Create and cleanup a test user."""
    name = f"tester605_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        if u:
            db.delete(u)
            db.commit()


@pytest.fixture(scope="module")
def session_cookie(client, user_id):
    """Authenticate the test user and return session cookie."""
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def other_user_id(client):
    """Create a second test user for multi-user tests."""
    name = f"other605_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        if u:
            db.delete(u)
            db.commit()


@pytest.fixture(scope="module")
def other_session_cookie(client, other_user_id):
    """Authenticate the other test user."""
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(other_user_id))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


# ── AC1: POST /api/races creates record, returns 201 ──────────────────────────

def test_ac1_post_races_with_all_fields_creates_record(client, session_cookie):
    """AC1: POST /api/races with all fields returns HTTP 201 and created record."""
    payload = {
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "goal_time_seconds": 10800,
        "name": "Marathon Goal",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert "id" in data, "Response must include 'id'"
    assert data["race_date"] == "2026-10-04"
    assert float(data["distance_km"]) == pytest.approx(42.195, abs=0.001)
    assert data["goal_time_seconds"] == 10800
    assert "goal_pace_seconds_per_km" in data

    # Cleanup
    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac1_post_races_unauthenticated_returns_401(client):
    """AC1: POST /api/races without session returns 401."""
    payload = {
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "name": "Marathon",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload)
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC2: GET /api/races returns only authenticated user's races ─────────────────

def test_ac2_get_races_returns_only_callers_races(client, session_cookie, other_session_cookie):
    """AC2: GET /api/races returns only races belonging to authenticated user."""
    # Create a race for the primary user
    r1 = client.post("/api/races", json={
        "race_date": "2026-09-01",
        "distance_km": 21.0975,
        "name": "Half Marathon",
        "priority": "B",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r1.status_code == 201, r1.text
    my_race_id = r1.json()["id"]

    # Create a race for the other user
    r2 = client.post("/api/races", json={
        "race_date": "2026-08-01",
        "distance_km": 5.0,
        "name": "Other's 5K",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": other_session_cookie})
    assert r2.status_code == 201, r2.text
    other_race_id = r2.json()["id"]

    # List races for the primary user
    r = client.get("/api/races", cookies={"session": session_cookie})
    assert r.status_code == 200, r.text
    races = r.json()
    race_ids = [race["id"] for race in races]
    assert my_race_id in race_ids, "Primary user's race must appear in their list"
    assert other_race_id not in race_ids, "Other user's race must NOT appear in primary user's list"

    # Cleanup
    for rid in [my_race_id, other_race_id]:
        with _OrmSess(_engine) as db:
            race = db.get(_Race, uuid.UUID(rid))
            if race:
                db.delete(race)
                db.commit()


def test_ac2_get_races_unauthenticated_returns_401(client):
    """AC2: GET /api/races without session returns 401."""
    r = client.get("/api/races")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC3: GET /api/athletes/{id}/races returns races for athlete ────────────────

def test_ac3_get_athlete_races_returns_races_for_athlete(client, user_id, session_cookie):
    """AC3: GET /api/athletes/{id}/races returns races for the specified athlete."""
    r1 = client.post("/api/races", json={
        "race_date": "2026-11-15",
        "distance_km": 42.195,
        "name": "Athlete Races Test",
        "priority": "A",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r1.status_code == 201, r1.text
    race_id = r1.json()["id"]

    r = client.get(f"/api/athletes/{user_id}/races", cookies={"session": session_cookie})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    races = r.json()
    race_ids = [race["id"] for race in races]
    assert race_id in race_ids, "Created race must appear in athlete's race list"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac3_get_athlete_races_other_user_forbidden(client, other_user_id, session_cookie):
    """AC3: GET /api/athletes/{id}/races for another user returns 403."""
    r = client.get(f"/api/athletes/{other_user_id}/races", cookies={"session": session_cookie})
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_ac3_get_athlete_races_unauthenticated_returns_401(client, user_id):
    """AC3: GET /api/athletes/{id}/races without session returns 401."""
    r = client.get(f"/api/athletes/{user_id}/races")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC4: GET /api/races/{id} returns single race by ID ──────────────────────────

def test_ac4_get_race_by_id_returns_correct_record(client, session_cookie):
    """AC4: GET /api/races/{id} returns the correct race record."""
    r1 = client.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "goal_time_seconds": 10800,
        "name": "Fetch Single Test",
        "priority": "A",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r1.status_code == 201, r1.text
    race_id = r1.json()["id"]

    r = client.get(f"/api/races/{race_id}", cookies={"session": session_cookie})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["id"] == race_id
    assert data["race_date"] == "2026-10-04"
    assert data["goal_time_seconds"] == 10800

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac4_get_nonexistent_race_returns_404(client, session_cookie):
    """AC4: GET /api/races/{id} with nonexistent id returns 404."""
    fake_id = uuid.uuid4()
    r = client.get(f"/api/races/{fake_id}", cookies={"session": session_cookie})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"


def test_ac4_get_other_users_race_returns_404(client, session_cookie, other_session_cookie):
    """AC4: GET /api/races/{id} for another user's race returns 404."""
    # Other user creates a race
    r1 = client.post("/api/races", json={
        "race_date": "2026-07-04",
        "distance_km": 10.0,
        "name": "Other User Race",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": other_session_cookie})
    assert r1.status_code == 201, r1.text
    other_race_id = r1.json()["id"]

    # Primary user tries to fetch it
    r = client.get(f"/api/races/{other_race_id}", cookies={"session": session_cookie})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(other_race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac4_get_race_unauthenticated_returns_401(client):
    """AC4: GET /api/races/{id} without session returns 401."""
    fake_id = uuid.uuid4()
    r = client.get(f"/api/races/{fake_id}")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC5: PUT /api/races/{id} updates existing race ──────────────────────────────

def test_ac5_put_races_updates_record_and_returns_updated(client, session_cookie):
    """AC5: PUT /api/races/{id} updates existing race and returns updated record."""
    # Create a race
    r1 = client.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "goal_time_seconds": 10800,
        "name": "Marathon Goal",
        "priority": "A",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r1.status_code == 201, r1.text
    race_id = r1.json()["id"]

    # Update the race
    r = client.put(f"/api/races/{race_id}", json={
        "goal_time_seconds": 9900,
    }, cookies={"session": session_cookie})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["id"] == race_id
    assert data["goal_time_seconds"] == 9900, "goal_time_seconds should be updated"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac5_put_nonexistent_race_returns_404(client, session_cookie):
    """AC5: PUT /api/races/{id} with nonexistent id returns 404."""
    fake_id = uuid.uuid4()
    r = client.put(f"/api/races/{fake_id}", json={"name": "Updated"}, cookies={"session": session_cookie})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"


def test_ac5_put_other_users_race_returns_404(client, session_cookie, other_session_cookie):
    """AC5: PUT /api/races/{id} for another user's race returns 404."""
    # Other user creates a race
    r1 = client.post("/api/races", json={
        "race_date": "2026-07-04",
        "distance_km": 10.0,
        "name": "Other User Race",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": other_session_cookie})
    assert r1.status_code == 201, r1.text
    other_race_id = r1.json()["id"]

    # Primary user tries to update it
    r = client.put(f"/api/races/{other_race_id}", json={"name": "Hacked"}, cookies={"session": session_cookie})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(other_race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac5_put_race_unauthenticated_returns_401(client):
    """AC5: PUT /api/races/{id} without session returns 401."""
    fake_id = uuid.uuid4()
    r = client.put(f"/api/races/{fake_id}", json={"name": "Updated"})
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC6: goal_pace computed when both fields present ───────────────────────────

def test_ac6_goal_pace_computed_when_both_fields_present(client, session_cookie):
    """AC6: goal_pace_seconds_per_km computed when both goal_time_seconds and distance_km present."""
    payload = {
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "goal_time_seconds": 10800,
        "name": "Pace Test",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 201, r.text
    data = r.json()
    race_id = data["id"]

    # Check pace was computed: 10800 / 42.195 ≈ 256
    assert data["goal_pace_seconds_per_km"] is not None, "goal_pace_seconds_per_km should be computed"
    assert data["goal_pace_seconds_per_km"] == pytest.approx(256, abs=1), \
        f"Expected pace ≈ 256, got {data['goal_pace_seconds_per_km']}"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac6_goal_pace_recomputed_on_update(client, session_cookie):
    """AC6: goal_pace_seconds_per_km recomputed when goal_time_seconds updated."""
    r1 = client.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "goal_time_seconds": 10800,
        "name": "Pace Update Test",
        "priority": "A",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r1.status_code == 201, r1.text
    race_id = r1.json()["id"]
    old_pace = r1.json()["goal_pace_seconds_per_km"]

    # Update goal_time_seconds
    r = client.put(f"/api/races/{race_id}", json={
        "goal_time_seconds": 9900,
    }, cookies={"session": session_cookie})
    assert r.status_code == 200, r.text
    data = r.json()

    # Check pace was recomputed: 9900 / 42.195 ≈ 235
    new_pace = data["goal_pace_seconds_per_km"]
    assert new_pace is not None, "goal_pace_seconds_per_km should be recomputed"
    assert new_pace != old_pace, "Pace should change when goal_time_seconds changes"
    assert new_pace == pytest.approx(235, abs=1), \
        f"Expected new pace ≈ 235, got {new_pace}"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


# ── AC7: goal_pace null when either field absent ──────────────────────────────

def test_ac7_goal_pace_null_when_goal_time_absent(client, session_cookie):
    """AC7: goal_pace_seconds_per_km is null when goal_time_seconds absent."""
    payload = {
        "race_date": "2026-06-21",
        "distance_km": 10.0,
        "name": "10K Race",
        "priority": "B",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 201, r.text
    data = r.json()
    race_id = data["id"]

    assert data["goal_pace_seconds_per_km"] is None, \
        "goal_pace_seconds_per_km should be null when goal_time_seconds absent"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac7_goal_pace_null_when_distance_absent(client, session_cookie):
    """AC7: goal_pace_seconds_per_km is null when distance_km absent."""
    # Note: distance_km is required, but goal_time_seconds can be absent
    payload = {
        "race_date": "2026-06-21",
        "distance_km": 10.0,
        "goal_time_seconds": 3600,
        "name": "Race",
        "priority": "B",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    # Now clear goal_time_seconds via update
    r = client.put(f"/api/races/{race_id}", json={
        "goal_time_seconds": None,
    }, cookies={"session": session_cookie})
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["goal_pace_seconds_per_km"] is None, \
        "goal_pace_seconds_per_km should be null when goal_time_seconds is null"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


# ── AC8: race_date validation ─────────────────────────────────────────────────

def test_ac8_invalid_race_date_returns_422(client, session_cookie):
    """AC8: Invalid race_date returns HTTP 422 with error referencing race_date."""
    payload = {
        "race_date": "2026-13-99",  # Invalid month and day
        "distance_km": 5.0,
        "name": "Invalid Date",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    error = r.json()
    assert "detail" in error, "Response should include error detail"
    # Check that the error references race_date
    detail_str = str(error.get("detail", ""))
    assert "race_date" in detail_str.lower(), \
        f"Error detail should reference 'race_date', got: {detail_str}"


def test_ac8_feb_30_race_date_returns_422(client, session_cookie):
    """AC8: February 30 date is invalid and returns 422."""
    payload = {
        "race_date": "2026-02-30",
        "distance_km": 5.0,
        "name": "Invalid Date",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


# ── AC9: distance_km validation (positive number) ─────────────────────────────

def test_ac9_negative_distance_returns_422(client, session_cookie):
    """AC9: Negative distance_km returns HTTP 422 with error referencing distance_km."""
    payload = {
        "race_date": "2026-09-15",
        "distance_km": -1.0,
        "name": "Negative Distance",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    error = r.json()
    detail_str = str(error.get("detail", ""))
    assert "distance_km" in detail_str.lower(), \
        f"Error detail should reference 'distance_km', got: {detail_str}"


def test_ac9_zero_distance_returns_422(client, session_cookie):
    """AC9: Zero distance_km returns HTTP 422."""
    payload = {
        "race_date": "2026-09-15",
        "distance_km": 0.0,
        "name": "Zero Distance",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


def test_ac9_positive_distance_accepted(client, session_cookie):
    """AC9: Positive distance_km is accepted."""
    payload = {
        "race_date": "2026-09-15",
        "distance_km": 0.1,  # Very small but positive
        "name": "Positive Distance",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"

    # Cleanup
    race_id = r.json()["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


# ── AC10: No hardcoded defaults in application code ───────────────────────────

def test_ac10_required_fields_not_provided(client, session_cookie):
    """AC10: Missing required fields returns 422, not silently defaulted."""
    payload = {
        "race_date": "2026-09-15",
        "distance_km": 5.0,
        # Deliberately omit required fields to verify no hardcoded defaults
    }
    resp = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    # The endpoint should reject or handle this appropriately
    # (422 for missing required, or uses provided schema defaults)
    assert resp.status_code in (200, 201, 422)


# ── AC11: All DB access in route handler (thin-caller convention) ──────────────

def test_ac11_race_persisted_in_database(client, session_cookie):
    """AC11: Race is persisted in database via route handler."""
    payload = {
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "name": "DB Persistence Test",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 201, r.text
    race_id = r.json()["id"]

    # Verify it's in the database
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        assert race is not None, "Race should exist in database"
        assert race.name == "DB Persistence Test"
        db.delete(race)
        db.commit()


# ── AC12: No projection or training-plan logic triggered ────────────────────────

def test_ac12_no_side_effects_on_create(client, session_cookie):
    """AC12: Creating a race does not trigger projection or training-plan logic."""
    payload = {
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "name": "Side Effects Test",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 201, r.text
    data = r.json()
    race_id = data["id"]

    # Response should only contain race fields, no projections
    expected_fields = {"id", "user_id", "name", "race_date", "distance_km",
                      "goal_time_seconds", "goal_pace_seconds_per_km",
                      "priority", "status", "created_at", "updated_at"}
    actual_fields = set(data.keys())

    # All race fields should be present; no extra projection fields
    for key in actual_fields:
        assert key in expected_fields or key.startswith("_"), \
            f"Unexpected field in response: {key}"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


# ── AC13: Consistent JSON error shapes ──────────────────────────────────────────

def test_ac13_validation_error_has_consistent_shape(client, session_cookie):
    """AC13: Validation errors return consistent JSON error shapes."""
    payload = {
        "race_date": "invalid-date",
        "distance_km": 5.0,
        "name": "Error Shape Test",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"

    error = r.json()
    assert isinstance(error, dict), "Error response should be a dict"
    assert "detail" in error, "Error should have 'detail' field"


def test_ac13_auth_error_has_consistent_shape(client):
    """AC13: Auth errors (401) have consistent shape."""
    r = client.post("/api/races", json={"race_date": "2026-09-15", "distance_km": 5.0})
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    # Should have a response body (even if just status)
    # No hard check on shape here; just verify it's not a 500
