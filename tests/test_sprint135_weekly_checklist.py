"""Sprint 135 — weekly checklist phase A (WC-01..WC-08)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.services.fuel import _race_calendar_day_type, compute_day_type


def test_compute_day_type_quality_flag():
    assert compute_day_type([
        {"type": "run", "duration_min": 50, "quality": True},
    ]) == "quality"


def test_race_calendar_pre_race_and_race_short_goal():
    class _Race:
        def __init__(self, race_date, goal_time_seconds=3000):
            self.race_date = race_date
            self.goal_time_seconds = goal_time_seconds
            self.priority = "B"
            self.race_type = "race"

    class _Q:
        def __init__(self, races):
            self._races = races

        def filter(self, *a, **kw):
            return self

        def order_by(self, *a, **kw):
            return self

        def all(self):
            return self._races

    class _DB:
        def __init__(self, races):
            self._races = races

        def query(self, model):
            return _Q(self._races)

    race_day = date(2026, 10, 4)
    db = _DB([_Race(race_day, goal_time_seconds=50 * 60)])
    assert _race_calendar_day_type(None, race_day, db) == "race"
    assert _race_calendar_day_type(None, race_day - timedelta(days=1), db) == "pre_race"
    assert _race_calendar_day_type(None, race_day - timedelta(days=2), db) is None


def test_race_calendar_carb_load_two_days_for_long_goal():
    class _Race:
        race_date = date(2026, 11, 15)
        goal_time_seconds = 4 * 3600 + 30 * 60
        priority = "A"
        race_type = "race"

    class _Q:
        def filter(self, *a, **kw):
            return self

        def order_by(self, *a, **kw):
            return self

        def all(self):
            return [_Race()]

    db = type("DB", (), {"query": lambda self, m: _Q()})()
    assert _race_calendar_day_type(None, date(2026, 11, 13), db) == "carb_load"
    assert _race_calendar_day_type(None, date(2026, 11, 14), db) == "carb_load"


def test_habit_autofill_sleep_hours_min():
    from backend.services.habit_autofill import _compute_date_values

    d = date(2026, 9, 28)
    out = _compute_date_values(
        "sleep.hours_min",
        [],
        sleep_dates=[(d, 8.0)],
        target_hours=7.5,
    )
    assert out[d] == 1.0
