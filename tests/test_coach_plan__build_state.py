"""Tests for coach_plan.py (issue #1502).

AC coverage:
- AC1: build_plan_state() signature and top-level keys
- AC2: Load lever — state, reason with ACWR+TSS, unlock_date
- AC3: Weight lever — measurement/deficit sub-phases
- AC4: Timeline — 5 phases, ordered, non-overlapping
- AC5: cut-end boundary ≥ 9 weeks before race
- AC6: constraints is list of strings
- AC7: lever_ranking keys
- AC8: graceful degradation when goal=None
- AC9: No LLM imports (AST guard)
- AC10: simulate_acwr_convergence unit test
- AC11: periodization from December race date
- AC12: measurement → deficit transition
- AC13: deficit cap during ramp / lifted outside ramp
"""
import ast
import pathlib
from datetime import date, timedelta

import pytest

from backend.services.coach_plan import build_plan_state, simulate_acwr_convergence

# ── Shared fixtures ────────────────────────────────────────────────────────────
_RACE_DATE = date(2026, 12, 12)
_TODAY = date(2026, 7, 17)

_SNAPSHOT_LOCKED = {"ctl": 60.0, "atl": 96.0, "acwr": 1.60, "tss_for_day": 45}
_SNAPSHOT_OK = {"ctl": 60.0, "atl": 72.0, "acwr": 1.20, "tss_for_day": 45}

_GOAL = {"race_date": _RACE_DATE, "race_distance": "half"}
_WEIGHT = {"current_kg": 80.0, "goal_kg": 75.0, "gap_kg": 5.0}
_LOG_ABOVE = {"logged_days": 13, "total_days": 14}
_LOG_BELOW = {"logged_days": 11, "total_days": 14}


def _make_state(
    snapshot=None,
    acwr_state="productive",
    guardrail_state="ok",
    log_consistency=None,
    goal=None,
    weight_status=None,
    today=_TODAY,
):
    return build_plan_state(
        goal=goal if goal is not None else _GOAL,
        training_load_snapshot=snapshot if snapshot is not None else _SNAPSHOT_OK,
        acwr_state=acwr_state,
        guardrail_state=guardrail_state,
        weight_status=weight_status if weight_status is not None else _WEIGHT,
        log_consistency=log_consistency if log_consistency is not None else _LOG_ABOVE,
        _today=today,
    )


# ── AC9: No LLM import guard ───────────────────────────────────────────────────

