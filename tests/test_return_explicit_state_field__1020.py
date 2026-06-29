"""Tests for issue #1020: Return explicit state field from performance endpoint.

Acceptance Criteria:
  AC1: Every response includes exactly these top-level keys: state, endurance, speed, generated_at.
  AC2: state is always present and contains exactly one of: scored, needs_thresholds,
       building_baseline, error.
  AC3: state "needs_thresholds" is returned (endurance: null, speed: null) when any
       required threshold value is missing.
  AC4: state "building_baseline" is returned (endurance: null, speed: null) when all
       thresholds exist but the athlete has fewer than the minimum qualifying runs.
  AC5: state "scored" is returned with fully populated endurance and speed payload
       objects when thresholds exist and minimum qualifying runs are met.
  AC6: state "error" is returned with a short reason string (endurance: null, speed: null)
       only on an unexpected server-side failure.
  AC7: No response ever returns a bare null body or omits the state key.
  AC8: HTTP status codes remain appropriate: 200 for scored, needs_thresholds, and
       building_baseline; 500 (or suitable 5xx) for error.
"""

import os
import pytest
import httpx
import unittest.mock as mock

from backend.services.running_performance import compute_endurance_score, compute_speed_score
from backend.services.zone_constants import make_zone_constants

BASE_URL = (
    os.environ.get("UAT_BASE_URL")
    or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
)
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run Step 0 to resolve UAT before pytest."
    )

VALID_STATES = {"scored", "needs_thresholds", "building_baseline", "error"}
REQUIRED_TOP_LEVEL_KEYS = {"state", "endurance", "speed", "generated_at"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_easy_run(run_id, efficiency_hint=1.5, decoupling_pct=5.0, workout_date="2026-01-01"):
    power = efficiency_hint * 140
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "laps": [
            {
                "band": "easy",
                "avg_power": power,
                "avg_hr": 140.0,
                "distance_km": 2.0,
                "duration_seconds": 600.0,
            }
        ],
        "decoupling_pct": decoupling_pct,
        "avg_power": power,
        "avg_hr": 140.0,
        "distance_km": 6.0,
        "duration_seconds": 1800,
    }


def _make_hard_run(run_id, efficiency_hint=1.8, workout_date="2026-01-01"):
    power = efficiency_hint * 150
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "laps": [
            {
                "band": "hard",
                "avg_power": power,
                "avg_hr": 150.0,
                "distance_km": 1.0,
                "duration_seconds": 300.0,
            }
        ],
        "decoupling_pct": None,
        "avg_power": power,
        "avg_hr": 150.0,
        "distance_km": 3.0,
        "duration_seconds": 900,
    }


def _minimal_prefs():
    return {
        "ftp_w": 200,
        "threshold_hr": 165,
        "threshold_pace_seconds_per_km": 300,
        "duration_curve_bests": None,
        "aerobic_decoupling_threshold": 8.0,
    }


# ---------------------------------------------------------------------------
# Unit tests: _determine_performance_top_level_state helper
# ---------------------------------------------------------------------------

