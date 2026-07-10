"""Tests for backend/services/training_verdict.py (Part B.2).

Pure function, no DB, no LLM — the verdict must be computable and testable
without any of that. See docs/calculations/acwr-guardrail.md for the
threshold rationale and the note on ACWR's contested injury-predictive
validity.
"""
from __future__ import annotations

from datetime import date

from backend.services.training_verdict import (
    ACWR_BACK_OFF_THRESHOLD,
    ACWR_HOLD_THRESHOLD,
    ATL_CTL_HOLD_RATIO,
    TSB_HOLD_FLOOR,
    compute_verdict,
)

_TODAY = date(2026, 7, 9)


def test_back_off_at_acwr_1_60():
    result = compute_verdict({"acwr": 1.60, "tsb": -16.8, "ctl": 32.0, "atl": 48.8}, today=_TODAY)
    assert result["verdict"] == "back_off"
    assert "1.60" in result["reason"]


def test_hold_at_acwr_1_35():
    result = compute_verdict({"acwr": 1.35, "tsb": -5.0, "ctl": 40.0, "atl": 50.0}, today=_TODAY)
    assert result["verdict"] == "hold"


def test_build_at_acwr_1_05_with_tsb_neg12():
    result = compute_verdict({"acwr": 1.05, "tsb": -12.0, "ctl": 40.0, "atl": 44.0}, today=_TODAY)
    assert result["verdict"] == "build"


def test_bug_report_snapshot_yields_back_off():
    """The exact numbers from the bug report: CTL 32, ATL 48.8, TSB -16.8,
    ACWR 1.60. Must resolve to back_off, unambiguously."""
    result = compute_verdict({"acwr": 1.60, "tsb": -16.8, "ctl": 32.0, "atl": 48.8}, today=_TODAY)
    assert result["verdict"] == "back_off"


def test_threshold_boundary_acwr_exactly_at_back_off_is_not_back_off():
    # Strictly greater-than semantics: exactly at the threshold is "hold", not "back_off".
    result = compute_verdict({"acwr": ACWR_BACK_OFF_THRESHOLD, "tsb": 0.0, "ctl": 40.0, "atl": 40.0}, today=_TODAY)
    assert result["verdict"] == "hold"


def test_threshold_boundary_acwr_exactly_at_hold_is_build():
    result = compute_verdict({"acwr": ACWR_HOLD_THRESHOLD, "tsb": 0.0, "ctl": 40.0, "atl": 40.0}, today=_TODAY)
    assert result["verdict"] == "build"


def test_hold_from_atl_ctl_ratio_even_when_acwr_is_low_or_missing():
    """ACWR alone can lag a fresh spike (its chronic window needs 28 days) —
    the ATL:CTL ratio catches what a missing/low ACWR would miss."""
    result = compute_verdict({"acwr": None, "tsb": -3.0, "ctl": 30.0, "atl": 45.0}, today=_TODAY)
    assert atl_over_ctl_ratio_triggers(result, 45.0, 30.0)


def atl_over_ctl_ratio_triggers(result, atl, ctl):
    assert atl > ATL_CTL_HOLD_RATIO * ctl
    return result["verdict"] == "hold" and "acute load well above chronic" in result["reason"]


def test_hold_from_deep_tsb_even_when_acwr_and_atl_ctl_are_fine():
    result = compute_verdict(
        {"acwr": 1.1, "tsb": TSB_HOLD_FLOOR - 1, "ctl": 40.0, "atl": 42.0}, today=_TODAY,
    )
    assert result["verdict"] == "hold"
    assert "TSB" in result["reason"]


def test_cold_start_first_workout_is_build_not_hold():
    """A brand-new user's (or a returning athlete's) FIRST workout always
    makes atl >> ctl and tsb deeply negative, purely because CTL starts at 0
    and rises slowly (42-day EWMA) while ATL reacts fast (7-day EWMA) — not
    because of real overreach. Without the _MIN_CTL_FOR_HOLD_GUARDS floor,
    compute_verdict would tell every new user to hold on day one: the same
    perpetual-flatline bug this fix removes, just moved to the verdict
    layer. Real numbers from a fresh single-workout snapshot."""
    result = compute_verdict({"acwr": None, "tsb": -19.44, "ctl": 6.57, "atl": 26.02}, today=_TODAY)
    assert result["verdict"] == "build"


def test_atl_ctl_ratio_guard_still_fires_once_ctl_is_established():
    below_floor = compute_verdict({"acwr": None, "tsb": -3.0, "ctl": 10.0, "atl": 20.0}, today=_TODAY)
    assert below_floor["verdict"] == "build"
    above_floor = compute_verdict({"acwr": None, "tsb": -3.0, "ctl": 20.0, "atl": 40.0}, today=_TODAY)
    assert above_floor["verdict"] == "hold"


def test_build_verdict_has_no_convergence_fields():
    result = compute_verdict({"acwr": 1.0, "tsb": 2.0, "ctl": 40.0, "atl": 38.0}, today=_TODAY)
    assert result["verdict"] == "build"
    assert result["expected_ctl_in_3w"] is None
    assert result["weeks_to_converge"] is None
    assert result["converge_date"] is None


def test_non_build_verdict_has_convergence_fields():
    result = compute_verdict({"acwr": 1.6, "tsb": -16.8, "ctl": 32.0, "atl": 48.8}, today=_TODAY)
    assert result["expected_ctl_in_3w"] is not None
    assert result["weeks_to_converge"] is not None
    assert result["converge_date"] is not None


def test_convergence_from_bug_report_state_is_2_to_4_weeks():
    """From CTL 32 / ATL 48.8 holding current load, weeks_to_converge must
    be a genuine near-term estimate — not 0 (nothing to converge from) and
    not something absurd like 12+ weeks for a gap this size."""
    result = compute_verdict({"acwr": 1.6, "tsb": -16.8, "ctl": 32.0, "atl": 48.8}, today=_TODAY)
    assert 2 <= result["weeks_to_converge"] <= 4


def test_converge_date_is_today_plus_weeks_to_converge():
    result = compute_verdict({"acwr": 1.6, "tsb": -16.8, "ctl": 32.0, "atl": 48.8}, today=_TODAY)
    from datetime import timedelta
    expected = (_TODAY + timedelta(weeks=result["weeks_to_converge"])).isoformat()
    assert result["converge_date"] == expected


def test_expected_ctl_in_3w_is_higher_than_current_ctl_when_atl_exceeds_ctl():
    result = compute_verdict({"acwr": 1.6, "tsb": -16.8, "ctl": 32.0, "atl": 48.8}, today=_TODAY)
    assert result["expected_ctl_in_3w"] > 32.0


def test_snapshot_values_passed_through_rounded():
    result = compute_verdict({"acwr": 1.234567, "tsb": -1.005, "ctl": 40.001, "atl": 41.009}, today=_TODAY)
    assert result["acwr"] == 1.234567  # acwr passed through as-is (already the canonical value)
    assert result["tsb"] == round(-1.005, 2)
    assert result["ctl"] == round(40.001, 2)
    assert result["atl"] == round(41.009, 2)
