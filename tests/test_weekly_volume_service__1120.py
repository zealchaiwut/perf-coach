"""Unit tests for issue #1120: get_weekly_volume service function.

Acceptance criteria covered:
  AC1 - A function in backend/services/training_load.py encapsulates weekly
        aggregation and returns distance_km, total_tss, and session_count.
  AC5 - Volume service function has at least one unit test verifying aggregation
        independently of the endpoint (multiple-workout and zero-workout cases).
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.services.training_load import get_weekly_volume


_USER_ID = str(uuid.uuid4())
_WEEK_START = date(2026, 6, 29)  # Monday
_WEEK_END = date(2026, 7, 5)    # Sunday


def _make_workout(distance_km=None, tss=None, workout_type="Run"):
    w = MagicMock()
    w.distance_km = distance_km
    w.tss = tss
    w.workout_type = workout_type
    return w


def _mock_session(workouts):
    """Return a context-manager mock whose query().filter().all() returns workouts."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.all.return_value = workouts
    return mock_session


# ── AC5 case 1: zero workouts ─────────────────────────────────────────────────

def test_zero_workouts_returns_zero_distance():
    """AC5: distance_km is 0.0 when no workouts exist in the window."""
    with patch("backend.services.training_load.Session", return_value=_mock_session([])):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert result["distance_km"] == 0.0


def test_zero_workouts_returns_zero_tss():
    """AC5: total_tss is 0.0 when no workouts exist in the window."""
    with patch("backend.services.training_load.Session", return_value=_mock_session([])):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert result["total_tss"] == 0.0


def test_zero_workouts_returns_zero_session_count():
    """AC5: session_count is 0 when no workouts exist in the window."""
    with patch("backend.services.training_load.Session", return_value=_mock_session([])):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert result["session_count"] == 0


def test_zero_workouts_returns_empty_workout_types():
    """AC5: workout_types is empty list when no workouts exist."""
    with patch("backend.services.training_load.Session", return_value=_mock_session([])):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert result["workout_types"] == []


# ── AC5 case 2: multiple workouts ────────────────────────────────────────────

def test_multiple_workouts_session_count():
    """AC5: session_count equals the number of workouts returned."""
    workouts = [
        _make_workout(distance_km=10.5, tss=70.0, workout_type="Run"),
        _make_workout(distance_km=None, tss=45.0, workout_type="Strength"),
    ]
    with patch("backend.services.training_load.Session", return_value=_mock_session(workouts)):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert result["session_count"] == 2


def test_multiple_workouts_distance_sum():
    """AC5: distance_km sums non-null distances across workouts."""
    workouts = [
        _make_workout(distance_km=10.5, tss=70.0, workout_type="Run"),
        _make_workout(distance_km=5.0, tss=30.0, workout_type="Run"),
        _make_workout(distance_km=None, tss=45.0, workout_type="Strength"),
    ]
    with patch("backend.services.training_load.Session", return_value=_mock_session(workouts)):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert abs(result["distance_km"] - 15.5) < 0.01


def test_multiple_workouts_tss_sum():
    """AC5: total_tss sums TSS values from all workouts."""
    workouts = [
        _make_workout(distance_km=10.5, tss=70.0, workout_type="Run"),
        _make_workout(distance_km=None, tss=45.0, workout_type="Strength"),
    ]
    with patch("backend.services.training_load.Session", return_value=_mock_session(workouts)):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert abs(result["total_tss"] - 115.0) < 0.01


def test_multiple_workouts_types_list():
    """AC5: workout_types contains the type string for each workout."""
    workouts = [
        _make_workout(distance_km=10.5, tss=70.0, workout_type="Run"),
        _make_workout(distance_km=None, tss=45.0, workout_type="Strength"),
    ]
    with patch("backend.services.training_load.Session", return_value=_mock_session(workouts)):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert result["workout_types"] == ["Run", "Strength"]


# ── AC1: return shape ─────────────────────────────────────────────────────────

def test_return_has_all_required_keys():
    """AC1: function returns all four required keys."""
    with patch("backend.services.training_load.Session", return_value=_mock_session([])):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert "distance_km" in result
    assert "total_tss" in result
    assert "session_count" in result
    assert "workout_types" in result


def test_workouts_with_no_tss_excluded_from_sum():
    """AC5: workouts without TSS (None) do not crash and contribute 0 to total_tss."""
    workouts = [
        _make_workout(distance_km=8.0, tss=None, workout_type="Run"),
        _make_workout(distance_km=None, tss=50.0, workout_type="Strength"),
    ]
    with patch("backend.services.training_load.Session", return_value=_mock_session(workouts)):
        result = get_weekly_volume(_USER_ID, _WEEK_START, _WEEK_END)
    assert abs(result["total_tss"] - 50.0) < 0.01
    assert result["session_count"] == 2