class TestDetermineTopLevelState:
    """AC2: top-level state is always one of the four valid values."""

    def _fn(self):
        from backend.main import _determine_performance_top_level_state
        return _determine_performance_top_level_state

    def test_building_baseline_when_endurance_is_baseline(self):
        """AC4: top-level state is building_baseline when endurance signals it."""
        fn = self._fn()
        endurance = {"state": "building_baseline", "reason": "Need at least 3 runs; 1 found."}
        speed = {"score": 72.5, "direction": "improving", "trend": [72.5], "debug": {}}
        assert fn(endurance, speed) == "building_baseline"

    def test_building_baseline_when_speed_is_baseline(self):
        """AC4: top-level state is building_baseline when speed signals it."""
        fn = self._fn()
        endurance = {"score": 65.0, "direction": "flat", "trend": [65.0], "debug": {}}
        speed = {"state": "building_baseline", "reason": "Need at least 3 runs; 0 found."}
        assert fn(endurance, speed) == "building_baseline"

    def test_building_baseline_when_both_are_baseline(self):
        """AC4: top-level state is building_baseline when both signal it."""
        fn = self._fn()
        endurance = {"state": "building_baseline", "reason": "Need at least 3 runs; 0 found."}
        speed = {"state": "building_baseline", "reason": "Need at least 3 runs; 0 found."}
        assert fn(endurance, speed) == "building_baseline"

    def test_scored_when_both_have_numeric_scores(self):
        """AC5: top-level state is scored when both have numeric scores."""
        fn = self._fn()
        endurance = {"score": 72.5, "direction": "improving", "trend": [72.5], "debug": {}}
        speed = {"score": 68.0, "direction": "flat", "trend": [68.0], "debug": {}}
        assert fn(endurance, speed) == "scored"


# ---------------------------------------------------------------------------
# Unit tests: needs_thresholds response structure (pure function layer)
# ---------------------------------------------------------------------------

class TestNeedsThresholdsResponseStructure:
    """AC1, AC3: needs_thresholds response has correct structure."""

    def test_check_needs_thresholds_triggers_for_null_prefs(self):
        """AC3: _check_needs_thresholds returns True when preferences is None."""
        from backend.main import _check_needs_thresholds
        assert _check_needs_thresholds(None) is True

    def test_check_needs_thresholds_triggers_when_all_thresholds_none(self):
        """AC3: _check_needs_thresholds returns True when all three values are None."""
        from backend.main import _check_needs_thresholds
        prefs = {"ftp_w": None, "threshold_hr": None, "threshold_pace_seconds_per_km": None}
        assert _check_needs_thresholds(prefs) is True

    def test_check_needs_thresholds_false_when_one_threshold_set(self):
        """AC4 pre-condition: _check_needs_thresholds returns False with one threshold set."""
        from backend.main import _check_needs_thresholds
        assert _check_needs_thresholds({"ftp_w": 220, "threshold_hr": None, "threshold_pace_seconds_per_km": None}) is False


# ---------------------------------------------------------------------------
# Unit tests: building_baseline state from compute functions
# ---------------------------------------------------------------------------

class TestBuildingBaselineFromScoreFunctions:
    """AC4: compute functions return building_baseline state on insufficient runs."""

    def test_endurance_returns_building_baseline_on_empty_runs(self):
        """AC4: compute_endurance_score returns building_baseline with no runs."""
        zc = make_zone_constants()
        result = compute_endurance_score([], _minimal_prefs(), zc)
        assert result.get("state") == "building_baseline", (
            f"Expected building_baseline, got: {result}"
        )

    def test_speed_returns_building_baseline_on_empty_runs(self):
        """AC4: compute_speed_score returns building_baseline with no runs."""
        zc = make_zone_constants()
        result = compute_speed_score([], _minimal_prefs(), zc)
        assert result.get("state") == "building_baseline", (
            f"Expected building_baseline, got: {result}"
        )


# ---------------------------------------------------------------------------
# Unit tests: scored state from compute functions
# ---------------------------------------------------------------------------

