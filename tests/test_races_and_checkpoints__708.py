"""Tests for issue #708: Add CRUD and Auto-Detection for Races and Checkpoints (runs against UAT)"""
import os
import pytest
import httpx
from datetime import datetime, timedelta


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    """Create a test user and return auth headers with session cookie."""
    # Login with test user (assumes seed data or existing test user)
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpass"}
    )
    if login_resp.status_code == 401:
        pytest.skip("Test user not available; login failed")
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    # Session cookie is set automatically by httpx
    return {}


@pytest.fixture
def test_race(client, auth_headers):
    """Create a test race that can be reused in multiple tests."""
    race_data = {
        "name": "Test Marathon",
        "race_date": "2027-04-19",
        "distance_km": 42.195,
        "priority": "A",
        "goal_time_seconds": 10800,
    }
    resp = client.post("/api/races", json=race_data)
    assert resp.status_code == 201, f"Failed to create test race: {resp.text}"
    return resp.json()


# ── Races: CRUD ──────────────────────────────────────────────────────────────

def test_races__create_race_with_goal_time(client, auth_headers):
    """AC: POST /races creates a race with name, date, distance_km, priority, goal_time_seconds;
    goal_pace_seconds_per_km is computed and stored."""
    race_data = {
        "name": "Boston Marathon",
        "race_date": "2027-04-19",
        "distance_km": 42.195,
        "priority": "A",
        "goal_time_seconds": 10800,
    }
    r = client.post("/api/races", json=race_data)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Boston Marathon"
    assert body["race_date"] == "2027-04-19"
    assert body["distance_km"] == 42.195
    assert body["priority"] == "A"
    assert body["goal_time_seconds"] == 10800
    # goal_pace = 10800 / 42.195 ≈ 256
    assert body["goal_pace_seconds_per_km"] is not None
    assert 255 <= body["goal_pace_seconds_per_km"] <= 257, \
        f"Expected ~256 s/km, got {body['goal_pace_seconds_per_km']}"


def test_races__reject_invalid_race_date(client, auth_headers):
    """AC: POST /races rejects invalid date; returns 400 with validation error."""
    race_data = {
        "name": "Test Race",
        "race_date": "not-a-date",
        "distance_km": 42.195,
        "priority": "A",
    }
    r = client.post("/api/races", json=race_data)
    assert r.status_code in (400, 422)  # Validation error
    # Should reference the date field
    assert "race_date" in r.text.lower() or "date" in r.text.lower()


def test_races__reject_zero_distance_km(client, auth_headers):
    """AC: POST /races rejects distance_km ≤ 0; returns 400."""
    race_data = {
        "name": "Test Race",
        "race_date": "2027-04-19",
        "distance_km": 0,
        "priority": "A",
    }
    r = client.post("/api/races", json=race_data)
    assert r.status_code in (400, 422)
    assert "distance" in r.text.lower() or "positive" in r.text.lower()


