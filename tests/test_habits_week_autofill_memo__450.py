"""Tests for issue #450: memoize _get_computed_logs_from_workouts within a
single GET /api/habits/week request scope.

Acceptance criterion (from issue body):
  When multiple weekly habits share the same auto_fill_source, the
  autofill computation function should be called AT MOST ONCE per unique
  source per request — not once per habit — to avoid redundant work.

Two test classes:
  (a) Correctness is preserved: two habits with the same source both receive
      the correct computed values.
  (b) Memoization: _get_computed_logs_from_workouts is called only once when
      two habits share the same auto_fill_source.
"""
import uuid
from datetime import date, datetime
from unittest.mock import MagicMock, call, patch

from fastapi.testclient import TestClient

from backend.main import app, resolve_user, _get_computed_logs_from_workouts
from backend.models import Habit, HabitLog, Workout

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000450")
_WEEK_MON = date(2026, 6, 8)
_WEEK_SUN = date(2026, 6, 14)
_TODAY_THU = date(2026, 6, 11)


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    async def _fake():
        return _make_user()
    app.dependency_overrides[resolve_user] = _fake
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_weekly_habit(*, hid=None, auto_fill_source=None, weekly_target=120.0, name="H"):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.description = None
    h.tracking_type = "weekly_minutes"
    h.weekly_target = weekly_target
    h.unit = "min"
    h.auto_fill_source = auto_fill_source
    h.icon = None
    h.color = None
    h.sort_order = 0
    h.is_archived = False
    h.created_at = None
    h.updated_at = None
    return h


def _make_workout(*, workout_date, workout_type="run", zone2_minutes=None, duration_seconds=None, distance_km=None):
    w = MagicMock(spec=Workout)
    w.id = uuid.uuid4()
    w.user_id = _USER_ID
    w.workout_date = workout_date
    w.workout_type = workout_type
    w.zone2_minutes = zone2_minutes
    w.duration_seconds = duration_seconds
    w.distance_km = distance_km
    return w


def _make_session(active_habits, archived_habits=None, logs=None, workouts=None):
    archived_habits = archived_habits or []
    logs = logs or []
    workouts = workouts or []

    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)

    habit_q = MagicMock()
    habit_q.filter.return_value = habit_q
    habit_q.order_by.return_value = habit_q
    habit_q.join.return_value = habit_q
    habit_q.distinct.return_value = habit_q

    _habit_calls = [0]

    def _habit_all():
        _habit_calls[0] += 1
        return active_habits if _habit_calls[0] == 1 else archived_habits

    habit_q.all.side_effect = _habit_all

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.all.return_value = logs

    workout_q = MagicMock()
    workout_q.filter.return_value = workout_q
    workout_q.all.return_value = workouts

    def _side(model):
        if model is Habit:
            return habit_q
        if model is HabitLog:
            return log_q
        if model is Workout:
            return workout_q
        return MagicMock()

    sess.query.side_effect = _side
    return sess


def _patch_today(target_date):
    from zoneinfo import ZoneInfo
    _BANGKOK = ZoneInfo("Asia/Bangkok")
    fake_dt = datetime(target_date.year, target_date.month, target_date.day, 10, 0, 0, tzinfo=_BANGKOK)
    mock_dt = MagicMock()
    mock_dt.now.return_value = fake_dt
    mock_dt.fromisoformat = datetime.fromisoformat
    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
    return patch("backend.main._datetime", mock_dt)


# ── AC (a): Correctness preserved with two habits sharing same source ──────────

