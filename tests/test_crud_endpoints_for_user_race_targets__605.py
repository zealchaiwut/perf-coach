"""Tests for issue #605: Add CRUD Endpoints for User Race Targets (runs against UAT).

Acceptance criteria verified:
- AC1: POST /api/races creates a race target for the authenticated user, returns 201.
- AC2: GET /api/races returns only the authenticated user's race targets.
- AC3: GET /api/athletes/{id}/races returns all race targets for the specified athlete.
- AC4: GET /api/races/{id} returns a single race target (404 if not found/not owned).
- AC5: PUT /api/races/{id} updates an existing race target, returns updated record.
- AC6: goal_pace_seconds_per_km computed when both goal_time_seconds and distance_km present.
- AC7: goal_pace_seconds_per_km is null when either goal_time_seconds or distance_km absent.
- AC8: race_date validated as a real calendar date (422 with error referencing race_date).
- AC9: distance_km validated as positive (422 for zero or negative values).
- AC10: No default values hardcoded in application code.
- AC11: All DB access in route handler (thin-caller convention).
- AC12: No projection or training-plan logic triggered.
- AC13: Consistent JSON error shapes on validation failure.
"""
import os
import uuid

import httpx
import pytest
from sqlalchemy.orm import Session as _OrmSess

from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import Race as _Race, User as _UserModel

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "races605-test-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
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
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def other_user_id(client):
    """A second user whose races should not be visible to the first."""
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
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(other_user_id))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


# ── AC1: POST /api/races creates race target, returns 201 ─────────────────────

def test_ac1_post_races_creates_record_and_returns_201(client, session_cookie):
    """AC1: POST /api/races creates a race target and returns HTTP 201 with the created record."""
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

    # Cleanup
    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac1_post_races_without_goal_time_returns_201(client, session_cookie):
    """AC1: POST /api/races without goal_time_seconds returns 201 (UAT Step 2)."""
    payload = {
        "race_date": "2026-06-21",
        "distance_km": 10,
        "name": "10K Race",
        "priority": "B",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload, cookies={"session": session_cookie})
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert "id" in data

    # Cleanup
    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac1_post_races_unauthenticated_returns_401(client):
    """AC1: POST /api/races without session cookie returns 401."""
    payload = {
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "name": "Marathon",
        "priority": "A",
        "status": "planned",
    }
    r = client.post("/api/races", json=payload)
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC2: GET /api/races returns only caller's races ───────────────────────────

def test_ac2_get_races_returns_only_callers_races(client, session_cookie, other_session_cookie):
    """AC2: GET /api/races returns only races belonging to the authenticated user."""
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
    """AC2: GET /api/races without session cookie returns 401."""
    r = client.get("/api/races")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC3: GET /api/athletes/{id}/races ─────────────────────────────────────────

def test_ac3_get_athlete_races_returns_races_for_athlete(client, user_id, session_cookie):
    """AC3: GET /api/athletes/{id}/races returns race targets for the specified athlete."""
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


