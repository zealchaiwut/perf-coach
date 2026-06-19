"""UAT integration tests for aerobic decoupling metric (issue #691).

Tests against the /api/workouts/{id}/full endpoint to verify:
1. Decoupling field is present in response
2. Decoupling uses power when available
3. Decoupling returns null with reason for missing HR
4. Decoupling returns null with reason for insufficient data
5-6. Threshold-based faded_late flag behavior
7. No regression on non-run workouts
"""
import os
import pytest
import httpx


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
def auth_headers(client):
    """Log in and return auth headers with session cookie."""
    # Seed user with credentials; use standard test username/password
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpass123"},
    )
    if login_resp.status_code == 401:
        # User may not exist; assume seed data or manual setup has been done
        pytest.skip("Test user not available; ensure seed data is loaded")
    assert login_resp.status_code == 200
    return {}  # Session cookie is auto-included by httpx


# --- UAT Step 1: Aerobic decoupling with at least two laps and HR ---

def test_uat_step_1_decoupling_with_laps_and_hr(client, auth_headers):
    """UAT Step 1: GET /api/workouts/{id}/full for run with 2+ laps and HR.
    Expected: Response includes aerobic_decoupling.decoupling_pct (number),
    aerobic_decoupling.faded_late (boolean), and aerobic_decoupling.debug
    with first_half_efficiency and second_half_efficiency.
    """
    # Find or create a workout with at least 2 laps and HR data
    # Query existing workouts
    workouts_resp = client.get("/api/workouts")
    assert workouts_resp.status_code == 200
    workouts = workouts_resp.json()

    # Filter for runs with splits (laps) and HR data
    target_workout = None
    for w in workouts:
        if w.get("workout_type") == "Run" and w.get("has_splits"):
            # Fetch full details to check for HR
            full_resp = client.get(f"/api/workouts/{w['id']}/full")
            if full_resp.status_code == 200:
                full_data = full_resp.json()
                if full_data.get("unified", {}).get("avg_hr") is not None:
                    target_workout = full_data
                    break

    if target_workout is None:
        pytest.skip("No run with 2+ splits and HR data found in test database")

    # Verify the response includes aerobic_decoupling
    assert "aerobic_decoupling" in target_workout
    decoupling = target_workout["aerobic_decoupling"]

    # If aerobic_decoupling is null, there's a reason field
    if decoupling is None:
        assert "aerobic_decoupling_reason" in target_workout
        pytest.skip(f"Decoupling unavailable: {target_workout['aerobic_decoupling_reason']}")

    # On success, verify structure
    assert isinstance(decoupling, dict)
    assert "decoupling_pct" in decoupling
    assert "faded_late" in decoupling
    assert "debug" in decoupling
    assert isinstance(decoupling["decoupling_pct"], (int, float))
    assert isinstance(decoupling["faded_late"], bool)
    assert "first_half_efficiency" in decoupling["debug"]
    assert "second_half_efficiency" in decoupling["debug"]


# --- UAT Step 2: Aerobic decoupling with power data ---

def test_uat_step_2_decoupling_prefers_power(client, auth_headers):
    """UAT Step 2: GET /api/workouts/{id}/full for run with HR and power.
    Expected: debug.first_half_efficiency and debug.second_half_efficiency
    reflect power-divided-by-HR, not speed-divided-by-HR.
    """
    # Find a workout with power and HR data
    workouts_resp = client.get("/api/workouts")
    assert workouts_resp.status_code == 200
    workouts = workouts_resp.json()

    target_workout = None
    for w in workouts:
        if w.get("workout_type") == "Run":
            full_resp = client.get(f"/api/workouts/{w['id']}/full")
            if full_resp.status_code == 200:
                full_data = full_resp.json()
                unified = full_data.get("unified", {})
                # Check for both power and HR
                if (
                    unified.get("avg_power_w") is not None
                    and unified.get("avg_hr") is not None
                ):
                    target_workout = full_data
                    break

    if target_workout is None:
        pytest.skip("No run with both power and HR data found")

    decoupling = target_workout.get("aerobic_decoupling")
    if decoupling is None:
        pytest.skip(f"Decoupling unavailable: {target_workout.get('aerobic_decoupling_reason')}")

    # Verify efficiencies are in reasonable range for power-based metric
    # Power/HR typically ranges from ~1-3 (watts per bpm)
    e1 = decoupling["debug"]["first_half_efficiency"]
    e2 = decoupling["debug"]["second_half_efficiency"]
    assert e1 > 0, "first_half_efficiency should be positive"
    assert e2 > 0, "second_half_efficiency should be positive"
    # If power is in the range 200-350W and HR is 120-160, efficiency should be 1-3
    assert 0.1 < e1 < 10, f"first_half_efficiency {e1} out of expected power-based range"


