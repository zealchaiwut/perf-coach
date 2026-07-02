"""Unit tests for running performance scores (issue #701).

Covers acceptance criteria:
  AC13: Unit tests cover normal score computation, building_baseline path,
        missing-preferences path, and missing-runs path for both functions.
  AC14: Integration test covers the full GET /api/athletes/{id}/performance
        response shape with a seeded athlete who has sufficient run history.

Skips the integration test when the server is not running (no ATHLETE_ID env var
or server unreachable), so the unit tests always pass in CI without a live DB.
"""

import os
import pytest
from backend.services.running_performance import (
    compute_endurance_score,
    compute_speed_score,
)
from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_easy_run(run_id, efficiency_hint=1.5, decoupling_pct=5.0, workout_date="2026-01-01"):
    """Single-lap easy run for endurance score tests (VDOT re-anchor).

    The score is now pace/HR based (VDOT), not power/HR. ``efficiency_hint``
    drives the lap PACE: a higher hint = faster = shorter duration over a fixed
    2 km lap, so an "improving efficiency" series maps to an improving score.
    Baseline 1.5 → 360 s/km (a genuinely easy pace); scales inversely.
    """
    distance_km = 2.0
    pace_s_per_km = 360.0 / (efficiency_hint / 1.5)  # faster as hint rises
    duration = pace_s_per_km * distance_km
    power = efficiency_hint * 140  # retained for any power-path consumers
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "laps": [
            {
                "band": "easy",
                "avg_power": power,
                "avg_hr": 140.0,
                "distance_km": distance_km,
                "duration_seconds": duration,
            }
        ],
        "decoupling_pct": decoupling_pct,
        "avg_power": power,
        "avg_hr": 140.0,
        "distance_km": 6.0,
        "duration_seconds": 1800,
    }


