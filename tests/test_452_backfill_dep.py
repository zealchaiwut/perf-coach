"""Tests for issue #452: Extract shared backfill window validation as FastAPI dependency.

Implicit acceptance criteria:
  (a) A FastAPI dependency function exists that parses and validates a date query param
      against the Bangkok backfill window.
  (b) The dependency raises 422 / future_date for dates after today.
  (c) The dependency raises 422 / past_week_locked for dates before this Monday.
  (d) The dependency returns the parsed date for in-window dates.
  (e) DELETE /api/habits/{id}/log uses Depends() for date validation (not ad-hoc inline).
  (f) All existing test_habits.py behaviours are preserved (backfill applies to DELETE).
"""
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import (
    app,
    _validated_backfill_date,
    _validate_backfill_window,
    resolve_user,
)
from backend.models import Habit, HabitLog

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000452")

_TODAY_BKK = date(2026, 6, 11)
_WEEK_MONDAY = date(2026, 6, 8)
_LAST_WEEK_DATE = date(2026, 6, 7)
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


def _make_habit(hid=None):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = "Test Habit"
    h.tracking_type = "weekly_quantity"
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


# ── (a) Dependency exists as a public symbol ──────────────────────────────────

class TestDependencyExists:
    """AC (a): _validated_backfill_date must exist and be callable."""

    def test_dependency_is_callable(self):
        assert callable(_validated_backfill_date)

    def test_core_validator_is_callable(self):
        assert callable(_validate_backfill_window)


# ── (b) Dependency raises 422 future_date for dates after today ───────────────

class TestFutureDateDependency:
    """AC (b): future date raises 422 with error_code='future_date'."""

    def test_future_date_raises_422(self):
        with patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            with pytest.raises(HTTPException) as exc_info:
                _validated_backfill_date(date=_TOMORROW.isoformat())
            assert exc_info.value.status_code == 422
            detail = exc_info.value.detail
            assert detail.get("error_code") == "future_date"

    def test_core_validator_future_date(self):
        with patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            with pytest.raises(HTTPException) as exc_info:
                _validate_backfill_window(_TOMORROW)
            assert exc_info.value.status_code == 422
            assert exc_info.value.detail.get("error_code") == "future_date"


# ── (c) Dependency raises 422 past_week_locked for pre-Monday dates ───────────

class TestPastWeekDependency:
    """AC (c): last-week date raises 422 with error_code='past_week_locked'."""

    def test_last_week_date_raises_422(self):
        with patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            with pytest.raises(HTTPException) as exc_info:
                _validated_backfill_date(date=_LAST_WEEK_DATE.isoformat())
            assert exc_info.value.status_code == 422
            detail = exc_info.value.detail
            assert detail.get("error_code") == "past_week_locked"

    def test_core_validator_past_week(self):
        with patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            with pytest.raises(HTTPException) as exc_info:
                _validate_backfill_window(_LAST_WEEK_DATE)
            assert exc_info.value.status_code == 422
            assert exc_info.value.detail.get("error_code") == "past_week_locked"


# ── (d) Dependency returns parsed date for in-window dates ────────────────────

class TestInWindowDependency:
    """AC (d): valid in-window date string returns the parsed date object."""

    def test_today_returns_date(self):
        with patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            result = _validated_backfill_date(date=_TODAY_BKK.isoformat())
        assert result == _TODAY_BKK

    def test_monday_returns_date(self):
        with patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            result = _validated_backfill_date(date=_WEEK_MONDAY.isoformat())
        assert result == _WEEK_MONDAY

    def test_mid_week_returns_date(self):
        mid_week = _TODAY_BKK - timedelta(days=1)
        with patch("backend.main._bangkok_today", return_value=_TODAY_BKK):
            result = _validated_backfill_date(date=mid_week.isoformat())
        assert result == mid_week


# ── (e) DELETE endpoint uses Depends via integration test ────────────────────

class TestDeleteEndpointValidation:
    """AC (e/f): DELETE /api/habits/{id}/log enforces the backfill window."""

    def setup_method(self):
        self.habit = _make_habit()
        self.client, _ = _make_client()

    def teardown_method(self):
        _teardown()

    def test_delete_future_date_returns_422(self):
        with (
            patch("backend.main._bangkok_today", return_value=_TODAY_BKK),
            patch("backend.main.Session") as mock_sess_cls,
        ):
            mock_sess = MagicMock()
            mock_sess.__enter__ = MagicMock(return_value=mock_sess)
            mock_sess.__exit__ = MagicMock(return_value=False)
            mock_sess_cls.return_value = mock_sess

            resp = self.client.delete(
                f"/api/habits/{self.habit.id}/log",
                params={"date": _TOMORROW.isoformat()},
            )
        assert resp.status_code == 422
        body = resp.json()
        detail = body.get("detail", body)
        if isinstance(detail, dict):
            assert detail.get("error_code") == "future_date"
        else:
            assert any(d.get("error_code") == "future_date" for d in detail if isinstance(d, dict))

    def test_delete_past_week_returns_422(self):
        with (
            patch("backend.main._bangkok_today", return_value=_TODAY_BKK),
            patch("backend.main.Session") as mock_sess_cls,
        ):
            mock_sess = MagicMock()
            mock_sess.__enter__ = MagicMock(return_value=mock_sess)
            mock_sess.__exit__ = MagicMock(return_value=False)
            mock_sess_cls.return_value = mock_sess

            resp = self.client.delete(
                f"/api/habits/{self.habit.id}/log",
                params={"date": _LAST_WEEK_DATE.isoformat()},
            )
        assert resp.status_code == 422
        body = resp.json()
        detail = body.get("detail", body)
        if isinstance(detail, dict):
            assert detail.get("error_code") == "past_week_locked"
        else:
            assert any(d.get("error_code") == "past_week_locked" for d in detail if isinstance(d, dict))

    def test_delete_invalid_date_format_returns_400(self):
        resp = self.client.delete(
            f"/api/habits/{self.habit.id}/log",
            params={"date": "not-a-date"},
        )
        assert resp.status_code == 400
