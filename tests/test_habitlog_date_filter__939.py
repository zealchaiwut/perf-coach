"""Tests for issue #939: Add date filter to HabitLog query in GET /api/habits/adherence.

Acceptance Criteria:
- AC1: The HabitLog query in get_habits_adherence must include a date lower-bound
       of today - 60 days so logs older than 60 days are never fetched from the DB.
- AC2: Logs within the 60-day window are still returned correctly.
- AC3: The date filter cutoff is exactly 60 days (not 30, not 90).
"""
from __future__ import annotations

import datetime
import types
import unittest.mock as mock



TODAY = datetime.date(2026, 8, 4)
CUTOFF = TODAY - datetime.timedelta(days=60)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fake_habit(habit_id="h1", name="Test"):
    h = types.SimpleNamespace()
    h.id = habit_id
    h.name = name
    h.is_archived = False
    h.active = True
    h.sort_order = 0
    h.schedule_type = "daily"
    h.schedule_target = None
    h.habit_type = "binary"
    h.target_value = None
    h.tracking_type = "daily_checkmark"
    return h


def _fake_log(log_date: datetime.date, habit_id="h1", user_id="u1"):
    lg = types.SimpleNamespace()
    lg.log_date = log_date
    lg.habit_id = habit_id
    lg.user_id = user_id
    lg.value = 1.0
    return lg


def _make_session_class(fake_habit, log_rows_by_query_call):
    """Build a fake Session class where HabitLog queries return specific rows."""
    from backend.models import Habit, HabitLog

    habitlog_filter_args = []

    class _FakeQuery:
        def __init__(self, model=None):
            self._model = model
            self._is_habitlog = model is HabitLog

        def filter(self, *args):
            if self._is_habitlog:
                habitlog_filter_args.extend(args)
            return self

        def order_by(self, *a):
            return self

        def all(self):
            if self._model is Habit:
                return [fake_habit]
            if self._model is HabitLog:
                return log_rows_by_query_call
            return []

    class _FakeSession:
        def query(self, model):
            return _FakeQuery(model)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _FakeSession, habitlog_filter_args


# ─── AC1: 60-day date filter is present in the HabitLog query ─────────────────

class TestDateFilterPresentInQuery:
    """The HabitLog filter must include a log_date lower-bound of today - 60 days.

    Strategy: intercept the SQLAlchemy filter() call arguments on the HabitLog
    query and assert that at least one expression string-compiles to include
    'log_date' with a date comparison. This gives us a compile-time check without
    needing a live Postgres connection.
    """

    def test_habitlog_query_has_log_date_filter(self):
        """After the fix, the HabitLog query must pass a log_date >= cutoff filter."""
        from backend.main import get_habits_adherence

        fake_habit = _fake_habit()
        recent_log = _fake_log(TODAY - datetime.timedelta(days=5))
        _FakeSession, habitlog_filter_args = _make_session_class(
            fake_habit, [recent_log]
        )

        fake_user = types.SimpleNamespace(id="u1")

        def _noop_build(habits, logs_by_habit, today):
            return {"building": False, "reason": None, "habits": []}

        with mock.patch("backend.main.Session", return_value=_FakeSession()):
            with mock.patch("backend.main._today_bkk", return_value=TODAY):
                with mock.patch(
                    "backend.main._build_adherence_payload", side_effect=_noop_build
                ):
                    get_habits_adherence(user=fake_user)

        # Convert each filter expression to string and check for log_date presence.
        # SQLAlchemy BinaryExpression.__str__() compiles to SQL like:
        # "habit_logs.log_date >= :log_date_1"
        filter_strings = []
        for arg in habitlog_filter_args:
            try:
                filter_strings.append(str(arg))
            except Exception:
                pass

        has_log_date_filter = any("log_date" in s for s in filter_strings)
        assert has_log_date_filter, (
            "HabitLog query has no log_date filter. "
            f"Filter args compiled to: {filter_strings!r}. "
            "Expected a filter like `HabitLog.log_date >= (today - timedelta(days=60))`."
        )

    def test_log_date_filter_uses_60_day_cutoff(self):
        """The date in the log_date filter must be exactly today - 60 days."""
        from backend.main import get_habits_adherence

        fake_habit = _fake_habit()
        recent_log = _fake_log(TODAY - datetime.timedelta(days=5))
        _FakeSession, habitlog_filter_args = _make_session_class(
            fake_habit, [recent_log]
        )

        fake_user = types.SimpleNamespace(id="u1")

        def _noop_build(habits, logs_by_habit, today):
            return {"building": False, "reason": None, "habits": []}

        with mock.patch("backend.main.Session", return_value=_FakeSession()):
            with mock.patch("backend.main._today_bkk", return_value=TODAY):
                with mock.patch(
                    "backend.main._build_adherence_payload", side_effect=_noop_build
                ):
                    get_habits_adherence(user=fake_user)

        # The cutoff date must appear somewhere in the compiled filter expressions.
        cutoff_str = CUTOFF.isoformat()  # "2026-06-05"
        filter_strings = []
        for arg in habitlog_filter_args:
            try:
                filter_strings.append(str(arg))
            except Exception:
                pass

        # Also check literal values: SQLAlchemy may embed the date object
        # directly — look at the right-hand side of each BinaryExpression.
        found_cutoff = False
        for arg in habitlog_filter_args:
            if hasattr(arg, "right") and hasattr(arg.right, "value"):
                val = arg.right.value
                if isinstance(val, datetime.date) and val == CUTOFF:
                    found_cutoff = True
                    break
            # Fallback: string representation
            try:
                if cutoff_str in str(arg):
                    found_cutoff = True
                    break
            except Exception:
                pass

        assert found_cutoff, (
            f"Expected the 60-day cutoff date {CUTOFF} ({cutoff_str}) in the HabitLog "
            f"filter expressions but did not find it. "
            f"Filter args compiled to: {filter_strings!r}"
        )