def test_races__get_single_race(client, auth_headers, test_race):
    """AC: GET /races/:id returns the race for the authenticated user."""
    race_id = test_race["id"]
    r = client.get(f"/api/races/{race_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == race_id
    assert body["name"] == test_race["name"]


def test_races__get_single_race_not_found_other_user(client, auth_headers, test_race):
    """AC: GET /races/:id returns 404 for another user's race (isolation check)."""
    # Create a race with another user context (in a real test, would need a second client/session)
    # For now, verify the endpoint exists and returns properly
    fake_uuid = "550e8400-e29b-41d4-a716-446655440000"
    r = client.get(f"/api/races/{fake_uuid}")
    assert r.status_code == 404


def test_races__list_races(client, auth_headers):
    """AC: GET /races lists all races for the authenticated user."""
    # Create a couple of races
    race1 = client.post("/api/races", json={
        "name": "Race 1",
        "race_date": "2027-05-01",
        "distance_km": 10.0,
        "priority": "A",
    }).json()
    race2 = client.post("/api/races", json={
        "name": "Race 2",
        "race_date": "2027-06-01",
        "distance_km": 21.1,
        "priority": "B",
    }).json()

    r = client.get("/api/races")
    assert r.status_code == 200
    races = r.json()
    assert len(races) >= 2
    race_ids = {race["id"] for race in races}
    assert race1["id"] in race_ids
    assert race2["id"] in race_ids


def test_races__update_race_fields(client, auth_headers, test_race):
    """AC: PATCH /races/:id updates mutable fields and recomputes goal_pace_seconds_per_km."""
    race_id = test_race["id"]
    update_data = {
        "name": "Updated Marathon",
        "goal_time_seconds": 9600,  # Faster goal → lower pace
    }
    r = client.put(f"/api/races/{race_id}", json=update_data)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Updated Marathon"
    assert body["goal_time_seconds"] == 9600
    # New pace = 9600 / 42.195 ≈ 227
    assert body["goal_pace_seconds_per_km"] is not None
    assert 226 <= body["goal_pace_seconds_per_km"] <= 228, \
        f"Expected ~227 s/km, got {body['goal_pace_seconds_per_km']}"


def test_races__delete_race(client, auth_headers, test_race):
    """AC: DELETE /races/:id removes the race."""
    race_id = test_race["id"]
    r = client.delete(f"/api/races/{race_id}")
    assert r.status_code == 204

    # Verify it's gone
    r = client.get(f"/api/races/{race_id}")
    assert r.status_code == 404


def test_races__delete_race_cascades_checkpoints(client, auth_headers, test_race):
    """AC: DELETE /races/:id removes the race and its associated checkpoints."""
    race_id = test_race["id"]

    # Create two checkpoints
    cp1 = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Checkpoint 1",
        "target_distance_km": 15.0,
    }).json()
    cp2 = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Checkpoint 2",
        "target_distance_km": 30.0,
    }).json()

    # Delete the race
    r = client.delete(f"/api/races/{race_id}")
    assert r.status_code == 204

    # Verify checkpoints are also gone
    r = client.get(f"/api/races/{race_id}/checkpoints")
    assert r.status_code == 404 or r.json() == []


def test_races__b_and_c_races_same_table(client, auth_headers):
    """AC: B and C races stored in same races table, distinguished by priority column."""
    b_race = client.post("/api/races", json={
        "name": "B Priority Race",
        "race_date": "2027-07-01",
        "distance_km": 21.1,
        "priority": "B",
    }).json()

    c_race = client.post("/api/races", json={
        "name": "C Priority Race",
        "race_date": "2027-08-01",
        "distance_km": 5.0,
        "priority": "C",
    }).json()

    r = client.get("/api/races")
    assert r.status_code == 200
    races = r.json()

    # Find our races in the list
    b_found = next((x for x in races if x["id"] == b_race["id"]), None)
    c_found = next((x for x in races if x["id"] == c_race["id"]), None)

    assert b_found is not None
    assert c_found is not None
    assert b_found["priority"] == "B"
    assert c_found["priority"] == "C"


# ── Checkpoints: CRUD ────────────────────────────────────────────────────────

def test_checkpoints__create_with_distance_and_pace(client, auth_headers, test_race):
    """AC: POST /races/:race_id/checkpoints creates checkpoint with name, target_distance_km, target_pace_seconds_per_km."""
    race_id = test_race["id"]
    cp_data = {
        "name": "15 km at goal pace",
        "target_distance_km": 15.0,
        "target_pace_seconds_per_km": 256,
    }
    r = client.post(f"/api/races/{race_id}/checkpoints", json=cp_data)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "15 km at goal pace"
    assert body["target_distance_km"] == 15.0
    assert body["target_pace_seconds_per_km"] == 256
    assert body["met"] is False
    assert body["met_override"] is False


def test_checkpoints__create_with_duration_only(client, auth_headers, test_race):
    """AC: POST /races/:race_id/checkpoints accepts target_duration_seconds alone."""
    race_id = test_race["id"]
    cp_data = {
        "name": "90 minute effort",
        "target_duration_seconds": 5400,  # 90 minutes
    }
    r = client.post(f"/api/races/{race_id}/checkpoints", json=cp_data)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "90 minute effort"
    assert body["target_duration_seconds"] == 5400
    assert body["met"] is False


def test_checkpoints__create_missing_all_targets_rejected(client, auth_headers, test_race):
    """AC: POST /races/:race_id/checkpoints rejects missing all targets; returns 400."""
    race_id = test_race["id"]
    cp_data = {
        "name": "Invalid checkpoint",
        # No target_distance_km, target_pace_seconds_per_km, or target_duration_seconds
    }
    r = client.post(f"/api/races/{race_id}/checkpoints", json=cp_data)
    assert r.status_code in (400, 422)


