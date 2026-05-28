"""
Tests for issue #105: Add distance, duration, heart rate, and elevation to workouts
Runs against UAT environment
"""
import os
import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


def _create_workout(client, user_id, **kwargs):
    payload = {
        "user_id": user_id,
        "name": kwargs.pop("name", "Metrics Test Workout"),
        "workout_date": kwargs.pop("workout_date", "2026-05-25"),
        "workout_type": kwargs.pop("workout_type", "Running"),
        "exercises": kwargs.pop("exercises", [{"name": "Run", "duration": "30 min"}]),
    }
    payload.update(kwargs)
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    return res.json()


def _delete_workout(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── New fields absent from response when omitted ─────────────────────────────

def test_post_workout_without_new_fields_returns_null(client, alice_id):
    w = _create_workout(client, alice_id)
    try:
        assert w["distance_km"] is None
        assert w["duration_seconds"] is None
        assert w["avg_hr"] is None
        assert w["max_hr"] is None
        assert w["elevation_m"] is None
    finally:
        _delete_workout(client, w["id"])


# ── POST round-trip ───────────────────────────────────────────────────────────

def test_post_workout_with_new_fields_round_trips(client, alice_id):
    w = _create_workout(
        client, alice_id,
        distance_km=42.2,
        avg_hr=145,
        elevation_m=320,
    )
    try:
        assert w["distance_km"] == pytest.approx(42.2)
        assert w["avg_hr"] == 145
        assert w["elevation_m"] == 320
        assert w["duration_seconds"] is None
        assert w["max_hr"] is None
    finally:
        _delete_workout(client, w["id"])


def test_get_workout_returns_new_fields(client, alice_id):
    w = _create_workout(
        client, alice_id,
        distance_km=42.2,
        avg_hr=145,
        elevation_m=320,
    )
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        body = res.json()
        assert body["distance_km"] == pytest.approx(42.2)
        assert body["avg_hr"] == 145
        assert body["elevation_m"] == 320
        assert body["duration_seconds"] is None
        assert body["max_hr"] is None
    finally:
        _delete_workout(client, w["id"])


def test_list_workouts_returns_new_fields(client, alice_id):
    w = _create_workout(
        client, alice_id,
        distance_km=10.0,
        duration_seconds=3600,
        workout_date="2026-05-24",
    )
    try:
        res = client.get(
            "/api/workouts",
            params={"user_id": alice_id, "from": "2026-05-24", "to": "2026-05-24"},
        )
        assert res.status_code == 200
        match = next((x for x in res.json() if x["id"] == w["id"]), None)
        assert match is not None
        assert match["distance_km"] == pytest.approx(10.0)
        assert match["duration_seconds"] == 3600
    finally:
        _delete_workout(client, w["id"])


# ── PATCH updates new fields ──────────────────────────────────────────────────

def test_patch_workout_sets_new_fields(client, alice_id):
    w = _create_workout(client, alice_id, distance_km=42.2, avg_hr=145, elevation_m=320)
    try:
        res = client.patch(
            f"/api/workouts/{w['id']}",
            json={"duration_seconds": 7200, "max_hr": 178},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["distance_km"] == pytest.approx(42.2)
        assert body["avg_hr"] == 145
        assert body["elevation_m"] == 320
        assert body["duration_seconds"] == 7200
        assert body["max_hr"] == 178
    finally:
        _delete_workout(client, w["id"])


def test_patch_workout_clears_field_when_set_to_null(client, alice_id):
    w = _create_workout(client, alice_id, distance_km=10.0)
    try:
        res = client.patch(f"/api/workouts/{w['id']}", json={"distance_km": None})
        assert res.status_code == 200
        assert res.json()["distance_km"] is None
    finally:
        _delete_workout(client, w["id"])


def test_patch_workout_omitting_new_fields_does_not_change_them(client, alice_id):
    w = _create_workout(client, alice_id, distance_km=5.0, avg_hr=140)
    try:
        res = client.patch(f"/api/workouts/{w['id']}", json={"name": "Updated Name"})
        assert res.status_code == 200
        body = res.json()
        assert body["distance_km"] == pytest.approx(5.0)
        assert body["avg_hr"] == 140
    finally:
        _delete_workout(client, w["id"])


# ── Validation: distance_km ───────────────────────────────────────────────────

def test_post_negative_distance_km_returns_422(client, alice_id):
    payload = {
        "user_id": alice_id,
        "name": "Bad Distance",
        "workout_date": "2026-05-25",
        "workout_type": "Running",
        "exercises": [{"name": "Run"}],
        "distance_km": -1,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 422


# ── Validation: duration_seconds ─────────────────────────────────────────────

def test_post_negative_duration_seconds_returns_422(client, alice_id):
    payload = {
        "user_id": alice_id,
        "name": "Bad Duration",
        "workout_date": "2026-05-25",
        "workout_type": "Running",
        "exercises": [{"name": "Run"}],
        "duration_seconds": -10,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 422


# ── Validation: avg_hr ────────────────────────────────────────────────────────

def test_post_avg_hr_below_minimum_returns_422(client, alice_id):
    payload = {
        "user_id": alice_id,
        "name": "Bad Avg HR",
        "workout_date": "2026-05-25",
        "workout_type": "Running",
        "exercises": [{"name": "Run"}],
        "avg_hr": 15,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 422


def test_post_avg_hr_at_boundary_low_is_valid(client, alice_id):
    w = _create_workout(client, alice_id, avg_hr=20)
    try:
        assert w["avg_hr"] == 20
    finally:
        _delete_workout(client, w["id"])


def test_post_avg_hr_at_boundary_high_is_valid(client, alice_id):
    w = _create_workout(client, alice_id, avg_hr=250)
    try:
        assert w["avg_hr"] == 250
    finally:
        _delete_workout(client, w["id"])


# ── Validation: max_hr ────────────────────────────────────────────────────────

def test_post_max_hr_above_maximum_returns_422(client, alice_id):
    payload = {
        "user_id": alice_id,
        "name": "Bad Max HR",
        "workout_date": "2026-05-25",
        "workout_type": "Running",
        "exercises": [{"name": "Run"}],
        "max_hr": 260,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 422


def test_post_max_hr_at_boundary_high_is_valid(client, alice_id):
    w = _create_workout(client, alice_id, max_hr=250)
    try:
        assert w["max_hr"] == 250
    finally:
        _delete_workout(client, w["id"])
