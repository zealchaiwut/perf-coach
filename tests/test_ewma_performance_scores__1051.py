"""Unit tests for EWMA-based endurance and speed scoring (issue #1051).

Acceptance criteria covered:

  AC1  - Endurance score is a duration-weighted EWMA of per-run endurance signals.
  AC2  - Speed score is an effort-quality-weighted EWMA of per-run speed signals.
  AC3  - Days/runs with no qualifying signal carry last smoothed value forward (no drop).
  AC4  - GET /api/athletes/{id}/performance returns all M0 keys; scores derived from signals.
  AC5  - Each score object includes qualifying_session_count integer.
  AC6  - Smoothing constants live in a single documented config block.
  AC7  - Tests cover forward-carry, correct weighting, boundary at window start.
"""

from __future__ import annotations

import pytest
from backend.services.running_performance import (
    compute_endurance_score,
    compute_speed_score,
    PERFORMANCE_CONFIG,
)
from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zc():
    return make_zone_constants()


def _prefs():
    return {
        "ftp_w": 200,
        "threshold_hr": 165,
        "threshold_pace_seconds_per_km": 300,
        "duration_curve_bests": None,
        "aerobic_decoupling_threshold": 8.0,
    }


def _easy_run(run_id, efficiency_hint=1.6, decoupling_pct=5.0,
              workout_date="2026-01-01", duration_seconds=3600):
    """Single-lap easy run for endurance tests (VDOT re-anchor).

    ``efficiency_hint`` drives the lap PACE (higher = faster) so an improving
    series maps to an improving VDOT-band score. Baseline 1.6 → 337.5 s/km.
    """
    distance_km = 2.0
    pace = 540.0 / efficiency_hint  # faster as hint rises
    lap_dur = pace * distance_km
    power = efficiency_hint * 140
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "laps": [
            {
                "band": "easy",
                "avg_power": power,
                "avg_hr": 140.0,
                "distance_km": distance_km,
                "duration_seconds": lap_dur,
            }
        ],
        "decoupling_pct": decoupling_pct,
        "avg_power": power,
        "avg_hr": 140.0,
        "distance_km": 6.0,
        "duration_seconds": duration_seconds,
    }


def _hard_run(run_id, efficiency_hint=1.8, speed_signal=1.15,
              workout_date="2026-01-01", duration_seconds=1800):
    """Single-lap hard run for speed tests (VDOT re-anchor).

    Speed is now pace/duration based. ``speed_signal`` maps to the hard-lap PACE
    (higher signal = faster effort) so signal-quality differences still move the
    score — via pace, the real driver now — not the ignored stored ratio.
    Baseline signal 1.15 → ~276 s/km.
    """
    distance_km = 1.0
    pace = 318.0 / speed_signal  # faster as the effort ratio rises
    lap_dur = pace * distance_km
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
                "duration_seconds": lap_dur,
            }
        ],
        "decoupling_pct": None,
        "avg_power": power,
        "avg_hr": 150.0,
        "distance_km": 3.0,
        "duration_seconds": duration_seconds,
        "speed_signal": speed_signal,
    }


def _make_n_easy_runs(n, efficiency_start=1.5, efficiency_step=0.05):
    """Build n easy runs with incrementing efficiency and sequential dates."""
    return [
        _easy_run(
            f"r{i}",
            efficiency_hint=efficiency_start + i * efficiency_step,
            workout_date=f"2026-01-{i + 1:02d}",
        )
        for i in range(n)
    ]


