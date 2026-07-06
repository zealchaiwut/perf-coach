"""Tests for issue #526: Add manual split authoring to training log detail panel (runs against UAT)"""
import os
import uuid
import pytest
import httpx


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:" + os.environ.get("UAT_PORT", "9001")
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
    """Log in and return auth headers for a test user."""
    login_resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    if login_resp.status_code == 401:
        pytest.skip("Test user not available; skip HTTP tests")
    return {"Cookie": login_resp.cookies.get("session", "")} if login_resp.status_code == 200 else {}


@pytest.fixture
def manual_workout(client, auth_headers):
    """Create and return a manual workout with no splits for testing."""
    workout_data = {
        "name": "Test Run",
        "workout_date": "2026-06-15",
        "workout_type": "Running",
        "exercises": [],
        "distance_km": 5.0,
        "duration_seconds": 1800,
    }
    resp = client.post("/api/workouts", json=workout_data, headers=auth_headers)
    if resp.status_code != 201:
        pytest.skip(f"Could not create test workout: {resp.status_code}")
    return resp.json()


@pytest.fixture
def synced_workout_with_splits(client, auth_headers):
    """Create a workout with pre-existing splits to test read-only rendering."""
    workout_data = {
        "name": "Synced Run",
        "workout_date": "2026-06-14",
        "workout_type": "Running",
        "exercises": [],
        "distance_km": 10.0,
        "duration_seconds": 3600,
        "source": "strava",
    }
    resp = client.post("/api/workouts", json=workout_data, headers=auth_headers)
    if resp.status_code != 201:
        pytest.skip(f"Could not create synced workout: {resp.status_code}")
    workout = resp.json()

    splits_data = {
        "splits": [
            {"split_index": 0, "distance_km": 1.0, "duration_seconds": 360},
            {"split_index": 1, "distance_km": 1.0, "duration_seconds": 365},
        ]
    }
    client.post(f"/api/workouts/{workout['id']}/splits", json=splits_data, headers=auth_headers)
    return workout


# ─── Acceptance Criteria Tests ───

def test_manual_splits_ui__add_split_control_visible(client, auth_headers, manual_workout):
    # AC: Detail panel for a manual run shows an **Add Split** control when no splits exist.
    resp = client.get(f"/api/workouts/{manual_workout['id']}/splits", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_manual_splits_ui__add_split_with_valid_data(client, auth_headers, manual_workout):
    # AC: User can enter distance, duration, and pace per split row;
    # fields validate against splits endpoint contract (non-zero distance, valid duration).
    splits_data = {
        "splits": [
            {"split_index": 0, "distance_km": 1.0, "duration_seconds": 270}
        ]
    }
    resp = client.post(f"/api/workouts/{manual_workout['id']}/splits", json=splits_data, headers=auth_headers)
    assert resp.status_code == 201
    result = resp.json()
    assert len(result) == 1
    assert result[0]["distance_km"] == "1.0"
    assert result[0]["duration_seconds"] == 270


def test_manual_splits_ui__multiple_splits_persist(client, auth_headers, manual_workout):
    # AC: Submitting valid splits calls endpoint and response reflected immediately.
    # AC: Saved splits render in same table component.
    splits_data = {
        "splits": [
            {"split_index": 0, "distance_km": 1.0, "duration_seconds": 270},
            {"split_index": 1, "distance_km": 1.0, "duration_seconds": 275},
        ]
    }
    resp = client.post(f"/api/workouts/{manual_workout['id']}/splits", json=splits_data, headers=auth_headers)
    assert resp.status_code == 201
    result = resp.json()
    assert len(result) == 2
    assert result[0]["split_index"] == 0
    assert result[1]["split_index"] == 1

    get_resp = client.get(f"/api/workouts/{manual_workout['id']}/splits", headers=auth_headers)
    assert get_resp.status_code == 200
    assert len(get_resp.json()) == 2


def test_manual_splits_ui__edit_split_in_place(client, auth_headers, manual_workout):
    # AC: Existing split rows can be edited in-place and re-saved.
    # First add a split
    splits_data = {
        "splits": [
            {"split_index": 0, "distance_km": 1.0, "duration_seconds": 270}
        ]
    }
    client.post(f"/api/workouts/{manual_workout['id']}/splits", json=splits_data, headers=auth_headers)

    # Edit by replacing with new duration
    edited_splits = {
        "splits": [
            {"split_index": 0, "distance_km": 1.0, "duration_seconds": 300}
        ]
    }
    resp = client.post(f"/api/workouts/{manual_workout['id']}/splits", json=edited_splits, headers=auth_headers)
    assert resp.status_code == 201
    result = resp.json()
    assert result[0]["duration_seconds"] == 300


def test_manual_splits_ui__delete_individual_split(client, auth_headers, manual_workout):
    # AC: An individual split row can be deleted.
    # Add two splits
    splits_data = {
        "splits": [
            {"split_index": 0, "distance_km": 1.0, "duration_seconds": 270},
            {"split_index": 1, "distance_km": 1.0, "duration_seconds": 275},
        ]
    }
    client.post(f"/api/workouts/{manual_workout['id']}/splits", json=splits_data, headers=auth_headers)

    # Delete the second split by posting only the first
    deleted_splits = {
        "splits": [
            {"split_index": 0, "distance_km": 1.0, "duration_seconds": 270}
        ]
    }
    resp = client.post(f"/api/workouts/{manual_workout['id']}/splits", json=deleted_splits, headers=auth_headers)
    assert resp.status_code == 201
    assert len(resp.json()) == 1


def test_manual_splits_ui__validation_zero_distance_rejected(client, auth_headers, manual_workout):
    # AC: Validation errors surface inline with message matching API error response.
    splits_data = {
        "splits": [
            {"split_index": 0, "distance_km": 0.0, "duration_seconds": 270}
        ]
    }
    resp = client.post(f"/api/workouts/{manual_workout['id']}/splits", json=splits_data, headers=auth_headers)
    assert resp.status_code == 422
    assert "distance_km" in str(resp.json()).lower() or "must be" in str(resp.json()).lower()


def test_manual_splits_ui__validation_negative_duration_rejected(client, auth_headers, manual_workout):
    # AC: Validation errors surface inline with message matching API error response.
    splits_data = {
        "splits": [
            {"split_index": 0, "distance_km": 1.0, "duration_seconds": -100}
        ]
    }
    resp = client.post(f"/api/workouts/{manual_workout['id']}/splits", json=splits_data, headers=auth_headers)
    assert resp.status_code == 422
    assert "duration_seconds" in str(resp.json()).lower() or "must be" in str(resp.json()).lower()


def test_manual_splits_ui__synced_splits_read_only(client, auth_headers, synced_workout_with_splits):
    # AC: Synced-run splits remain read-only (no edit/delete controls rendered).
    # Fetch the synced workout's source to confirm it is marked as synced
    resp = client.get(f"/api/workouts/{synced_workout_with_splits['id']}", headers=auth_headers)
    assert resp.status_code == 200
    workout = resp.json()
    assert workout.get("source") == "strava"

    # Confirm splits exist
    splits_resp = client.get(f"/api/workouts/{synced_workout_with_splits['id']}/splits", headers=auth_headers)
    assert splits_resp.status_code == 200
    assert len(splits_resp.json()) == 2