def test_no_llm_imports():
    """AC9: coach_plan.py must not import any LLM client module."""
    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "backend" / "services" / "coach_plan.py"
    )
    tree = ast.parse(source.read_text())
    llm_modules = {"anthropic", "openai", "langchain", "litellm"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in llm_modules, (
                    f"coach_plan.py imported LLM module '{top}' — forbidden"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                assert top not in llm_modules, (
                    f"coach_plan.py imported from LLM module '{top}' — forbidden"
                )


# ── AC1: Top-level keys ────────────────────────────────────────────────────────

def test_build_plan_state_returns_required_keys():
    """AC1: Return dict has levers, timeline, constraints, lever_ranking."""
    result = _make_state()
    assert set(result.keys()) >= {"levers", "timeline", "constraints", "lever_ranking"}


def test_levers_has_load_and_weight():
    """AC1: levers dict contains load and weight sub-dicts."""
    result = _make_state()
    assert "load" in result["levers"]
    assert "weight" in result["levers"]


# ── AC2: Load lever locked ─────────────────────────────────────────────────────

def test_load_lever_locked_state():
    """AC2: ACWR 1.60 → load lever state == 'locked'."""
    result = _make_state(snapshot=_SNAPSHOT_LOCKED, acwr_state="high_risk")
    assert result["levers"]["load"]["state"] == "locked"


def test_load_lever_reason_contains_acwr_and_tss():
    """AC2: Locked reason includes numeric ACWR and current TSS."""
    result = _make_state(snapshot=_SNAPSHOT_LOCKED, acwr_state="high_risk")
    lever = result["levers"]["load"]
    assert "1.60" in lever["reason"]
    # weekly TSS = tss_for_day * 7 = 45 * 7 = 315 (shown as ~315)
    assert "315" in lever["reason"]


def test_load_lever_unlock_date_is_future():
    """AC2: unlock_date is a future date when load is locked."""
    result = _make_state(snapshot=_SNAPSHOT_LOCKED, acwr_state="high_risk", today=_TODAY)
    unlock = result["levers"]["load"]["unlock_date"]
    assert isinstance(unlock, date)
    assert unlock > _TODAY


def test_load_lever_unlock_date_within_12_weeks():
    """AC2: unlock_date is capped at 12 weeks from today."""
    result = _make_state(snapshot=_SNAPSHOT_LOCKED, acwr_state="high_risk", today=_TODAY)
    unlock = result["levers"]["load"]["unlock_date"]
    assert unlock <= _TODAY + timedelta(weeks=12)


# ── AC2: Load lever available ──────────────────────────────────────────────────

def test_load_lever_available_when_acwr_below_threshold():
    """AC2: ACWR 1.20 → load lever state == 'available'."""
    result = _make_state(snapshot=_SNAPSHOT_OK, acwr_state="productive")
    assert result["levers"]["load"]["state"] == "available"


# ── AC10: simulate_acwr_convergence ───────────────────────────────────────────

def test_simulate_acwr_convergence_returns_date():
    """AC10: simulate_acwr_convergence returns a date object."""
    result = simulate_acwr_convergence(
        atl=96.0, ctl=60.0, current_daily_tss=316 / 7, today=_TODAY
    )
    assert isinstance(result, date)


def test_simulate_acwr_convergence_known_fixture():
    """AC10: ATL=96 CTL=60 daily_tss=316/7 converges on day 4 (today + 4 days).

    Manual computation using EWMA math (alpha_atl ≈ 0.1331, alpha_ctl ≈ 0.0235):
    Day 1: acwr ≈ 1.496  Day 2: ≈ 1.406  Day 3: ≈ 1.327  Day 4: ≈ 1.259 < 1.30
    """
    result = simulate_acwr_convergence(
        atl=96.0, ctl=60.0, current_daily_tss=316 / 7, today=_TODAY
    )
    expected = _TODAY + timedelta(days=4)
    assert result == expected, f"Expected {expected}, got {result}"


def test_simulate_acwr_convergence_already_below_threshold():
    """AC10: When current ATL/CTL < 1.30, returns today (day 0 or day 1)."""
    # atl/ctl = 70/60 ≈ 1.167 < 1.30 — already converged
    result = simulate_acwr_convergence(
        atl=70.0, ctl=60.0, current_daily_tss=45.0, today=_TODAY
    )
    assert result <= _TODAY + timedelta(days=1)


def test_simulate_acwr_convergence_cap_respected():
    """AC10: Cap fires when convergence would exceed max_weeks.

    ATL=500, CTL=60, daily_tss=45 → ACWR still ≈ 3.7 after 7 days.
    Passing max_weeks=1 forces the cap to return today + 7 days.
    """
    result = simulate_acwr_convergence(
        atl=500.0,
        ctl=60.0,
        current_daily_tss=45.0,
        today=_TODAY,
        max_weeks=1,
    )
    assert result == _TODAY + timedelta(weeks=1)


# ── AC11: Periodization from December race ─────────────────────────────────────

def _get_timeline(today=_TODAY, snapshot=_SNAPSHOT_OK):
    result = _make_state(snapshot=snapshot, today=today)
    return result["timeline"]


def test_periodization_all_five_phases_present():
    """AC11: Timeline contains exactly the 5 named phases."""
    timeline = _get_timeline()
    names = {p["name"] for p in timeline}
    assert names == {"hold", "ramp", "cut-end", "peak block", "taper"}


def test_periodization_phases_have_required_keys():
    """AC11: Each phase has name, start_date, end_date, directive."""
    for phase in _get_timeline():
        assert "name" in phase
        assert "start_date" in phase
        assert "end_date" in phase
        assert "directive" in phase
        assert isinstance(phase["directive"], str)
        assert len(phase["directive"]) > 0


def test_periodization_chronologically_ordered():
    """AC11: Phases are in chronological start_date order."""
    timeline = _get_timeline()
    starts = [p["start_date"] for p in timeline]
    assert starts == sorted(starts)


def test_periodization_non_overlapping():
    """AC11: No two consecutive phases overlap (end_date of phase i < start_date of phase i+1)."""
    timeline = _get_timeline()
    for i in range(len(timeline) - 1):
        assert timeline[i]["end_date"] < timeline[i + 1]["start_date"], (
            f"Phase '{timeline[i]['name']}' overlaps '{timeline[i+1]['name']}'"
        )


def test_periodization_taper_ends_on_race_date():
    """AC11: taper.end_date == race_date."""
    timeline = _get_timeline()
    taper = next(p for p in timeline if p["name"] == "taper")
    assert taper["end_date"] == _RACE_DATE


def test_periodization_taper_is_14_days():
    """AC11: Taper spans 14 days."""
    timeline = _get_timeline()
    taper = next(p for p in timeline if p["name"] == "taper")
    assert (taper["end_date"] - taper["start_date"]).days == 14


def test_periodization_cut_end_boundary_at_least_9_weeks():
    """AC11: cut-end.end_date ≤ race_date - 63 days (≥ 9 weeks before race)."""
    timeline = _get_timeline()
    cut_end = next(p for p in timeline if p["name"] == "cut-end")
    nine_weeks_before = _RACE_DATE - timedelta(days=63)
    assert cut_end["end_date"] <= nine_weeks_before, (
        f"cut-end ends {cut_end['end_date']}, but must be ≤ {nine_weeks_before}"
    )


# ── AC12: Weight lever measurement → deficit transition ───────────────────────

def test_weight_lever_measurement_when_below_threshold():
    """AC12: logged_days=11 → active (measurement), no deficit recommended."""
    result = _make_state(log_consistency={"logged_days": 11, "total_days": 14})
    wl = result["levers"]["weight"]
    assert wl["state"] == "active (measurement)"
    assert "recommended_deficit_kcal" not in wl


def test_weight_lever_deficit_when_at_threshold():
    """AC12: logged_days=12 → active (deficit) when ramp not active."""
    # Use locked snapshot so ramp is NOT active (today is in hold phase)
    result = _make_state(
        snapshot=_SNAPSHOT_LOCKED,
        acwr_state="high_risk",
        log_consistency={"logged_days": 12, "total_days": 14},
    )
    wl = result["levers"]["weight"]
    assert wl["state"] == "active (deficit)"


def test_weight_lever_deficit_in_300_400_range_outside_ramp():
    """AC12: Recommended deficit is 300–400 kcal when ramp not active."""
    # Locked snapshot → hold phase (ramp not active)
    result = _make_state(
        snapshot=_SNAPSHOT_LOCKED,
        acwr_state="high_risk",
        log_consistency={"logged_days": 13, "total_days": 14},
    )
    deficit = result["levers"]["weight"]["recommended_deficit_kcal"]
    assert 300 <= deficit <= 400, f"Expected 300–400 kcal, got {deficit}"


# ── AC13: Deficit cap during ramp ─────────────────────────────────────────────

def test_deficit_capped_when_ramp_active():
    """AC13: Deficit is capped (< 300 kcal or 0) when ramp phase is active.

    Ramp is active when unlock_date <= today < cut_end_start.
    Using _SNAPSHOT_OK (ACWR=1.20), unlock_date = today → ramp starts today.
    Today (Jul 17) < cut_end_start (Dec 12 - 70 = Oct 3) → ramp is active.
    """
    result = _make_state(
        snapshot=_SNAPSHOT_OK,
        acwr_state="productive",
        log_consistency={"logged_days": 13, "total_days": 14},
        today=_TODAY,
    )
    wl = result["levers"]["weight"]
    assert wl["state"] == "active (deficit)"
    deficit = wl["recommended_deficit_kcal"]
    assert deficit < 300, f"Expected deficit < 300 during ramp, got {deficit}"


def test_deficit_cap_lifted_when_ramp_not_active():
    """AC13: Deficit is 300–400 kcal when ramp phase is not active (hold phase)."""
    # Locked snapshot → unlock_date is in the future → today is in hold → ramp not active
    result = _make_state(
        snapshot=_SNAPSHOT_LOCKED,
        acwr_state="high_risk",
        log_consistency={"logged_days": 13, "total_days": 14},
        today=_TODAY,
    )
    wl = result["levers"]["weight"]
    assert wl["state"] == "active (deficit)"
    deficit = wl["recommended_deficit_kcal"]
    assert 300 <= deficit <= 400, f"Expected 300–400 kcal outside ramp, got {deficit}"


def test_constraints_includes_ramp_cap_string_when_ramp_active():
    """AC13 (UAT step 5): constraints list references ramp cap when ramp is active."""
    result = _make_state(
        snapshot=_SNAPSHOT_OK,
        acwr_state="productive",
        log_consistency={"logged_days": 13, "total_days": 14},
        today=_TODAY,
    )
    constraints = result["constraints"]
    assert any("ramp" in c.lower() or "deficit" in c.lower() for c in constraints), (
        f"Expected a ramp-related constraint, got: {constraints}"
    )


# ── AC6: constraints ───────────────────────────────────────────────────────────

def test_constraints_is_list_of_strings():
    """AC6: constraints is a list of plain-English strings."""
    result = _make_state()
    c = result["constraints"]
    assert isinstance(c, list)
    for item in c:
        assert isinstance(item, str)


# ── AC7: lever_ranking ─────────────────────────────────────────────────────────

def test_lever_ranking_has_required_keys():
    """AC7: lever_ranking contains bigger_lever, more_tractable, rationale."""
    result = _make_state()
    lr = result["lever_ranking"]
    assert "bigger_lever" in lr
    assert "more_tractable" in lr
    assert "rationale" in lr


def test_lever_ranking_values_are_valid():
    """AC7: bigger_lever and more_tractable are 'load' or 'weight'."""
    result = _make_state()
    lr = result["lever_ranking"]
    assert lr["bigger_lever"] in ("load", "weight")
    assert lr["more_tractable"] in ("load", "weight")
    assert isinstance(lr["rationale"], str)


# ── AC8: Graceful degradation when goal=None ──────────────────────────────────

def test_goal_none_no_exception():
    """AC8: goal=None returns without raising an exception."""
    try:
        result = build_plan_state(
            goal=None,
            training_load_snapshot=_SNAPSHOT_LOCKED,
            acwr_state="high_risk",
            guardrail_state="warn",
            weight_status=_WEIGHT,
            log_consistency=_LOG_ABOVE,
        )
    except Exception as exc:
        pytest.fail(f"build_plan_state raised with goal=None: {exc}")


def test_goal_none_returns_unavailable_load():
    """AC8: goal=None → levers.load has state indicating unavailability."""
    result = build_plan_state(
        goal=None,
        training_load_snapshot=_SNAPSHOT_LOCKED,
        acwr_state="high_risk",
        guardrail_state="warn",
        weight_status=_WEIGHT,
        log_consistency=_LOG_ABOVE,
    )
    state = result["levers"]["load"]["state"]
    assert "unavailable" in state.lower() or state in ("unavailable",)


def test_goal_none_returns_required_structure():
    """AC8: goal=None still returns dict with all four top-level keys."""
    result = build_plan_state(
        goal=None,
        training_load_snapshot=None,
        acwr_state="productive",
        guardrail_state="ok",
        weight_status=None,
        log_consistency=None,
    )
    assert set(result.keys()) >= {"levers", "timeline", "constraints", "lever_ranking"}
