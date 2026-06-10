"""Tests for issue #431: Enforce backfill window and add increment-log mode.

Seven unit tests anchored to the AC items (a)-(g):
  (a) backfill within current week → 201
  (b) future date → 422 future_date
  (c) last-week date → 422 past_week_locked
  (d) add mode accumulates: log 20, then +15 same day → row value = 35
  (e) set mode replaces: log 20, then set 15 same day → row value = 15
  (f) checkmark ignores mode: always value = 1 regardless of submitted mode/value
  (g) response includes correct week_current_value
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000431")

# Fixed Bangkok "today" for deterministic tests: Thursday 2026-06-11
# Week Monday: 2026-06-08
_TODAY_BKK = date(2026, 6, 11)
_WEEK_MONDAY = date(2026, 6, 8)
_LAST_WEEK_DATE = date(2026, 6, 7)   # Sunday of previous week
_TOMORROW = date(2026, 6, 12)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app), mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_habit(tracking_type="weekly_quantity", hid=None):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = "Test Habit"
    h.tracking_type = tracking_type
    h.weekly_target = 100.0
    h.unit = "minutes"
    h.auto_fill_source = None
    h.icon = None
    h.color = None
    h.sort_order = 0
    h.is_archived = False
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-11T00:00:00+00:00"
    h.created_at = ts
    h.updated_at = None
    return h


def _make_log_mock(habit_id, log_date, value, log_week_start=None):
    log = MagicMock(spec=HabitLog)
    log.id = uuid.uuid4()
    log.habit_id = habit_id
    log.user_id = _USER_ID
    log.log_date = log_date
    log.log_week_start = log_week_start or _WEEK_MONDAY
    log.value = value
    log.notes = None
    log.source = "manual"
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-11T00:00:00+00:00"
    log.created_at = ts
    log.updated_at = None
    return log


def _make_post_session(habit, existing_log=None, week_logs=None):
    """Session mock for POST /log endpoint — handles two consecutive query() calls."""
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = habit

    call_count = [0]

    def _query_side(model):
        call_count[0] += 1
        q = MagicMock()
        q.filter.return_value = q
        if call_count[0] == 1:
            q.first.return_value = existing_log
        else:
            q.all.return_value = week_logs if week_logs is not None else []
        return q

    sess.query.side_effect = _query_side
    return sess


def _make_delete_session(habit, existing_log=None):
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = habit

    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = existing_log
    sess.query.return_value = q
    return sess


# ── (a) Backfill within current week → 201 ────────────────────────────────────

class TestACa_BackfillCurrentWeek:
    """AC (a): logging a date within the current Bangkok week succeeds."""

    def test_monday_of_current_week_returns_201(self):
        client, _ = _make_client()
        habit = _make_habit()
        sess = _make_post_session(habit, existing_log=None, week_logs=[])

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.post(
                f"/api/habits/{habit.id}/log",
                json={"log_date": _WEEK_MONDAY.isoformat(), "value": 30},
            )
        _teardown()
        assert r.status_code == 201

    def test_today_returns_201(self):
        client, _ = _make_client()
        habit = _make_habit()
        sess = _make_post_session(habit, existing_log=None, week_logs=[])

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.post(
                f"/api/habits/{habit.id}/log",
                json={"log_date": _TODAY_BKK.isoformat(), "value": 20},
            )
        _teardown()
        assert r.status_code == 201


# ── (b) Future date → 422 future_date ─────────────────────────────────────────

class TestACb_FutureDate:
    """AC (b): log_date after today returns 422 with error_code='future_date'."""

    def test_tomorrow_returns_422_future_date(self):
        client, _ = _make_client()
        habit = _make_habit()
        sess = _make_post_session(habit)

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.post(
                f"/api/habits/{habit.id}/log",
                json={"log_date": _TOMORROW.isoformat(), "value": 10},
            )
        _teardown()
        assert r.status_code == 422
        detail = r.json().get("detail", r.json())
        if isinstance(detail, dict):
            assert detail.get("error_code") == "future_date"
        else:
            assert any(
                d.get("error_code") == "future_date"
                for d in (detail if isinstance(detail, list) else [])
            )


# ── (c) Last-week date → 422 past_week_locked ─────────────────────────────────

class TestACc_LastWeekLocked:
    """AC (c): log_date before this Monday returns 422 with error_code='past_week_locked'."""

    def test_last_week_date_returns_422_past_week_locked(self):
        client, _ = _make_client()
        habit = _make_habit()
        sess = _make_post_session(habit)

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.post(
                f"/api/habits/{habit.id}/log",
                json={"log_date": _LAST_WEEK_DATE.isoformat(), "value": 10},
            )
        _teardown()
        assert r.status_code == 422
        detail = r.json().get("detail", r.json())
        if isinstance(detail, dict):
            assert detail.get("error_code") == "past_week_locked"
        else:
            assert any(
                d.get("error_code") == "past_week_locked"
                for d in (detail if isinstance(detail, list) else [])
            )

    def test_delete_last_week_date_returns_422(self):
        """DELETE enforces the same window."""
        client, _ = _make_client()
        habit = _make_habit()
        existing = _make_log_mock(habit.id, _LAST_WEEK_DATE, 20.0)
        sess = _make_delete_session(habit, existing_log=existing)

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.delete(
                f"/api/habits/{habit.id}/log",
                params={"date": _LAST_WEEK_DATE.isoformat()},
            )
        _teardown()
        assert r.status_code == 422
        detail = r.json().get("detail", r.json())
        if isinstance(detail, dict):
            assert detail.get("error_code") == "past_week_locked"


# ── (d) Add mode accumulates ──────────────────────────────────────────────────

class TestACd_AddModeAccumulates:
    """AC (d): mode='add' adds submitted value to existing log value."""

    def test_add_mode_20_plus_15_equals_35(self):
        client, _ = _make_client()
        habit = _make_habit(tracking_type="weekly_quantity")
        existing = _make_log_mock(habit.id, _TODAY_BKK, 20.0)
        result_log = _make_log_mock(habit.id, _TODAY_BKK, 35.0)
        sess = _make_post_session(habit, existing_log=existing, week_logs=[result_log])

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.post(
                f"/api/habits/{habit.id}/log",
                json={"log_date": _TODAY_BKK.isoformat(), "value": 15, "mode": "add"},
            )
        _teardown()
        assert r.status_code == 201
        assert r.json()["value"] == 35.0


# ── (e) Set mode replaces ──────────────────────────────────────────────────────

class TestACe_SetModeReplaces:
    """AC (e): mode='set' (default) replaces the existing log value."""

    def test_set_mode_20_set_15_equals_15(self):
        client, _ = _make_client()
        habit = _make_habit(tracking_type="weekly_quantity")
        existing = _make_log_mock(habit.id, _TODAY_BKK, 20.0)
        result_log = _make_log_mock(habit.id, _TODAY_BKK, 15.0)
        sess = _make_post_session(habit, existing_log=existing, week_logs=[result_log])

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.post(
                f"/api/habits/{habit.id}/log",
                json={"log_date": _TODAY_BKK.isoformat(), "value": 15, "mode": "set"},
            )
        _teardown()
        assert r.status_code == 201
        assert r.json()["value"] == 15.0


# ── (f) Checkmark ignores mode ────────────────────────────────────────────────

class TestACf_CheckmarkIgnoresMode:
    """AC (f): daily_checkmark habits always write value=1 regardless of mode/value."""

    def test_checkmark_add_mode_value_5_gives_1(self):
        client, _ = _make_client()
        habit = _make_habit(tracking_type="daily_checkmark")
        existing = _make_log_mock(habit.id, _TODAY_BKK, 1.0)
        result_log = _make_log_mock(habit.id, _TODAY_BKK, 1.0)
        sess = _make_post_session(habit, existing_log=existing, week_logs=[result_log])

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.post(
                f"/api/habits/{habit.id}/log",
                json={"log_date": _TODAY_BKK.isoformat(), "value": 5, "mode": "add"},
            )
        _teardown()
        assert r.status_code == 201
        assert r.json()["value"] == 1.0

    def test_checkmark_no_existing_always_1(self):
        client, _ = _make_client()
        habit = _make_habit(tracking_type="daily_checkmark")
        result_log = _make_log_mock(habit.id, _TODAY_BKK, 1.0)
        sess = _make_post_session(habit, existing_log=None, week_logs=[result_log])

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.post(
                f"/api/habits/{habit.id}/log",
                json={"log_date": _TODAY_BKK.isoformat(), "value": 99, "mode": "add"},
            )
        _teardown()
        assert r.status_code == 201
        assert r.json()["value"] == 1.0


# ── (g) Response includes week_current_value ──────────────────────────────────

class TestACg_WeekCurrentValue:
    """AC (g): response body includes week_current_value = sum of current-week logs."""

    def test_week_current_value_in_response(self):
        client, _ = _make_client()
        habit = _make_habit(tracking_type="weekly_quantity")
        log_a = _make_log_mock(habit.id, _WEEK_MONDAY, 20.0)
        log_b = _make_log_mock(habit.id, _TODAY_BKK, 15.0)
        # No existing log for today; week logs = [log_a, log_b] after write
        sess = _make_post_session(habit, existing_log=None, week_logs=[log_a, log_b])

        with patch("backend.main.Session", return_value=sess), \
             patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            r = client.post(
                f"/api/habits/{habit.id}/log",
                json={"log_date": _TODAY_BKK.isoformat(), "value": 15},
            )
        _teardown()
        assert r.status_code == 201
        assert "week_current_value" in r.json()
        assert r.json()["week_current_value"] == 35.0
