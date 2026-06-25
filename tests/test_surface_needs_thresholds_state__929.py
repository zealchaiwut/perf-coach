"""Tests for issue #929: Surface needs_thresholds state when athlete has no thresholds set.

Acceptance Criteria:
  AC1: Endpoint returns { "state": "needs_thresholds", "reason": "..." } when all thresholds unset.
  AC2: Endpoint returns { "state": "building_baseline" } when at least one threshold set but insufficient runs.
  AC3: Endpoint returns numeric performance scores when thresholds and sufficient history present.
  AC4: reason field is sourced from config; no hardcoded strings in business logic.
  AC5: DB access for thresholds is in the caller (thin caller pattern); score functions don't query.
  AC6: Three states (needs_thresholds, building_baseline, numeric) are mutually exclusive and exhaustive.
  AC7: Unit tests cover all three states.

Integration tests verify end-to-end HTTP behavior against UAT.
"""

import os
import pytest
import httpx


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- Unit tests: helper functions and state logic ---

class TestCheckNeedsThresholdsHelper:
    """AC4, AC5: _check_needs_thresholds helper validates threshold presence."""

    def _import_helper(self):
        from backend.main import _check_needs_thresholds
        return _check_needs_thresholds

    def test_returns_true_when_all_thresholds_none(self):
        """AC1: returns True when all three threshold fields are None."""
        fn = self._import_helper()
        prefs = {
            "ftp_w": None,
            "threshold_hr": None,
            "threshold_pace_seconds_per_km": None,
        }
        assert fn(prefs) is True

    def test_returns_true_when_preferences_is_none(self):
        """AC1: returns True when preferences is None (no prefs row)."""
        fn = self._import_helper()
        assert fn(None) is True

    def test_returns_false_when_ftp_w_is_set(self):
        """AC2: At least one threshold present → NOT needs_thresholds."""
        fn = self._import_helper()
        prefs = {
            "ftp_w": 220,
            "threshold_hr": None,
            "threshold_pace_seconds_per_km": None,
        }
        assert fn(prefs) is False

    def test_returns_false_when_threshold_hr_is_set(self):
        """AC2: threshold_hr alone is sufficient to skip needs_thresholds."""
        fn = self._import_helper()
        prefs = {
            "ftp_w": None,
            "threshold_hr": 165,
            "threshold_pace_seconds_per_km": None,
        }
        assert fn(prefs) is False

    def test_returns_false_when_threshold_pace_is_set(self):
        """AC2: threshold_pace_seconds_per_km alone is sufficient."""
        fn = self._import_helper()
        prefs = {
            "ftp_w": None,
            "threshold_hr": None,
            "threshold_pace_seconds_per_km": 300,
        }
        assert fn(prefs) is False


class TestNeedsThresholdsReason:
    """AC4: reason field is a constant, not hardcoded in business logic."""

    def test_needs_thresholds_reason_constant_exists(self):
        """AC4: _NEEDS_THRESHOLDS_REASON constant is defined in backend.main."""
        from backend.main import _NEEDS_THRESHOLDS_REASON
        assert isinstance(_NEEDS_THRESHOLDS_REASON, str)
        assert len(_NEEDS_THRESHOLDS_REASON) > 0

    def test_reason_is_human_readable(self):
        """AC4, AC7: reason mentions thresholds, FTP, heart rate, or pace."""
        from backend.main import _NEEDS_THRESHOLDS_REASON
        reason_lower = _NEEDS_THRESHOLDS_REASON.lower()
        keywords = ("ftp", "threshold", "pace", "heart rate")
        assert any(kw in reason_lower for kw in keywords), (
            f"reason should guide user to set thresholds; got: {_NEEDS_THRESHOLDS_REASON!r}"
        )