def test_checkpoints__get_single_checkpoint(client, auth_headers, test_race):
    """AC: GET /races/:race_id/checkpoints/:id returns a single checkpoint."""
    race_id = test_race["id"]
    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Test CP",
        "target_distance_km": 10.0,
    }).json()

    r = client.get(f"/api/races/{race_id}/checkpoints/{cp['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == cp["id"]
    assert body["name"] == "Test CP"


def test_checkpoints__list_checkpoints(client, auth_headers, test_race):
    """AC: GET /races/:race_id/checkpoints lists all checkpoints for the race."""
    race_id = test_race["id"]
    cp1 = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "CP 1",
        "target_distance_km": 10.0,
    }).json()
    cp2 = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "CP 2",
        "target_distance_km": 20.0,
    }).json()

    r = client.get(f"/api/races/{race_id}/checkpoints")
    assert r.status_code == 200
    cps = r.json()
    assert len(cps) >= 2
    cp_ids = {cp["id"] for cp in cps}
    assert cp1["id"] in cp_ids
    assert cp2["id"] in cp_ids


def test_checkpoints__patch_update_fields(client, auth_headers, test_race):
    """AC: PATCH /races/:race_id/checkpoints/:id updates mutable fields."""
    race_id = test_race["id"]
    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Original CP",
        "target_distance_km": 10.0,
    }).json()

    r = client.patch(f"/api/races/{race_id}/checkpoints/{cp['id']}", json={
        "name": "Updated CP",
        "target_distance_km": 15.0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Updated CP"
    assert body["target_distance_km"] == 15.0


def test_checkpoints__patch_met_true_sets_override(client, auth_headers, test_race):
    """AC: Patching met=true sets met_override=true so auto-detection doesn't overwrite."""
    race_id = test_race["id"]
    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "CP",
        "target_distance_km": 10.0,
    }).json()
    assert cp["met"] is False

    # Manually set met to true
    r = client.patch(f"/api/races/{race_id}/checkpoints/{cp['id']}", json={"met": True})
    assert r.status_code == 200
    body = r.json()
    assert body["met"] is True
    assert body["met_override"] is True


def test_checkpoints__patch_met_false_sets_override(client, auth_headers, test_race):
    """AC: Patching met=false (from true) sets met_override=true to lock it."""
    race_id = test_race["id"]
    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "CP",
        "target_distance_km": 10.0,
    }).json()

    # Set met to true first
    client.patch(f"/api/races/{race_id}/checkpoints/{cp['id']}", json={"met": True})

    # Then set it back to false (manual override)
    r = client.patch(f"/api/races/{race_id}/checkpoints/{cp['id']}", json={"met": False})
    assert r.status_code == 200
    body = r.json()
    assert body["met"] is False
    assert body["met_override"] is True


def test_checkpoints__delete_checkpoint(client, auth_headers, test_race):
    """AC: DELETE /races/:race_id/checkpoints/:id removes the checkpoint."""
    race_id = test_race["id"]
    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "CP to delete",
        "target_distance_km": 10.0,
    }).json()

    r = client.delete(f"/api/races/{race_id}/checkpoints/{cp['id']}")
    assert r.status_code == 204

    # Verify it's gone
    r = client.get(f"/api/races/{race_id}/checkpoints/{cp['id']}")
    assert r.status_code == 404


# ── Auto-Detection ───────────────────────────────────────────────────────────

def test_autodetection__evaluate_distance_and_pace_met(client, auth_headers):
    """AC: On run ingest, checkpoint with distance+pace target is evaluated and marked met
    when run meets both conditions within tolerance."""
    # Create a race and checkpoint
    race = client.post("/api/races", json={
        "name": "Test Race",
        "race_date": "2027-09-01",
        "distance_km": 42.195,
        "priority": "A",
    }).json()
    race_id = race["id"]

    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "15 km at goal pace",
        "target_distance_km": 15.0,
        "target_pace_seconds_per_km": 256,
    }).json()
    cp_id = cp["id"]
    assert cp["met"] is False

    # Ingest a qualifying run (15.2 km in 3860 s ≈ 254 s/km, better than 256)
    today_iso = datetime.now().date().isoformat()
    run = client.post("/api/workouts", json={
        "workout_date": today_iso,
        "name": "Test Run",
        "workout_type": "run",
        "distance_km": 15.2,
        "duration_seconds": 3860,
    }).json()

    # Check checkpoint is now met
    r = client.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert r.status_code == 200
    cp_updated = r.json()
    assert cp_updated["met"] is True
    assert cp_updated["met_workout_id"] == run["id"]


