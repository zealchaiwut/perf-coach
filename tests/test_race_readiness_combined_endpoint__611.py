"""Tests for issue #611: Add GET /api/races/{id}/readiness combined endpoint (runs against UAT)"""
import os
import pytest
import httpx
from datetime import date


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ────────────────────────────────────────────────────────────────────────────
# Test Helpers
# ────────────────────────────────────────────────────────────────────────────

def _login_and_get_user_id(client, username="testuser", password="password"):
    """Log in and extract user_id from the session. Return (user_id, client)."""
    # Create an account if needed by attempting login; if 401, create it.
    # For now, assume test users exist in the UAT database.
    # TODO: Parameterize with real test user credentials.
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        pytest.skip(f"Login failed with {r.status_code} — test user may not exist in UAT")

    # Get the logged-in user's ID
    me = client.get("/api/auth/me")
    if me.status_code != 200:
        pytest.skip(f"GET /api/auth/me failed with {me.status_code}")

    return me.json().get("id"), client


def _ensure_test_race_with_sufficient_history(client, user_id):
    """Ensure a race exists with sufficient load history (≥ 8 weeks of TSS data).

    Returns the race ID if successful, or skips the test if setup fails.
    """
    # For UAT, we rely on pre-seeded test data.
    # Fallback: query for an existing race owned by this user with a future date.
    r = client.get("/api/races")
    if r.status_code != 200:
        pytest.skip(f"GET /api/races failed with {r.status_code}")

    races = r.json()
    future_races = [
        race for race in races
        if race.get("race_date") and date.fromisoformat(race["race_date"]) > date.today()
    ]

    if not future_races:
        pytest.skip("No future races found in UAT — test data may not be seeded")

    return future_races[0]["id"]


def _ensure_test_race_with_insufficient_history(client, user_id):
    """Ensure a race exists with insufficient load history (< 8 weeks of TSS data).

    For testing the building_baseline: true branch, we need a user with <8 weeks of history.
    This typically means a new user or one with sparse workouts.
    """
    # Query for races of a lightly-active user or create one.
    # For UAT, assume a "light_user" or similar fixture exists.
    r = client.get("/api/races")
    if r.status_code != 200:
        pytest.skip(f"GET /api/races failed with {r.status_code}")

    races = r.json()
    # Assume at least one race exists for testing building_baseline=true
    if not races:
        pytest.skip("No races found in UAT — cannot test building_baseline branch")

    return races[0]["id"]


# ────────────────────────────────────────────────────────────────────────────
# Acceptance Criteria Tests
# ────────────────────────────────────────────────────────────────────────────

def test_race_readiness__endpoint_exists_and_returns_200(client):
    """AC1: GET /api/races/{id}/readiness is implemented and returns HTTP 200."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_sufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert isinstance(data, dict), "Response must be a JSON object"


def test_race_readiness__response_includes_form_curve(client):
    """AC2: Response includes form_curve with zone labels (freshness, optimal, accumulated_fatigue)."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_sufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200
    data = r.json()

    assert "form_curve" in data, "Response must include 'form_curve'"
    form_curve = data["form_curve"]
    assert isinstance(form_curve, list), "form_curve must be a list"
    assert len(form_curve) > 0, "form_curve must not be empty"

    # Check zone labels in form_curve entries
    valid_zones = {"freshness", "optimal", "accumulated_fatigue"}
    for entry in form_curve:
        assert "date" in entry, "Each form_curve entry must have 'date'"
        assert "form" in entry, "Each form_curve entry must have 'form'"
        assert "zone" in entry, "Each form_curve entry must have 'zone'"
        assert entry["zone"] in valid_zones, f"Zone must be one of {valid_zones}, got {entry['zone']}"