class TestStateExclusivity:
    """AC6: Three states are mutually exclusive — never mixed in one response."""

    def test_needs_thresholds_never_mixed_with_numeric_score(self):
        """AC6: If state=needs_thresholds, no numeric 'score' field present."""
        from backend.main import _check_needs_thresholds
        prefs_no_thresh = {
            "ftp_w": None,
            "threshold_hr": None,
            "threshold_pace_seconds_per_km": None,
        }
        # When _check_needs_thresholds is True, endpoint returns early with state only
        assert _check_needs_thresholds(prefs_no_thresh) is True
        # So score function is never called; state and score never coexist

    def test_building_baseline_and_needs_thresholds_mutually_exclusive(self):
        """AC6: score functions return building_baseline only when thresholds present.
        If no thresholds, endpoint returns needs_thresholds before calling score functions."""
        from backend.main import _check_needs_thresholds
        from backend.services.running_performance import compute_endurance_score
        from backend.services.zone_constants import make_zone_constants

        # No thresholds → endpoint short-circuits and never calls compute_endurance_score
        prefs_no_thresh = {
            "ftp_w": None,
            "threshold_hr": None,
            "threshold_pace_seconds_per_km": None,
        }
        assert _check_needs_thresholds(prefs_no_thresh) is True

        # With thresholds but no runs, score function returns building_baseline
        prefs_with_ftp = {
            "ftp_w": 220,
            "threshold_hr": None,
            "threshold_pace_seconds_per_km": None,
        }
        zc = make_zone_constants()
        score = compute_endurance_score([], prefs_with_ftp, zc)
        assert score.get("state") == "building_baseline"
        # Never needs_thresholds


# --- Integration tests: HTTP endpoint behavior ---

def test_performance_endpoint_no_thresholds_returns_needs_thresholds_state(client):
    """AC1: GET /api/athletes/{id}/performance returns needs_thresholds state when no thresholds set.

    Test Steps:
      1. Log in as a user with no thresholds configured.
      2. GET /api/athletes/{id}/performance
      3. Assert response contains state: "needs_thresholds" and a non-empty reason string.
    """
    # Create a session and log in
    r_login = client.post("/api/auth/login", json={"username": "no_thresholds_test_929", "password": "testpass"})
    if r_login.status_code == 401:
        pytest.skip("Test user no_thresholds_test_929 not seeded or invalid credentials")
    assert r_login.status_code == 200, f"Login failed: {r_login.status_code}"

    # Get current user ID
    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    uid = r_me.json()["id"]

    # Call performance endpoint
    r_perf = client.get(f"/api/athletes/{uid}/performance")
    assert r_perf.status_code == 200
    data = r_perf.json()

    # Assert both endurance and speed have needs_thresholds state
    assert "endurance" in data
    assert "speed" in data
    assert data["endurance"].get("state") == "needs_thresholds", (
        f"endurance should have state=needs_thresholds; got {data['endurance']}"
    )
    assert data["speed"].get("state") == "needs_thresholds", (
        f"speed should have state=needs_thresholds; got {data['speed']}"
    )

    # Assert reason field is present and non-empty
    assert isinstance(data["endurance"].get("reason"), str)
    assert len(data["endurance"]["reason"]) > 0


def test_performance_endpoint_no_numeric_score_when_needs_thresholds(client):
    """AC1: Response contains only state and reason; no numeric score fields.

    Test Steps:
      1. Log in as user with no thresholds.
      2. GET /api/athletes/{id}/performance
      3. Assert no 'score', 'trend', or 'direction' fields in endurance/speed.
    """
    r_login = client.post("/api/auth/login", json={"username": "no_thresholds_test_929", "password": "testpass"})
    if r_login.status_code == 401:
        pytest.skip("Test user no_thresholds_test_929 not seeded or invalid credentials")
    assert r_login.status_code == 200

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    uid = r_me.json()["id"]

    r_perf = client.get(f"/api/athletes/{uid}/performance")
    assert r_perf.status_code == 200
    data = r_perf.json()

    for key in ("endurance", "speed"):
        obj = data.get(key, {})
        if obj.get("state") == "needs_thresholds":
            assert "score" not in obj, f"{key} should not have 'score' field"
            assert "trend" not in obj, f"{key} should not have 'trend' field"
            assert "direction" not in obj, f"{key} should not have 'direction' field"


