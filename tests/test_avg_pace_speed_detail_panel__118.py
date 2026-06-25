"""
Tests for issue #118: Show average pace/speed for distance workouts in the detail panel.
Runs against UAT environment (http://localhost:9001)
"""
import os
from datetime import date

import httpx
import pytest


BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

ALICE_USER_ID = "2898f7d7-e2f9-4125-871d-cc4fd5cb40ff"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def run_workout_with_distance(client):
    """10 km run in 3600 s → pace must be 6:00 /km."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Test Run #118",
        "workout_date": str(date.today()),
        "workout_type": "run",
        "distance_km": 10.0,
        "duration_seconds": 3600,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create run workout: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def bike_workout_with_distance(client):
    """36 km ride in 3600 s → speed must be 36.0 km/h."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Test Ride #118",
        "workout_date": str(date.today()),
        "workout_type": "bike",
        "distance_km": 36.0,
        "duration_seconds": 3600,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create bike workout: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def run_workout_no_distance(client):
    """Run with no distance_km — pace section must be hidden."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Test Run No Distance #118",
        "workout_date": str(date.today()),
        "workout_type": "run",
        "duration_seconds": 1800,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create run workout: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def run_workout_no_duration(client):
    """Run with no duration_seconds — pace section must be hidden."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Test Run No Duration #118",
        "workout_date": str(date.today()),
        "workout_type": "run",
        "distance_km": 5.0,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create run workout: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def interval_run_workout(client):
    """Run with multiple exercises representing intervals."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Test Interval Run #118",
        "workout_date": str(date.today()),
        "workout_type": "run",
        "distance_km": 4.0,
        "duration_seconds": 1200,
        "exercises": [
            {"name": "400m rep 1", "duration": "1:45"},
            {"name": "400m rep 2", "duration": "1:48"},
            {"name": "400m rep 3", "duration": "1:50"},
            {"name": "400m rep 4", "duration": "1:52"},
        ],
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create interval workout: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


# ── AC: API returns distance_km and duration_seconds in workout detail ──

def test_workout_detail_includes_distance_km(client, run_workout_with_distance):
    """GET /api/workouts/{id} must include distance_km field."""
    res = client.get(f"/api/workouts/{run_workout_with_distance}")
    assert res.status_code == 200
    data = res.json()
    assert "distance_km" in data, "Workout detail must include distance_km"
    assert data["distance_km"] == 10.0


def test_workout_detail_includes_duration_seconds(client, run_workout_with_distance):
    """GET /api/workouts/{id} must include duration_seconds field."""
    res = client.get(f"/api/workouts/{run_workout_with_distance}")
    assert res.status_code == 200
    data = res.json()
    assert "duration_seconds" in data, "Workout detail must include duration_seconds"
    assert data["duration_seconds"] == 3600


def test_workout_detail_includes_workout_type(client, run_workout_with_distance):
    """GET /api/workouts/{id} must include workout_type field."""
    res = client.get(f"/api/workouts/{run_workout_with_distance}")
    assert res.status_code == 200
    data = res.json()
    assert "workout_type" in data
    assert data["workout_type"] == "run"


# ── AC: Run with no distance returns null distance_km ──

def test_run_without_distance_has_null_distance_km(client, run_workout_no_distance):
    """Workout with no distance_km must return null in the API response."""
    res = client.get(f"/api/workouts/{run_workout_no_distance}")
    assert res.status_code == 200
    data = res.json()
    assert data.get("distance_km") is None


def test_run_without_duration_has_null_duration_seconds(client, run_workout_no_duration):
    """Workout with no duration_seconds must return null in the API response."""
    res = client.get(f"/api/workouts/{run_workout_no_duration}")
    assert res.status_code == 200
    data = res.json()
    assert data.get("duration_seconds") is None


# ── AC: Interval exercises are returned in workout detail ──

def test_interval_workout_exercises_returned(client, interval_run_workout):
    """GET /api/workouts/{id} for an interval run must return its exercises."""
    res = client.get(f"/api/workouts/{interval_run_workout}")
    assert res.status_code == 200
    data = res.json()
    exercises = data.get("exercises", [])
    assert len(exercises) == 4, f"Expected 4 exercises, got {len(exercises)}"


def test_interval_workout_exercise_fields(client, interval_run_workout):
    """Each exercise must include name and duration fields."""
    res = client.get(f"/api/workouts/{interval_run_workout}")
    assert res.status_code == 200
    data = res.json()
    for ex in data["exercises"]:
        assert "name" in ex, "Exercise must have 'name'"
        assert "duration" in ex, "Exercise must have 'duration'"


# ── AC: Pace formula verified via JS source ──

def test_training_log_js_has_fmtPaceFromSec(client):
    """training-log.js must define fmtPaceFromSec for avg pace computation."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "fmtPaceFromSec" in res.text, \
        "training-log.js must define fmtPaceFromSec for pace computation"


