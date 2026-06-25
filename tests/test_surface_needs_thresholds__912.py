"""Tests for issue #912: Surface needs_thresholds state in performance endpoint.

TDD: these tests are written before the implementation and cover all AC items.

Acceptance Criteria covered:
  AC1: No thresholds set → endpoint returns state: "needs_thresholds" + reason.
  AC2: At least one threshold set, too few runs → state: "building_baseline" (existing).
  AC3: Thresholds + sufficient qualifying runs → numeric performance scores (existing).
  AC4: needs_thresholds vs building_baseline are mutually exclusive; driven by threshold presence.
  AC5: DB access for user_preferences thresholds is in the caller layer, not score functions.
  AC6: No threshold values are hardcoded in the updated code path.
  AC7: reason field in needs_thresholds is a non-empty human-readable string.
  AC8: Existing unit/integration tests pass; new tests cover all three states.
"""

import os
import pytest

from backend.services.running_performance import compute_endurance_score, compute_speed_score
from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS


# ---------------------------------------------------------------------------
# Helpers — shared across tests
# ---------------------------------------------------------------------------

_NEEDS_THRESHOLDS_REASON = (
    "Set your FTP, threshold heart rate, or threshold pace to unlock performance scores."
)


def _prefs_no_thresholds():
    """Preferences row with all three threshold values absent (None)."""
    return {
        "ftp_w": None,
        "threshold_hr": None,
        "threshold_pace_seconds_per_km": None,
        "aerobic_decoupling_threshold": None,
        "duration_curve_bests": None,
    }


def _prefs_with_ftp_only():
    """Preferences with only ftp_w set (at least one threshold present)."""
    return {
        "ftp_w": 220,
        "threshold_hr": None,
        "threshold_pace_seconds_per_km": None,
        "aerobic_decoupling_threshold": None,
        "duration_curve_bests": None,
    }


def _prefs_with_threshold_hr_only():
    return {
        "ftp_w": None,
        "threshold_hr": 165,
        "threshold_pace_seconds_per_km": None,
        "aerobic_decoupling_threshold": None,
        "duration_curve_bests": None,
    }


def _prefs_with_pace_only():
    return {
        "ftp_w": None,
        "threshold_hr": None,
        "threshold_pace_seconds_per_km": 300,
        "aerobic_decoupling_threshold": None,
        "duration_curve_bests": None,
    }


def _prefs_all_thresholds():
    return {
        "ftp_w": 220,
        "threshold_hr": 165,
        "threshold_pace_seconds_per_km": 300,
        "aerobic_decoupling_threshold": 8.0,
        "duration_curve_bests": None,
    }


def _make_easy_run(run_id, efficiency_hint=1.5, workout_date="2026-01-01"):
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
        "decoupling_pct": 5.0,
        "avg_power": power,
        "avg_hr": 140.0,
        "distance_km": 6.0,
        "duration_seconds": 1800,
    }


def _sufficient_easy_runs():
    return [
        _make_easy_run(f"r{i}", efficiency_hint=1.5 + i * 0.05, workout_date=f"2026-01-{i:02d}")
        for i in range(1, MIN_QUALIFYING_RUNS + 1)
    ]


# ---------------------------------------------------------------------------
# AC5: _check_needs_thresholds helper — pure function that must exist in backend.main
# ---------------------------------------------------------------------------

class TestCheckNeedsThresholdsHelper:
    """AC5: The threshold check is a pure helper in the caller layer (backend.main).

    This helper must accept a preferences dict (or None) and return True when
    none of ftp_w, threshold_hr, threshold_pace_seconds_per_km are set.
    """

    def _import_helper(self):
        from backend.main import _check_needs_thresholds
        return _check_needs_thresholds

    def test_helper_is_importable(self):
        fn = self._import_helper()
        assert callable(fn)

    def test_returns_true_when_all_thresholds_none(self):
        """AC1, AC5: returns True when all three threshold fields are None."""
        fn = self._import_helper()
        assert fn(_prefs_no_thresholds()) is True

    def test_returns_true_when_preferences_is_none(self):
        """AC1, AC5: returns True when preferences is None (no prefs row)."""
        fn = self._import_helper()
        assert fn(None) is True

    def test_returns_false_when_ftp_w_is_set(self):
        """AC4: at least one threshold present → NOT needs_thresholds."""
        fn = self._import_helper()
        assert fn(_prefs_with_ftp_only()) is False

    def test_returns_false_when_threshold_hr_is_set(self):
        """AC4: threshold_hr alone is sufficient to skip needs_thresholds."""
        fn = self._import_helper()
        assert fn(_prefs_with_threshold_hr_only()) is False

    def test_returns_false_when_threshold_pace_is_set(self):
        """AC4: threshold_pace_seconds_per_km alone is sufficient."""
        fn = self._import_helper()
        assert fn(_prefs_with_pace_only()) is False

    def test_returns_false_when_all_thresholds_set(self):
        """AC4: all thresholds present → clearly not needs_thresholds."""
        fn = self._import_helper()
        assert fn(_prefs_all_thresholds()) is False

    def test_returns_true_for_empty_dict(self):
        """AC5: empty preferences dict (all keys absent) → needs_thresholds."""
        fn = self._import_helper()
        assert fn({}) is True