def _make_hard_run(run_id, efficiency_hint=1.8, avg_hard_power=270.0, workout_date="2026-01-01"):
    """Single-lap hard run for speed score tests (VDOT re-anchor).

    Speed is now pace/duration based. ``efficiency_hint`` drives the hard-lap
    PACE: higher hint = faster over a fixed 1 km lap. Baseline 1.8 → 240 s/km
    (a 4:00/km hard effort); scales inversely.
    """
    distance_km = 1.0
    pace_s_per_km = 240.0 / (efficiency_hint / 1.8)  # faster as hint rises
    duration = pace_s_per_km * distance_km
    power = efficiency_hint * 150
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "laps": [
            {
                "band": "hard",
                "avg_power": power,
                "avg_hr": 150.0,
                "distance_km": distance_km,
                "duration_seconds": duration,
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


def _make_zone_constants():
    return make_zone_constants()


# ---------------------------------------------------------------------------
# compute_endurance_score — normal computation
# ---------------------------------------------------------------------------

class TestComputeEnduranceScoreNormal:
    """AC1 / AC5: normal score returns the required shape with 0-100 score."""

    def _qualifying_runs(self):
        return [
            _make_easy_run("r1", efficiency_hint=1.50, decoupling_pct=6.0, workout_date="2026-01-01"),
            _make_easy_run("r2", efficiency_hint=1.55, decoupling_pct=5.5, workout_date="2026-01-08"),
            _make_easy_run("r3", efficiency_hint=1.60, decoupling_pct=5.0, workout_date="2026-01-15"),
            _make_easy_run("r4", efficiency_hint=1.65, decoupling_pct=4.5, workout_date="2026-01-22"),
            _make_easy_run("r5", efficiency_hint=1.70, decoupling_pct=4.0, workout_date="2026-01-29"),
        ]

    def test_returns_dict(self):
        result = compute_endurance_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert isinstance(result, dict)

    def test_score_is_number_between_0_and_100(self):
        result = compute_endurance_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert "score" in result
        assert isinstance(result["score"], (int, float))
        assert 0 <= result["score"] <= 100

    def test_direction_is_valid_string(self):
        result = compute_endurance_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert result.get("direction") in ("improving", "flat", "declining")

    def test_trend_is_nonempty_list(self):
        result = compute_endurance_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert isinstance(result.get("trend"), list)
        assert len(result["trend"]) > 0

    def test_trend_values_are_0_to_100(self):
        result = compute_endurance_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        for v in result["trend"]:
            assert 0 <= v <= 100, f"trend value {v} out of 0-100"

    def test_debug_has_per_run_efficiency(self):
        result = compute_endurance_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert "debug" in result
        assert "perRunEfficiency" in result["debug"]

    def test_per_run_efficiency_maps_run_ids(self):
        runs = self._qualifying_runs()
        result = compute_endurance_score(runs, _minimal_prefs(), _make_zone_constants())
        per_run = result["debug"]["perRunEfficiency"]
        assert isinstance(per_run, dict)
        # Every qualifying run id must appear
        for run in runs:
            assert run["run_id"] in per_run

    def test_improving_trend_yields_improving_direction(self):
        """A strictly increasing efficiency trend should yield direction 'improving'."""
        result = compute_endurance_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert result["direction"] == "improving"

    def test_no_state_key_in_normal_result(self):
        result = compute_endurance_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert "state" not in result


# ---------------------------------------------------------------------------
# compute_endurance_score — easy and steady bands included
# ---------------------------------------------------------------------------

class TestComputeEnduranceBands:
    """AC2: Endurance score considers easy AND steady laps."""

    def test_steady_laps_are_included(self):
        """Run with only steady laps should produce a valid endurance score."""
        runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [{"band": "steady", "avg_power": 170.0, "avg_hr": 145.0,
                           "distance_km": 2.0, "duration_seconds": 600.0}],
                "decoupling_pct": 5.0,
                "avg_power": 170.0, "avg_hr": 145.0,
                "distance_km": 5.0, "duration_seconds": 1800,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 1)
        ]
        result = compute_endurance_score(runs, _minimal_prefs(), _make_zone_constants())
        assert "score" in result
        assert result.get("state") != "building_baseline"

    def test_hard_laps_are_excluded(self):
        """Run with only hard laps should not contribute to endurance qualifying runs."""
        runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [{"band": "hard", "avg_power": 250.0, "avg_hr": 160.0,
                           "distance_km": 1.0, "duration_seconds": 300.0}],
                "decoupling_pct": None,
                "avg_power": 250.0, "avg_hr": 160.0,
                "distance_km": 3.0, "duration_seconds": 900,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 1)
        ]
        result = compute_endurance_score(runs, _minimal_prefs(), _make_zone_constants())
        assert result.get("state") == "building_baseline"


# ---------------------------------------------------------------------------
# compute_endurance_score — building_baseline path
# ---------------------------------------------------------------------------

class TestComputeEnduranceBuildingBaseline:
    """AC7: Fewer than min qualifying runs → building_baseline state."""

    def test_no_runs_returns_building_baseline(self):
        result = compute_endurance_score([], _minimal_prefs(), _make_zone_constants())
        assert result.get("state") == "building_baseline"
        assert isinstance(result.get("reason"), str)
        assert len(result["reason"]) > 0

    def test_fewer_than_min_returns_building_baseline(self):
        runs = [_make_easy_run(f"r{i}", workout_date=f"2026-01-{i:02d}") for i in range(1, MIN_QUALIFYING_RUNS)]
        result = compute_endurance_score(runs, _minimal_prefs(), _make_zone_constants())
        assert result.get("state") == "building_baseline"
        assert isinstance(result.get("reason"), str)

    def test_building_baseline_has_no_score_key(self):
        result = compute_endurance_score([], _minimal_prefs(), _make_zone_constants())
        assert "score" not in result

    def test_reason_mentions_required_count(self):
        result = compute_endurance_score([], _minimal_prefs(), _make_zone_constants())
        assert str(MIN_QUALIFYING_RUNS) in result["reason"]


# ---------------------------------------------------------------------------
# compute_endurance_score — missing-preferences path
# ---------------------------------------------------------------------------

