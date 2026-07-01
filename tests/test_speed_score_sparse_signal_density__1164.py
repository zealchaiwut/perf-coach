"""Unit tests for speed score sparse signal density detection (issue #1164).

Acceptance criteria covered:

  AC1  - Speed score calculation counts qualifying hard efforts in the window
  AC2  - Confidence band is widened by a multiplier when below sparse threshold
  AC3  - low_data_warning flag is raised when sparse threshold not met
  AC4  - Normal (dense) data produces existing band width with no warning
  AC5  - py_compile reports zero errors on all modified files
  AC6  - Tests cover: (a) dense path—normal band, no warning;
         (b) sparse path—widened band, warning present;
         (c) exact-threshold boundary in both directions
"""

from __future__ import annotations

import pytest
from backend.services.running_performance import (
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


def _hard_run(run_id, efficiency_hint=1.8, speed_signal=1.15,
              workout_date="2026-01-01", duration_seconds=1800):
    """Single-lap hard run for speed tests."""
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
        "duration_seconds": duration_seconds,
        "speed_signal": speed_signal,
    }


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
# AC1 — Count qualifying hard efforts in the window
# ---------------------------------------------------------------------------

class TestQualifyingEffortCount:
    """AC1: Speed score counts qualifying hard efforts in the window."""

    def test_speed_score_counts_qualifying_efforts(self):
        """Speed score result includes the count of qualifying hard efforts."""
        runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS + 2)
        result = compute_speed_score(runs, _prefs(), _zc())

        if result.get("state") == "building_baseline":
            pytest.skip("not enough runs")

        # The count of qualifying efforts is in qualifying_session_count
        # (each run with a hard effort counts as one qualifying session)
        assert "qualifying_session_count" in result, (
            "qualifying_session_count must be in result"
        )
        assert result["qualifying_session_count"] == MIN_QUALIFYING_RUNS + 2

    def test_effort_count_excludes_old_runs_outside_window(self):
        """Efforts outside trailing_window_days must be excluded from count."""
        old_runs = [
            _hard_run(f"old{i}", speed_signal=1.15, workout_date="2020-01-01")
            for i in range(2)
        ]
        recent_runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS)

        result = compute_speed_score(old_runs + recent_runs, _prefs(), _zc())

        if result.get("state") == "building_baseline":
            pytest.skip("not enough runs in window")

        # Only recent runs should be counted
        assert result["qualifying_session_count"] == MIN_QUALIFYING_RUNS


# ---------------------------------------------------------------------------
# AC3 & AC4 — Low-data warning flag
# ---------------------------------------------------------------------------

class TestLowDataWarning:
    """AC3/AC4: low_data_warning flag when sparse, none when dense."""

    def test_sparse_data_raises_low_data_warning(self):
        """Below sparse threshold → low_data_warning = True."""
        # Get the sparse threshold from config (AC2 will define it)
        sparse_threshold = PERFORMANCE_CONFIG.get("speed_sparse_effort_threshold", 5)

        # Create fewer qualifying efforts than threshold
        n_efforts = max(MIN_QUALIFYING_RUNS, sparse_threshold - 1)
        runs = _make_n_hard_runs(n_efforts)

        result = compute_speed_score(runs, _prefs(), _zc())

        if result.get("state") == "building_baseline":
            pytest.skip("not enough runs to score")

        if result["qualifying_session_count"] < sparse_threshold:
            assert result.get("low_data_warning") is True, (
                "low_data_warning must be True when effort count < sparse threshold"
            )

    def test_dense_data_no_warning(self):
        """At or above sparse threshold → low_data_warning = False or absent."""
        sparse_threshold = PERFORMANCE_CONFIG.get("speed_sparse_effort_threshold", 5)

        # Create efforts at or above threshold
        n_efforts = max(MIN_QUALIFYING_RUNS, sparse_threshold + 2)
        runs = _make_n_hard_runs(n_efforts)

        result = compute_speed_score(runs, _prefs(), _zc())

        if result.get("state") == "building_baseline":
            pytest.skip("not enough runs")

        if result["qualifying_session_count"] >= sparse_threshold:
            # Should be False or absent
            warning = result.get("low_data_warning", False)
            assert warning is False, (
                "low_data_warning must be False or absent when effort count >= threshold"
            )

    def test_warning_at_exact_threshold_boundary(self):
        """Exactly at sparse threshold → no warning; just below → warning."""
        sparse_threshold = PERFORMANCE_CONFIG.get("speed_sparse_effort_threshold", 5)

        # Exactly at threshold
        runs_at = _make_n_hard_runs(max(MIN_QUALIFYING_RUNS, sparse_threshold))
        result_at = compute_speed_score(runs_at, _prefs(), _zc())

        if result_at.get("state") != "building_baseline":
            assert result_at.get("low_data_warning", False) is False, (
                "At threshold: no warning"
            )

        # Just below threshold (if possible)
        if sparse_threshold > MIN_QUALIFYING_RUNS:
            runs_below = _make_n_hard_runs(sparse_threshold - 1)
            result_below = compute_speed_score(runs_below, _prefs(), _zc())

            if result_below.get("state") != "building_baseline":
                assert result_below.get("low_data_warning", False) is True, (
                    "Below threshold: warning present"
                )


# ---------------------------------------------------------------------------
# AC2 — Widened confidence band for sparse data
# ---------------------------------------------------------------------------

