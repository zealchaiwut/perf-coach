"""Tests for issue #430: habit_stats service module.

7 unit tests (a–g) anchored to issue #430 Acceptance Criteria.
"""
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock

from backend.models import Habit, HabitLog
from backend.services.habit_stats import best_streak, current_streak, week_summary

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000430")


def _make_habit(hid=None, tracking_type="daily_checkmark", name="Test Habit"):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = name
    h.tracking_type = tracking_type
    h.is_archived = False
    return h


def _make_log(habit_id, log_date, user_id=_USER_ID, log_week_start=None):
    lg = MagicMock(spec=HabitLog)
    lg.id = uuid.uuid4()
    lg.habit_id = habit_id
    lg.user_id = user_id
    lg.log_date = log_date
    if log_week_start is None:
        d = log_date
        log_week_start = d - timedelta(days=d.weekday())
    lg.log_week_start = log_week_start
    lg.value = 1.0
    lg.source = "manual"
    return lg


def _session_for_streak(habit, logs):
    """Mock session for current_streak / best_streak calls."""
    sess = MagicMock()

    habit_q = MagicMock()
    habit_q.filter.return_value = habit_q
    habit_q.first.return_value = habit

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.all.return_value = logs

    def _side(model):
        if model is Habit:
            return habit_q
        if model is HabitLog:
            return log_q
        return MagicMock()

    sess.query.side_effect = _side
    return sess


def _session_for_week_summary(habits, logs):
    """Mock session for week_summary calls."""
    sess = MagicMock()

    habit_q = MagicMock()
    habit_q.filter.return_value = habit_q
    habit_q.all.return_value = habits

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.all.return_value = logs

    def _side(model):
        if model is Habit:
            return habit_q
        if model is HabitLog:
            return log_q
        return MagicMock()

    sess.query.side_effect = _side
    return sess


# ── (a): simple 3-day streak ─────────────────────────────────────────────────

def test_a_simple_3_day_streak():
    """current_streak returns 3 for 3 consecutive days logged ending at as_of_date."""
    hid = uuid.uuid4()
    habit = _make_habit(hid=hid)
    as_of = date(2026, 6, 11)
    logs = [
        _make_log(hid, date(2026, 6, 9)),
        _make_log(hid, date(2026, 6, 10)),
        _make_log(hid, date(2026, 6, 11)),
    ]
    sess = _session_for_streak(habit, logs)
    assert current_streak(hid, as_of, session=sess) == 3


# ── (b): today unlogged does not break streak; yesterday unlogged does ────────

def test_b_today_unlogged_does_not_break_streak():
    """Missing today's log does not end a streak if yesterday is logged."""
    hid = uuid.uuid4()
    habit = _make_habit(hid=hid)
    today = date(2026, 6, 11)
    logs = [
        _make_log(hid, date(2026, 6, 9)),
        _make_log(hid, date(2026, 6, 10)),
        # June 11 (today) NOT logged
    ]
    sess = _session_for_streak(habit, logs)
    assert current_streak(hid, today, session=sess) == 2


def test_b_yesterday_unlogged_breaks_streak():
    """Missing yesterday's log breaks the streak even if earlier days were logged."""
    hid = uuid.uuid4()
    habit = _make_habit(hid=hid)
    today = date(2026, 6, 11)
    logs = [
        _make_log(hid, date(2026, 6, 8)),
        _make_log(hid, date(2026, 6, 9)),
        # June 10 (yesterday) NOT logged
    ]
    sess = _session_for_streak(habit, logs)
    assert current_streak(hid, today, session=sess) == 0


# ── (c): streak crosses a week boundary ──────────────────────────────────────

def test_c_streak_crosses_week_boundary():
    """A streak continues across the Mon/Sun week boundary without breaking."""
    hid = uuid.uuid4()
    habit = _make_habit(hid=hid)
    # June 14 = Sunday (end of week), June 15 = Monday (start of next week)
    as_of = date(2026, 6, 16)  # Tuesday
    logs = [
        _make_log(hid, date(2026, 6, 14)),  # Sunday
        _make_log(hid, date(2026, 6, 15)),  # Monday (new week)
        _make_log(hid, date(2026, 6, 16)),  # Tuesday
    ]
    sess = _session_for_streak(habit, logs)
    assert current_streak(hid, as_of, session=sess) == 3


# ── (d): best streak selects the correct habit ───────────────────────────────

def test_d_best_streak_selects_correct_habit():
    """best_streak returns a higher length for the habit with more consecutive days."""
    hid_a = uuid.uuid4()
    hid_b = uuid.uuid4()
    habit_a = _make_habit(hid=hid_a, name="Habit A")
    habit_b = _make_habit(hid=hid_b, name="Habit B")

    # Habit A: 5 consecutive days
    logs_a = [_make_log(hid_a, date(2026, 6, 7) + timedelta(days=i)) for i in range(5)]
    # Habit B: 2 consecutive days
    logs_b = [_make_log(hid_b, date(2026, 6, 7) + timedelta(days=i)) for i in range(2)]

    sess_a = _session_for_streak(habit_a, logs_a)
    sess_b = _session_for_streak(habit_b, logs_b)

    result_a = best_streak(hid_a, session=sess_a)
    result_b = best_streak(hid_b, session=sess_b)

    assert result_a["length"] == 5
    assert result_b["length"] == 2
    assert result_a["length"] > result_b["length"]


# ── (e): last_week computes correctly from real log data ─────────────────────

def test_e_last_week_computes_correctly():
    """week_summary returns correct done/possible/pct from real log data."""
    hid = uuid.uuid4()
    last_mon = date(2026, 6, 1)
    habit = _make_habit(hid=hid)
    logs = [
        _make_log(hid, date(2026, 6, 1), log_week_start=last_mon),
        _make_log(hid, date(2026, 6, 2), log_week_start=last_mon),
        _make_log(hid, date(2026, 6, 3), log_week_start=last_mon),
    ]
    sess = _session_for_week_summary([habit], logs)
    result = week_summary(_USER_ID, last_mon, session=sess)

    assert result is not None
    assert result["done"] == 3
    assert result["possible"] == 7
    expected_pct = round(3 / 7 * 100, 2)
    assert abs(result["pct"] - expected_pct) < 0.01


# ── (f): last_week returns None when no logs exist ───────────────────────────

def test_f_last_week_null_when_no_logs():
    """week_summary returns None when no log data exists for the period."""
    hid = uuid.uuid4()
    habit = _make_habit(hid=hid)
    sess = _session_for_week_summary([habit], [])  # no logs
    result = week_summary(_USER_ID, date(2026, 5, 25), session=sess)
    assert result is None


# ── (g): weekly-type habits excluded from streak calculations ─────────────────

def test_g_weekly_habits_excluded_from_streaks():
    """current_streak returns 0 for non-daily_checkmark habits."""
    hid = uuid.uuid4()
    habit = _make_habit(hid=hid, tracking_type="weekly_minutes")
    logs = [
        _make_log(hid, date(2026, 6, 9)),
        _make_log(hid, date(2026, 6, 10)),
        _make_log(hid, date(2026, 6, 11)),
    ]
    sess = _session_for_streak(habit, logs)
    assert current_streak(hid, date(2026, 6, 11), session=sess) == 0