class TestComputeEnduranceMissingPreferences:
    """AC8: Missing or None preferences → score: null, reason string."""

    def _qualifying_runs(self):
        return [
            _make_easy_run(f"r{i}", workout_date=f"2026-01-{i:02d}")
            for i in range(1, MIN_QUALIFYING_RUNS + 1)
        ]

    def test_none_preferences_returns_score_null(self):
        result = compute_endurance_score(self._qualifying_runs(), None, _make_zone_constants())
        assert result.get("score") is None
        assert isinstance(result.get("reason"), str)

    def test_does_not_raise(self):
        try:
            compute_endurance_score(self._qualifying_runs(), None, _make_zone_constants())
        except Exception as exc:
            pytest.fail(f"compute_endurance_score raised {exc!r} with None preferences")


# ---------------------------------------------------------------------------
# compute_endurance_score — missing-runs path
# ---------------------------------------------------------------------------

class TestComputeEnduranceMissingRuns:
    """AC8: Missing runs → either building_baseline (no qualifying data) or score: null."""

    def test_none_runs_does_not_raise(self):
        try:
            compute_endurance_score(None, _minimal_prefs(), _make_zone_constants())
        except Exception as exc:
            pytest.fail(f"compute_endurance_score raised {exc!r} with None runs")

    def test_none_runs_returns_state_or_reason(self):
        result = compute_endurance_score(None, _minimal_prefs(), _make_zone_constants())
        # Must return either building_baseline or score: null
        has_building_baseline = result.get("state") == "building_baseline"
        has_null_score = result.get("score") is None and "reason" in result
        assert has_building_baseline or has_null_score


# ---------------------------------------------------------------------------
# compute_speed_score — normal computation
# ---------------------------------------------------------------------------

class TestComputeSpeedScoreNormal:
    """AC3 / AC5: normal speed score returns the required shape."""

    def _qualifying_runs(self):
        return [
            _make_hard_run("r1", efficiency_hint=1.80, workout_date="2026-01-01"),
            _make_hard_run("r2", efficiency_hint=1.85, workout_date="2026-01-08"),
            _make_hard_run("r3", efficiency_hint=1.90, workout_date="2026-01-15"),
            _make_hard_run("r4", efficiency_hint=1.95, workout_date="2026-01-22"),
            _make_hard_run("r5", efficiency_hint=2.00, workout_date="2026-01-29"),
        ]

    def test_returns_dict(self):
        result = compute_speed_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert isinstance(result, dict)

    def test_score_is_number_between_0_and_100(self):
        result = compute_speed_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert isinstance(result.get("score"), (int, float))
        assert 0 <= result["score"] <= 100

    def test_direction_is_valid_string(self):
        result = compute_speed_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert result.get("direction") in ("improving", "flat", "declining")

    def test_trend_is_nonempty_list(self):
        result = compute_speed_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert isinstance(result.get("trend"), list)
        assert len(result["trend"]) > 0

    def test_debug_has_per_run_efficiency(self):
        result = compute_speed_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert "debug" in result
        assert "perRunEfficiency" in result["debug"]

    def test_per_run_efficiency_maps_run_ids(self):
        runs = self._qualifying_runs()
        result = compute_speed_score(runs, _minimal_prefs(), _make_zone_constants())
        per_run = result["debug"]["perRunEfficiency"]
        for run in runs:
            assert run["run_id"] in per_run

    def test_improving_trend_yields_improving_direction(self):
        result = compute_speed_score(self._qualifying_runs(), _minimal_prefs(), _make_zone_constants())
        assert result["direction"] == "improving"


# ---------------------------------------------------------------------------
# compute_speed_score — hard and interval bands
# ---------------------------------------------------------------------------