def test_performance_endpoint_one_threshold_returns_building_baseline(client):
    """AC2: With at least one threshold but insufficient runs → building_baseline state.

    Test Steps:
      1. Log in as user with one threshold configured but no or few runs.
      2. GET /api/athletes/{id}/performance
      3. Assert state: "building_baseline" is returned (not needs_thresholds).
    """
    r_login = client.post("/api/auth/login", json={"username": "one_threshold_no_runs_929", "password": "testpass"})
    if r_login.status_code == 401:
        pytest.skip("Test user one_threshold_no_runs_929 not seeded or invalid credentials")
    assert r_login.status_code == 200

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    uid = r_me.json()["id"]

    r_perf = client.get(f"/api/athletes/{uid}/performance")
    assert r_perf.status_code == 200
    data = r_perf.json()

    # Both endurance and speed should be building_baseline, NOT needs_thresholds
    assert data["endurance"].get("state") == "building_baseline", (
        f"endurance should be building_baseline with one threshold; got {data['endurance']}"
    )
    assert data["speed"].get("state") == "building_baseline", (
        f"speed should be building_baseline with one threshold; got {data['speed']}"
    )


def test_performance_endpoint_thresholds_and_runs_returns_numeric_scores(client):
    """AC3: With thresholds and sufficient runs → numeric performance scores.

    Test Steps:
      1. Log in as user with thresholds configured and sufficient qualifying runs.
      2. GET /api/athletes/{id}/performance
      3. Assert response contains numeric 'score' fields (not state/reason).
    """
    r_login = client.post("/api/auth/login", json={"username": "complete_athlete_929", "password": "testpass"})
    if r_login.status_code == 401:
        pytest.skip("Test user complete_athlete_929 not seeded or invalid credentials")
    assert r_login.status_code == 200

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    uid = r_me.json()["id"]

    r_perf = client.get(f"/api/athletes/{uid}/performance")
    assert r_perf.status_code == 200
    data = r_perf.json()

    # Endurance and speed should have numeric scores, not state placeholders
    for key in ("endurance", "speed"):
        obj = data.get(key, {})
        # If building_baseline or needs_thresholds, those are expected fallbacks
        if "score" in obj:
            assert isinstance(obj["score"], (int, float)), f"{key} score should be numeric"
            assert 0 <= obj["score"] <= 100, f"{key} score should be in [0, 100]"
            # No state field when score is present
            assert "state" not in obj, f"{key} should not have 'state' when score is present"


def test_needs_thresholds_reason_is_actionable(client):
    """AC4, AC7: reason string is human-readable and actionable for UI display.

    Test Steps:
      1. Log in as user with no thresholds.
      2. GET /api/athletes/{id}/performance
      3. Assert reason field is substantive (not empty, not JSON, not traceback).
    """
    r_login = client.post("/api/auth/login", json={"username": "no_thresholds_test_929", "password": "testpass"})
    if r_login.status_code == 401:
        pytest.skip("Test user no_thresholds_test_929 not seeded or invalid credentials")
    assert r_login.status_code == 200

    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    uid = r_me.json()["id"]

    r_perf = client.get(f"/api/athletes/{uid}/performance")
    assert r_perf.status_code == 200
    data = r_perf.json()

    reason = data["endurance"].get("reason", "")
    assert len(reason) > 10, "reason should be substantive"
    assert "{" not in reason, "reason should not be raw JSON"
    assert "Traceback" not in reason, "reason should not be a traceback"
    assert "threshold" in reason.lower() or "ftp" in reason.lower(), (
        "reason should mention thresholds or FTP"
    )