def test_training_log_js_has_fmtSpeedKmh(client):
    """training-log.js must define fmtSpeedKmh for avg speed computation."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "fmtSpeedKmh" in res.text, \
        "training-log.js must define fmtSpeedKmh for bike speed computation"


def test_training_log_js_pace_formula_correct(client):
    """The pace formula must divide duration_seconds by distance_km (secPerKm = durSeconds / distKm)."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    # Verify the formula: secPerKm = durSeconds / distKm
    assert "durSeconds / distKm" in res.text, \
        "fmtPaceFromSec must compute secPerKm = durSeconds / distKm"


def test_training_log_js_speed_formula_correct(client):
    """The speed formula must divide distance by (duration/3600) for km/h."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    # Verify speed formula: distKm / (durSeconds / 3600)
    assert "durSeconds / 3600" in res.text, \
        "fmtSpeedKmh must compute speed as distKm / (durSeconds / 3600)"


def test_training_log_js_pace_format_has_space_before_slash(client):
    """Pace display format must be 'M:SS /km' (with a space before /km)."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "' /km'" in res.text or "\" /km\"" in res.text, \
        "Pace format must include a space before /km (e.g. '6:00 /km')"


def test_training_log_js_speed_format_has_kmh(client):
    """Speed display format must end with ' km/h'."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "km/h" in res.text, \
        "Speed format must include 'km/h'"


# ── AC: No per-km bar charts ──

def test_training_log_js_has_no_bar_charts(client):
    """training-log.js must not render per-km bar charts."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    text = res.text.lower()
    assert "barchart" not in text and "bar-chart" not in text and "per-km" not in text, \
        "training-log.js must not contain per-km bar chart rendering"


def test_log_page_has_no_bar_chart_elements(client):
    """training-log.html must not contain bar chart canvas or per-km split elements."""
    res = client.get("/log")
    assert res.status_code == 200
    text = res.text.lower()
    assert "per-km" not in text and "split-bar" not in text, \
        "training-log.html must not contain per-km bar chart elements"


# ── AC: Pace section hidden when distance or duration absent (JS logic) ──

def test_training_log_js_hides_pace_without_both_fields(client):
    """JS must conditionally show pace/speed only when both distance_km and duration_seconds exist."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    # The guard: showPaceSpeed = (isRun || isBike) && hasDist && hasDur
    assert "hasDist" in src and "hasDur" in src, \
        "training-log.js must guard pace/speed display behind hasDist && hasDur checks"
    assert "showPaceSpeed" in src, \
        "training-log.js must use a showPaceSpeed flag to control pace display"


# ── AC: Bike workout speed display ──

def test_bike_workout_has_distance_and_duration(client, bike_workout_with_distance):
    """Bike workout fixture must return 36 km and 3600 s from the API."""
    res = client.get(f"/api/workouts/{bike_workout_with_distance}")
    assert res.status_code == 200
    data = res.json()
    assert data["workout_type"] == "bike"
    assert data["distance_km"] == 36.0
    assert data["duration_seconds"] == 3600


def test_training_log_js_handles_bike_type(client):
    """training-log.js must check isBike alongside isRun for pace/speed display."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "isBike" in res.text, \
        "training-log.js must define isBike to conditionally show avg speed for bike workouts"


# ── AC: Exercises section rendered in JS ──

def test_training_log_js_renders_exercises_section(client):
    """training-log.js must build and append an exercises section in the detail panel."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "exercises-section" in res.text, \
        "training-log.js must render a .exercises-section element for workout exercises"
    assert "exercise-item" in res.text, \
        "training-log.js must render individual .exercise-item elements"


def test_log_page_has_exercises_section_css(client):
    """training-log.html must include CSS for the exercises section."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "exercises-section" in res.text, \
        "training-log.html must include CSS for .exercises-section"