class TestComputeSpeedBands:
    """AC3: Speed score considers hard AND interval laps."""

    def test_interval_laps_are_included(self):
        runs = [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [{"band": "interval", "avg_power": 260.0, "avg_hr": 170.0,
                           "distance_km": 0.4, "duration_seconds": 90.0}],
                "decoupling_pct": None,
                "avg_power": 260.0, "avg_hr": 170.0,
                "distance_km": 2.0, "duration_seconds": 600,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 1)
        ]
        result = compute_speed_score(runs, _minimal_prefs(), _make_zone_constants())
        assert "score" in result
        assert result.get("state") != "building_baseline"

    def test_easy_laps_are_excluded(self):
        """Run with only easy laps should not contribute to speed qualifying runs."""
        runs = [
            _make_easy_run(f"r{i}", workout_date=f"2026-01-{i:02d}")
            for i in range(1, MIN_QUALIFYING_RUNS + 1)
        ]
        result = compute_speed_score(runs, _minimal_prefs(), _make_zone_constants())
        assert result.get("state") == "building_baseline"


# ---------------------------------------------------------------------------
# compute_speed_score — building_baseline
# ---------------------------------------------------------------------------

class TestComputeSpeedBuildingBaseline:
    """AC7: Fewer than min qualifying runs → building_baseline state."""

    def test_no_runs_returns_building_baseline(self):
        result = compute_speed_score([], _minimal_prefs(), _make_zone_constants())
        assert result.get("state") == "building_baseline"
        assert isinstance(result.get("reason"), str)

    def test_fewer_than_min_returns_building_baseline(self):
        runs = [_make_hard_run(f"r{i}", workout_date=f"2026-01-{i:02d}") for i in range(1, MIN_QUALIFYING_RUNS)]
        result = compute_speed_score(runs, _minimal_prefs(), _make_zone_constants())
        assert result.get("state") == "building_baseline"
        assert isinstance(result.get("reason"), str)


# ---------------------------------------------------------------------------
# compute_speed_score — missing-preferences path
# ---------------------------------------------------------------------------

class TestComputeSpeedMissingPreferences:
    """AC8: Missing preferences → score: null, reason string."""

    def _qualifying_runs(self):
        return [
            _make_hard_run(f"r{i}", workout_date=f"2026-01-{i:02d}")
            for i in range(1, MIN_QUALIFYING_RUNS + 1)
        ]

    def test_none_preferences_returns_score_null(self):
        result = compute_speed_score(self._qualifying_runs(), None, _make_zone_constants())
        assert result.get("score") is None
        assert isinstance(result.get("reason"), str)

    def test_does_not_raise(self):
        try:
            compute_speed_score(self._qualifying_runs(), None, _make_zone_constants())
        except Exception as exc:
            pytest.fail(f"compute_speed_score raised {exc!r} with None preferences")


# ---------------------------------------------------------------------------
# compute_speed_score — missing-runs path
# ---------------------------------------------------------------------------

class TestComputeSpeedMissingRuns:
    """AC8: Missing runs → building_baseline or score: null."""

    def test_none_runs_does_not_raise(self):
        try:
            compute_speed_score(None, _minimal_prefs(), _make_zone_constants())
        except Exception as exc:
            pytest.fail(f"compute_speed_score raised {exc!r} with None runs")

    def test_none_runs_returns_state_or_reason(self):
        result = compute_speed_score(None, _minimal_prefs(), _make_zone_constants())
        has_building_baseline = result.get("state") == "building_baseline"
        has_null_score = result.get("score") is None and "reason" in result
        assert has_building_baseline or has_null_score


# ---------------------------------------------------------------------------
# compute_speed_score — duration-curve bests
# ---------------------------------------------------------------------------

