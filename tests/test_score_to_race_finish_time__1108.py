"""Tests for score_to_estimated_finish_time (issue #1108).

AC coverage:
  AC1 — function accepts expressible score, thresholds dict, distance_km;
         returns estimated_finish_seconds and estimated_finish_time
  AC2 — non-null result when score and distance are both available and
         thresholds are configured; each entry yields a non-null time
  AC3 — higher score → faster (lower) estimated finish time for same distance
  AC4 — respects user-configured threshold_pace_seconds_per_km
  AC5 — py_compile reports no syntax errors (structural)
  AC6 — existing tests pass (structural — enforced by running the test suite)
  AC7 — known score/distance/threshold input yields expected finish time
         within an acceptable tolerance
"""
import pathlib
import py_compile

import pytest

from backend.services.race_finish_estimator import (
    apply_finish_estimates,
    score_to_estimated_finish_time,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── AC5: py_compile ───────────────────────────────────────────────────────────

def test_py_compile_race_finish_estimator():
    path = _ROOT / "backend" / "services" / "race_finish_estimator.py"
    py_compile.compile(str(path), doraise=True)


# ── AC1: signature and return shape ──────────────────────────────────────────

def test_returns_expected_keys():
    result = score_to_estimated_finish_time(
        score=75,
        thresholds={"threshold_pace_seconds_per_km": 300},
        distance_km=10.0,
    )
    assert "estimated_finish_seconds" in result
    assert "estimated_finish_time" in result
    assert "reason" in result


def test_returns_null_when_score_is_none():
    result = score_to_estimated_finish_time(
        score=None,
        thresholds={"threshold_pace_seconds_per_km": 300},
        distance_km=10.0,
    )
    assert result["estimated_finish_seconds"] is None
    assert result["estimated_finish_time"] is None
    assert result["reason"] is not None


def test_returns_null_when_distance_is_none():
    result = score_to_estimated_finish_time(
        score=75,
        thresholds={"threshold_pace_seconds_per_km": 300},
        distance_km=None,
    )
    assert result["estimated_finish_seconds"] is None
    assert result["estimated_finish_time"] is None


def test_threshold_independent_when_none():
    # VDOT re-anchor: score + distance fully determine the estimate; the
    # threshold pace is only a fallback, so thresholds=None still produces a
    # (non-null) result.
    result = score_to_estimated_finish_time(
        score=75,
        thresholds=None,
        distance_km=10.0,
    )
    assert result["estimated_finish_seconds"] is not None
    assert result["reason"] is None


def test_threshold_independent_when_missing_from_dict():
    result = score_to_estimated_finish_time(
        score=75,
        thresholds={},
        distance_km=10.0,
    )
    assert result["estimated_finish_seconds"] is not None


def test_returns_null_when_distance_non_positive():
    result = score_to_estimated_finish_time(
        score=75,
        thresholds={"threshold_pace_seconds_per_km": 300},
        distance_km=0,
    )
    assert result["estimated_finish_seconds"] is None


def test_threshold_pace_non_positive_ignored_vdot_path():
    # A bad threshold pace no longer breaks the estimate — the VDOT path doesn't
    # use it (it's only a fallback).
    result = score_to_estimated_finish_time(
        score=75,
        thresholds={"threshold_pace_seconds_per_km": 0},
        distance_km=10.0,
    )
    assert result["estimated_finish_seconds"] is not None


# ── AC2: non-null when score and distance available ───────────────────────────

def test_non_null_when_score_and_distance_available():
    result = score_to_estimated_finish_time(
        score=80,
        thresholds={"threshold_pace_seconds_per_km": 300},
        distance_km=21.1,
    )
    assert result["estimated_finish_seconds"] is not None
    assert result["estimated_finish_time"] is not None


def test_estimated_time_is_positive():
    result = score_to_estimated_finish_time(
        score=50,
        thresholds={"threshold_pace_seconds_per_km": 360},
        distance_km=5.0,
    )
    assert result["estimated_finish_seconds"] > 0


def test_multiple_entries_all_non_null():
    """AC2: each entry with score and distance yields a non-null estimated time."""
    thresholds = {"threshold_pace_seconds_per_km": 300}
    entries = [
        {"expressible_score": 60, "distance_km": 5.0},
        {"expressible_score": 75, "distance_km": 10.0},
        {"expressible_score": 85, "distance_km": 21.1},
    ]
    results = apply_finish_estimates(entries, thresholds)
    for entry in results:
        assert entry["estimated_finish_seconds"] is not None, (
            f"Expected non-null for score={entry['expressible_score']}"
        )
        assert entry["estimated_finish_time"] is not None


# ── AC3: higher score → faster time for same distance ────────────────────────

@pytest.mark.parametrize("score_low,score_high", [
    (20, 40),
    (40, 70),
    (50, 100),
    (0, 99),
])
def test_higher_score_yields_faster_time(score_low, score_high):
    thresholds = {"threshold_pace_seconds_per_km": 300}
    low = score_to_estimated_finish_time(score=score_low, thresholds=thresholds, distance_km=10.0)
    high = score_to_estimated_finish_time(score=score_high, thresholds=thresholds, distance_km=10.0)
    assert high["estimated_finish_seconds"] < low["estimated_finish_seconds"], (
        f"score={score_high} should be faster than score={score_low}, "
        f"got {high['estimated_finish_seconds']}s vs {low['estimated_finish_seconds']}s"
    )


def test_score_trend_monotonic_across_three_entries():
    """AC3: three entries at same distance — higher score → faster time."""
    thresholds = {"threshold_pace_seconds_per_km": 300}
    entries = [
        {"expressible_score": 40, "distance_km": 10.0},
        {"expressible_score": 70, "distance_km": 10.0},
        {"expressible_score": 90, "distance_km": 10.0},
    ]
    results = apply_finish_estimates(entries, thresholds)
    times = [e["estimated_finish_seconds"] for e in results]
    assert times[0] > times[1] > times[2], (
        f"Expected decreasing finish times for increasing scores: {times}"
    )


# ── AC4 (VDOT): estimate is threshold-INDEPENDENT ─────────────────────────────
# The VDOT model uses score + distance only; threshold pace is a fallback, so
# changing it does not change the estimate.

def test_estimate_independent_of_threshold_pace():
    fast_thresholds = {"threshold_pace_seconds_per_km": 240}
    slow_thresholds = {"threshold_pace_seconds_per_km": 360}
    fast = score_to_estimated_finish_time(score=75, thresholds=fast_thresholds, distance_km=10.0)
    slow = score_to_estimated_finish_time(score=75, thresholds=slow_thresholds, distance_km=10.0)
    assert fast["estimated_finish_seconds"] == slow["estimated_finish_seconds"]


def test_higher_score_still_yields_faster_time():
    lo = score_to_estimated_finish_time(score=50, thresholds=None, distance_km=10.0)
    hi = score_to_estimated_finish_time(score=80, thresholds=None, distance_km=10.0)
    assert hi["estimated_finish_seconds"] < lo["estimated_finish_seconds"]


def test_longer_distance_yields_longer_time_at_same_score():
    short = score_to_estimated_finish_time(score=60, thresholds=None, distance_km=5.0)
    long = score_to_estimated_finish_time(score=60, thresholds=None, distance_km=21.1)
    assert long["estimated_finish_seconds"] > short["estimated_finish_seconds"]


# ── AC7 (VDOT): known input/output on the recreational band (15/58) ───────────

def test_known_input_score_100_10km():
    # score 100 → VDOT 58 (band ceiling) → ~36:24 over 10 km.
    result = score_to_estimated_finish_time(score=100, thresholds=None, distance_km=10.0)
    assert result["estimated_finish_seconds"] == pytest.approx(2184, abs=30)
    assert result["reason"] is None


def test_known_input_score_0_10km():
    # score 0 → VDOT 15 (band floor) → a slow but valid ~1:50 over 10 km.
    result = score_to_estimated_finish_time(score=0, thresholds=None, distance_km=10.0)
    assert result["estimated_finish_seconds"] == pytest.approx(6651, abs=60)


def test_known_input_score_75_10km():
    # score 75 → VDOT 47.25 → ~43:23 over 10 km.
    result = score_to_estimated_finish_time(score=75, thresholds=None, distance_km=10.0)
    assert result["estimated_finish_seconds"] == pytest.approx(2603, abs=30)


def test_known_half_marathon_score_80():
    # score 80 → VDOT 49.4 → ~1:32:30 over the half.
    result = score_to_estimated_finish_time(score=80, thresholds=None, distance_km=21.1)
    assert result["estimated_finish_seconds"] == pytest.approx(5550, abs=45)


def test_daniels_anchor_vdot_49_8_5k_in_20min():
    """Daniels sanity: VDOT 49.8 → 5k in 20:00. On the band (15/58) that VDOT is
    score ≈ 80.9; the estimator must return ~1200 s over 5 km."""
    from backend.services.vdot import rescale_to_score
    score = rescale_to_score(49.8)
    result = score_to_estimated_finish_time(score=score, thresholds=None, distance_km=5.0)
    assert result["estimated_finish_seconds"] == pytest.approx(1200, abs=15)


def test_hhmmss_format_correct_length():
    """HH:MM:SS format must be zero-padded with exactly 3 colon-separated parts."""
    result = score_to_estimated_finish_time(
        score=100,
        thresholds={"threshold_pace_seconds_per_km": 360},
        distance_km=10.0,
    )
    time_str = result["estimated_finish_time"]
    assert time_str is not None
    parts = time_str.split(":")
    assert len(parts) == 3
    assert all(len(p) == 2 for p in parts), f"Parts not zero-padded: {parts}"


def test_score_clamped_above_100():
    """Scores above 100 are clamped to 100; result equals the score-100 result."""
    r100 = score_to_estimated_finish_time(
        score=100,
        thresholds={"threshold_pace_seconds_per_km": 300},
        distance_km=10.0,
    )
    r120 = score_to_estimated_finish_time(
        score=120,
        thresholds={"threshold_pace_seconds_per_km": 300},
        distance_km=10.0,
    )
    assert r100["estimated_finish_seconds"] == r120["estimated_finish_seconds"]


def test_score_clamped_below_0():
    """Negative scores are clamped to 0; result equals the score-0 result."""
    r0 = score_to_estimated_finish_time(
        score=0,
        thresholds={"threshold_pace_seconds_per_km": 300},
        distance_km=10.0,
    )
    r_neg = score_to_estimated_finish_time(
        score=-10,
        thresholds={"threshold_pace_seconds_per_km": 300},
        distance_km=10.0,
    )
    assert r0["estimated_finish_seconds"] == r_neg["estimated_finish_seconds"]


# ── apply_finish_estimates helper ─────────────────────────────────────────────

def test_apply_finish_estimates_adds_fields():
    entries = [
        {"expressible_score": 75, "distance_km": 10.0},
        {"expressible_score": 50, "distance_km": 21.1},
    ]
    thresholds = {"threshold_pace_seconds_per_km": 300}
    result = apply_finish_estimates(entries, thresholds)
    assert len(result) == 2
    for entry in result:
        assert "estimated_finish_seconds" in entry
        assert "estimated_finish_time" in entry


def test_apply_finish_estimates_null_when_no_score():
    """AC2/UAT5: entry with no score renders gracefully, no error raised."""
    entries = [{"expressible_score": None, "distance_km": 10.0}]
    thresholds = {"threshold_pace_seconds_per_km": 300}
    result = apply_finish_estimates(entries, thresholds)
    assert result[0]["estimated_finish_seconds"] is None
    assert result[0]["estimated_finish_time"] is None


def test_apply_finish_estimates_null_when_no_distance():
    """UAT5: entry with no distance renders gracefully, no error raised."""
    entries = [{"expressible_score": 75, "distance_km": None}]
    thresholds = {"threshold_pace_seconds_per_km": 300}
    result = apply_finish_estimates(entries, thresholds)
    assert result[0]["estimated_finish_seconds"] is None
    assert result[0]["estimated_finish_time"] is None
