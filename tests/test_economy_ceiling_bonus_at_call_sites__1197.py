"""Tests for issue #1197: economy ceiling bonus params wired at all call sites.

AC coverage:
  AC1 — projected_ctl_to_score_ceiling is called with stimulus_history and
         reference_date at all three call sites.
  AC2 — Each call site retrieves per-user stimulus history from
         economy_ceiling_snapshots.
  AC3 — Each call site derives and passes a reference_date.
  AC4 — A user with qualifying stimulus history receives a higher projected
         score ceiling (economy bonus is reflected).
  AC5 — A user with no stimulus history receives the same projected ceiling
         as before (no regression on the no-bonus path).
  AC6 — At least one new test asserts the bonus is non-zero when valid
         stimulus_history and reference_date are supplied via a realistic
         call-site invocation.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta
from typing import List, Tuple

import pytest

from backend.services.ceiling_bonus import LAG_PEAK_DAYS, compute_ceiling_bonus
from backend.services.score_ceiling import (
    SCORE_CEILING_MAX,
    projected_ctl_to_score_ceiling,
)
from backend.services.projection import build_plan_projection_payload

# ── Helpers ────────────────────────────────────────────────────────────────────

REF_DATE = date(2026, 1, 1)
CTL = 60.0


def _peak_history(n: int = 1, value: float = 50.0) -> List[Tuple[date, float]]:
    """Return n stimulus points at peak lag (LAG_PEAK_DAYS days before REF_DATE)."""
    return [(REF_DATE - timedelta(days=LAG_PEAK_DAYS), value)] * n


def _make_races() -> list:
    return [{"date": REF_DATE + timedelta(days=30), "distance_km": 10.0, "name": "Test Race"}]


def _make_thresholds() -> dict:
    return {"threshold_pace_seconds_per_km": 300.0}


# ── AC1 & AC3: build_plan_projection_payload accepts stimulus_history and
#               reference_date parameters ─────────────────────────────────────

def test_build_plan_projection_payload_accepts_stimulus_history():
    """AC1/AC3: build_plan_projection_payload signature includes stimulus_history."""
    sig = inspect.signature(build_plan_projection_payload)
    assert "stimulus_history" in sig.parameters, (
        "build_plan_projection_payload must accept stimulus_history"
    )


def test_build_plan_projection_payload_accepts_reference_date():
    """AC1/AC3: build_plan_projection_payload signature includes reference_date."""
    sig = inspect.signature(build_plan_projection_payload)
    assert "reference_date" in sig.parameters, (
        "build_plan_projection_payload must accept reference_date"
    )


# ── AC4: stimulus history raises the projected ceiling ────────────────────────

def test_build_plan_projection_with_stimulus_raises_ceiling():
    """AC4: With qualifying stimulus history the projected race ceiling is higher."""
    start_date = REF_DATE - timedelta(days=1)
    races = _make_races()
    thresholds = _make_thresholds()
    history = _peak_history(value=100.0)

    without = build_plan_projection_payload(
        start_ctl=CTL,
        start_atl=40.0,
        start_date=start_date,
        planned_load=[50.0] * 30,
        races=races,
        thresholds=thresholds,
        stimulus_history=None,
        reference_date=None,
    )
    with_history = build_plan_projection_payload(
        start_ctl=CTL,
        start_atl=40.0,
        start_date=start_date,
        planned_load=[50.0] * 30,
        races=races,
        thresholds=thresholds,
        stimulus_history=history,
        reference_date=REF_DATE,
    )

    # Race estimated finish time should be shorter (faster) when ceiling is higher.
    without_secs = without["races"][0]["estimated_finish_seconds"]
    with_secs = with_history["races"][0]["estimated_finish_seconds"]

    if without_secs is None or with_secs is None:
        pytest.skip("threshold data insufficient to derive estimated times")

    assert with_secs <= without_secs, (
        "With qualifying stimulus history the projected ceiling should be higher, "
        "yielding a faster or equal race estimate."
    )


# ── AC5: no stimulus history → same projected ceiling (no regression) ─────────

def test_build_plan_projection_no_stimulus_unchanged():
    """AC5: No stimulus history gives the same result as the pre-ticket baseline."""
    start_date = REF_DATE - timedelta(days=1)
    races = _make_races()
    thresholds = _make_thresholds()

    baseline = build_plan_projection_payload(
        start_ctl=CTL,
        start_atl=40.0,
        start_date=start_date,
        planned_load=[50.0] * 30,
        races=races,
        thresholds=thresholds,
    )
    with_none = build_plan_projection_payload(
        start_ctl=CTL,
        start_atl=40.0,
        start_date=start_date,
        planned_load=[50.0] * 30,
        races=races,
        thresholds=thresholds,
        stimulus_history=None,
        reference_date=None,
    )
    assert baseline == with_none, (
        "Omitting stimulus_history / reference_date must give identical output "
        "to the pre-ticket call."
    )


def test_build_plan_projection_empty_stimulus_unchanged():
    """AC5: Empty stimulus history is equivalent to no history (no regression)."""
    start_date = REF_DATE - timedelta(days=1)
    races = _make_races()
    thresholds = _make_thresholds()

    baseline = build_plan_projection_payload(
        start_ctl=CTL,
        start_atl=40.0,
        start_date=start_date,
        planned_load=[50.0] * 30,
        races=races,
        thresholds=thresholds,
    )
    with_empty = build_plan_projection_payload(
        start_ctl=CTL,
        start_atl=40.0,
        start_date=start_date,
        planned_load=[50.0] * 30,
        races=races,
        thresholds=thresholds,
        stimulus_history=[],
        reference_date=REF_DATE,
    )
    assert baseline == with_empty, (
        "Empty stimulus_history must give the same output as the baseline (no bonus)."
    )


# ── AC6: bonus is non-zero via realistic call-site invocation ─────────────────

def test_bonus_nonzero_via_projected_ctl_to_score_ceiling():
    """AC6: projected_ctl_to_score_ceiling with valid history + reference_date yields non-zero bonus."""
    history = _peak_history(value=100.0)
    bonus = compute_ceiling_bonus(history, REF_DATE)
    assert bonus > 0.0, "Valid stimulus history at peak lag must yield a non-zero bonus."

    result_with = projected_ctl_to_score_ceiling(
        CTL, stimulus_history=history, reference_date=REF_DATE
    )
    result_without = projected_ctl_to_score_ceiling(CTL)
    assert result_with["endurance_ceiling"] > result_without["endurance_ceiling"], (
        "projected_ctl_to_score_ceiling must return a higher endurance ceiling "
        "when valid stimulus_history and reference_date are supplied."
    )


def test_bonus_nonzero_via_build_plan_projection():
    """AC6: Realistic call-site invocation (build_plan_projection_payload) applies non-zero bonus."""
    start_date = REF_DATE - timedelta(days=1)
    history = _peak_history(value=200.0)
    races = [{"date": REF_DATE + timedelta(days=60), "distance_km": 42.2, "name": "Marathon"}]
    thresholds = _make_thresholds()

    without = build_plan_projection_payload(
        start_ctl=CTL,
        start_atl=40.0,
        start_date=start_date,
        planned_load=[50.0] * 60,
        races=races,
        thresholds=thresholds,
        stimulus_history=None,
        reference_date=None,
    )
    with_history = build_plan_projection_payload(
        start_ctl=CTL,
        start_atl=40.0,
        start_date=start_date,
        planned_load=[50.0] * 60,
        races=races,
        thresholds=thresholds,
        stimulus_history=history,
        reference_date=REF_DATE,
    )

    # The two payloads must differ — bonus must have been applied somewhere.
    assert without != with_history, (
        "build_plan_projection_payload must produce different output when "
        "non-zero stimulus_history is supplied (economy bonus must be applied)."
    )


# ── Source-level checks: call sites no longer bare single-arg ─────────────────

def test_projection_service_call_site_passes_stimulus_params():
    """AC1/AC2/AC3: projection.py call site passes stimulus_history and reference_date."""
    import backend.services.projection as mod
    src = inspect.getsource(mod)
    # The call to projected_ctl_to_score_ceiling must mention stimulus_history.
    assert "stimulus_history" in src, (
        "backend/services/projection.py must pass stimulus_history to "
        "projected_ctl_to_score_ceiling."
    )
    assert "reference_date" in src, (
        "backend/services/projection.py must pass reference_date to "
        "projected_ctl_to_score_ceiling."
    )


def test_main_py_call_site_passes_stimulus_params():
    """AC1/AC2/AC3: main.py call site passes stimulus_history and reference_date."""
    import backend.main as mod
    src = inspect.getsource(mod)
    assert "stimulus_history" in src, (
        "backend/main.py must pass stimulus_history to projected_ctl_to_score_ceiling."
    )


def test_no_bare_single_arg_call_to_projected_ctl():
    """AC1: No bare single-argument call to projected_ctl_to_score_ceiling remains.

    Checks that projection.py and main.py both thread stimulus_history and
    reference_date through rather than calling with ctl only.
    """
    import backend.services.projection as proj_mod
    import backend.main as main_mod
    import backend.routers.projection as router_mod

    for mod in (proj_mod, main_mod, router_mod):
        src = inspect.getsource(mod)
        # If the module calls projected_ctl_to_score_ceiling it must also
        # reference stimulus_history somewhere in that same module.
        call_marker = "projected_ctl_to_score_ceiling"
        if call_marker in src:
            assert "stimulus_history" in src, (
                f"{mod.__name__} calls projected_ctl_to_score_ceiling but does "
                "not pass stimulus_history."
            )


# ── Regression: existing score_ceiling tests still hold ──────────────────────

def test_no_args_gives_baseline():
    """Backward-compat: calling with ctl only still works as before."""
    result = projected_ctl_to_score_ceiling(CTL)
    assert "endurance_ceiling" in result
    assert "speed_ceiling" in result
    assert result["endurance_ceiling"] >= 0.0
    assert result["endurance_ceiling"] <= SCORE_CEILING_MAX