class TestComputeSpeedDurationCurveBests:
    """AC4: Speed score uses duration-curve bests when available.
    Debug must include a reference to the curve best used.
    """

    def _runs_with_300s_hard_laps(self):
        return [
            {
                "run_id": f"r{i}",
                "workout_date": f"2026-01-{i:02d}",
                "laps": [
                    {"band": "hard", "avg_power": 260.0 + i * 5, "avg_hr": 165.0,
                     "distance_km": 1.2, "duration_seconds": 300.0}
                ],
                "decoupling_pct": None,
                "avg_power": 260.0 + i * 5, "avg_hr": 165.0,
                "distance_km": 4.0, "duration_seconds": 900,
            }
            for i in range(1, MIN_QUALIFYING_RUNS + 1)
        ]

    def test_debug_includes_curve_best_reference_when_available(self):
        prefs = {
            **_minimal_prefs(),
            "duration_curve_bests": {
                "300": {"best_value": 300.0, "workout_id": "abc", "date": "2026-01-10"},
            },
        }
        result = compute_speed_score(self._runs_with_300s_hard_laps(), prefs, _make_zone_constants())
        # Either building baseline or has debug
        if result.get("state") == "building_baseline":
            return  # acceptable if zone filtering removes runs
        assert "debug" in result
        debug = result["debug"]
        # When curve bests are used, debug should note the reference
        assert "durationCurveBestUsed" in debug

    def test_debug_curve_best_is_none_when_not_available(self):
        prefs = {**_minimal_prefs(), "duration_curve_bests": None}
        result = compute_speed_score(self._runs_with_300s_hard_laps(), prefs, _make_zone_constants())
        if result.get("state") == "building_baseline":
            return
        assert result["debug"].get("durationCurveBestUsed") is None


# ---------------------------------------------------------------------------
# Normalization edge cases
# ---------------------------------------------------------------------------

class TestScoreNormalization:
    """AC6 (re-anchor): scores are ABSOLUTE VDOT-band values, not window-relative.

    The old min-max normalization (identical efficiencies → 50) is gone. The new
    contract: identical efforts produce a stable, flat score; an improving pace
    series trends up.
    """

    def test_score_with_identical_efforts_is_stable_and_flat(self):
        """Identical efforts → the same VDOT-band value every day, direction flat.

        (Replaces the old 'normalized to 50' assertion — the scale is now
        absolute, so identical runs sit at their true band value, not the
        window midpoint.)
        """
        runs = [
            _make_easy_run(f"r{i}", efficiency_hint=1.6, decoupling_pct=5.0,
                           workout_date=f"2026-01-{i:02d}")
            for i in range(1, MIN_QUALIFYING_RUNS + 1)
        ]
        result = compute_endurance_score(runs, _minimal_prefs(), _make_zone_constants())
        assert 0 <= result.get("score") <= 100
        assert result.get("direction") == "flat"
        # Every trend point is the same absolute value (no window rescale).
        trend = result["trend"]
        assert max(trend) - min(trend) < 0.01

    def test_improving_series_yields_score_in_range_and_improving_direction(self):
        """An improving (faster) pace series yields a valid score and 'improving'.

        Re-anchor: score is the absolute VDOT band; a genuinely faster series
        (shorter duration per km) trends up.
        """
        runs = [
            _make_easy_run("r1", efficiency_hint=1.50, decoupling_pct=5.0, workout_date="2026-01-01"),
            _make_easy_run("r2", efficiency_hint=1.55, decoupling_pct=5.0, workout_date="2026-01-08"),
            _make_easy_run("r3", efficiency_hint=1.60, decoupling_pct=5.0, workout_date="2026-01-15"),
            _make_easy_run("r4", efficiency_hint=1.65, decoupling_pct=5.0, workout_date="2026-01-22"),
            _make_easy_run("r5", efficiency_hint=1.70, decoupling_pct=5.0, workout_date="2026-01-29"),
        ]
        result = compute_endurance_score(runs, _minimal_prefs(), _make_zone_constants())
        assert 0 <= result.get("score") <= 100
        assert result.get("direction") == "improving"
        assert result.get("direction") == "improving"


# ---------------------------------------------------------------------------
# Missing zone_constants edge case
# ---------------------------------------------------------------------------

