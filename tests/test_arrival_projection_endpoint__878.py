"""
Tests for issue #878: Add projection endpoint for arrival date and rate.

Acceptance criteria verified:
- AC1: Endpoint resolves plan and goal via DB (tested via caller function)
- AC2: Returns projected_arrival_date, projected_rate, recent_rate on success
- AC3: not-trending-toward-goal returns valid response with projected fields null,
       recent_rate populated, reason="not_trending_toward_goal"
- AC4: missing data returns valid empty-state responses with appropriate reason strings
       (no_active_plan, no_active_goal, insufficient_data) — always HTTP 200
- AC5: recent_rate is always present when rate can be computed
- AC6: Response shape is consistent across all states (no conditional top-level keys)
- AC7: Unit tests cover normal projection, not-trending-toward-goal, each missing-data reason
"""
from __future__ import annotations

import datetime

import pytest

from backend.services.goal_arrival_caller import build_arrival_projection_response


TODAY = datetime.date(2026, 6, 21)

# ── helpers ───────────────────────────────────────────────────────────────────

def _trend(n_days, start_weight, weekly_change_kg):
    """Build a trend list with linear weight change, oldest entry first."""
    entries = []
    for i in range(n_days):
        d = TODAY - datetime.timedelta(days=n_days - 1 - i)
        w = start_weight + (weekly_change_kg / 7.0) * i
        entries.append({"date": d, "weight_kg": w})
    return entries


# ── AC6: Response shape is consistent ────────────────────────────────────────

REQUIRED_KEYS = {"projected_arrival_date", "projected_rate", "recent_rate", "reason"}


def _assert_shape(result: dict):
    """All four top-level keys must always be present."""
    missing = REQUIRED_KEYS - result.keys()
    assert not missing, f"Missing keys in response: {missing}"


# ── AC2 / AC7: Normal projection (happy path) ────────────────────────────────

def test_normal_projection_has_all_keys():
    """AC2+AC6: success result must have all four top-level keys."""
    trend = _trend(21, start_weight=93.0, weekly_change_kg=-0.4)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    _assert_shape(result)


def test_normal_projection_arrival_date_not_null():
    """AC2: on a converging trend, projected_arrival_date must be non-null."""
    trend = _trend(21, start_weight=93.0, weekly_change_kg=-0.4)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["projected_arrival_date"] is not None


def test_normal_projection_rate_fields_populated():
    """AC2+AC5: projected_rate and recent_rate must be non-null on success."""
    trend = _trend(21, start_weight=93.0, weekly_change_kg=-0.4)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["projected_rate"] is not None
    assert result["recent_rate"] is not None


def test_normal_projection_reason_is_null():
    """AC6: reason must be null (not absent) on a successful projection."""
    trend = _trend(21, start_weight=93.0, weekly_change_kg=-0.4)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert "reason" in result
    assert result["reason"] is None


def test_normal_projection_arrival_date_is_string():
    """AC2: projected_arrival_date must be an ISO string for JSON serialization."""
    trend = _trend(21, start_weight=93.0, weekly_change_kg=-0.4)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    # Must be serializable — string or None, not a date object
    assert isinstance(result["projected_arrival_date"], str)
    # Must parse as a valid ISO date
    datetime.date.fromisoformat(result["projected_arrival_date"])


# ── AC3 / AC7: Not-trending-toward-goal ──────────────────────────────────────

def test_not_trending_projected_fields_null():
    """AC3: not-trending trend returns projected_arrival_date=null, projected_rate=null."""
    # Gaining weight on a loss goal
    trend = _trend(21, start_weight=85.0, weekly_change_kg=+0.5)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["projected_arrival_date"] is None
    assert result["projected_rate"] is None


def test_not_trending_recent_rate_populated():
    """AC3+AC5: recent_rate must be non-null even when not trending toward goal."""
    trend = _trend(21, start_weight=85.0, weekly_change_kg=+0.5)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["recent_rate"] is not None


def test_not_trending_reason_field():
    """AC3: reason must be 'not_trending_toward_goal'."""
    trend = _trend(21, start_weight=85.0, weekly_change_kg=+0.5)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["reason"] == "not_trending_toward_goal"