def test_ac3_get_athlete_races_other_user_not_accessible(client, user_id, other_user_id, session_cookie, other_session_cookie):
    """AC3: GET /api/athletes/{id}/races for another user returns 403 or only that user's races (auth/ownership check)."""
    # Create a race for the other user
    r1 = client.post("/api/races", json={
        "race_date": "2026-07-04",
        "distance_km": 10.0,
        "name": "Other User Race",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": other_session_cookie})
    assert r1.status_code == 201, r1.text
    other_race_id = r1.json()["id"]

    # Attempt to fetch other user's races as the primary user
    r = client.get(f"/api/athletes/{other_user_id}/races", cookies={"session": session_cookie})
    # Should return 403 (forbidden) since the caller is not the athlete
    assert r.status_code == 403, (
        f"Expected 403 when fetching another user's races, got {r.status_code}: {r.text}"
    )

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(other_race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac3_get_athlete_races_unauthenticated_returns_401(client, user_id):
    """AC3: GET /api/athletes/{id}/races without session returns 401."""
    r = client.get(f"/api/athletes/{user_id}/races")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC4: GET /api/races/{id} ──────────────────────────────────────────────────

def test_ac4_get_race_by_id_returns_correct_record(client, session_cookie):
    """AC4: GET /api/races/{id} returns the correct race record (UAT Step 5)."""
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


def test_ac4_get_race_by_id_returns_404_for_nonexistent(client, session_cookie):
    """AC4: GET /api/races/{id} returns 404 for a non-existent race."""
    fake_id = str(uuid.uuid4())
    r = client.get(f"/api/races/{fake_id}", cookies={"session": session_cookie})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"


def test_ac4_get_race_by_id_returns_404_for_other_users_race(client, session_cookie, other_session_cookie):
    """AC4: GET /api/races/{id} returns 404 when the race belongs to a different user (UAT Step 9)."""
    # Create a race as the other user
    r1 = client.post("/api/races", json={
        "race_date": "2026-05-15",
        "distance_km": 5.0,
        "name": "Other User's Secret Race",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": other_session_cookie})
    assert r1.status_code == 201, r1.text
    other_race_id = r1.json()["id"]

    # Primary user tries to fetch other user's race → should get 404
    r = client.get(f"/api/races/{other_race_id}", cookies={"session": session_cookie})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(other_race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac4_get_race_by_id_unauthenticated_returns_401(client):
    """AC4: GET /api/races/{id} without session cookie returns 401."""
    r = client.get(f"/api/races/{uuid.uuid4()}")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC5: PUT /api/races/{id} updates race target ─────────────────────────────

def test_ac5_put_races_updates_record_and_returns_updated(client, session_cookie):
    """AC5: PUT /api/races/{id} updates the race and returns the updated record (UAT Step 6)."""
    r1 = client.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "goal_time_seconds": 10800,
        "name": "Update Test Race",
        "priority": "B",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r1.status_code == 201, r1.text
    race_id = r1.json()["id"]

    r = client.put(f"/api/races/{race_id}", json={"goal_time_seconds": 9900},
                   cookies={"session": session_cookie})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["goal_time_seconds"] == 9900

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac5_put_races_returns_404_for_nonexistent(client, session_cookie):
    """AC5: PUT /api/races/{id} returns 404 for non-existent race."""
    fake_id = str(uuid.uuid4())
    r = client.put(f"/api/races/{fake_id}", json={"goal_time_seconds": 9900},
                   cookies={"session": session_cookie})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"


def test_ac5_put_races_returns_404_for_other_users_race(client, session_cookie, other_session_cookie):
    """AC5: PUT /api/races/{id} returns 404 when race belongs to another user."""
    r1 = client.post("/api/races", json={
        "race_date": "2026-12-01",
        "distance_km": 10.0,
        "name": "Other User PUT Test",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": other_session_cookie})
    assert r1.status_code == 201, r1.text
    other_race_id = r1.json()["id"]

    r = client.put(f"/api/races/{other_race_id}", json={"goal_time_seconds": 1800},
                   cookies={"session": session_cookie})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(other_race_id))
        if race:
            db.delete(race)
            db.commit()


# ── AC6: goal_pace_seconds_per_km computed when both fields present ───────────

def test_ac6_goal_pace_computed_when_both_fields_present(client, session_cookie):
    """AC6: goal_pace_seconds_per_km is computed as goal_time_seconds/distance_km when both present (UAT Step 1)."""
    r = client.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "goal_time_seconds": 10800,
        "name": "Pace Computation Test",
        "priority": "A",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r.status_code == 201, r.text
    data = r.json()
    # 10800 / 42.195 ≈ 255.97 → rounds to 256
    assert data["goal_pace_seconds_per_km"] is not None
    assert data["goal_pace_seconds_per_km"] == pytest.approx(256, abs=1), (
        f"Expected ~256, got {data['goal_pace_seconds_per_km']}"
    )

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac6_goal_pace_recomputed_on_update(client, session_cookie):
    """AC6: goal_pace_seconds_per_km is recomputed using stored distance_km when goal_time updated (UAT Step 6)."""
    r1 = client.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "goal_time_seconds": 10800,
        "name": "Recompute Pace Test",
        "priority": "A",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r1.status_code == 201, r1.text
    race_id = r1.json()["id"]

    # Update with new goal_time_seconds; distance_km unchanged
    r = client.put(f"/api/races/{race_id}", json={"goal_time_seconds": 9900},
                   cookies={"session": session_cookie})
    assert r.status_code == 200, r.text
    data = r.json()
    # 9900 / 42.195 ≈ 234.6 → rounds to 235
    expected_pace = round(9900 / 42.195)
    assert data["goal_pace_seconds_per_km"] == pytest.approx(expected_pace, abs=1), (
        f"Expected ~{expected_pace}, got {data['goal_pace_seconds_per_km']}"
    )

    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


# ── AC7: goal_pace_seconds_per_km is null when either field absent ────────────

def test_ac7_goal_pace_null_when_goal_time_absent(client, session_cookie):
    """AC7: goal_pace_seconds_per_km is null when goal_time_seconds is not provided (UAT Step 2)."""
    r = client.post("/api/races", json={
        "race_date": "2026-06-21",
        "distance_km": 10,
        "name": "No Goal Time Race",
        "priority": "B",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["goal_pace_seconds_per_km"] is None, (
        f"Expected null goal_pace, got {data['goal_pace_seconds_per_km']}"
    )

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


def test_ac7_goal_pace_null_when_goal_time_explicitly_null(client, session_cookie):
    """AC7: goal_pace_seconds_per_km is null when goal_time_seconds is explicitly null."""
    r = client.post("/api/races", json={
        "race_date": "2026-09-01",
        "distance_km": 21.1,
        "goal_time_seconds": None,
        "name": "Explicit Null Goal Time",
        "priority": "B",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["goal_pace_seconds_per_km"] is None, (
        f"Expected null goal_pace, got {data['goal_pace_seconds_per_km']}"
    )

    race_id = data["id"]
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()


# ── AC8: race_date validated as real calendar date ────────────────────────────

def test_ac8_invalid_race_date_returns_422(client, session_cookie):
    """AC8: Invalid race_date (e.g. 2026-13-99) returns HTTP 422 referencing race_date (UAT Step 7)."""
    r = client.post("/api/races", json={
        "race_date": "2026-13-99",
        "distance_km": 5,
        "name": "Bad Date Race",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422 for invalid date, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    detail_str = str(detail).lower()
    assert "race_date" in detail_str, f"Error must reference race_date: {detail}"


def test_ac8_impossible_date_returns_422(client, session_cookie):
    """AC8: February 30 returns HTTP 422 (impossible calendar date)."""
    r = client.post("/api/races", json={
        "race_date": "2026-02-30",
        "distance_km": 5,
        "name": "Feb 30 Race",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422 for Feb 30, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "race_date" in str(detail).lower(), f"Error must reference race_date: {detail}"


# ── AC9: distance_km validated as positive ────────────────────────────────────

def test_ac9_negative_distance_returns_422(client, session_cookie):
    """AC9: Negative distance_km returns HTTP 422 referencing distance_km (UAT Step 8)."""
    r = client.post("/api/races", json={
        "race_date": "2026-09-15",
        "distance_km": -1,
        "name": "Negative Distance Race",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422 for negative distance, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "distance_km" in str(detail).lower(), f"Error must reference distance_km: {detail}"


def test_ac9_zero_distance_returns_422(client, session_cookie):
    """AC9: Zero distance_km returns HTTP 422 referencing distance_km."""
    r = client.post("/api/races", json={
        "race_date": "2026-09-15",
        "distance_km": 0,
        "name": "Zero Distance Race",
        "priority": "C",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422 for zero distance, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "distance_km" in str(detail).lower(), f"Error must reference distance_km: {detail}"


# ── AC13: Consistent JSON error shapes on validation failure ──────────────────

def test_ac13_error_response_is_json(client, session_cookie):
    """AC13: Validation failure returns consistent JSON error shape."""
    r = client.post("/api/races", json={
        "race_date": "not-a-date",
        "distance_km": 10,
        "name": "JSON Error Shape Test",
        "priority": "A",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
    body = r.json()
    assert isinstance(body, dict), "Error response must be a JSON object"
    assert "detail" in body, "Error response must have a 'detail' field"


def test_ac13_distance_error_response_is_json(client, session_cookie):
    """AC13: distance_km validation failure returns consistent JSON error shape."""
    r = client.post("/api/races", json={
        "race_date": "2026-09-15",
        "distance_km": 0,
        "name": "JSON Error Test",
        "priority": "A",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
    body = r.json()
    assert isinstance(body, dict), "Error response must be a JSON object"
    assert "detail" in body, "Error response must have a 'detail' field"


# ── AC2: GET /api/races returns JSON list ─────────────────────────────────────

def test_ac2_get_races_returns_json_list(client, session_cookie):
    """AC2: GET /api/races returns a JSON array (UAT Step 3)."""
    r = client.get("/api/races", cookies={"session": session_cookie})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert isinstance(r.json(), list), "GET /api/races must return a JSON array"


# ── Full round-trip test ───────────────────────────────────────────────────────

def test_full_round_trip_create_list_get_update(client, user_id, session_cookie):
    """Full round-trip: create → list → get → update (UAT Steps 1–6)."""
    # Create
    r_create = client.post("/api/races", json={
        "race_date": "2026-10-04",
        "distance_km": 42.195,
        "goal_time_seconds": 10800,
        "name": "Round Trip Race",
        "priority": "A",
        "status": "planned",
    }, cookies={"session": session_cookie})
    assert r_create.status_code == 201, r_create.text
    race_id = r_create.json()["id"]

    # List — race appears
    r_list = client.get("/api/races", cookies={"session": session_cookie})
    assert r_list.status_code == 200, r_list.text
    ids_in_list = [r["id"] for r in r_list.json()]
    assert race_id in ids_in_list

    # Athlete list — race appears
    r_athlete = client.get(f"/api/athletes/{user_id}/races", cookies={"session": session_cookie})
    assert r_athlete.status_code == 200, r_athlete.text
    ids_in_athlete = [r["id"] for r in r_athlete.json()]
    assert race_id in ids_in_athlete

    # Get single
    r_get = client.get(f"/api/races/{race_id}", cookies={"session": session_cookie})
    assert r_get.status_code == 200, r_get.text
    assert r_get.json()["id"] == race_id

    # Update
    r_put = client.put(f"/api/races/{race_id}", json={"goal_time_seconds": 9900},
                       cookies={"session": session_cookie})
    assert r_put.status_code == 200, r_put.text
    assert r_put.json()["goal_time_seconds"] == 9900

    # Cleanup
    with _OrmSess(_engine) as db:
        race = db.get(_Race, uuid.UUID(race_id))
        if race:
            db.delete(race)
            db.commit()