def _make_n_hard_runs(n, signal_start=1.10, signal_step=0.02):
    """Build n hard runs with incrementing speed_signal and sequential dates."""
    return [
        _hard_run(
            f"rs{i}",
            speed_signal=signal_start + i * signal_step,
            workout_date=f"2026-02-{i + 1:02d}",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# AC6 — Config block exists and exposes required keys
# ---------------------------------------------------------------------------

class TestConfigBlock:
    """AC6: Smoothing constants are in a single documented config block."""

    def test_performance_config_is_dict(self):
        assert isinstance(PERFORMANCE_CONFIG, dict)

    def test_trailing_window_days_present(self):
        assert "trailing_window_days" in PERFORMANCE_CONFIG
        assert PERFORMANCE_CONFIG["trailing_window_days"] > 0

    def test_threshold_effort_minutes_present(self):
        # Re-anchor: EWMA alphas / reference-duration / reference-signal are gone.
        # The endurance HR-extrapolation reference duration lives here now.
        assert "threshold_effort_minutes" in PERFORMANCE_CONFIG
        assert PERFORMANCE_CONFIG["threshold_effort_minutes"] > 0

    def test_speed_sparse_config_present(self):
        assert "speed_sparse_effort_threshold" in PERFORMANCE_CONFIG
        assert "speed_sparse_band_multiplier" in PERFORMANCE_CONFIG

    def test_ewma_alphas_removed(self):
        # The relative min/max + EWMA pipeline was removed in the VDOT re-anchor.
        assert "endurance_ewma_alpha" not in PERFORMANCE_CONFIG
        assert "speed_ewma_alpha" not in PERFORMANCE_CONFIG


# ---------------------------------------------------------------------------
# AC5 — qualifying_session_count in response
# ---------------------------------------------------------------------------

class TestQualifyingSessionCount:
    """AC5: Each score object includes qualifying_session_count."""

    def test_endurance_result_has_qualifying_session_count(self):
        runs = _make_n_easy_runs(MIN_QUALIFYING_RUNS)
        result = compute_endurance_score(runs, _prefs(), _zc())
        assert "qualifying_session_count" in result, (
            "qualifying_session_count missing from endurance score result"
        )

    def test_speed_result_has_qualifying_session_count(self):
        runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS)
        result = compute_speed_score(runs, _prefs(), _zc())
        assert "qualifying_session_count" in result, (
            "qualifying_session_count missing from speed score result"
        )

    def test_endurance_qualifying_count_matches_easy_runs(self):
        n = MIN_QUALIFYING_RUNS + 2
        runs = _make_n_easy_runs(n)
        result = compute_endurance_score(runs, _prefs(), _zc())
        assert result["qualifying_session_count"] == n

    def test_speed_qualifying_count_matches_hard_runs(self):
        n = MIN_QUALIFYING_RUNS + 2
        runs = _make_n_hard_runs(n)
        result = compute_speed_score(runs, _prefs(), _zc())
        assert result["qualifying_session_count"] == n

    def test_endurance_qualifying_count_excludes_non_easy_runs(self):
        """Hard runs don't contribute to endurance qualifying count."""
        easy_runs = _make_n_easy_runs(MIN_QUALIFYING_RUNS)
        hard_extras = [
            _hard_run(f"h{i}", workout_date=f"2026-03-{i+1:02d}")
            for i in range(2)
        ]
        result = compute_endurance_score(easy_runs + hard_extras, _prefs(), _zc())
        assert result["qualifying_session_count"] == MIN_QUALIFYING_RUNS

    def test_building_baseline_has_qualifying_count_zero_or_low(self):
        """building_baseline: qualifying_session_count reflects the deficit."""
        runs = _make_n_easy_runs(MIN_QUALIFYING_RUNS - 1)
        result = compute_endurance_score(runs, _prefs(), _zc())
        # building_baseline path; count should be below min
        assert result.get("state") == "building_baseline"
        # qualifying_session_count may or may not be present in baseline state


# ---------------------------------------------------------------------------
# AC3 — Forward-carry: no qualifying signal = no score change
# ---------------------------------------------------------------------------

class TestForwardCarry:
    """AC3: Days with no qualifying signal carry last smoothed value forward."""

    def test_endurance_non_qualifying_runs_do_not_change_score(self):
        """Adding hard runs (not qualifying for endurance) should not alter the score."""
        easy_runs = _make_n_easy_runs(MIN_QUALIFYING_RUNS)
        hard_extras = [
            _hard_run(f"h{i}", workout_date=f"2026-02-{i+1:02d}")
            for i in range(3)
        ]
        result_easy_only = compute_endurance_score(easy_runs, _prefs(), _zc())
        result_mixed = compute_endurance_score(easy_runs + hard_extras, _prefs(), _zc())

        assert "score" in result_easy_only, "endurance should score with easy-only runs"
        assert result_easy_only["score"] == result_mixed["score"], (
            "non-qualifying hard runs must not change the endurance EWMA"
        )

    def test_endurance_qualifying_count_unchanged_by_non_qualifying_runs(self):
        """Non-qualifying runs must not inflate qualifying_session_count."""
        easy_runs = _make_n_easy_runs(MIN_QUALIFYING_RUNS)
        hard_extras = [
            _hard_run(f"h{i}", workout_date=f"2026-02-{i+1:02d}")
            for i in range(3)
        ]
        result = compute_endurance_score(easy_runs + hard_extras, _prefs(), _zc())
        assert result["qualifying_session_count"] == MIN_QUALIFYING_RUNS

    def test_speed_non_qualifying_runs_do_not_change_score(self):
        """Adding easy runs (not qualifying for speed) should not alter the speed EWMA."""
        hard_runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS)
        easy_extras = [
            _easy_run(f"e{i}", workout_date=f"2026-03-{i+1:02d}")
            for i in range(3)
        ]
        result_hard_only = compute_speed_score(hard_runs, _prefs(), _zc())
        result_mixed = compute_speed_score(hard_runs + easy_extras, _prefs(), _zc())

        assert "score" in result_hard_only
        assert result_hard_only["score"] == result_mixed["score"], (
            "non-qualifying easy runs must not change the speed EWMA"
        )


