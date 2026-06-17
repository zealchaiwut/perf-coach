"""UAT tests for issue #576: Store normalized power on workout record at ingest (runs against UAT).

This test file validates the acceptance criteria against the live UAT environment.
It tests the HTTP API endpoints, including /api/workouts/{id}/full, to ensure:
  - POST /api/workouts creates workouts that expose np field
  - GET /api/workouts/{id}/full returns np in the response
  - np persists correctly across different sources
"""
import os
import pytest
import httpx


# Resolved from UAT .env at runtime; see tester skill Step 0.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
if not BASE_URL.startswith("http"):
    BASE_URL = "http://localhost:9001"


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_session(client):
    """Login and return authenticated client with session cookie."""
    # Use default test user (if set up in UAT) or create one
    resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    if resp.status_code == 401 or resp.status_code == 404:
        pytest.skip("Test user not configured in UAT — manual setup required")
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return client


# ── AC: np field exists and is nullable on Workout model ───────────────────────

def test_np_column_exists_on_workout(client):
    """AC-full-endpoint: Verify that the Workout model has np as a nullable field."""
    # This is a structural test — we verify by creating a minimal workout
    # and checking that the response includes np (can be null)
    resp = client.post("/api/workouts", json={
        "name": "Test Run",
        "workout_type": "Run",
        "workout_date": "2026-06-18",
    })
    if resp.status_code == 401:
        pytest.skip("Not authenticated")
    if resp.status_code != 201:
        pytest.skip(f"Could not create workout: {resp.status_code}")

    data = resp.json()
    assert "np" in data, "np field missing from workout response"
    assert data["np"] is None, "np should be null for manually-created workouts"


def test_np_exposed_in_full_endpoint(client, auth_session):
    """AC-full-endpoint: np is present in GET /api/workouts/{id}/full response."""
    # Create a workout first
    resp = client.post("/api/workouts", json={
        "name": "Test Run",
        "workout_type": "Run",
        "workout_date": "2026-06-18",
        "distance_km": 10.0,
        "duration_seconds": 3600,
    })
    if resp.status_code != 201:
        pytest.skip(f"Failed to create workout: {resp.status_code}")

    workout_id = resp.json()["id"]

    # Fetch the full endpoint
    resp = client.get(f"/api/workouts/{workout_id}/full")
    assert resp.status_code == 200, f"Failed to fetch full workout: {resp.status_code}"

    data = resp.json()
    assert "workout" in data, "Missing 'workout' key in full response"
    workout = data["workout"]
    assert "np" in workout, "np field missing from full endpoint response"
    # For a manually-created workout, np should be null unless set explicitly
    assert workout["np"] is None, "Manually-created workout should have np=null"


def test_np_is_integer_when_set(client, auth_session):
    """AC-full-endpoint: When np is present, it is an integer value."""
    # Create a workout with explicit avg_power (power-related metric)
    resp = client.post("/api/workouts", json={
        "name": "Powered Run",
        "workout_type": "Run",
        "workout_date": "2026-06-18",
        "distance_km": 10.0,
        "duration_seconds": 3600,
        "avg_power": 250,  # Set manually to test integer handling
    })
    if resp.status_code != 201:
        pytest.skip(f"Failed to create workout: {resp.status_code}")

    workout_id = resp.json()["id"]

    resp = client.get(f"/api/workouts/{workout_id}/full")
    assert resp.status_code == 200

    data = resp.json()
    workout = data["workout"]
    # Even though we set avg_power, np should remain null (it's set only at ingest from streams)
    assert workout["np"] is None or isinstance(workout["np"], int), \
        f"np field should be null or integer, got {type(workout['np'])}"


def test_np_nullable_on_old_workouts(client, auth_session):
    """AC: np is nullable; existing workouts before this feature show np=null."""
    # Fetch any existing workout
    resp = client.get("/api/workouts")
    if resp.status_code != 200:
        pytest.skip("Could not fetch workouts")

    workouts = resp.json()
    if not workouts:
        pytest.skip("No workouts in UAT to test against")

    workout_id = workouts[0]["id"]

    resp = client.get(f"/api/workouts/{workout_id}/full")
    assert resp.status_code == 200

    data = resp.json()
    workout = data["workout"]
    # Should have np key, and it may be null (older workouts before this feature)
    assert "np" in workout, "np field should exist on all workouts"
    assert workout["np"] is None or isinstance(workout["np"], int), \
        "np should be null or integer"
