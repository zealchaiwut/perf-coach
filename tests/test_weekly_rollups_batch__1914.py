"""Issue #1914 — batched weekly_rollups(), ≤8 queries, parity with weekly_rollup()."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session as SASession

from backend.models import LoadPlanWeekSnapshot, PlannedSession, Race, UserPreferences, Workout
from backend.services.weekly_rollup import weekly_rollup, weekly_rollups

_USER = uuid.uuid4()
TODAY = date(2026, 11, 23)  # Monday


def _run(*, day, tss, name="run"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=_USER,
        workout_date=day,
        start_time=None,
        workout_type="run",
        distance_km=10.0,
        duration_seconds=3600,
        tss=float(tss),
        name=name,
    )


def _strength(*, day, tss):
    w = _run(day=day, tss=tss)
    w.workout_type = "strength"
    w.distance_km = None
    return w


def _planned(*, day, status="planned", name="Easy", session_type="run"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=_USER,
        planned_date=day,
        status=status,
        name=name,
        session_type=session_type,
        matched_workout_id=None,
        structure={"duration_minutes": 40},
        notes=None,
    )


def _race(*, day, name="Osaka", status="planned", priority="A"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=_USER,
        race_date=day,
        name=name,
        status=status,
        priority=priority,
        distance_km=42.195,
        goal_time_seconds=16200,
        actual_time_seconds=None,
        tss_if_override=None,
    )


class CountingSession:
    """ORM stand-in: each query/get fires SQL so a before_cursor_execute listener counts."""

    def __init__(self, sql_engine, store):
        self._engine = sql_engine
        self._store = store
        self._sa = SASession(bind=sql_engine)

    def _fire(self):
        self._sa.execute(text("SELECT 1"))

    def query(self, model):
        self._fire()
        rows = list(self._store.get(model, []))
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = rows
        q.first.return_value = rows[0] if rows else None
        return q

    def get(self, model, ident):
        self._fire()
        for row in self._store.get(model, []):
            if getattr(row, "id", None) == ident or getattr(row, "user_id", None) == ident:
                return row
        return None

    def flush(self):
        pass

    def close(self):
        self._sa.close()


def _listen(engine):
    box = {"n": 0}

    def _on(*_a, **_k):
        box["n"] += 1

    event.listen(engine, "before_cursor_execute", _on)
    return box


def test_weekly_rollups_query_count_bounded_independent_of_weeks():
    sql = create_engine("sqlite://")
    box = _listen(sql)
    store = {
        UserPreferences: [],
        Workout: [],
        PlannedSession: [],
        Race: [],
        LoadPlanWeekSnapshot: [],
    }
    sess = CountingSession(sql, store)
    with (
        patch("backend.services.weekly_rollup.chronic_weekly_tss", create=True),
        patch(
            "backend.services.revamp_load_plan.chronic_weekly_tss",
            return_value=300.0,
        ),
        patch(
            "backend.services.revamp_plan_settings.resolve_a_race",
            return_value=None,
        ),
    ):
        four = weekly_rollups(str(_USER), date(2026, 10, 26), date(2026, 11, 16), session=sess, today=TODAY)
        n_four = box["n"]
        box["n"] = 0
        twelve = weekly_rollups(str(_USER), date(2026, 9, 7), date(2026, 11, 23), session=sess, today=TODAY)
        n_twelve = box["n"]
    assert len(four) == 4
    assert len(twelve) == 12
    assert n_four <= 8
    assert n_twelve <= 8
    assert n_four == n_twelve


def test_weekly_rollups_parity_with_per_week():
    ws0 = date(2026, 11, 9)
    ws1 = date(2026, 11, 16)
    ws2 = date(2026, 11, 23)  # partial current week
    runs = [
        _run(day=date(2026, 11, 10), tss=80),
        _run(day=date(2026, 11, 12), tss=50),
        _strength(day=date(2026, 11, 18), tss=40),
        _run(day=date(2026, 11, 23), tss=30),
    ]
    planned = [
        _planned(day=date(2026, 11, 11), status="planned"),
        _planned(day=date(2026, 11, 19), status="missed"),
        _planned(day=date(2026, 11, 25), status="planned"),
    ]
    race = _race(day=date(2026, 11, 15), name="Tune-up 10k")
    sql = create_engine("sqlite://")
    store = {
        UserPreferences: [SimpleNamespace(user_id=_USER, tss_method_default="power")],
        Workout: runs,
        PlannedSession: planned,
        Race: [race],
        LoadPlanWeekSnapshot: [],
    }
    sess = CountingSession(sql, store)
    race_payload = [
        {
            "race_id": str(race.id),
            "name": race.name,
            "race_date": str(race.race_date),
            "priority": "A",
            "tss": 80,
            "tss_source": "estimate",
            "kind": "race",
        }
    ]

    def _payload(session, user_id, week_start, week_end, **kw):
        if week_start <= race.race_date <= week_end:
            return list(race_payload)
        return []

    with (
        patch(
            "backend.services.weekly_rollup._estimate_planned_tss_remaining",
            return_value=0.0,
        ),
        patch("backend.services.race_day_tss.race_week_payload", side_effect=_payload),
        patch("backend.services.revamp_load_plan.chronic_weekly_tss", return_value=300.0),
        patch("backend.services.revamp_plan_settings.resolve_a_race", return_value=None),
        patch("backend.services.revamp_plan_settings.get_row", return_value=None),
        patch("backend.services.training_load.estimate_historical_pace_and_tss", return_value={}),
    ):
        batched = weekly_rollups(str(_USER), ws0, ws2, session=sess, today=TODAY)
        per = [
            weekly_rollup(str(_USER), d, session=sess, today=TODAY)
            for d in (ws0, ws1, ws2)
        ]
    assert len(batched) == 3
    for a, b in zip(batched, per):
        assert a == b
    assert batched[0]["tss_total"] == 130.0
    assert batched[1]["tss_strength"] == 40.0
    assert batched[2]["partial"] is True
    assert batched[0]["race_items"][0]["name"] == "Tune-up 10k"
    assert batched[1]["counts"]["missed"] == 1


def test_weekly_rollups_range_week_count():
    sql = create_engine("sqlite://")
    sess = CountingSession(sql, {UserPreferences: [], Workout: [], PlannedSession: [], Race: []})
    with (
        patch("backend.services.revamp_load_plan.chronic_weekly_tss", return_value=300.0),
        patch("backend.services.revamp_plan_settings.resolve_a_race", return_value=None),
        patch("backend.services.training_load.estimate_historical_pace_and_tss", return_value={}),
    ):
        rows = weekly_rollups(str(_USER), date(2026, 11, 2), date(2026, 11, 16), session=sess, today=TODAY)
    assert len(rows) == 3
    assert rows[0]["week_start"] == "2026-11-02"
