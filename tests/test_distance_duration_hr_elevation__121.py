"""
Acceptance tests for issue #121: Add distance, duration, heart rate, and elevation to workouts
Runs against UAT environment
"""
import os
import httpx
import pytest
from tests._admin_helpers import admin_cookies as _admin_cookies

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
    res = client.get("/api/users", cookies=_admin_cookies())
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


def _create_workout(client, user_id, **kwargs):
    payload = {
        "user_id": user_id,
        "name": kwargs.pop("name", "Issue 121 Test Workout"),
        "workout_date": kwargs.pop("workout_date", "2026-05-29"),
        "workout_type": kwargs.pop("workout_type", "run"),
        "exercises": kwargs.pop("exercises", []),
    }
    payload.update(kwargs)
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    return res.json()


def _delete_workout(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── UAT Step 3: POST with new fields round-trips ─────────────────────────────

def test_post_workout_with_new_fields_returns_201(client, alice_id):
    payload = {
        "user_id": alice_id,
        "workout_date": "2026-05-29",
        "workout_type": "run",
        "name": "Test",
        "distance_km": 8.0,
        "duration_seconds": 2322,
        "avg_hr": 162,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201
    body = res.json()
    assert body["distance_km"] == pytest.approx(8.0)
    assert body["duration_seconds"] == 2322
    assert body["avg_hr"] == 162
    assert body["max_hr"] is None
    assert body["elevation_m"] is None
    _delete_workout(client, body["id"])


# ── UAT Step 4: GET returns saved new fields ──────────────────────────────────

def test_get_workout_returns_saved_new_fields(client, alice_id):
    w = _create_workout(client, alice_id, distance_km=8.0, duration_seconds=2322, avg_hr=162)
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        body = res.json()
        assert body["distance_km"] == pytest.approx(8.0)
        assert body["duration_seconds"] == 2322
        assert body["avg_hr"] == 162
        assert body["max_hr"] is None
        assert body["elevation_m"] is None
    finally:
        _delete_workout(client, w["id"])


# ── UAT Step 5: PATCH updates new fields without touching others ──────────────

def test_patch_updates_max_hr_and_elevation(client, alice_id):
    w = _create_workout(
        client, alice_id,
        distance_km=8.0,
        duration_seconds=2322,
        avg_hr=162,
    )
    try:
        res = client.patch(f"/api/workouts/{w['id']}", json={"max_hr": 178, "elevation_m": 95})
        assert res.status_code == 200
        body = res.json()
        assert body["max_hr"] == 178
        assert body["elevation_m"] == 95
        assert body["distance_km"] == pytest.approx(8.0)
        assert body["duration_seconds"] == 2322
        assert body["avg_hr"] == 162
    finally:
        _delete_workout(client, w["id"])


# ── UAT Step 6: distance_km < 0 returns 422 ──────────────────────────────────

def test_post_negative_distance_km_returns_422(client, alice_id):
    payload = {
        "user_id": alice_id,
        "workout_date": "2026-05-29",
        "workout_type": "run",
        "name": "Bad",
        "distance_km": -1,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 422
    assert "distance_km" in res.text


# ── UAT Step 7: avg_hr out of range returns 422 ───────────────────────────────

def test_post_avg_hr_out_of_range_returns_422(client, alice_id):
    payload = {
        "user_id": alice_id,
        "workout_date": "2026-05-29",
        "workout_type": "run",
        "name": "Bad HR",
        "avg_hr": 300,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 422
    assert "avg_hr" in res.text


def test_post_max_hr_out_of_range_returns_422(client, alice_id):
    payload = {
        "user_id": alice_id,
        "workout_date": "2026-05-29",
        "workout_type": "run",
        "name": "Bad Max HR",
        "max_hr": 300,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 422
    assert "max_hr" in res.text


# ── UAT Step 8: pre-migration workout has null new fields ─────────────────────

def test_workout_without_new_fields_returns_nulls(client, alice_id):
    w = _create_workout(client, alice_id)
    try:
        res = client.get(f"/api/workouts/{w['id']}")
        assert res.status_code == 200
        body = res.json()
        assert body["distance_km"] is None
        assert body["duration_seconds"] is None
        assert body["avg_hr"] is None
        assert body["max_hr"] is None
        assert body["elevation_m"] is None
    finally:
        _delete_workout(client, w["id"])


# ── duration_seconds validation ────────────────────────────────────────────────

def test_post_negative_duration_seconds_returns_422(client, alice_id):
    payload = {
        "user_id": alice_id,
        "workout_date": "2026-05-29",
        "workout_type": "run",
        "name": "Bad Duration",
        "duration_seconds": -10,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 422
    assert "duration_seconds" in res.text


# ── HR boundary values ─────────────────────────────────────────────────────────

def test_post_avg_hr_at_boundary_20_is_valid(client, alice_id):
    w = _create_workout(client, alice_id, avg_hr=20)
    try:
        assert w["avg_hr"] == 20
    finally:
        _delete_workout(client, w["id"])


def test_post_avg_hr_at_boundary_250_is_valid(client, alice_id):
    w = _create_workout(client, alice_id, avg_hr=250)
    try:
        assert w["avg_hr"] == 250
    finally:
        _delete_workout(client, w["id"])


def test_post_max_hr_at_boundary_250_is_valid(client, alice_id):
    w = _create_workout(client, alice_id, max_hr=250)
    try:
        assert w["max_hr"] == 250
    finally:
        _delete_workout(client, w["id"])
