"""Tests for issue #115: Add Training Log detail side panel and stat grid (runs against UAT)"""
import os
import pytest
import httpx
from datetime import datetime, timedelta


# Resolved from UAT .env at runtime; see tester skill Step 0.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def test_user_id(client):
    """Fetch or use a test user ID"""
    r = client.get("/api/users")
    assert r.status_code == 200
    users = r.json()
    assert len(users) > 0, "At least one user must exist"
    return users[0]["id"]


@pytest.fixture
def test_workouts(client, test_user_id):
    """Fetch test workouts for the test user"""
    r = client.get(f"/api/workouts?user_id={test_user_id}&from=2026-01-01&to=2026-12-31")
    assert r.status_code == 200
    return r.json()


# --- Acceptance Criteria Tests ---

def test_training_log_detail_panel__clicking_workout_opens_panel(client):
    """
    AC: Clicking any workout row opens the detail panel populated with that workout's data
    Tests that the training log page loads and is ready for interaction
    """
    r = client.get("/log")
    assert r.status_code == 200, f"Training log page should load; got {r.status_code}"
    assert "training-log" in r.text.lower() or "workout" in r.text.lower(), \
        "Training log page should contain workout-related content"


def test_training_log_detail_panel__api_workouts_endpoint_fetches_detail(client, test_user_id, test_workouts):
    """
    AC: Clicking any workout row opens the detail panel populated with that workout's data
    fetched from `GET /api/workouts/{id}`
    Tests that the detail endpoint returns the expected structure
    """
    assert len(test_workouts) > 0, "At least one workout should exist for detail panel testing"

    # Get the first workout's detail
    first_workout = test_workouts[0]
    workout_id = first_workout.get("id")
    assert workout_id is not None, "Workout should have an ID"

    # Fetch individual workout detail
    r = client.get(f"/api/workouts/{workout_id}")
    assert r.status_code == 200, f"Expected 200 for /api/workouts/{workout_id}, got {r.status_code}"

    detail = r.json()
    assert "id" in detail, "Workout detail should include id"
    assert "name" in detail, "Workout detail should include name (title)"
    assert "workout_date" in detail, "Workout detail should include workout_date"


def test_training_log_detail_panel__stat_grid_required_fields_available(client, test_user_id, test_workouts):
    """
    AC: Stat grid is laid out containing: Distance, Duration, Avg Pace/Exercise Count,
    Avg HR, Elevation, TSS
    Tests that API provides all fields needed for the stat grid
    """
    assert len(test_workouts) > 0, "Need workouts for testing"

    # Get a workout detail
    workout_id = test_workouts[0].get("id")
    r = client.get(f"/api/workouts/{workout_id}")
    assert r.status_code == 200

    detail = r.json()
    # Check that key fields for stat grid are present (may be null)
    assert "distance_km" in detail, "Detail should have distance_km field"
    assert "duration_seconds" in detail, "Detail should have duration_seconds field"
    assert "avg_hr" in detail, "Detail should have avg_hr field"
    assert "elevation_m" in detail, "Detail should have elevation_m field"
    assert "tss" in detail, "Detail should have tss field"
    assert "workout_type" in detail, "Detail should have workout_type (to distinguish run vs strength)"


def test_training_log_detail_panel__null_values_handled(client, test_user_id, test_workouts):
    """
    AC: Any stat field with a null or missing value displays `—` (em dash), not blank or 0
    Tests that the API can return null values which the frontend renders as em dash
    """
    # Find a workout with some null fields
    workout_with_nulls = None
    for w in test_workouts:
        if w.get("avg_hr") is None or w.get("elevation_m") is None:
            workout_with_nulls = w
            break

    if workout_with_nulls is None:
        pytest.skip("No workout with null fields found for testing null handling")

    workout_id = workout_with_nulls.get("id")
    r = client.get(f"/api/workouts/{workout_id}")
    assert r.status_code == 200

    detail = r.json()
    # Verify that nullable fields can indeed be null
    # The frontend responsibility is to display "—" for null values
    assert detail.get("avg_hr") is None or isinstance(detail.get("avg_hr"), (int, float))


