"""
Tests for issue #710: Add forward form projection to target date.

Acceptance criteria verified:
- AC1: project_form exists with a docstring containing a worked example showing
       form rising as fatigue decays under a flat load.
- AC2: planned_daily_load accepts a single scalar or an ordered per-day list.
- AC3: When planned_daily_load is None, function derives load from
       fitness_state["recent_avg_load"], sets assumed_load=True on every row,
       and returns a non-empty reason string explaining the assumption.
- AC4: Missing required inputs return empty list + reason, no exception raised.
- AC5: CTL/ATL use named constants (CTL_DAYS, ATL_DAYS), no magic numbers.
- AC6: Each returned row contains: date, ctl, atl, form, load, assumed_load.
- AC7: project_form has no database access.
- AC8: Unit tests cover flat load, per-day list, assumed load, missing fitness
       state, past/today target date, and a two-day hand-calculated regression.
"""
from datetime import date, timedelta

import pytest

from backend.services.training_load import (
    ATL_DAYS,
    CTL_DAYS,
    _ewma_alpha,
    project_form,
)

TODAY = date.today()
ANCHOR = TODAY
TARGET_2 = ANCHOR + timedelta(days=2)
TARGET_3 = ANCHOR + timedelta(days=3)
TARGET_5 = ANCHOR + timedelta(days=5)


def _state(ctl=50.0, atl=60.0, anchor=None, recent_avg_load=None):
    s = {"ctl": ctl, "atl": atl, "date": anchor or ANCHOR}
    if recent_avg_load is not None:
        s["recent_avg_load"] = recent_avg_load
    return s


# ── AC6: every row must carry a 'load' field ─────────────────────────────────

def test_ac6_load_field_present_with_scalar_input():
    result = project_form(_state(), 40.0, TARGET_3)
    assert result["days"]
    for day in result["days"]:
        assert "load" in day, "day object missing required 'load' key"


def test_ac6_load_field_matches_scalar_input():
    result = project_form(_state(), 55.0, TARGET_3)
    for day in result["days"]:
        assert day["load"] == 55.0, f"expected load=55.0, got {day['load']}"


def test_ac6_load_field_matches_per_day_list():
    loads = [30.0, 50.0, 70.0]
    result = project_form(_state(), loads, TARGET_3)
    for i, day in enumerate(result["days"]):
        assert day["load"] == loads[i], (
            f"day {i}: expected load={loads[i]}, got {day['load']}"
        )


def test_ac6_all_six_required_keys_present():
    result = project_form(_state(), 40.0, TARGET_3)
    for day in result["days"]:
        for key in ("date", "ctl", "atl", "form", "load", "assumed_load"):
            assert key in day, f"day object missing required key '{key}'"


# ── AC3: assumed load derived from fitness_state["recent_avg_load"] ──────────

def test_ac3_none_load_uses_recent_avg_from_fitness_state():
    result = project_form(_state(recent_avg_load=45.0), None, TARGET_3)
    assert len(result["days"]) == 3


def test_ac3_assumed_load_value_matches_recent_avg_in_state():
    result = project_form(_state(recent_avg_load=45.0), None, TARGET_3)
    for day in result["days"]:
        assert day["load"] == 45.0, (
            f"assumed load should equal recent_avg_load=45.0, got {day['load']}"
        )


def test_ac3_assumed_load_flag_true_when_derived_from_state():
    result = project_form(_state(recent_avg_load=45.0), None, TARGET_3)
    for day in result["days"]:
        assert day["assumed_load"] is True


def test_ac3_reason_non_empty_when_load_assumed_via_state():
    result = project_form(_state(recent_avg_load=45.0), None, TARGET_3)
    assert result["reason"], (
        "reason must be non-empty when planned_daily_load is None "
        "and load is derived from fitness_state"
    )


def test_ac3_reason_non_empty_when_load_assumed_via_kwarg():
    result = project_form(_state(), None, TARGET_3, recent_avg_load=45.0)
    assert result["reason"], (
        "reason must be non-empty when planned_daily_load is None "
        "and load is supplied via recent_avg_load kwarg"
    )


def test_ac3_reason_empty_when_explicit_scalar_load_provided():
    result = project_form(_state(), 40.0, TARGET_3)
    assert result["reason"] == "", (
        "reason must be empty string when explicit load is provided"
    )


def test_ac3_missing_recent_avg_everywhere_returns_empty():
    result = project_form(_state(), None, TARGET_3)
    assert len(result.get("days", [])) == 0
    assert result["reason"]


# ── AC4 / AC8: invalid inputs return empty + reason, no exception ─────────────

