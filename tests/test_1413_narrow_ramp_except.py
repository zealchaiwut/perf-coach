"""Tests for narrowed ramp-computation exception handling (issue #1413).

AC1 — ValueError from ramp helpers falls back to "base" phase (not propagated)
AC2 — Unexpected exceptions (non-ValueError) are NOT swallowed; they propagate
AC3 — A debug log is emitted when ValueError triggers the fallback

Strategy: mock the DB session and helper functions so no live DB is required.
The try block in _resolve_week_phase_from_db is entered only when an A-race
exists and the user is outside the taper window, so we configure the mock
Session to return a plausible Race and then patch daily_tss_series to
exercise the exception path.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.services.fuel import _resolve_week_phase_from_db


def _make_mock_race(today: date) -> MagicMock:
    """Return a mock Race-like object far outside the taper window."""
    race = MagicMock()
    race.race_date = today + timedelta(days=90)  # ~13 weeks out
    race.priority = "A"
    race.status = "planned"
    return race


def _make_mock_db(today: date) -> MagicMock:
    """Return a mock Session whose Race queries return an A-race and no 7-day race.

    The mock is configured so the function enters the ramp-computation try block:
    - race_7d → None (no imminent race)
    - a_race → future A-race (90 days out)
    - plan → None (no TrainingPlan, so the load-plan branch is skipped, but the
      try block is still entered so daily_tss_series runs first)
    """
    a_race = _make_mock_race(today)

    db = MagicMock()

    query_mock = MagicMock()
    db.query.return_value = query_mock
    # Chained .filter().first() and .filter().order_by().first() both return the
    # race for the A-race query, and None for the 7-day race check.
    filter_mock = MagicMock()
    query_mock.filter.return_value = filter_mock
    # The 7-day race uses .first() directly; A-race uses .order_by().first().
    order_mock = MagicMock()
    filter_mock.order_by.return_value = order_mock

    call_count = [0]

    def first_side_effect():
        call_count[0] += 1
        if call_count[0] == 1:
            return None   # 1st call: race_7d check → no imminent race
        if call_count[0] == 2:
            return a_race  # 2nd call: a_race (via order_by().first()) — but this
                           # goes through order_mock, handled below
        return None

    filter_mock.first.side_effect = first_side_effect

    order_call = [0]

    def order_first():
        order_call[0] += 1
        if order_call[0] == 1:
            return a_race  # A-race lookup
        return None

    order_mock.first.side_effect = order_first

    # plan query: return None (no TrainingPlan) — keeps taper_weeks at 3
    # We need a second db.query path for TrainingPlan. The simplest approach:
    # make all filter().first() calls after the race return None (plan = None).
    return db, a_race


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mock_db_and_uid(today: date):
    db, _ = _make_mock_db(today)
    uid = uuid.uuid4()
    return uid, db


# ── AC1 ─────────────────────────────────────────────────────────────────────

def test_value_error_falls_back_to_base():
    """AC1 — ValueError from daily_tss_series is caught; function returns base phase."""
    today = date.today()
    uid, db = _mock_db_and_uid(today)

    with patch(
        "backend.services.fuel.daily_tss_series",
        side_effect=ValueError("simulated missing training data"),
    ):
        phase, reason, avg = _resolve_week_phase_from_db(uid, today, db)

    assert phase == "base"


def test_value_error_trailing_avg_remains_none():
    """AC1 — When ValueError is caught, trailing_28d_weekly_avg stays None."""
    today = date.today()
    uid, db = _mock_db_and_uid(today)

    with patch(
        "backend.services.fuel.daily_tss_series",
        side_effect=ValueError("simulated missing training data"),
    ):
        _, _, trailing = _resolve_week_phase_from_db(uid, today, db)

    assert trailing is None


# ── AC2 ─────────────────────────────────────────────────────────────────────

def test_runtime_error_propagates():
    """AC2 — RuntimeError (unexpected bug) is NOT silently swallowed."""
    today = date.today()
    uid, db = _mock_db_and_uid(today)

    with patch(
        "backend.services.fuel.daily_tss_series",
        side_effect=RuntimeError("unexpected bug in tss helper"),
    ):
        with pytest.raises(RuntimeError, match="unexpected bug in tss helper"):
            _resolve_week_phase_from_db(uid, today, db)


def test_attribute_error_propagates():
    """AC2 — AttributeError (e.g. unexpected None attribute) propagates."""
    today = date.today()
    uid, db = _mock_db_and_uid(today)

    with patch(
        "backend.services.fuel.daily_tss_series",
        side_effect=AttributeError("no attribute 'tss'"),
    ):
        with pytest.raises(AttributeError):
            _resolve_week_phase_from_db(uid, today, db)


def test_type_error_propagates():
    """AC2 — TypeError from a computation bug propagates."""
    today = date.today()
    uid, db = _mock_db_and_uid(today)

    with patch(
        "backend.services.fuel.daily_tss_series",
        side_effect=TypeError("unsupported operand"),
    ):
        with pytest.raises(TypeError):
            _resolve_week_phase_from_db(uid, today, db)


# ── AC3 ─────────────────────────────────────────────────────────────────────

def test_debug_log_emitted_on_value_error():
    """AC3 — A debug log is emitted when ValueError triggers the fallback."""
    today = date.today()
    uid, db = _mock_db_and_uid(today)

    with patch(
        "backend.services.fuel.daily_tss_series",
        side_effect=ValueError("no data"),
    ):
        with patch("backend.services.fuel._log") as mock_log:
            _resolve_week_phase_from_db(uid, today, db)

    mock_log.debug.assert_called_once()