class TestACa_CorrectnessTwoHabitsSameSource:
    """Two weekly habits sharing the same auto_fill_source both receive the
    correct computed values from the memoized result."""

    def test_both_habits_get_correct_autofill_value(self):
        client = _make_client()
        hid_a = uuid.uuid4()
        hid_b = uuid.uuid4()
        habit_a = _make_weekly_habit(
            hid=hid_a,
            auto_fill_source="workout.zone2_minutes",
            weekly_target=120.0,
            name="Zone2 A",
        )
        habit_b = _make_weekly_habit(
            hid=hid_b,
            auto_fill_source="workout.zone2_minutes",
            weekly_target=60.0,
            name="Zone2 B",
        )
        workout = _make_workout(
            workout_date=date(2026, 6, 10),
            workout_type="run",
            zone2_minutes=45,
        )
        sess = _make_session([habit_a, habit_b], workouts=[workout])

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text
            body = res.json()
            wh = {h["id"]: h for h in body["weekly_habits"]}

            # Both habits must show current_value from the same autofill workout
            assert wh[str(hid_a)]["current_value"] == 45.0, (
                f"habit_a should have current_value=45.0, got {wh[str(hid_a)]['current_value']}"
            )
            assert wh[str(hid_b)]["current_value"] == 45.0, (
                f"habit_b should have current_value=45.0, got {wh[str(hid_b)]['current_value']}"
            )
            # Both should have the Wednesday workout in their daily_breakdown
            for hid_str, label in ((str(hid_a), "habit_a"), (str(hid_b), "habit_b")):
                dates = [e["date"] for e in wh[hid_str]["daily_breakdown"]]
                assert "2026-06-10" in dates, f"{label} breakdown must include Wed workout date"
        finally:
            _teardown()


# ── AC (b): Memoization — function called once per unique source ───────────────

class TestACb_MemoizationCallCount:
    """_get_computed_logs_from_workouts must be called at most once per unique
    auto_fill_source per request, even when multiple habits share the same source."""

    def test_function_called_once_for_two_habits_with_same_source(self):
        client = _make_client()
        hid_a = uuid.uuid4()
        hid_b = uuid.uuid4()
        habit_a = _make_weekly_habit(
            hid=hid_a,
            auto_fill_source="workout.zone2_minutes",
            name="Zone2 A",
        )
        habit_b = _make_weekly_habit(
            hid=hid_b,
            auto_fill_source="workout.zone2_minutes",
            name="Zone2 B",
        )
        workout = _make_workout(
            workout_date=date(2026, 6, 10),
            workout_type="run",
            zone2_minutes=30,
        )
        sess = _make_session([habit_a, habit_b], workouts=[workout])

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                with patch(
                    "backend.main._get_computed_logs_from_workouts",
                    wraps=_get_computed_logs_from_workouts,
                ) as mock_fn:
                    res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text

            # Two habits share the same source → function must be called exactly once
            actual_calls = mock_fn.call_count
            assert actual_calls == 1, (
                f"Expected _get_computed_logs_from_workouts to be called 1 time "
                f"(memoized for shared source), but was called {actual_calls} times"
            )
        finally:
            _teardown()

    def test_function_called_once_per_distinct_source(self):
        """When habits have DIFFERENT sources, function is called once per source."""
        client = _make_client()
        hid_a = uuid.uuid4()
        hid_b = uuid.uuid4()
        habit_a = _make_weekly_habit(
            hid=hid_a,
            auto_fill_source="workout.zone2_minutes",
            name="Zone2",
        )
        habit_b = _make_weekly_habit(
            hid=hid_b,
            auto_fill_source="workout.run_count",
            name="RunCount",
        )
        workout = _make_workout(
            workout_date=date(2026, 6, 10),
            workout_type="run",
            zone2_minutes=30,
        )
        sess = _make_session([habit_a, habit_b], workouts=[workout])

        try:
            with _patch_today(_TODAY_THU), patch("backend.main.Session", return_value=sess):
                with patch(
                    "backend.main._get_computed_logs_from_workouts",
                    wraps=_get_computed_logs_from_workouts,
                ) as mock_fn:
                    res = client.get("/api/habits/week?week_start=2026-06-08")
            assert res.status_code == 200, res.text

            # Two different sources → function called exactly twice (once each)
            actual_calls = mock_fn.call_count
            assert actual_calls == 2, (
                f"Expected _get_computed_logs_from_workouts to be called 2 times "
                f"(one per distinct source), but was called {actual_calls} times"
            )
            # Verify the two distinct sources were passed
            sources_used = {c.args[1] for c in mock_fn.call_args_list}
            assert sources_used == {"workout.zone2_minutes", "workout.run_count"}
        finally:
            _teardown()