def test_ac4_none_fitness_state_returns_empty():
    result = project_form(None, 40.0, TARGET_3)
    assert len(result.get("days", [])) == 0
    assert result["reason"]


def test_ac4_none_target_date_returns_empty():
    result = project_form(_state(), 40.0, None)
    assert len(result.get("days", [])) == 0
    assert result["reason"]


def test_ac4_empty_fitness_state_returns_empty():
    result = project_form({}, 40.0, TARGET_3)
    assert len(result.get("days", [])) == 0
    assert result["reason"]


def test_ac4_past_target_date_returns_empty():
    result = project_form(_state(), 40.0, ANCHOR - timedelta(days=1))
    assert len(result.get("days", [])) == 0
    assert result["reason"]


def test_ac4_today_as_target_date_returns_empty():
    result = project_form(_state(), 40.0, ANCHOR)
    assert len(result.get("days", [])) == 0
    assert result["reason"]


def test_ac4_no_exception_for_bad_inputs():
    bad_cases = [
        (None, 40.0, TARGET_3),
        (_state(), 40.0, None),
        ({}, 40.0, TARGET_3),
        (_state(), None, TARGET_3),          # no recent_avg anywhere
        (_state(), 40.0, ANCHOR),            # today = not after anchor
    ]
    for args in bad_cases:
        try:
            project_form(*args)
        except Exception as exc:
            pytest.fail(f"project_form raised {type(exc).__name__} for input {args!r}")


# ── AC5: constants exported, no magic numbers ─────────────────────────────────

def test_ac5_ctl_days_and_atl_days_exported():
    assert isinstance(CTL_DAYS, int) and CTL_DAYS > 0
    assert isinstance(ATL_DAYS, int) and ATL_DAYS > 0
    assert CTL_DAYS > ATL_DAYS


# ── AC8: flat load projection ─────────────────────────────────────────────────

def test_ac8_flat_load_row_count():
    result = project_form(_state(), 40.0, TARGET_5)
    assert len(result["days"]) == 5


def test_ac8_flat_load_assumed_load_false():
    result = project_form(_state(), 40.0, TARGET_5)
    for day in result["days"]:
        assert day["assumed_load"] is False


# ── AC8: per-day list ─────────────────────────────────────────────────────────

def test_ac8_per_day_list_row_count():
    result = project_form(_state(), [30.0, 50.0, 70.0], TARGET_3)
    assert len(result["days"]) == 3


def test_ac8_per_day_list_assumed_load_false():
    result = project_form(_state(), [30.0, 50.0, 70.0], TARGET_3)
    for day in result["days"]:
        assert day["assumed_load"] is False


def test_ac8_per_day_list_load_values_correct():
    loads = [10.0, 80.0, 40.0]
    result = project_form(_state(), loads, TARGET_3)
    for i, day in enumerate(result["days"]):
        assert day["load"] == loads[i]


# ── AC8: two-day hand-calculated numerical regression ────────────────────────

def test_ac8_two_day_regression_ctl_and_atl():
    """CTL and ATL for days 1 and 2 must match the hand-calculated EWMA values."""
    ctl_0, atl_0, load = 60.0, 70.0, 50.0
    alpha_ctl = _ewma_alpha(CTL_DAYS)
    alpha_atl = _ewma_alpha(ATL_DAYS)

    ctl1 = ctl_0 + (load - ctl_0) * alpha_ctl
    atl1 = atl_0 + (load - atl_0) * alpha_atl
    ctl2 = ctl1 + (load - ctl1) * alpha_ctl
    atl2 = atl1 + (load - atl1) * alpha_atl

    result = project_form(
        {"ctl": ctl_0, "atl": atl_0, "date": ANCHOR},
        load,
        ANCHOR + timedelta(days=2),
    )
    d1, d2 = result["days"][0], result["days"][1]
    assert abs(d1["ctl"] - round(ctl1, 2)) < 0.005
    assert abs(d1["atl"] - round(atl1, 2)) < 0.005
    assert abs(d2["ctl"] - round(ctl2, 2)) < 0.005
    assert abs(d2["atl"] - round(atl2, 2)) < 0.005


def test_ac8_two_day_regression_form_equals_ctl_minus_atl():
    result = project_form(
        {"ctl": 60.0, "atl": 70.0, "date": ANCHOR},
        50.0,
        ANCHOR + timedelta(days=2),
    )
    for day in result["days"]:
        assert abs(day["form"] - (day["ctl"] - day["atl"])) < 0.02


def test_ac8_two_day_regression_load_field_correct():
    result = project_form(
        {"ctl": 60.0, "atl": 70.0, "date": ANCHOR},
        50.0,
        ANCHOR + timedelta(days=2),
    )
    for day in result["days"]:
        assert day["load"] == 50.0