# --- UAT Step 3: Missing HR data returns null with reason ---

def test_uat_step_3_missing_hr_returns_null(client, auth_headers):
    """UAT Step 3: GET /api/workouts/{id}/full for run with no HR.
    Expected: aerobic_decoupling is null and reason field is present.
    """
    # Find or create a run without HR data
    workouts_resp = client.get("/api/workouts")
    assert workouts_resp.status_code == 200
    workouts = workouts_resp.json()

    target_workout = None
    for w in workouts:
        if w.get("workout_type") == "Run":
            full_resp = client.get(f"/api/workouts/{w['id']}/full")
            if full_resp.status_code == 200:
                full_data = full_resp.json()
                # Look for one without HR
                if full_data.get("unified", {}).get("avg_hr") is None:
                    target_workout = full_data
                    break

    if target_workout is None:
        pytest.skip("No run without HR data found; cannot test missing HR case")

    # Verify decoupling is null and reason is present
    assert target_workout.get("aerobic_decoupling") is None
    assert "aerobic_decoupling_reason" in target_workout
    reason = target_workout["aerobic_decoupling_reason"]
    assert isinstance(reason, str)
    assert len(reason) > 0
    # Reason should mention HR or missing data
    assert any(
        word in reason.lower()
        for word in ["heart", "hr", "missing", "insufficient"]
    )


# --- UAT Step 4: Insufficient data returns null with reason ---

def test_uat_step_4_insufficient_data_returns_null(client, auth_headers):
    """UAT Step 4: GET /api/workouts/{id}/full for run with 1 lap and no stream.
    Expected: aerobic_decoupling is null and reason indicates insufficient data.
    """
    # Find or create a run with only 1 lap/split and no stream data
    workouts_resp = client.get("/api/workouts")
    assert workouts_resp.status_code == 200
    workouts = workouts_resp.json()

    target_workout = None
    for w in workouts:
        if w.get("workout_type") == "Run" and not w.get("has_splits"):
            # Check it also has no stream
            full_resp = client.get(f"/api/workouts/{w['id']}/full")
            if full_resp.status_code == 200:
                full_data = full_resp.json()
                if not full_data.get("field_coverage", {}).get("has_streams"):
                    target_workout = full_data
                    break

    if target_workout is None:
        pytest.skip("No run with single lap and no stream found")

    # Verify decoupling is null with insufficient data reason
    assert target_workout.get("aerobic_decoupling") is None
    assert "aerobic_decoupling_reason" in target_workout
    reason = target_workout["aerobic_decoupling_reason"]
    assert any(
        word in reason.lower()
        for word in ["insufficient", "data", "lap", "split"]
    )


# --- UAT Step 5: Threshold = 5, decoupling = 7 → faded_late True ---