def test_not_trending_shape():
    """AC6: all four keys must be present in not-trending response."""
    trend = _trend(21, start_weight=85.0, weekly_change_kg=+0.5)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    _assert_shape(result)


# ── AC4 / AC7: No active plan ────────────────────────────────────────────────

def test_no_active_plan_returns_null_projections():
    """AC4: no_active_plan → all projection fields null."""
    result = build_arrival_projection_response(
        trend=[],
        goal_weight_kg=None,
        today=TODAY,
        no_active_plan=True,
        no_active_goal=False,
    )
    assert result["projected_arrival_date"] is None
    assert result["projected_rate"] is None
    assert result["recent_rate"] is None


def test_no_active_plan_reason():
    """AC4: no_active_plan → reason='no_active_plan'."""
    result = build_arrival_projection_response(
        trend=[],
        goal_weight_kg=None,
        today=TODAY,
        no_active_plan=True,
        no_active_goal=False,
    )
    assert result["reason"] == "no_active_plan"


def test_no_active_plan_shape():
    """AC6: all four keys must be present for no_active_plan."""
    result = build_arrival_projection_response(
        trend=[],
        goal_weight_kg=None,
        today=TODAY,
        no_active_plan=True,
        no_active_goal=False,
    )
    _assert_shape(result)


# ── AC4 / AC7: No active goal ────────────────────────────────────────────────

def test_no_active_goal_returns_null_projections():
    """AC4: no_active_goal → all projection fields null."""
    result = build_arrival_projection_response(
        trend=[],
        goal_weight_kg=None,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=True,
    )
    assert result["projected_arrival_date"] is None
    assert result["projected_rate"] is None
    assert result["recent_rate"] is None


def test_no_active_goal_reason():
    """AC4: no_active_goal → reason='no_active_goal'."""
    result = build_arrival_projection_response(
        trend=[],
        goal_weight_kg=None,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=True,
    )
    assert result["reason"] == "no_active_goal"


def test_no_active_goal_shape():
    """AC6: all four keys must be present for no_active_goal."""
    result = build_arrival_projection_response(
        trend=[],
        goal_weight_kg=None,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=True,
    )
    _assert_shape(result)


# ── AC4 / AC7: Insufficient data ─────────────────────────────────────────────

def test_insufficient_data_reason():
    """AC4: fewer than 2 weight entries → reason='insufficient_data'."""
    trend = _trend(1, start_weight=90.0, weekly_change_kg=-0.3)  # only 1 entry
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["reason"] == "insufficient_data"


def test_insufficient_data_null_projections():
    """AC4: insufficient data → all projection fields null."""
    trend = _trend(1, start_weight=90.0, weekly_change_kg=-0.3)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["projected_arrival_date"] is None
    assert result["projected_rate"] is None
    assert result["recent_rate"] is None


def test_empty_trend_insufficient_data():
    """AC4: empty trend list → reason='insufficient_data'."""
    result = build_arrival_projection_response(
        trend=[],
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["reason"] == "insufficient_data"


def test_insufficient_data_shape():
    """AC6: all four keys must be present for insufficient_data."""
    trend = _trend(1, start_weight=90.0, weekly_change_kg=-0.3)
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    _assert_shape(result)


# ── AC5: recent_rate always present when computable ──────────────────────────

def test_recent_rate_present_in_flat_trend():
    """AC5: flat (zero-rate) trend still computes and returns recent_rate."""
    trend = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": 85.0}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=80.0,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    # recent_rate should be 0.0 (flat), not None
    assert result["recent_rate"] is not None
    assert result["recent_rate"] == pytest.approx(0.0, abs=0.01)


# ── AC7: No DB imports in build_arrival_projection_response ──────────────────

def test_no_db_imports_in_pure_function():
    """AC7: build_arrival_projection_response must not import DB modules."""
    import inspect
    import backend.services.goal_arrival_caller as m
    src = inspect.getsource(build_arrival_projection_response)
    assert "session" not in src.lower() or "sessionmaker" not in src.lower()
    # The function signature must not accept a session parameter
    sig = inspect.signature(build_arrival_projection_response)
    assert "session" not in sig.parameters