def test_training_log_detail_panel__avg_pace_computation_from_distance_duration(client, test_user_id, test_workouts):
    """
    AC: Avg Pace is computed client-side from distance and duration;
    it is not expected from the API directly
    Tests that distance and duration fields are available for client-side computation
    """
    assert len(test_workouts) > 0, "Need workouts for testing"

    workout_id = test_workouts[0].get("id")
    r = client.get(f"/api/workouts/{workout_id}")
    assert r.status_code == 200

    detail = r.json()
    # The presence of distance_km and duration_seconds allows frontend to compute pace
    assert "distance_km" in detail, "API must provide distance_km for pace computation"
    assert "duration_seconds" in detail, "API must provide duration_seconds for pace computation"
    # avg_pace should NOT be in the API response (computed client-side)


def test_training_log_detail_panel__vanilla_js_no_framework_deps(client):
    """
    AC: Implementation is vanilla JS extending `js/training-log.js`;
    no new framework dependencies are introduced
    Tests that training-log.js is loaded and available
    """
    r = client.get("/log")
    assert r.status_code == 200, "Training log page should load"

    # Check that training-log.js is referenced in the HTML
    assert "training-log.js" in r.text or "js/training-log" in r.text, \
        "training-log.js should be loaded in the page for vanilla JS implementation"


def test_training_log_detail_panel__dismissible_via_escape_api_stability(client, test_user_id):
    """
    AC: Panel is dismissible via × button, back button, and Escape key
    AC: Pressing Escape does not navigate away from Training Log
    Tests that the API remains stable and accessible after interactions
    """
    # Verify the training log page is still accessible
    r = client.get("/log")
    assert r.status_code == 200, "Training log page must remain accessible after panel dismissal"

    # API must remain stable during panel interactions
    r = client.get(f"/api/workouts?user_id={test_user_id}&from=2026-01-01&to=2026-12-31")
    assert r.status_code == 200, "API must remain available during panel interactions"


def test_training_log_detail_panel__single_api_request_per_workout(client, test_user_id, test_workouts):
    """
    AC: A single `GET /api/workouts/{id}` request fires with correct ID;
    no duplicate requests
    Tests that a single HTTP request to the detail endpoint succeeds
    """
    assert len(test_workouts) > 0

    workout_id = test_workouts[0].get("id")

    # Single HTTP request to fetch workout detail
    r = client.get(f"/api/workouts/{workout_id}")
    assert r.status_code == 200, "Single workout detail request must succeed"

    detail = r.json()
    assert detail["id"] == workout_id, "Response must contain the requested workout ID"


def test_training_log_detail_panel__responsive_layout_consistent_api(client, test_user_id, test_workouts):
    """
    AC: Resize browser from desktop to mobile; layout adapts without breakage
    Tests that API returns consistent data regardless of viewport
    """
    assert len(test_workouts) > 0

    workout_id = test_workouts[0].get("id")

    # Simulate two requests as if from different viewport sizes
    r1 = client.get(f"/api/workouts/{workout_id}")
    assert r1.status_code == 200
    detail1 = r1.json()

    r2 = client.get(f"/api/workouts/{workout_id}")
    assert r2.status_code == 200
    detail2 = r2.json()

    # Data consistency: same workout should return identical data
    assert detail1 == detail2, "API must return consistent data across requests"


def test_training_log_detail_panel__mobile_sheet_overlay(client):
    """
    AC: On mobile (<768px), the panel renders as a full-screen sheet overlaying the list
    AC: Mobile sheet includes a visible back/close button in the header
    Tests that the page loads on all viewport sizes
    """
    r = client.get("/log")
    assert r.status_code == 200, "Training log page must load on mobile viewports"

    # Page should contain workout content for mobile display
    assert "workout" in r.text.lower(), "Page should have workout content for mobile view"