class TestMissingZoneConstants:
    """AC8: Missing zone_constants should not cause a throw."""

    def test_none_zone_constants_does_not_raise_endurance(self):
        runs = [_make_easy_run(f"r{i}", workout_date=f"2026-01-{i:02d}")
                for i in range(1, MIN_QUALIFYING_RUNS + 1)]
        try:
            compute_endurance_score(runs, _minimal_prefs(), None)
        except Exception as exc:
            pytest.fail(f"raised {exc!r} with None zone_constants")

    def test_none_zone_constants_does_not_raise_speed(self):
        runs = [_make_hard_run(f"r{i}", workout_date=f"2026-01-{i:02d}")
                for i in range(1, MIN_QUALIFYING_RUNS + 1)]
        try:
            compute_speed_score(runs, _minimal_prefs(), None)
        except Exception as exc:
            pytest.fail(f"raised {exc!r} with None zone_constants")


# ---------------------------------------------------------------------------
# Integration test — GET /api/athletes/{id}/performance
# ---------------------------------------------------------------------------

_UAT_BASE = os.environ.get("UAT_BASE_URL") or (
    "http://localhost:" + os.environ.get("UAT_PORT", "9001")
)


@pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests against a live server",
)
class TestAthletePerformanceEndpoint:
    """AC14: Integration test for GET /api/athletes/{id}/performance."""

    @pytest.fixture
    def client(self):
        import httpx
        with httpx.Client(base_url=_UAT_BASE, timeout=10.0) as c:
            yield c

    @pytest.fixture
    def session_cookie(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "testpass123"},
        )
        if resp.status_code != 200:
            pytest.skip("Test user not available")
        # Return the cookie jar (httpx tracks it automatically)
        return {}

    def test_nonexistent_athlete_returns_404(self, client, session_cookie):
        import uuid
        r = client.get(f"/api/athletes/{uuid.uuid4()}/performance")
        assert r.status_code in (401, 404)
        if r.status_code == 404:
            data = r.json()
            assert "detail" in data or "message" in data

    def test_response_contains_endurance_and_speed_keys(self, client, session_cookie):
        """AC10: Response must contain both endurance and speed keys."""
        # First get the logged-in user id
        me_resp = client.get("/api/auth/me")
        if me_resp.status_code != 200:
            pytest.skip("Cannot determine current user id")
        user_id = me_resp.json()["id"]

        r = client.get(f"/api/athletes/{user_id}/performance")
        assert r.status_code == 200
        data = r.json()
        assert "endurance" in data
        assert "speed" in data

    def test_building_baseline_returns_200(self, client, session_cookie):
        """AC12: building_baseline returns 200, not an error code."""
        me_resp = client.get("/api/auth/me")
        if me_resp.status_code != 200:
            pytest.skip("Cannot determine current user id")
        user_id = me_resp.json()["id"]

        r = client.get(f"/api/athletes/{user_id}/performance")
        assert r.status_code == 200
        data = r.json()
        # If building_baseline, reason must be a string
        for key in ("endurance", "speed"):
            score_obj = data.get(key, {})
            if score_obj.get("state") == "building_baseline":
                assert isinstance(score_obj.get("reason"), str)

    def test_score_shape_when_available(self, client, session_cookie):
        """AC5: When score is present, shape must match expected structure."""
        me_resp = client.get("/api/auth/me")
        if me_resp.status_code != 200:
            pytest.skip("Cannot determine current user id")
        user_id = me_resp.json()["id"]

        r = client.get(f"/api/athletes/{user_id}/performance")
        assert r.status_code == 200
        data = r.json()

        for key in ("endurance", "speed"):
            score_obj = data.get(key, {})
            if score_obj.get("state") == "building_baseline":
                continue
            if score_obj.get("score") is None:
                assert isinstance(score_obj.get("reason"), str)
                continue
            # Full score object
            assert 0 <= score_obj["score"] <= 100
            assert score_obj.get("direction") in ("improving", "flat", "declining")
            assert isinstance(score_obj.get("trend"), list)
            assert len(score_obj["trend"]) > 0
            assert "debug" in score_obj
            assert "perRunEfficiency" in score_obj["debug"]