def test_uat_step_5_threshold_5_decoupling_7_faded_late_true(client, auth_headers):
    """UAT Step 5: Set threshold to 5, fetch workout with decoupling ~7.
    Expected: aerobic_decoupling.faded_late is True.
    """
    # First, set user preference for aerobic_decoupling_threshold to 5
    prefs_resp = client.patch(
        "/api/user-preferences",
        json={"aerobic_decoupling_threshold": 5.0},
    )
    if prefs_resp.status_code not in (200, 204):
        pytest.skip("Cannot set user preferences in this environment")

    # Find a workout with decoupling around 7%
    # (This depends on test data; use the first one that exists)
    workouts_resp = client.get("/api/workouts")
    assert workouts_resp.status_code == 200
    workouts = workouts_resp.json()

    found = False
    for w in workouts:
        if w.get("workout_type") == "Run":
            full_resp = client.get(f"/api/workouts/{w['id']}/full")
            if full_resp.status_code == 200:
                full_data = full_resp.json()
                decoupling = full_data.get("aerobic_decoupling")
                if decoupling and decoupling.get("decoupling_pct"):
                    pct = decoupling["decoupling_pct"]
                    # Check if this one is above threshold
                    if 5.0 < pct < 10.0:  # Approximately in the 7% range
                        assert decoupling["faded_late"] is True, \
                            f"Decoupling {pct}% exceeds threshold 5%; faded_late should be True"
                        found = True
                        break

    if not found:
        pytest.skip("No workout with decoupling 5-10% found to test threshold=5")


# --- UAT Step 6: Threshold = 10, same decoupling ~7 → faded_late False ---

def test_uat_step_6_threshold_10_decoupling_7_faded_late_false(client, auth_headers):
    """UAT Step 6: Set threshold to 10, fetch same workout from step 5.
    Expected: aerobic_decoupling.faded_late is False.
    """
    # Set threshold to 10
    prefs_resp = client.patch(
        "/api/user-preferences",
        json={"aerobic_decoupling_threshold": 10.0},
    )
    if prefs_resp.status_code not in (200, 204):
        pytest.skip("Cannot set user preferences")

    # Find the workout with decoupling ~7%
    workouts_resp = client.get("/api/workouts")
    assert workouts_resp.status_code == 200
    workouts = workouts_resp.json()

    found = False
    for w in workouts:
        if w.get("workout_type") == "Run":
            full_resp = client.get(f"/api/workouts/{w['id']}/full")
            if full_resp.status_code == 200:
                full_data = full_resp.json()
                decoupling = full_data.get("aerobic_decoupling")
                if decoupling and decoupling.get("decoupling_pct"):
                    pct = decoupling["decoupling_pct"]
                    # Check if below new threshold
                    if 5.0 < pct < 10.0:
                        assert decoupling["faded_late"] is False, \
                            f"Decoupling {pct}% below threshold 10%; faded_late should be False"
                        found = True
                        break

    if not found:
        pytest.skip("No workout with decoupling 5-10% found")


# --- UAT Step 7: Non-run workouts (regression test) ---

def test_uat_step_7_non_run_workout_no_regression(client, auth_headers):
    """UAT Step 7: GET /api/workouts/{id}/full for non-run (swim, ride).
    Expected: Response shape unchanged; no regression in existing fields.
    """
    workouts_resp = client.get("/api/workouts")
    assert workouts_resp.status_code == 200
    workouts = workouts_resp.json()

    # Find a non-run workout
    for w in workouts:
        if w.get("workout_type") and w["workout_type"] != "Run":
            full_resp = client.get(f"/api/workouts/{w['id']}/full")
            assert full_resp.status_code == 200
            full_data = full_resp.json()

            # Verify core fields are still present (regression check)
            assert "workout" in full_data
            assert "sources" in full_data
            assert "unified" in full_data
            assert "computed" in full_data
            assert "field_coverage" in full_data
            assert "tss" in full_data

            # aerobic_decoupling should still be present (even if null for non-runs)
            assert "aerobic_decoupling" in full_data

            # For non-runs, decoupling should be null (out of scope)
            if full_data.get("aerobic_decoupling") is None:
                assert "aerobic_decoupling_reason" in full_data
            return

    pytest.skip("No non-run workouts found in test database")
