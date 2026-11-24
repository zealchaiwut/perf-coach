"""Issue #1842 — SessionEditor planned mode."""

from datetime import date, timedelta

from backend.services.plan_rules_engine import PlanSessionView, evaluate_plan_change


def test_session_editor_snapshot_markers():
    planned = open("frontend/js/v2-session-editor.js", encoding="utf-8").read()
    logged = open("frontend/js/v2-strength-drawer.js", encoding="utf-8").read()
    assert "SESSION_EDITOR_MODE_PLANNED" in planned
    assert "v2-strength-editor-mode" in logged
    assert "LOGGED_DELEGATE_MARKER" in planned
    assert "V2StrengthDrawer" in planned


def test_v2_training_plan_wires_session_editor():
    html = open("frontend/pages/v2-training-plan.html", encoding="utf-8").read()
    assert "v2-session-editor.js" in html
    assert "v2-session-editor" in html


def test_blocked_plyo_session_near_race_is_rule_block():
    race = date(2026, 11, 16)
    target = race - timedelta(days=2)
    hits = evaluate_plan_change(
        sessions=[],
        change={
            "action": "create",
            "planned_date": target.isoformat(),
            "session_type": "plyo",
            "structure": {"exercises": [{"name": "Bounds", "sets": 3}]},
            "source": "support",
            "estimated_tss": 20.0,
        },
        preferred_rest_days=[0],
        max_consecutive_cap=3,
        week_target_tss=400.0,
        acwr_ceiling=800.0,
        races=[{"name": "A race", "race_date": race.isoformat(), "priority": "A"}],
        phase="race_week",
        exercise_groups={},
    )
    assert any(h.level == "block" for h in hits)


def test_context_route_registered():
    src = open("backend/main.py", encoding="utf-8").read()
    assert "/api/plan/revamp-planned-editor/context" in src


def test_planned_editor_imports_week_target_from_load_plan():
    src = open("backend/services/revamp_planned_editor.py", encoding="utf-8").read()
    assert "from backend.services.revamp_load_plan import week_target_and_phase" in src
    assert "week_target_and_phase" not in src.split("weekly_rollup import", 1)[-1].split("\n")[0]