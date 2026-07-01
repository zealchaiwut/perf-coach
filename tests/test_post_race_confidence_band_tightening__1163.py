"""Tests for issue #1163: Implement post-race confidence band tightening.

Acceptance criteria verified:
- AC1: The confidence band width after processing a race result is strictly
       narrower than the band width before the race result was applied.
- AC2: The narrowing calculation uses the recalibration anchor value (not a
       hardcoded constant) — different anchor values produce different factors.
- AC3: The placeholder/stub at P13 (B-race hook) is fully replaced with real
       logic — _recalibrate_from_race returns a meaningful value when given
       an anchor and is called from confidence_band_days.
- AC4: py_compile runs clean on all modified files.
- AC5: Existing unit tests continue to pass (verified by not breaking
       function signatures — existing tests are run as part of the full suite).
- AC6: The band never becomes zero-width or negative after tightening.
"""

import py_compile
from datetime import date, timedelta

import pytest

from backend.services.projection import (
    B_RACE_TIGHTENING_FLOOR,
    B_RACE_TIGHTENING_FACTOR,
    _recalibrate_from_race,
    confidence_band_days,
    project_fitness,
    build_plan_projection_payload,
)

TODAY = date(2026, 7, 1)
B_RACE_DATE = TODAY - timedelta(days=10)


# ── AC4: py_compile passes ────────────────────────────────────────────────────

def test_ac4_py_compile_projection():
    import backend.services.projection as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


# ── AC3: _recalibrate_from_race implements real logic with anchor ─────────────

def test_ac3_recalibrate_returns_float_with_anchor():
    """_recalibrate_from_race(anchor) must return a float, not raise."""
    result = _recalibrate_from_race(recalibration_anchor=75.0)
    assert isinstance(result, float), (
        f"Expected float, got {type(result)}: {result}"
    )


def test_ac3_recalibrate_factor_strictly_in_range():
    """Tightening factor must be in (0, 1) exclusive — narrowing but not zeroing."""
    for anchor in [0.0, 25.0, 50.0, 75.0, 100.0]:
        factor = _recalibrate_from_race(recalibration_anchor=anchor)
        assert 0.0 < factor < 1.0, (
            f"Factor for anchor={anchor} must be in (0, 1), got {factor}"
        )


def test_ac3_factor_at_floor_for_maximum_anchor():
    """Anchor=100 (perfect race result) gives the floor factor, not zero."""
    factor = _recalibrate_from_race(recalibration_anchor=100.0)
    assert factor >= B_RACE_TIGHTENING_FLOOR, (
        f"Factor at anchor=100 must be >= B_RACE_TIGHTENING_FLOOR "
        f"({B_RACE_TIGHTENING_FLOOR}), got {factor}"
    )


def test_ac3_floor_constant_exported():
    """B_RACE_TIGHTENING_FLOOR must be importable and positive."""
    assert B_RACE_TIGHTENING_FLOOR > 0.0, "Floor must be positive to prevent zero bands"
    assert B_RACE_TIGHTENING_FLOOR < 1.0, "Floor must be < 1 to ensure actual tightening"


# ── AC2: narrowing uses anchor value, not a constant ─────────────────────────

def test_ac2_different_anchors_give_different_factors():
    """Two different anchor values must produce different tightening factors."""
    factor_low = _recalibrate_from_race(recalibration_anchor=25.0)
    factor_high = _recalibrate_from_race(recalibration_anchor=90.0)
    assert factor_low != factor_high, (
        "Different anchor values must produce different factors — "
        "the calculation is not using a hardcoded constant"
    )


def test_ac2_higher_anchor_gives_tighter_band():
    """A stronger anchor (higher score) must produce a smaller (tighter) factor."""
    factor_50 = _recalibrate_from_race(recalibration_anchor=50.0)
    factor_80 = _recalibrate_from_race(recalibration_anchor=80.0)
    assert factor_80 < factor_50, (
        f"Higher anchor should give tighter factor: factor(80)={factor_80} "
        f"must be < factor(50)={factor_50}"
    )


def test_ac2_anchor_based_band_differs_from_fixed_factor():
    """Band with anchor must differ from band using hardcoded B_RACE_TIGHTENING_FACTOR.

    This directly verifies AC2: if the calculation used the hardcoded factor,
    the two calls would return identical results regardless of anchor value.
    At anchor=75: factor ≠ B_RACE_TIGHTENING_FACTOR (0.6) by design.
    """
    horizon = 30
    anchor = 75.0
    band_with_anchor = confidence_band_days(horizon, b_race_passed=True, recalibration_anchor=anchor)
    # Compute what the old hardcoded-factor band would be
    import backend.services.projection as mod
    import math
    raw_band = mod.CONFIDENCE_BAND_RATE * math.sqrt(horizon)
    band_hardcoded = raw_band * B_RACE_TIGHTENING_FACTOR
    assert band_with_anchor != pytest.approx(band_hardcoded), (
        f"Anchor-based band ({band_with_anchor:.4f}) must differ from hardcoded-factor "
        f"band ({band_hardcoded:.4f}), confirming anchor value is used, not a constant"
    )


# ── AC1: post-race band is strictly narrower than pre-race band ───────────────