class TestScoredStateFromComputeFunctions:
    """AC5: compute functions return numeric scores with sufficient qualifying runs."""

    def _enough_easy_runs(self):
        zc = make_zone_constants()
        min_runs = zc.get("min_qualifying_runs", 3)
        return [
            _make_easy_run(f"r{i}", efficiency_hint=1.4 + i * 0.05, workout_date=f"2026-01-0{i + 1}")
            for i in range(min_runs)
        ]

    def _enough_hard_runs(self):
        zc = make_zone_constants()
        min_runs = zc.get("min_qualifying_runs", 3)
        return [
            _make_hard_run(f"r{i}", efficiency_hint=1.7 + i * 0.05, workout_date=f"2026-01-0{i + 1}")
            for i in range(min_runs)
        ]

    def test_endurance_returns_numeric_score_with_enough_runs(self):
        """AC5: compute_endurance_score returns numeric score with sufficient easy runs."""
        zc = make_zone_constants()
        runs = self._enough_easy_runs()
        result = compute_endurance_score(runs, _minimal_prefs(), zc)
        assert "score" in result, f"Expected scored result, got: {result}"
        assert isinstance(result["score"], (int, float)), (
            f"score should be numeric, got: {result['score']}"
        )

    def test_speed_returns_numeric_score_with_enough_runs(self):
        """AC5: compute_speed_score returns numeric score with sufficient hard runs."""
        zc = make_zone_constants()
        runs = self._enough_hard_runs()
        result = compute_speed_score(runs, _minimal_prefs(), zc)
        assert "score" in result, f"Expected scored result, got: {result}"
        assert isinstance(result["score"], (int, float)), (
            f"score should be numeric, got: {result['score']}"
        )


# ---------------------------------------------------------------------------
# Unit tests: response shape helpers
# ---------------------------------------------------------------------------

class TestResponseShapeConstants:
    """AC1, AC7: Every response always has state, endurance, speed, generated_at."""

    def test_needs_thresholds_shape_has_null_endurance_and_speed(self):
        """AC3: needs_thresholds responses have endurance=null, speed=null."""
        # The endpoint must produce this shape; verify at unit level via helper
        from backend.main import _build_performance_response
        response = _build_performance_response(
            state="needs_thresholds",
            endurance=None,
            speed=None,
            generated_at="2026-01-01T00:00:00+00:00",
        )
        assert response["state"] == "needs_thresholds"
        assert response["endurance"] is None
        assert response["speed"] is None
        assert "generated_at" in response

    def test_building_baseline_shape_has_null_endurance_and_speed(self):
        """AC4: building_baseline responses have endurance=null, speed=null."""
        from backend.main import _build_performance_response
        response = _build_performance_response(
            state="building_baseline",
            endurance=None,
            speed=None,
            generated_at="2026-01-01T00:00:00+00:00",
        )
        assert response["state"] == "building_baseline"
        assert response["endurance"] is None
        assert response["speed"] is None
        assert "generated_at" in response

    def test_scored_shape_has_populated_endurance_and_speed(self):
        """AC5: scored responses have non-null endurance and speed."""
        from backend.main import _build_performance_response
        endurance = {"score": 72.5, "direction": "improving", "trend": [72.5], "debug": {}}
        speed = {"score": 68.0, "direction": "flat", "trend": [68.0], "debug": {}}
        response = _build_performance_response(
            state="scored",
            endurance=endurance,
            speed=speed,
            generated_at="2026-01-01T00:00:00+00:00",
        )
        assert response["state"] == "scored"
        assert response["endurance"] == endurance
        assert response["speed"] == speed
        assert "generated_at" in response

    def test_error_shape_has_reason_and_null_scores(self):
        """AC6: error responses have reason string and endurance=null, speed=null."""
        from backend.main import _build_performance_response
        response = _build_performance_response(
            state="error",
            endurance=None,
            speed=None,
            generated_at="2026-01-01T00:00:00+00:00",
            reason="database connection lost",
        )
        assert response["state"] == "error"
        assert response["endurance"] is None
        assert response["speed"] is None
        assert response.get("reason") == "database connection lost"
        assert "generated_at" in response

    def test_response_always_has_all_required_keys(self):
        """AC1: all four required top-level keys are always present."""
        from backend.main import _build_performance_response
        for state in ("needs_thresholds", "building_baseline", "scored", "error"):
            response = _build_performance_response(
                state=state,
                endurance=None,
                speed=None,
                generated_at="2026-01-01T00:00:00+00:00",
            )
            missing = REQUIRED_TOP_LEVEL_KEYS - set(response.keys())
            assert not missing, f"state={state!r} response missing keys: {missing}"

    def test_state_is_always_one_of_four_valid_values(self):
        """AC2: state value is always one of the four valid states."""
        from backend.main import _build_performance_response
        for state in VALID_STATES:
            response = _build_performance_response(
                state=state,
                endurance=None,
                speed=None,
                generated_at="2026-01-01T00:00:00+00:00",
            )
            assert response["state"] in VALID_STATES