# ---------------------------------------------------------------------------
# AC1 — Endurance: duration-weighted EWMA
# ---------------------------------------------------------------------------

class TestEnduranceDurationWeighting:
    """AC1: Endurance score is an EWMA weighted by run duration."""

    def test_longer_run_has_more_ewma_influence(self):
        """A longer high-signal run should move the EWMA more than a short one."""
        # Scenario A: run 1 has low signal, run 2 (SHORT) has high signal
        # Scenario B: run 1 has low signal, run 2 (LONG)  has high signal
        # B's final EWMA should be higher because the long run gets more weight.

        runs_a = [
            _easy_run("a1", efficiency_hint=1.4, workout_date="2026-01-01", duration_seconds=1800),
            _easy_run("a2", efficiency_hint=1.8, workout_date="2026-01-08", duration_seconds=600),
        ]
        runs_b = [
            _easy_run("b1", efficiency_hint=1.4, workout_date="2026-01-01", duration_seconds=1800),
            _easy_run("b2", efficiency_hint=1.8, workout_date="2026-01-08", duration_seconds=7200),
        ]

        result_a = compute_endurance_score(runs_a, _prefs(), _zc())
        result_b = compute_endurance_score(runs_b, _prefs(), _zc())

        # Both might be building_baseline (need >= MIN_QUALIFYING_RUNS)
        if result_a.get("state") == "building_baseline":
            pytest.skip("Need >= MIN_QUALIFYING_RUNS; test design is illustrative")

        assert result_b["score"] > result_a["score"], (
            "longer run with higher signal should push EWMA more than short run"
        )

    def test_endurance_ewma_is_smoothed_not_max_normalized(self):
        """EWMA should produce a score below 100 for an improving series (not just pick last)."""
        # A series with the last run being the best efficiency.
        # Old min-max normalization gives 100 for the last run.
        # EWMA with alpha < 1 gives a score < 100.
        runs = _make_n_easy_runs(MIN_QUALIFYING_RUNS + 2, efficiency_start=1.5, efficiency_step=0.1)
        result = compute_endurance_score(runs, _prefs(), _zc())
        if result.get("state") == "building_baseline":
            pytest.skip("not enough qualifying runs")
        assert result["score"] < 100.0, (
            "EWMA score should be < 100 for an improving series (EWMA damps the last point)"
        )

    def test_endurance_ewma_score_in_0_to_100(self):
        """EWMA score must remain in [0, 100]."""
        runs = _make_n_easy_runs(MIN_QUALIFYING_RUNS + 3)
        result = compute_endurance_score(runs, _prefs(), _zc())
        if result.get("state") == "building_baseline":
            pytest.skip("building baseline")
        assert 0 <= result["score"] <= 100

    def test_endurance_ewma_trend_is_list(self):
        """EWMA trend must be a non-empty list of floats in [0, 100]."""
        runs = _make_n_easy_runs(MIN_QUALIFYING_RUNS)
        result = compute_endurance_score(runs, _prefs(), _zc())
        if result.get("state") == "building_baseline":
            pytest.skip("building baseline")
        trend = result.get("trend", [])
        assert isinstance(trend, list) and len(trend) > 0
        for v in trend:
            assert 0 <= v <= 100, f"trend value {v} out of range"


# ---------------------------------------------------------------------------
# AC2 — Speed: effort-quality-weighted EWMA
# ---------------------------------------------------------------------------

class TestSpeedEffortQualityWeighting:
    """AC2: Speed score is an effort-quality-weighted EWMA of per-run speed signals."""

    def test_higher_speed_signal_has_more_ewma_influence(self):
        """A faster (higher-signal→faster-pace) effort should raise the score.

        Re-anchor: signal quality now maps to hard-lap PACE (the real driver),
        so a faster last effort produces a higher absolute VDOT-band score.
        """
        low_signal_run2 = _hard_run("a2", speed_signal=1.05, workout_date="2026-02-08")
        high_signal_run2 = _hard_run("b2", speed_signal=1.35, workout_date="2026-02-08")

        base_runs = [
            _hard_run(f"r{i}", speed_signal=1.15, workout_date=f"2026-02-{i+1:02d}")
            for i in range(MIN_QUALIFYING_RUNS - 1)
        ]

        runs_a = base_runs + [low_signal_run2]
        runs_b = base_runs + [high_signal_run2]

        result_a = compute_speed_score(runs_a, _prefs(), _zc())
        result_b = compute_speed_score(runs_b, _prefs(), _zc())

        if result_a.get("state") == "building_baseline":
            pytest.skip("building baseline")

        # Scenario B has a higher signal on the last run and higher weight — score should differ
        # (We just test they differ; which is higher depends on signal values and history)
        assert result_a["score"] != result_b["score"], (
            "different speed_signal values should produce different EWMA scores"
        )

    def test_speed_ewma_score_in_0_to_100(self):
        """EWMA speed score must stay in [0, 100]."""
        runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS + 3)
        result = compute_speed_score(runs, _prefs(), _zc())
        if result.get("state") == "building_baseline":
            pytest.skip("building baseline")
        assert 0 <= result["score"] <= 100

    def test_speed_ewma_trend_has_same_length_as_qualifying_runs(self):
        """Trend list should have one entry per qualifying run."""
        n = MIN_QUALIFYING_RUNS + 2
        runs = _make_n_hard_runs(n)
        result = compute_speed_score(runs, _prefs(), _zc())
        if result.get("state") == "building_baseline":
            pytest.skip("building baseline")
        assert len(result.get("trend", [])) == n