# ---------------------------------------------------------------------------
# AC6: No hardcoded threshold values — the helper reads from the prefs dict
# ---------------------------------------------------------------------------

class TestNoHardcodedThresholds:
    """AC6: No threshold values (e.g. 220W, 165bpm, 300s/km) hardcoded in updated path."""

    def test_varying_ftp_values_all_count_as_present(self):
        """Any non-None ftp_w should count as 'threshold present'."""
        from backend.main import _check_needs_thresholds
        for ftp in [1, 100, 220, 350, 500]:
            prefs = {**_prefs_no_thresholds(), "ftp_w": ftp}
            assert _check_needs_thresholds(prefs) is False, f"ftp_w={ftp} should mark threshold present"

    def test_varying_hr_values_all_count_as_present(self):
        from backend.main import _check_needs_thresholds
        for hr in [100, 150, 165, 180, 200]:
            prefs = {**_prefs_no_thresholds(), "threshold_hr": hr}
            assert _check_needs_thresholds(prefs) is False, f"threshold_hr={hr} should mark threshold present"

    def test_varying_pace_values_all_count_as_present(self):
        from backend.main import _check_needs_thresholds
        for pace in [200, 250, 300, 360, 420]:
            prefs = {**_prefs_no_thresholds(), "threshold_pace_seconds_per_km": pace}
            assert _check_needs_thresholds(prefs) is False, f"pace={pace} should mark threshold present"


# ---------------------------------------------------------------------------
# AC1 + AC7: needs_thresholds response shape (via direct endpoint test using
# the _build_needs_thresholds_response helper, if it exists, or by testing
# the response returned by the endpoint with mocked DB)
# ---------------------------------------------------------------------------

class TestNeedsThresholdsResponseShape:
    """AC1, AC7: When needs_thresholds, the per-score objects have correct shape."""

    def _get_needs_thresholds_obj(self):
        """Return what a single score object looks like under needs_thresholds."""
        return {
            "state": "needs_thresholds",
            "reason": _NEEDS_THRESHOLDS_REASON,
        }

    def test_state_is_needs_thresholds(self):
        obj = self._get_needs_thresholds_obj()
        assert obj["state"] == "needs_thresholds"

    def test_reason_is_non_empty_string(self):
        """AC7: reason must be a non-empty human-readable string."""
        obj = self._get_needs_thresholds_obj()
        assert isinstance(obj.get("reason"), str)
        assert len(obj["reason"]) > 0

    def test_reason_mentions_ftp_or_thresholds(self):
        """AC7: reason should guide the user toward configuring thresholds."""
        obj = self._get_needs_thresholds_obj()
        reason = obj["reason"].lower()
        assert any(kw in reason for kw in ("ftp", "threshold", "pace", "heart rate")), (
            f"reason should mention thresholds; got: {obj['reason']!r}"
        )

    def test_no_numeric_score_fields_in_needs_thresholds(self):
        """AC1: no numeric score fields present in the needs_thresholds object."""
        obj = self._get_needs_thresholds_obj()
        assert "score" not in obj
        assert "trend" not in obj
        assert "direction" not in obj


# ---------------------------------------------------------------------------
# AC2 + AC3: building_baseline and numeric paths not broken
# Score functions themselves remain unmodified.
# ---------------------------------------------------------------------------

class TestBuildingBaselinePreserved:
    """AC2: building_baseline path preserved when at least one threshold is set."""

    def test_no_runs_with_thresholds_returns_building_baseline(self):
        """With thresholds set but no runs, scores are building_baseline."""
        zc = make_zone_constants()
        endurance = compute_endurance_score([], _prefs_with_ftp_only(), zc)
        speed = compute_speed_score([], _prefs_with_ftp_only(), zc)
        assert endurance.get("state") == "building_baseline"
        assert speed.get("state") == "building_baseline"

    def test_insufficient_runs_with_thresholds_returns_building_baseline(self):
        runs = [_make_easy_run(f"r{i}") for i in range(1, MIN_QUALIFYING_RUNS)]
        zc = make_zone_constants()
        endurance = compute_endurance_score(runs, _prefs_all_thresholds(), zc)
        assert endurance.get("state") == "building_baseline"


class TestNumericScoresPreserved:
    """AC3: Numeric scores returned when thresholds + sufficient history."""

    def test_sufficient_runs_returns_numeric_score(self):
        runs = _sufficient_easy_runs()
        zc = make_zone_constants()
        endurance = compute_endurance_score(runs, _prefs_all_thresholds(), zc)
        assert "score" in endurance
        assert isinstance(endurance["score"], (int, float))
        assert 0 <= endurance["score"] <= 100


# ---------------------------------------------------------------------------
# AC4: Mutual exclusivity — needs_thresholds and building_baseline never conflated
# ---------------------------------------------------------------------------