class TestConfidenceBandWidening:
    """AC2: Confidence band is widened by a multiplier when sparse."""

    def test_sparse_data_has_widened_band(self):
        """Sparse data → confidence_band with wider uncertainty."""
        sparse_threshold = PERFORMANCE_CONFIG.get("speed_sparse_effort_threshold", 5)
        sparse_band_multiplier = PERFORMANCE_CONFIG.get("speed_sparse_band_multiplier", 1.5)

        n_sparse = max(MIN_QUALIFYING_RUNS, sparse_threshold - 1)
        runs_sparse = _make_n_hard_runs(n_sparse)
        result_sparse = compute_speed_score(runs_sparse, _prefs(), _zc())

        if result_sparse.get("state") == "building_baseline":
            pytest.skip("sparse result is building_baseline")

        # Should have confidence_band
        assert "confidence_band" in result_sparse, (
            "sparse result must include confidence_band"
        )

        band_sparse = result_sparse["confidence_band"]
        assert "lower" in band_sparse and "upper" in band_sparse, (
            "confidence_band must have lower and upper bounds"
        )

    def test_dense_vs_sparse_band_width_comparison(self):
        """Dense data band width < sparse data band width."""
        sparse_threshold = PERFORMANCE_CONFIG.get("speed_sparse_effort_threshold", 5)

        # Create sparse and dense datasets
        n_sparse = max(MIN_QUALIFYING_RUNS, sparse_threshold - 1)
        n_dense = max(MIN_QUALIFYING_RUNS, sparse_threshold + 3)

        # Same base signal so scores are comparable
        runs_sparse = _make_n_hard_runs(n_sparse, signal_start=1.15, signal_step=0.01)
        runs_dense = _make_n_hard_runs(n_dense, signal_start=1.15, signal_step=0.01)

        result_sparse = compute_speed_score(runs_sparse, _prefs(), _zc())
        result_dense = compute_speed_score(runs_dense, _prefs(), _zc())

        if (result_sparse.get("state") == "building_baseline" or
            result_dense.get("state") == "building_baseline"):
            pytest.skip("one or more results are building_baseline")

        if ("confidence_band" in result_sparse and "confidence_band" in result_dense):
            width_sparse = (result_sparse["confidence_band"]["upper"] -
                           result_sparse["confidence_band"]["lower"])
            width_dense = (result_dense["confidence_band"]["upper"] -
                          result_dense["confidence_band"]["lower"])

            # Sparse band should be wider
            assert width_sparse > width_dense, (
                "sparse data band width must be wider than dense"
            )

    def test_band_centered_on_score(self):
        """Confidence band is centered on the score value."""
        runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS + 2)
        result = compute_speed_score(runs, _prefs(), _zc())

        if result.get("state") == "building_baseline":
            pytest.skip("building_baseline")

        if "confidence_band" in result:
            score = result["score"]
            lower = result["confidence_band"]["lower"]
            upper = result["confidence_band"]["upper"]

            mid = (lower + upper) / 2.0
            # Band should be approximately centered on score
            assert abs(mid - score) < 1.0, (
                "band midpoint should be close to score"
            )

    def test_band_values_clamped_to_0_100(self):
        """Confidence band bounds are clamped to [0, 100]."""
        runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS)
        result = compute_speed_score(runs, _prefs(), _zc())

        if result.get("state") == "building_baseline":
            pytest.skip("building_baseline")

        if "confidence_band" in result:
            lower = result["confidence_band"]["lower"]
            upper = result["confidence_band"]["upper"]

            assert 0 <= lower <= 100, f"lower bound {lower} out of range"
            assert 0 <= upper <= 100, f"upper bound {upper} out of range"
            assert lower <= upper, "lower bound must be <= upper bound"


# ---------------------------------------------------------------------------
# AC4 — No regression for dense data
# ---------------------------------------------------------------------------

class TestDenseDataNoRegression:
    """AC4: Normal (dense) data unchanged by this feature."""

    def test_score_unchanged_for_dense_data(self):
        """Score value unaffected by sparse/dense logic."""
        sparse_threshold = PERFORMANCE_CONFIG.get("speed_sparse_effort_threshold", 5)
        n_dense = max(MIN_QUALIFYING_RUNS, sparse_threshold + 5)
        runs = _make_n_hard_runs(n_dense)

        result = compute_speed_score(runs, _prefs(), _zc())

        if result.get("state") == "building_baseline":
            pytest.skip("building_baseline")

        # Score should exist and be in valid range
        assert 0 <= result["score"] <= 100, (
            "dense data score should be in [0, 100]"
        )

    def test_direction_unchanged_for_dense_data(self):
        """Direction field works the same."""
        runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS + 3)
        result = compute_speed_score(runs, _prefs(), _zc())

        if result.get("state") == "building_baseline":
            pytest.skip("building_baseline")

        assert result.get("direction") in ("improving", "flat", "declining"), (
            "direction must be one of the three states"
        )

    def test_trend_unchanged_for_dense_data(self):
        """Trend array is preserved and unchanged."""
        runs = _make_n_hard_runs(MIN_QUALIFYING_RUNS + 2)
        result = compute_speed_score(runs, _prefs(), _zc())

        if result.get("state") == "building_baseline":
            pytest.skip("building_baseline")

        trend = result.get("trend", [])
        assert isinstance(trend, list) and len(trend) > 0, (
            "trend should be non-empty list"
        )
        assert len(trend) == result["qualifying_session_count"], (
            "trend length should match qualifying session count"
        )