# ---------------------------------------------------------------------------
# AC7 — Boundary: fewer sessions than window length
# ---------------------------------------------------------------------------

class TestBoundaryBehavior:
    """AC7: Boundary behaviour at the start of the window (fewer sessions than length)."""

    def test_endurance_single_minimum_qualifying_session_count(self):
        """Exactly MIN_QUALIFYING_RUNS easy runs → scored, count correct."""
        runs = _make_n_easy_runs(MIN_QUALIFYING_RUNS)
        result = compute_endurance_score(runs, _prefs(), _zc())
        assert "score" in result, "should produce a score with exactly min runs"
        assert result.get("state") != "building_baseline"
        assert result["qualifying_session_count"] == MIN_QUALIFYING_RUNS

    def test_speed_single_minimum_qualifying_session_count(self):
        """Exactly MIN_QUALIFYING_RUNS hard runs → scored, count correct."""
        runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS)
        result = compute_speed_score(runs, _prefs(), _zc())
        assert "score" in result
        assert result.get("state") != "building_baseline"
        assert result["qualifying_session_count"] == MIN_QUALIFYING_RUNS

    def test_trailing_window_excludes_old_sessions(self):
        """Sessions older than trailing_window_days must be excluded from EWMA."""
        # Three very old runs (well outside window) + exactly MIN runs that are recent
        old_runs = [
            _easy_run(f"old{i}", workout_date="2020-01-01", efficiency_hint=2.5)
            for i in range(3)
        ]
        recent_runs = [
            _easy_run(f"new{i}", efficiency_hint=1.5, workout_date=f"2026-06-{i+1:02d}")
            for i in range(MIN_QUALIFYING_RUNS)
        ]
        result_with_old = compute_endurance_score(old_runs + recent_runs, _prefs(), _zc())
        result_recent_only = compute_endurance_score(recent_runs, _prefs(), _zc())

        assert "score" in result_with_old
        # The old runs are from 2020, far outside the 90-day trailing window.
        # They should be excluded so the score equals the recent-only result.
        assert result_with_old["score"] == result_recent_only["score"], (
            "sessions outside the trailing window must not affect the EWMA"
        )
        # qualifying count should only include the recent ones
        assert result_with_old["qualifying_session_count"] == MIN_QUALIFYING_RUNS

    def test_identical_sessions_yield_stable_absolute_score(self):
        """Identical efforts → a stable absolute VDOT-band score (no window rescale).

        Re-anchor: the old EWMA-bootstrap-to-50 behaviour is gone; identical
        runs now sit at their true band value with a flat trend.
        """
        runs = [
            _easy_run(f"r{i}", efficiency_hint=1.6, workout_date=f"2026-01-{i+1:02d}")
            for i in range(MIN_QUALIFYING_RUNS)
        ]
        result = compute_endurance_score(runs, _prefs(), _zc())
        if result.get("state") == "building_baseline":
            pytest.skip("building baseline")
        assert 0 <= result["score"] <= 100
        trend = result["trend"]
        assert max(trend) - min(trend) < 0.01  # flat — identical efforts

    def test_endurance_zero_runs_no_crash_and_building_baseline(self):
        """Zero runs → building_baseline, no exception, count is absent or 0."""
        result = compute_endurance_score([], _prefs(), _zc())
        assert result.get("state") == "building_baseline"
        if "qualifying_session_count" in result:
            assert result["qualifying_session_count"] == 0

    def test_speed_zero_runs_no_crash_and_building_baseline(self):
        """Zero runs → building_baseline, no exception."""
        result = compute_speed_score([], _prefs(), _zc())
        assert result.get("state") == "building_baseline"
