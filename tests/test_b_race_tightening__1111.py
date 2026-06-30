"""
Tests for issue #1111: Add B-race tightening hook to confidence band.

Acceptance criteria verified:
- AC1: Post-B-race confidence band is measurably narrower than pre-B-race band.
- AC2: A _recalibrate_from_race stub exists with TODO comment; raises
       NotImplementedError or returns without side effects.
- AC3: B-race hook is documented in the relevant module/function (docstring or
       inline comment explaining when and how narrowing is applied).
- AC4: python -m py_compile exits clean on all modified files.
- AC5: Existing unit tests for the confidence band continue to pass (ensured
       by not breaking existing function signatures).
- AC6: At least one test asserts band_width_post_b < band_width_pre_b given
       the same input conditions.
"""

import inspect
import py_compile
from datetime import date, timedelta


from backend.services.projection import (
    _recalibrate_from_race,
    confidence_band_days,
    project_fitness,
)

TODAY = date(2026, 6, 29)
B_RACE_DATE = TODAY - timedelta(days=7)   # B-race was 7 days ago
FUTURE_TARGET = TODAY + timedelta(days=14)


# ── AC4: py_compile passes ─────────────────────────────────────────────────────

def test_ac4_py_compile_projection():
    import backend.services.projection as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


# ── AC2: _recalibrate_from_race stub exists ────────────────────────────────────

def test_ac2_recalibrate_stub_exists():
    """_recalibrate_from_race must be importable from projection module."""
    assert callable(_recalibrate_from_race)


def test_ac2_recalibrate_stub_has_todo_comment():
    """Stub source must contain a 'TODO: calibration milestone' comment."""
    src = inspect.getsource(_recalibrate_from_race)
    assert "TODO" in src and "calibration" in src.lower(), (
        "_recalibrate_from_race must contain a TODO: calibration milestone comment"
    )


def test_ac2_recalibrate_stub_no_side_effects():
    """Calling the stub must either raise NotImplementedError or return without mutating."""
    try:
        result = _recalibrate_from_race()
        # If it doesn't raise, it must return None (no side effects)
        assert result is None or result == {}, (
            "stub must return None or empty dict if not raising"
        )
    except NotImplementedError:
        pass  # Acceptable per AC


# ── AC3: narrowing is documented ──────────────────────────────────────────────

def test_ac3_b_race_hook_documented():
    """The narrowing behavior must be described in confidence_band_days or project_fitness docstring."""
    import backend.services.projection as mod
    src = inspect.getsource(mod)
    assert "b_race" in src.lower() or "b-race" in src.lower(), (
        "projection module must mention B-race hook in comments or docstrings"
    )


# ── AC1 / AC6: post-B-race band is narrower ───────────────────────────────────

def test_ac6_band_width_post_b_narrower_than_pre_b():
    """Band with b_race_passed=True must be strictly narrower than b_race_passed=False."""
    horizon = 30
    band_pre_b = confidence_band_days(horizon, b_race_passed=False)
    band_post_b = confidence_band_days(horizon, b_race_passed=True)
    assert band_post_b < band_pre_b, (
        f"Expected post-B-race band ({band_post_b}) < pre-B-race band ({band_pre_b})"
    )


def test_ac6_post_b_band_still_positive():
    """Post-B-race band must remain positive for positive horizons."""
    band = confidence_band_days(14, b_race_passed=True)
    assert band > 0, f"Post-B-race band must be positive, got {band}"


def test_ac1_project_fitness_post_b_entries_narrower():
    """project_fitness entries after b_race_date must be narrower than without b_race_date."""
    planned = [50.0] * 20
    result_no_brace = project_fitness(
        planned_load=planned,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
    )
    result_with_brace = project_fitness(
        planned_load=planned,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
        b_race_date=B_RACE_DATE,  # B-race already passed
    )
    # Every projected day is after B_RACE_DATE, so all bands should be narrower
    for day in sorted(result_no_brace.keys()):
        if day > B_RACE_DATE:
            assert result_with_brace[day]["confidence_band"] < result_no_brace[day]["confidence_band"], (
                f"Post-B-race band on {day} should be narrower with b_race_date set"
            )


def test_ac1_project_fitness_pre_b_entries_unchanged():
    """project_fitness entries before or on b_race_date must be unchanged."""
    b_race = TODAY + timedelta(days=10)  # B-race is in the future
    planned = [50.0] * 20
    result_no_brace = project_fitness(
        planned_load=planned,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
    )
    result_with_brace = project_fitness(
        planned_load=planned,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
        b_race_date=b_race,
    )
    # Days before B-race should have unchanged bands
    for day in sorted(result_no_brace.keys()):
        if day <= b_race:
            assert result_with_brace[day]["confidence_band"] == result_no_brace[day]["confidence_band"], (
                f"Pre-B-race band on {day} should be unchanged"
            )


def test_ac1_no_b_race_date_unchanged():
    """Without b_race_date, project_fitness output is identical to original behavior."""
    planned = [40.0] * 10
    result = project_fitness(
        planned_load=planned,
        start_ctl=50.0,
        start_atl=60.0,
        start_date=TODAY,
    )
    result_none = project_fitness(
        planned_load=planned,
        start_ctl=50.0,
        start_atl=60.0,
        start_date=TODAY,
        b_race_date=None,
    )
    for day in result:
        assert result[day]["confidence_band"] == result_none[day]["confidence_band"]


def test_ac5_existing_confidence_band_signature_preserved():
    """confidence_band_days(horizon) with no extra arg must still work (backward compat)."""
    band = confidence_band_days(30)
    assert band > 0


def test_ac5_existing_project_fitness_signature_preserved():
    """project_fitness without b_race_date must still work as before."""
    result = project_fitness(
        planned_load=[50.0] * 5,
        start_ctl=60.0,
        start_atl=70.0,
        start_date=TODAY,
    )
    assert len(result) == 5
    for day, entry in result.items():
        assert "ctl" in entry
        assert "atl" in entry
        assert "tsb" in entry
        assert "confidence_band" in entry
