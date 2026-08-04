"""Tests for issue #1523 — coach_plan timeline phase inversion guard.

Covers two edge cases that produce start_date > end_date before the fix:
  1. Available load (unlock_date == today): hold phase was inverted.
  2. Near-term race (<= ~10 weeks): ramp phase is inverted.
"""
from datetime import date, timedelta

from backend.services.coach_plan import build_plan_state

_TODAY = date(2026, 7, 17)
_RACE_DATE = date(2026, 12, 12)
_NEAR_RACE_DATE = _TODAY + timedelta(weeks=8)

_SNAPSHOT_OK = {"ctl": 60.0, "atl": 72.0, "acwr": 1.20, "tss_for_day": 45}
_SNAPSHOT_LOCKED = {"ctl": 60.0, "atl": 96.0, "acwr": 1.60, "tss_for_day": 45}

_GOAL = {"race_date": _RACE_DATE, "race_distance": "half"}
_NEAR_GOAL = {"race_date": _NEAR_RACE_DATE, "race_distance": "half"}
_WEIGHT = {"current_kg": 80.0, "goal_kg": 75.0, "gap_kg": 5.0}
_LOG = {"logged_days": 13, "total_days": 14}


def _make(goal=None, snapshot=_SNAPSHOT_OK, acwr_state="productive"):
    return build_plan_state(
        goal=goal if goal is not None else _GOAL,
        training_load_snapshot=snapshot,
        acwr_state=acwr_state,
        guardrail_state="ok",
        weight_status=_WEIGHT,
        log_consistency=_LOG,
        _today=_TODAY,
    )


# ── Available load (unlock_date == today) ────────────────────────────────────

def test_available_load_no_inverted_phases():
    """#1523: available load + far race → every phase has start_date <= end_date."""
    for p in _make()["timeline"]:
        assert p["start_date"] <= p["end_date"], (
            f"Phase '{p['name']}' inverted: {p['start_date']} > {p['end_date']}"
        )


# ── Near-term race (ramp inversion) ──────────────────────────────────────────

def test_near_term_race_ramp_absent_available_load():
    """#1523: 8-week race + available load → inverted ramp is dropped from timeline."""
    names = {p["name"] for p in _make(goal=_NEAR_GOAL)["timeline"]}
    assert "ramp" not in names, f"ramp should be absent for near-term race, got: {names}"


def test_near_term_race_ramp_absent_locked_load():
    """#1523: 8-week race + locked load → inverted ramp is also dropped."""
    names = {p["name"] for p in _make(goal=_NEAR_GOAL, snapshot=_SNAPSHOT_LOCKED, acwr_state="high_risk")["timeline"]}
    assert "ramp" not in names, f"ramp should be absent for near-term race, got: {names}"


def test_near_term_race_no_inverted_phases():
    """#1523: 8-week race + available load → every remaining phase has start <= end."""
    for p in _make(goal=_NEAR_GOAL)["timeline"]:
        assert p["start_date"] <= p["end_date"], (
            f"Phase '{p['name']}' inverted: {p['start_date']} > {p['end_date']}"
        )


def test_near_term_race_phases_chronologically_sorted():
    """#1523: 8-week race timeline is sorted by start_date after ramp is dropped."""
    timeline = _make(goal=_NEAR_GOAL)["timeline"]
    starts = [p["start_date"] for p in timeline]
    assert starts == sorted(starts), f"Timeline not sorted: {starts}"