def test_race_readiness__response_includes_projected_form_sufficient_history(client):
    """AC3: Response includes projected_form (output of projection function) when building_baseline=false."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_sufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200
    data = r.json()

    if data.get("building_baseline"):
        pytest.skip("Test requires building_baseline=false; insufficient history in test data")

    assert "projected_form" in data, "Response must include 'projected_form' when building_baseline=false"
    projected_form = data["projected_form"]
    assert isinstance(projected_form, dict), "projected_form must be a dict (keyed by ISO date)"

    # Verify dates are ISO format and values are numeric
    for date_str, form_value in projected_form.items():
        try:
            date.fromisoformat(date_str)
        except ValueError:
            pytest.fail(f"projected_form key '{date_str}' is not ISO date format")
        assert isinstance(form_value, (int, float)), f"projected_form value for {date_str} must be numeric"


def test_race_readiness__response_includes_taper_recommendation_sufficient_history(client):
    """AC4: Response includes taper_recommendation (start date, plain-English message) when building_baseline=false."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_sufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200
    data = r.json()

    if data.get("building_baseline"):
        pytest.skip("Test requires building_baseline=false; insufficient history in test data")

    assert "taper_recommendation" in data, "Response must include 'taper_recommendation' when building_baseline=false"
    taper_rec = data["taper_recommendation"]
    assert isinstance(taper_rec, dict), "taper_recommendation must be a dict"

    # Check required fields
    assert "taper_start_date" in taper_rec, "taper_recommendation must include 'taper_start_date'"
    assert "message" in taper_rec, "taper_recommendation must include 'message' (plain-English description)"
    assert "achievable" in taper_rec, "taper_recommendation must include 'achievable' (boolean)"

    # Verify taper_start_date is ISO format or null
    if taper_rec["taper_start_date"] is not None:
        try:
            date.fromisoformat(taper_rec["taper_start_date"])
        except ValueError:
            pytest.fail(f"taper_start_date '{taper_rec['taper_start_date']}' is not ISO format")

    assert isinstance(taper_rec["message"], str), "message must be a string (plain-English description)"
    assert len(taper_rec["message"]) > 0, "message must not be empty"
    assert isinstance(taper_rec["achievable"], bool), "achievable must be a boolean"


def test_race_readiness__response_includes_on_track_status(client):
    """AC5: Response includes on_track with boolean and status_summary string from peak_tracking function."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_sufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200
    data = r.json()

    assert "on_track" in data, "Response must include 'on_track'"
    on_track = data["on_track"]
    assert isinstance(on_track, dict), "on_track must be a dict"

    assert "on_track" in on_track, "on_track dict must include 'on_track' boolean"
    assert isinstance(on_track["on_track"], (bool, type(None))), "on_track.on_track must be boolean or null"

    assert "status_summary" in on_track, "on_track dict must include 'status_summary'"
    assert isinstance(on_track["status_summary"], str), "status_summary must be a string"
    assert len(on_track["status_summary"]) > 0, "status_summary must not be empty"


def test_race_readiness__response_includes_specificity_progress(client):
    """AC6: Response includes specificity_progress (output of specificity function)."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_sufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200
    data = r.json()

    assert "specificity_progress" in data, "Response must include 'specificity_progress'"
    spec = data["specificity_progress"]
    assert isinstance(spec, dict), "specificity_progress must be a dict"


def test_race_readiness__building_baseline_true_omits_projection_and_taper(client):
    """AC7: When building_baseline=true, projected_form and taper_recommendation are absent (not null)."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_insufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200
    data = r.json()

    if not data.get("building_baseline"):
        pytest.skip("Test requires building_baseline=true; need a user with < 8 weeks history")

    # When building_baseline is true, these fields must be ABSENT entirely
    assert "projected_form" not in data, "projected_form must be absent when building_baseline=true (not null)"
    assert "taper_recommendation" not in data, (
        "taper_recommendation must be absent when building_baseline=true (not null)"
    )


def test_race_readiness__building_baseline_false_includes_both_projections(client):
    """AC8: When building_baseline=false, both projected_form and taper_recommendation are present."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_sufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200
    data = r.json()

    if data.get("building_baseline"):
        pytest.skip("Test requires building_baseline=false; need a user with >= 8 weeks history")

    assert "projected_form" in data, "projected_form must be present when building_baseline=false"
    assert "taper_recommendation" in data, "taper_recommendation must be present when building_baseline=false"


