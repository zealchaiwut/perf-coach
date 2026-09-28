"""Sprint 138 slice A — checklist mock API + Habits shell (WC-21..WC-23)."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from backend.services.checklist_week import (
    _ribbon_for_day,
    _structure_summary,
    build_checklist_week,
)


def test_structure_summary_counts_blocks_and_exercises():
    struct = {
        "duration_minutes": 45,
        "exercises": [{"name": "a"}, {"name": "b"}],
        "blocks": [{"duration_min": 10, "repeat": 3}],
    }
    out = _structure_summary(struct)
    assert out["duration_minutes"] == 45
    assert out["exercise_count"] == 2
    assert out["block_count"] == 1


def test_structure_summary_derives_duration_from_blocks():
    struct = {"blocks": [{"duration_min": 8, "repeat": 2, "rest_min": 1}]}
    out = _structure_summary(struct)
    assert out["duration_minutes"] == 17


def test_ribbon_prefers_non_rest_session():
    ps = SimpleNamespace(
        id=uuid4(),
        name="Easy Run",
        session_type="run",
        status="planned",
        planned_date=date(2026, 9, 28),
    )
    rest = SimpleNamespace(
        id=uuid4(),
        name="Rest",
        session_type="rest",
        status="planned",
        planned_date=date(2026, 9, 28),
    )
    score = {"core_done": 1, "core_total": 3}
    rb = _ribbon_for_day([rest, ps], score)
    assert rb["label"] == "Easy Run"
    assert rb["session_type"] == "run"
    assert rb["core_done"] == 1


def test_ribbon_rest_when_no_sessions():
    rb = _ribbon_for_day([], {"core_done": 0, "core_total": 0})
    assert rb["label"] == "Rest"
    assert rb["session_type"] == "rest"
    assert rb["session_id"] is None


def test_build_checklist_week_mock_fields(monkeypatch):
    from backend.services import checklist_week as cw

    class _Q:
        def __init__(self, rows=None):
            self._rows = rows or []

        def filter(self, *a, **kw):
            return self

        def order_by(self, *a, **kw):
            return self

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    habit = SimpleNamespace(
        id=uuid4(),
        name="Sleep 7h+",
        checklist_role="core",
        auto_fill_source="sleep.hours_min",
        tracking_type="daily_checkmark",
        target_value=None,
        sort_order=0,
    )
    ps = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        planned_date=date(2026, 9, 28),
        session_type="run",
        status="planned",
        name="Long Run",
        structure={"duration_minutes": 90, "exercises": [], "blocks": []},
    )

    def _query(model):
        name = getattr(model, "__name__", str(model))
        if name == "Habit":
            return _Q([habit])
        if name == "PlannedSession":
            return _Q([ps])
        if name == "Race":
            a = SimpleNamespace(
                id=uuid4(),
                name="Bangkok Marathon 2026",
                race_date=date(2026, 12, 6),
                goal_time_seconds=12600,
                distance_km=42.2,
                priority="A",
                type="marathon",
            )
            return _Q([a])
        return _Q([])

    db = MagicMock()
    db.query.side_effect = _query

    monkeypatch.setattr(cw, "today_bangkok", lambda: date(2026, 9, 28))
    monkeypatch.setattr(
        "backend.services.checklist_habits.ensure_sleep_habit",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "backend.services.habit_autofill.recompute_autofill_for_week",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "backend.services.training_prefs.active_dict",
        lambda *a, **kw: {"payload": {"weekly_checklist_enabled": True}},
    )
    monkeypatch.setattr(
        "backend.services.fuel.get_week_payload",
        lambda *a, **kw: {
            "days": [{"date": "2026-09-28", "day_type": "long_run", "budget": 2400, "burn": 800}],
            "week_phase": "build",
        },
    )
    monkeypatch.setattr(
        "backend.services.fuel.get_today_payload",
        lambda *a, **kw: {
            "day_type": "long_run",
            "week_phase": "build",
            "targets": {"protein_g": 120},
            "food_portions": [],
        },
    )
    monkeypatch.setattr(
        "backend.services.plan_build_status.plan_build_status",
        lambda *a, **kw: {"status": "up_to_date", "last_built_at": "2026-09-28T08:00:00"},
    )
    monkeypatch.setattr(
        "backend.services.habit_evidence.build_user_evidence",
        lambda *a, **kw: [{"habit": "sleep", "sentence": "Sleep supports recovery.", "better": True}],
    )

    out = build_checklist_week(db, uuid4(), date(2026, 9, 28), today=date(2026, 9, 28))
    assert out["week_number"] == 40
    assert "races_header" in out
    assert out["races_header"]["a_race"]["name"] == "Bangkok Marathon 2026"

    mon = out["days"][0]
    assert mon["date"] == "2026-09-28"
    assert mon["ribbon"]["label"] == "Long Run"
    assert mon["fuel_detail"]["day_type"] == "long_run"

    session_item = next(it for it in mon["items"] if it["kind"] == "planned_session")
    assert session_item["structure_summary"]["duration_minutes"] == 90

    habit_item = next(it for it in mon["items"] if it["kind"] == "habit")
    assert habit_item["auto_fill_source"] == "sleep.hours_min"


def test_checklist_habits_page_module_exists():
    src = open("frontend/js/checklist-habits-page.js", encoding="utf-8").read()
    assert "ChecklistHabitsPage" in src
    assert "clh-ribbon" in src
    assert "clh-body" in src


def test_checklist_ui_delegates_to_habits_page():
    ui = open("frontend/js/checklist-ui.js", encoding="utf-8").read()
    assert "ChecklistHabitsPage" in ui
    assert "habits-page-header" in ui


def test_habits_html_loads_checklist_habits_assets():
    html = open("frontend/pages/habits.html", encoding="utf-8").read()
    assert "checklist-habits-page.js" in html
    assert "checklist-habits.css" in html