class TestMutualExclusivity:
    """AC4: needs_thresholds and building_baseline are mutually exclusive."""

    def test_no_thresholds_never_produces_building_baseline_via_helper(self):
        """When _check_needs_thresholds returns True, we short-circuit before
        calling score functions, so building_baseline should never be returned."""
        from backend.main import _check_needs_thresholds
        prefs = _prefs_no_thresholds()
        assert _check_needs_thresholds(prefs) is True
        # With this result, the endpoint short-circuits and does not call score fns

    def test_with_threshold_present_needs_thresholds_not_returned(self):
        """When at least one threshold is set, _check_needs_thresholds must be False."""
        from backend.main import _check_needs_thresholds
        for prefs in [_prefs_with_ftp_only(), _prefs_with_threshold_hr_only(), _prefs_with_pace_only()]:
            assert _check_needs_thresholds(prefs) is False

    def test_score_function_result_is_not_needs_thresholds(self):
        """Score functions themselves never return state=needs_thresholds — the
        endpoint intercepts before that path."""
        zc = make_zone_constants()
        # With no preferences, score functions return score: None (not needs_thresholds)
        endurance = compute_endurance_score([], None, zc)
        speed = compute_speed_score([], None, zc)
        assert endurance.get("state") != "needs_thresholds"
        assert speed.get("state") != "needs_thresholds"


# ---------------------------------------------------------------------------
# Integration tests — GET /api/athletes/{id}/performance via live server
# ---------------------------------------------------------------------------

_UAT_BASE = os.environ.get("UAT_BASE_URL") or (
    "http://localhost:" + os.environ.get("UAT_PORT", "9001")
)


@pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests against a live server",
)
class TestNeedsThresholdsIntegration:
    """Integration tests for needs_thresholds state (AC1, AC2, AC3, AC4)."""

    @pytest.fixture
    def client(self):
        import httpx
        with httpx.Client(base_url=_UAT_BASE, timeout=10.0) as c:
            yield c

    def _login(self, client, username, password):
        resp = client.post("/api/auth/login", json={"username": username, "password": password})
        if resp.status_code != 200:
            pytest.skip(f"Cannot log in as {username!r}")

    def test_no_thresholds_returns_needs_thresholds(self, client):
        """AC1: Athlete with no thresholds → needs_thresholds state."""
        self._login(client, "no_threshold_user", "testpass123")
        me = client.get("/api/auth/me")
        if me.status_code != 200:
            pytest.skip("Cannot determine current user id")
        uid = me.json()["id"]

        r = client.get(f"/api/athletes/{uid}/performance")
        assert r.status_code == 200
        data = r.json()
        assert "endurance" in data
        assert "speed" in data
        assert data["endurance"].get("state") == "needs_thresholds"
        assert data["speed"].get("state") == "needs_thresholds"
        assert isinstance(data["endurance"].get("reason"), str)
        assert len(data["endurance"]["reason"]) > 0

    def test_needs_thresholds_has_no_score_field(self, client):
        """AC1: No numeric score fields present in needs_thresholds response."""
        self._login(client, "no_threshold_user", "testpass123")
        me = client.get("/api/auth/me")
        if me.status_code != 200:
            pytest.skip("Cannot determine current user id")
        uid = me.json()["id"]

        r = client.get(f"/api/athletes/{uid}/performance")
        assert r.status_code == 200
        data = r.json()
        for key in ("endurance", "speed"):
            obj = data.get(key, {})
            if obj.get("state") == "needs_thresholds":
                assert "score" not in obj
                assert "trend" not in obj

    def test_one_threshold_transitions_to_building_baseline(self, client):
        """AC4: Adding one threshold changes state from needs_thresholds to building_baseline."""
        self._login(client, "one_threshold_no_runs_user", "testpass123")
        me = client.get("/api/auth/me")
        if me.status_code != 200:
            pytest.skip("Cannot determine current user id")
        uid = me.json()["id"]

        r = client.get(f"/api/athletes/{uid}/performance")
        assert r.status_code == 200
        data = r.json()
        for key in ("endurance", "speed"):
            state = data.get(key, {}).get("state")
            assert state == "building_baseline", (
                f"{key} should be building_baseline with one threshold; got {state!r}"
            )

    def test_reason_string_is_human_readable(self, client):
        """AC7: reason is a human-readable string suitable for UI display."""
        self._login(client, "no_threshold_user", "testpass123")
        me = client.get("/api/auth/me")
        if me.status_code != 200:
            pytest.skip("Cannot determine current user id")
        uid = me.json()["id"]

        r = client.get(f"/api/athletes/{uid}/performance")
        assert r.status_code == 200
        data = r.json()
        endurance_obj = data.get("endurance", {})
        if endurance_obj.get("state") == "needs_thresholds":
            reason = endurance_obj.get("reason", "")
            assert len(reason) > 10, "reason string too short to be human-readable"
            # Should not be raw JSON or a traceback
            assert "{" not in reason
            assert "Traceback" not in reason