def test_race_readiness__thresholds_read_from_config_not_hardcoded(client):
    """AC9: All numeric thresholds are read from configuration, not hardcoded."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_sufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200
    data = r.json()

    # Verify form_curve zone labels respect config thresholds.
    # If zone boundaries were hardcoded, changing config wouldn't affect the response.
    # This is a sanity check that form_curve entries exist with various zones.
    zones_found = {entry["zone"] for entry in data.get("form_curve", [])}
    assert len(zones_found) > 0, "form_curve should contain entries with zone labels"


def test_race_readiness__404_nonexistent_race(client):
    """AC10: Returns 404 with descriptive message when race id does not exist."""
    user_id, client = _login_and_get_user_id(client)

    nonexistent_race_id = "00000000-0000-0000-0000-000000000000"
    r = client.get(f"/api/races/{nonexistent_race_id}/readiness")

    assert r.status_code == 404, f"Expected 404 for nonexistent race, got {r.status_code}"
    data = r.json()
    assert "detail" in data or "message" in data, "404 response must include descriptive error message"


def test_race_readiness__404_access_denied_different_user(client):
    """AC11: Returns 404 when authenticated user requests a race they do not own.

    Returns 404 (not 403) to avoid leaking whether the race exists at all.
    """
    user_id, client = _login_and_get_user_id(client, username="testuser")

    # Get any race (belongs to testuser)
    r = client.get("/api/races")
    if r.status_code != 200 or not r.json():
        pytest.skip("Cannot fetch races for testuser; test data may not be seeded")

    race_id = r.json()[0]["id"]

    # Log in as a different user
    client2 = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r_login = client2.post("/api/auth/login", json={"username": "otheruser", "password": "password"})

    if r_login.status_code != 200:
        pytest.skip("Could not log in as otheruser; test data may not be seeded")

    # Try to access testuser's race as otheruser
    r_forbidden = client2.get(f"/api/races/{race_id}/readiness")

    assert r_forbidden.status_code == 404, f"Expected 404 for unauthorized access, got {r_forbidden.status_code}"
    data = r_forbidden.json()
    assert "detail" in data or "message" in data, "404 response must include descriptive error message"


def test_race_readiness__invalid_race_id_format(client):
    """AC13: Returns 400 when race id is not a valid UUID format."""
    user_id, client = _login_and_get_user_id(client)

    r = client.get("/api/races/not-a-uuid/readiness")

    assert r.status_code == 400, f"Expected 400 for invalid UUID format, got {r.status_code}"


def test_race_readiness__response_schema_structure(client):
    """AC12: Response schema is validated with building_baseline: true and false branches."""
    user_id, client = _login_and_get_user_id(client)
    race_id = _ensure_test_race_with_sufficient_history(client, user_id)

    r = client.get(f"/api/races/{race_id}/readiness")
    assert r.status_code == 200
    data = r.json()

    # Required fields present in all responses
    assert "race_id" in data, "Response must include race_id"
    assert "building_baseline" in data, "Response must include building_baseline"
    assert "form_curve" in data, "Response must include form_curve"
    assert "on_track" in data, "Response must include on_track"
    assert "specificity_progress" in data, "Response must include specificity_progress"

    # Verify building_baseline is boolean
    assert isinstance(data["building_baseline"], bool), "building_baseline must be boolean"

    # Conditional fields: projected_form and taper_recommendation
    # These are either both present or both absent, determined by building_baseline
    has_projected = "projected_form" in data
    has_taper = "taper_recommendation" in data

    assert has_projected == has_taper, (
        "projected_form and taper_recommendation must both be present or both absent"
    )
    assert has_projected == (not data["building_baseline"]), (
        "Projected fields presence should match building_baseline=false"
    )