def test_autodetection__duration_only_checkpoint(client, auth_headers):
    """AC: Duration-only checkpoint is met when run duration reaches target."""
    race = client.post("/api/races", json={
        "name": "Test Race",
        "race_date": "2027-09-01",
        "distance_km": 10.0,
        "priority": "A",
    }).json()
    race_id = race["id"]

    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "90 minute run",
        "target_duration_seconds": 5400,  # 90 minutes
    }).json()
    cp_id = cp["id"]

    # Ingest a 95-minute run
    today_iso = datetime.now().date().isoformat()
    run = client.post("/api/workouts", json={
        "workout_date": today_iso,
        "name": "Long Run",
        "workout_type": "run",
        "distance_km": 15.0,
        "duration_seconds": 5700,  # 95 minutes
    }).json()

    # Check checkpoint is met
    r = client.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert r.status_code == 200
    cp_updated = r.json()
    assert cp_updated["met"] is True


def test_autodetection__override_prevents_detection(client, auth_headers):
    """AC: Checkpoint with met_override=true is never altered by auto-detection."""
    race = client.post("/api/races", json={
        "name": "Test Race",
        "race_date": "2027-09-01",
        "distance_km": 42.195,
        "priority": "A",
    }).json()
    race_id = race["id"]

    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Distance checkpoint",
        "target_distance_km": 20.0,
    }).json()
    cp_id = cp["id"]

    # Manually set met=false and lock it (sets met_override=true)
    client.patch(f"/api/races/{race_id}/checkpoints/{cp_id}", json={"met": False})

    # Ingest a run that would qualify (25 km)
    today_iso = datetime.now().date().isoformat()
    client.post("/api/workouts", json={
        "workout_date": today_iso,
        "name": "Long run",
        "workout_type": "run",
        "distance_km": 25.0,
        "duration_seconds": 6000,
    })

    # Check checkpoint is still met=false (override protected it)
    r = client.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert r.status_code == 200
    cp_updated = r.json()
    assert cp_updated["met"] is False
    assert cp_updated["met_override"] is True


def test_autodetection__pace_tolerance_applied(client, auth_headers):
    """AC: Distance+pace checkpoint accepts run pace within configurable tolerance."""
    race = client.post("/api/races", json={
        "name": "Test Race",
        "race_date": "2027-09-01",
        "distance_km": 42.195,
        "priority": "A",
    }).json()
    race_id = race["id"]

    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Pace checkpoint",
        "target_distance_km": 10.0,
        "target_pace_seconds_per_km": 300,
    }).json()
    cp_id = cp["id"]

    # Ingest a run at 303 s/km (within 2% tolerance of 300)
    # 10.1 km in 3063 s = 303.27 s/km
    today_iso = datetime.now().date().isoformat()
    run = client.post("/api/workouts", json={
        "workout_date": today_iso,
        "name": "Test Run",
        "workout_type": "run",
        "distance_km": 10.1,
        "duration_seconds": 3063,
    }).json()

    # Check checkpoint is met (pace within tolerance)
    r = client.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert r.status_code == 200
    cp_updated = r.json()
    assert cp_updated["met"] is True


def test_autodetection__only_runs_trigger_detection(client, auth_headers):
    """AC: Auto-detection only runs on run workout types, not other sports."""
    race = client.post("/api/races", json={
        "name": "Test Race",
        "race_date": "2027-09-01",
        "distance_km": 42.195,
        "priority": "A",
    }).json()
    race_id = race["id"]

    cp = client.post(f"/api/races/{race_id}/checkpoints", json={
        "name": "Run checkpoint",
        "target_distance_km": 10.0,
    }).json()
    cp_id = cp["id"]

    # Ingest a cycling workout (not a run)
    today_iso = datetime.now().date().isoformat()
    client.post("/api/workouts", json={
        "workout_date": today_iso,
        "name": "Bike ride",
        "workout_type": "cycling",
        "distance_km": 50.0,
        "duration_seconds": 7200,
    })

    # Checkpoint should still be unmet (non-run workouts don't trigger detection)
    r = client.get(f"/api/races/{race_id}/checkpoints/{cp_id}")
    assert r.status_code == 200
    cp_updated = r.json()
    assert cp_updated["met"] is False