# ─── AC2: Recent logs still reach build_adherence_payload ─────────────────────

class TestRecentLogsIncluded:
    """Logs within the 60-day window must be passed through to the payload builder."""

    def test_log_from_yesterday_is_in_payload(self):
        from backend.main import get_habits_adherence

        fake_habit = _fake_habit()
        yesterday_log = _fake_log(TODAY - datetime.timedelta(days=1))
        _FakeSession, _ = _make_session_class(fake_habit, [yesterday_log])

        fake_user = types.SimpleNamespace(id="u1")
        captured = {}

        def _capturing_build(habits, logs_by_habit, today):
            captured.update(logs_by_habit)
            return {"building": False, "reason": None, "habits": []}

        with mock.patch("backend.main.Session", return_value=_FakeSession()):
            with mock.patch("backend.main._today_bkk", return_value=TODAY):
                with mock.patch(
                    "backend.main._build_adherence_payload",
                    side_effect=_capturing_build,
                ):
                    get_habits_adherence(user=fake_user)

        hid = str(fake_habit.id)
        assert hid in captured, "Habit missing from logs_by_habit"
        log_dates = [lg.log_date for lg in captured[hid]]
        assert yesterday_log.log_date in log_dates, (
            f"Log from {yesterday_log.log_date} missing — recent logs must be included"
        )

    def test_log_at_day_60_boundary_is_included(self):
        """A log exactly at today - 60 days (the cutoff itself) must be included (>= filter)."""
        from backend.main import get_habits_adherence

        fake_habit = _fake_habit()
        boundary_log = _fake_log(CUTOFF)
        _FakeSession, _ = _make_session_class(fake_habit, [boundary_log])

        fake_user = types.SimpleNamespace(id="u1")
        captured = {}

        def _capturing_build(habits, logs_by_habit, today):
            captured.update(logs_by_habit)
            return {"building": False, "reason": None, "habits": []}

        with mock.patch("backend.main.Session", return_value=_FakeSession()):
            with mock.patch("backend.main._today_bkk", return_value=TODAY):
                with mock.patch(
                    "backend.main._build_adherence_payload",
                    side_effect=_capturing_build,
                ):
                    get_habits_adherence(user=fake_user)

        hid = str(fake_habit.id)
        assert hid in captured, "Habit missing from logs_by_habit"
        log_dates = [lg.log_date for lg in captured[hid]]
        assert CUTOFF in log_dates, (
            f"Log at boundary {CUTOFF} (day 60) should be included by >= filter"
        )