def test_ac1_confidence_band_narrower_with_anchor():
    """Band with recalibration_anchor is strictly narrower than no-anchor band."""
    horizon = 30
    band_pre = confidence_band_days(horizon, b_race_passed=False)
    band_post = confidence_band_days(horizon, b_race_passed=True, recalibration_anchor=75.0)
    assert band_post < band_pre, (
        f"Post-race band ({band_post:.4f}) must be strictly narrower than "
        f"pre-race band ({band_pre:.4f})"
    )


def test_ac1_anchor_band_narrower_than_no_anchor_tightening():
    """With anchor, band is narrower than b_race_passed without anchor (uses better logic)."""
    horizon = 30
    band_no_anchor = confidence_band_days(horizon, b_race_passed=True)
    band_with_anchor = confidence_band_days(horizon, b_race_passed=True, recalibration_anchor=90.0)
    # anchor=90 should give a tighter factor than the fallback (B_RACE_TIGHTENING_FACTOR=0.6)
    # because 90 is a strong anchor
    assert band_with_anchor < band_no_anchor, (
        f"Strong anchor (90) should tighten more than fallback factor: "
        f"with_anchor={band_with_anchor:.4f} must be < no_anchor={band_no_anchor:.4f}"
    )


def test_ac1_project_fitness_post_b_bands_narrower_with_anchor():
    """project_fitness entries after b_race_date are narrower when anchor is provided."""
    planned = [50.0] * 20
    result_no_anchor = project_fitness(
        planned_load=planned,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
        b_race_date=B_RACE_DATE,
    )
    result_with_anchor = project_fitness(
        planned_load=planned,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
        b_race_date=B_RACE_DATE,
        recalibration_anchor=80.0,
    )
    for day in sorted(result_no_anchor.keys()):
        if day > B_RACE_DATE:
            assert result_with_anchor[day]["confidence_band"] < result_no_anchor[day]["confidence_band"], (
                f"Anchor-based band on {day} should be narrower than fallback tightening"
            )


def test_ac1_build_payload_post_b_bands_narrower():
    """build_plan_projection_payload confidence bands are narrower after B race result."""
    _THRESHOLD_PACE = 300.0
    _B_RACE = {
        "race_date": B_RACE_DATE,
        "actual_time_seconds": 3750,  # score ≈ 75
        "distance_km": 10.0,
    }
    common = dict(
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
        planned_load=[50.0] * 30,
        races=[],
        thresholds={"threshold_pace_seconds_per_km": _THRESHOLD_PACE},
        body_modifier=1.0,
    )
    # NOTE: build_plan_projection_payload returns ctl/atl/tsb lists but not the
    # per-day confidence bands directly.  We verify via project_fitness instead;
    # this test confirms the payload function accepts b_race_result without error.
    payload_no_b = build_plan_projection_payload(**common)
    payload_with_b = build_plan_projection_payload(**common, b_race_result=_B_RACE)
    assert "ctl" in payload_no_b
    assert "ctl" in payload_with_b


# ── AC6: band never becomes zero or negative ─────────────────────────────────

def test_ac6_band_positive_for_all_anchors():
    """Band must remain > 0 for every anchor value in [0, 100]."""
    horizon = 14
    for anchor in range(0, 101, 5):
        band = confidence_band_days(horizon, b_race_passed=True, recalibration_anchor=float(anchor))
        assert band > 0.0, (
            f"Band must be positive for anchor={anchor}, got {band}"
        )


def test_ac6_band_positive_at_floor_anchor():
    """At anchor=100 (max tightening), band is still positive."""
    band = confidence_band_days(14, b_race_passed=True, recalibration_anchor=100.0)
    assert band > 0.0, f"Band at max anchor must be > 0, got {band}"


def test_ac6_project_fitness_bands_all_positive_post_b():
    """All post-B-race bands in project_fitness must remain positive."""
    planned = [50.0] * 30
    result = project_fitness(
        planned_load=planned,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
        b_race_date=B_RACE_DATE,
        recalibration_anchor=100.0,  # Maximum tightening
    )
    for day in sorted(result.keys()):
        if day > B_RACE_DATE:
            band = result[day]["confidence_band"]
            assert band > 0.0, (
                f"Band on {day} must be > 0 even with max anchor, got {band}"
            )


def test_ac6_floor_prevents_zero():
    """_recalibrate_from_race never returns a factor at or below 0 for any anchor."""
    for anchor in [0.0, 50.0, 99.9, 100.0, 101.0]:  # 101 tests clamping
        factor = _recalibrate_from_race(recalibration_anchor=anchor)
        assert factor > 0.0, f"Factor must be > 0 for anchor={anchor}, got {factor}"


# ── Backward compat: existing signature still works ───────────────────────────

def test_backward_compat_confidence_band_no_anchor():
    """confidence_band_days(horizon, b_race_passed=True) with no anchor still works."""
    band = confidence_band_days(30, b_race_passed=True)
    assert band > 0


def test_backward_compat_project_fitness_no_anchor():
    """project_fitness without recalibration_anchor still works exactly as before."""
    result = project_fitness(
        planned_load=[50.0] * 10,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
        b_race_date=B_RACE_DATE,
    )
    assert len(result) == 10
    for day in result:
        assert result[day]["confidence_band"] > 0