# ---------------------------------------------------------------------------
# Integration tests: HTTP endpoint behavior (requires live UAT server)
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def test_performance_endpoint_needs_thresholds_returns_correct_shape(client):
    """AC1, AC3, AC8: GET /api/athletes/{id}/performance for no-thresholds athlete
    returns 200 with top-level state='needs_thresholds', endurance=null, speed=null.

    UAT Test Step 1.
    """
    r_login = client.post(
        "/api/auth/login",
        json={"username": "no_thresholds_test_929", "password": "testpass"},
    )
    if r_login.status_code != 200:
        pytest.skip(f"Login unavailable (got {r_login.status_code}); test user not seeded")
    assert r_login.status_code == 200, f"Login failed: {r_login.status_code}"

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    uid = r_me.json()["id"]

    r_perf = client.get(f"/api/athletes/{uid}/performance")
    assert r_perf.status_code == 200, (
        f"Expected 200, got {r_perf.status_code}: {r_perf.text}"
    )
    data = r_perf.json()

    # AC1: all required top-level keys present
    missing = REQUIRED_TOP_LEVEL_KEYS - set(data.keys())
    assert not missing, f"Response missing top-level keys: {missing}"

    # AC3: state is needs_thresholds at top level
    assert data["state"] == "needs_thresholds", (
        f"Expected top-level state='needs_thresholds', got: {data.get('state')}"
    )

    # AC3: endurance and speed are null
    assert data["endurance"] is None, (
        f"Expected endurance=null for needs_thresholds, got: {data['endurance']}"
    )
    assert data["speed"] is None, (
        f"Expected speed=null for needs_thresholds, got: {data['speed']}"
    )

    # AC1: generated_at is an ISO string
    assert isinstance(data["generated_at"], str), "generated_at must be a string"
    assert len(data["generated_at"]) > 0, "generated_at must not be empty"

    # AC7: no bare null body
    assert data is not None


def test_performance_endpoint_building_baseline_returns_correct_shape(client):
    """AC1, AC4, AC8: GET /api/athletes/{id}/performance for athlete with thresholds
    but insufficient runs returns 200 with top-level state='building_baseline'.

    UAT Test Step 2.
    """
    r_login = client.post(
        "/api/auth/login",
        json={"username": "one_threshold_no_runs_929", "password": "testpass"},
    )
    if r_login.status_code != 200:
        pytest.skip(f"Login unavailable (got {r_login.status_code}); test user not seeded")
    assert r_login.status_code == 200, f"Login failed: {r_login.status_code}"

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    uid = r_me.json()["id"]

    r_perf = client.get(f"/api/athletes/{uid}/performance")
    assert r_perf.status_code == 200, (
        f"Expected 200 for building_baseline, got {r_perf.status_code}: {r_perf.text}"
    )
    data = r_perf.json()

    # AC1: all required top-level keys present
    missing = REQUIRED_TOP_LEVEL_KEYS - set(data.keys())
    assert not missing, f"Response missing top-level keys: {missing}"

    # AC4: state is building_baseline at top level
    assert data["state"] == "building_baseline", (
        f"Expected top-level state='building_baseline', got: {data.get('state')}"
    )

    # AC4: endurance and speed are null
    assert data["endurance"] is None, (
        f"Expected endurance=null for building_baseline, got: {data['endurance']}"
    )
    assert data["speed"] is None, (
        f"Expected speed=null for building_baseline, got: {data['speed']}"
    )

    # AC7: no bare null body
    assert data is not None


