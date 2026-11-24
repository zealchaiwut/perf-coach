"""Table-driven tests for plan rules engine (P3-9, #1843)."""
from __future__ import annotations

from datetime import date, timedelta

from backend.services.plan_rules_engine import (
    PlanSessionView,
    RULE_THRESHOLDS,
    evaluate_plan_change,
)


def _ctx(
    *,
    rest=None,
    max_consecutive=3,
    target=100.0,
    ceiling=130.0,
    races=None,
    phase=None,
    groups=None,
):
    return {
        "preferred_rest_days": rest or [],
        "max_consecutive_cap": max_consecutive,
        "week_target_tss": target,
        "acwr_ceiling": ceiling,
        "races": races or [],
        "phase": phase,
        "exercise_groups": groups or {},
    }


def _hit_ids(hits):
    return {h.rule_id: h.level for h in hits}


def test_max_consecutive_block_above_cap():
    mon = date(2026, 7, 6)
    sessions = [
        PlanSessionView(None, mon + timedelta(days=i), "run", None, "user", 40) for i in range(3)
    ]
    change = {
        "action": "create",
        "planned_date": (mon + timedelta(days=3)).isoformat(),
        "session_type": "run",
        "estimated_tss": 40,
    }
    hits = evaluate_plan_change(
        sessions=sessions,
        change=change,
        **_ctx(max_consecutive=3),
    )
    assert _hit_ids(hits)["max_consecutive"] == "block"


def test_max_consecutive_warn_at_cap():
    mon = date(2026, 7, 6)
    sessions = [
        PlanSessionView(None, mon + timedelta(days=i), "run", None, "user", 40) for i in range(2)
    ]
    change = {
        "action": "create",
        "planned_date": (mon + timedelta(days=2)).isoformat(),
        "session_type": "run",
        "estimated_tss": 40,
    }
    hits = evaluate_plan_change(sessions=sessions, change=change, **_ctx(max_consecutive=3))
    assert _hit_ids(hits).get("max_consecutive") == "warn"


def test_rest_day_warn_and_block_with_coach():
    wed = date(2026, 7, 8)  # Wednesday
    sessions = [
        PlanSessionView(None, wed, "run", {"source": "coach"}, "coach", 50),
    ]
    change = {
        "action": "create",
        "planned_date": wed.isoformat(),
        "session_type": "strength",
        "estimated_tss": 30,
        "source": "support",
    }
    hits = evaluate_plan_change(
        sessions=sessions,
        change=change,
        **_ctx(rest=[2]),
    )
    levels = _hit_ids(hits)
    assert levels["rest_day"] == "block"


def test_weekly_ceiling_block_and_target_warn():
    mon = date(2026, 7, 6)
    sessions = [
        PlanSessionView(None, mon, "run", None, "user", 80),
    ]
    change = {
        "action": "create",
        "planned_date": (mon + timedelta(days=1)).isoformat(),
        "session_type": "run",
        "estimated_tss": 26,
    }
    hits = evaluate_plan_change(sessions=sessions, change=change, **_ctx(target=100.0, ceiling=200.0))
    assert _hit_ids(hits)["weekly_ceiling"] == "warn"

    sessions2 = [
        PlanSessionView(None, mon, "run", None, "user", 100),
        PlanSessionView(None, mon + timedelta(days=1), "run", None, "user", 20),
    ]
    change2 = {
        "action": "create",
        "planned_date": (mon + timedelta(days=2)).isoformat(),
        "session_type": "run",
        "estimated_tss": 25,
    }
    hits2 = evaluate_plan_change(sessions=sessions2, change=change2, **_ctx(target=100.0, ceiling=130.0))
    assert _hit_ids(hits2)["weekly_ceiling"] == "block"


def test_race_proximity_plyo_boundary():
    race_d = date(2026, 7, 20)
    plyo_day = race_d - timedelta(days=int(RULE_THRESHOLDS["race_proximity_plyo_days"]))
    sessions: list[PlanSessionView] = []
    change = {
        "action": "create",
        "planned_date": plyo_day.isoformat(),
        "session_type": "plyo",
        "estimated_tss": 25,
    }
    hits = evaluate_plan_change(
        sessions=sessions,
        change=change,
        **_ctx(races=[{"name": "Half", "race_date": race_d.isoformat(), "priority": "B"}]),
    )
    assert _hit_ids(hits)["race_proximity_plyo"] == "block"

    ok_day = plyo_day - timedelta(days=1)
    change["planned_date"] = ok_day.isoformat()
    hits_ok = evaluate_plan_change(
        sessions=sessions,
        change=change,
        **_ctx(races=[{"name": "Half", "race_date": race_d.isoformat(), "priority": "B"}]),
    )
    assert "race_proximity_plyo" not in _hit_ids(hits_ok)


def test_race_proximity_lifting_a_race_10d():
    race_d = date(2026, 8, 1)
    lift_day = race_d - timedelta(days=int(RULE_THRESHOLDS["race_proximity_lifting_days"]))
    groups = {"back squat": {"heavy_compound"}}
    change = {
        "action": "create",
        "planned_date": lift_day.isoformat(),
        "session_type": "strength",
        "structure": {"exercises": [{"name": "Back Squat"}]},
        "estimated_tss": 60,
    }
    hits = evaluate_plan_change(
        sessions=[],
        change=change,
        **_ctx(races=[{"name": "A Marathon", "race_date": race_d.isoformat(), "priority": "A"}], groups=groups),
    )
    assert _hit_ids(hits)["race_proximity_lifting"] == "block"


def test_day_before_race_bodyweight_ok():
    race_d = date(2026, 8, 1)
    day_before = race_d - timedelta(days=1)
    groups = {"band pull": {"bodyweight"}}
    change = {
        "action": "create",
        "planned_date": day_before.isoformat(),
        "session_type": "strength",
        "structure": {"exercises": [{"name": "Band Pull"}]},
        "estimated_tss": 15,
    }
    hits = evaluate_plan_change(
        sessions=[],
        change=change,
        **_ctx(races=[{"name": "Race", "race_date": race_d.isoformat(), "priority": "A"}], groups=groups),
    )
    assert "day_before_race" not in _hit_ids(hits)

    change["session_type"] = "run"
    hits_run = evaluate_plan_change(
        sessions=[],
        change=change,
        **_ctx(races=[{"name": "Race", "race_date": race_d.isoformat(), "priority": "A"}], groups=groups),
    )
    assert _hit_ids(hits_run)["day_before_race"] == "block"


def test_race_week_support_cap_warn():
    mon = date(2026, 7, 6)
    sessions = [PlanSessionView(None, mon, "run", None, "coach", 40)]
    change = {
        "action": "create",
        "planned_date": mon.isoformat(),
        "session_type": "strength",
        "source": "support",
        "estimated_tss": 20,
    }
    hits = evaluate_plan_change(
        sessions=sessions,
        change=change,
        **_ctx(phase="race_week"),
    )
    assert _hit_ids(hits).get("race_week_support_cap") == "warn"