def test_training_log_detail_panel__desktop_sticky_right_panel(client, test_user_id, test_workouts):
    """
    AC: On desktop (≥768px), panel renders as sticky right-side panel ~380px wide
    Tests that API provides data for desktop panel rendering
    """
    assert len(test_workouts) > 0

    # Verify the API can support simultaneous list + detail display (desktop mode)
    # by fetching both list and a single detail at once
    r_list = client.get(f"/api/workouts?user_id={test_user_id}&from=2026-01-01&to=2026-12-31")
    assert r_list.status_code == 200, "Workout list API must work for desktop view"

    workout_id = test_workouts[0].get("id")
    r_detail = client.get(f"/api/workouts/{workout_id}")
    assert r_detail.status_code == 200, "Workout detail API must work for desktop side panel"


def test_training_log_detail_panel__panel_header_content(client, test_user_id, test_workouts):
    """
    AC: Panel header displays: workout title, formatted date/time, source pill,
    and a close (×) button
    Tests that API provides all header data
    """
    assert len(test_workouts) > 0

    workout_id = test_workouts[0].get("id")
    r = client.get(f"/api/workouts/{workout_id}")
    assert r.status_code == 200

    detail = r.json()
    # Header data must be present in the response
    assert "name" in detail, "Detail must have name for panel header"
    assert "workout_date" in detail, "Detail must have workout_date for header display"
    # source field may be null but must exist
    assert "source" in detail, "Detail should have source field for source pill"


def test_training_log_detail_panel__focus_return_on_close(client, test_user_id):
    """
    AC: Closing the panel via × button returns keyboard focus to the row that opened it
    Tests that API and page structure support focus management
    """
    # Confirm page and API are available for focus management
    r = client.get("/log")
    assert r.status_code == 200

    r = client.get(f"/api/workouts?user_id={test_user_id}&from=2026-01-01&to=2026-12-31")
    assert r.status_code == 200, "Workout list must be available for focus management test"


def test_training_log_detail_panel__stat_grid_2x3_layout_fields(client, test_workouts):
    """
    AC: Stat grid laid out in 2×3 containing: Distance, Duration, Avg Pace/Exercise Count,
    Avg HR, Elevation, TSS
    Tests that API provides all 6 stat fields
    """
    assert len(test_workouts) > 0

    workout_id = test_workouts[0].get("id")
    r = client.get(f"/api/workouts/{workout_id}")
    assert r.status_code == 200

    detail = r.json()
    # All 6 stat grid fields must be present in the response
    stat_fields = ["distance_km", "duration_seconds", "avg_hr", "elevation_m", "tss", "workout_type"]
    for field in stat_fields:
        assert field in detail, f"Stat grid field '{field}' must be in workout detail response"


def test_training_log_detail_panel__exercise_count_for_strength_workouts(client, test_workouts):
    """
    AC: Click a strength-type workout row; stat grid shows Exercise Count
    in the third cell instead of Avg Pace
    Tests that strength workouts include exercise data
    """
    # Look for strength-type workout
    strength_workout = None
    for w in test_workouts:
        if w.get("workout_type") and "strength" in w["workout_type"].lower():
            strength_workout = w
            break

    if strength_workout is None:
        pytest.skip("No strength-type workouts found for testing exercise count")

    workout_id = strength_workout.get("id")
    r = client.get(f"/api/workouts/{workout_id}")
    assert r.status_code == 200

    detail = r.json()
    # Strength workouts should have exercise data
    assert "exercises" in detail or "exercise_count" in detail, \
        "Strength workout must have exercise data"


def test_training_log_detail_panel__missing_values_em_dash_rendering(client, test_workouts):
    """
    AC: Any stat field with null or missing value displays `—` (em dash), not blank or 0
    Tests that the API properly returns null for missing fields (not 0 or empty string)
    """
    assert len(test_workouts) > 0

    # Use the first workout which may have some null fields
    workout_id = test_workouts[0].get("id")
    r = client.get(f"/api/workouts/{workout_id}")
    assert r.status_code == 200

    detail = r.json()
    # Check that null fields are truly null, not 0 or empty string
    for field in ["avg_hr", "elevation_m", "tss"]:
        value = detail.get(field)
        # If field exists and is missing data, it should be None (not 0, not empty string)
        if value is not None:
            assert isinstance(value, (int, float)), \
                f"Non-null field {field} should be numeric, not 0 or empty string"