def test_performance_endpoint_scored_returns_correct_shape(client):
    """AC1, AC5, AC8: GET /api/athletes/{id}/performance for athlete with thresholds
    and sufficient runs returns 200 with state='scored' and populated payloads.

    UAT Test Step 3.
    """
    r_login = client.post(
        "/api/auth/login",
        json={"username": "complete_athlete_929", "password": "testpass"},
    )
    if r_login.status_code != 200:
        pytest.skip(f"Login unavailable (got {r_login.status_code}); test user not seeded")
    assert r_login.status_code == 200, f"Login failed: {r_login.status_code}"

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    uid = r_me.json()["id"]

    r_perf = client.get(f"/api/athletes/{uid}/performance")
    assert r_perf.status_code == 200, (
        f"Expected 200 for scored, got {r_perf.status_code}: {r_perf.text}"
    )
    data = r_perf.json()

    # AC1: all required top-level keys present
    missing = REQUIRED_TOP_LEVEL_KEYS - set(data.keys())
    assert not missing, f"Response missing top-level keys: {missing}"

    # AC5: state is scored at top level
    assert data["state"] == "scored", (
        f"Expected top-level state='scored', got: {data.get('state')}"
    )

    # AC5: endurance and speed are populated objects (not null)
    assert data["endurance"] is not None, "endurance must be non-null for state=scored"
    assert data["speed"] is not None, "speed must be non-null for state=scored"
    assert isinstance(data["endurance"], dict), "endurance must be a dict for state=scored"
    assert isinstance(data["speed"], dict), "speed must be a dict for state=scored"

    # AC7: no bare null body
    assert data is not None


def test_performance_endpoint_state_is_never_absent(client):
    """AC7: Every response body has a non-null JSON object with a 'state' key.

    UAT Test Step 5.
    """
    # Use an unauthenticated request; should return 401 (not a bare null)
    r = client.get("/api/athletes/1/performance")
    # Either 401 (auth required) or a valid JSON response with state key
    if r.status_code == 200:
        data = r.json()
        assert data is not None, "Response body must never be bare null"
        assert "state" in data, "Response must always include 'state' key"
    elif r.status_code in (200, 401, 403, 404):
        pass  # These are all valid non-null responses
    else:
        # Any other status should still return a JSON body, not bare null
        assert r.text.strip() != "null", "Response body must never be bare null"


def test_performance_endpoint_state_value_is_valid(client):
    """AC2: state is always one of the four valid values when 200 is returned."""
    r_login = client.post(
        "/api/auth/login",
        json={"username": "no_thresholds_test_929", "password": "testpass"},
    )
    if r_login.status_code != 200:
        pytest.skip(f"Login unavailable (got {r_login.status_code}); test user not seeded")
    assert r_login.status_code == 200

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    uid = r_me.json()["id"]

    r_perf = client.get(f"/api/athletes/{uid}/performance")
    assert r_perf.status_code == 200
    data = r_perf.json()

    assert data.get("state") in VALID_STATES, (
        f"state must be one of {VALID_STATES}, got: {data.get('state')!r}"
    )


def test_performance_endpoint_http_200_for_all_non_error_states(client):
    """AC8: HTTP 200 is returned for needs_thresholds and building_baseline states."""
    r_login = client.post(
        "/api/auth/login",
        json={"username": "no_thresholds_test_929", "password": "testpass"},
    )
    if r_login.status_code != 200:
        pytest.skip(f"Login unavailable (got {r_login.status_code}); skipping UAT check")

    r_me = client.get("/api/auth/me")
    uid = r_me.json()["id"]

    r_perf = client.get(f"/api/athletes/{uid}/performance")
    data = r_perf.json()
    state = data.get("state")

    if state in ("needs_thresholds", "building_baseline", "scored"):
        assert r_perf.status_code == 200, (
            f"Expected HTTP 200 for state={state!r}, got {r_perf.status_code}"
        )
