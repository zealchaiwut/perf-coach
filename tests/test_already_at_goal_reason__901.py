"""
Tests for issue #901: Map already-at-goal to a distinct reason in
build_arrival_projection_response.

Acceptance criteria:
- AC1: When project_arrival returns reason="already at or past goal" (user exactly
       at goal weight), build_arrival_projection_response returns reason="already_at_goal"
       instead of "insufficient_data".
- AC2: When the user has overshot (past goal, still losing), reason="already_at_goal".
- AC3: recent_rate is still populated (not null) in the already_at_goal case.
- AC4: projected_arrival_date and projected_rate are null in the already_at_goal case.
- AC5: All four response keys are present (consistent shape).
- AC6: "already_at_goal" is distinct from "insufficient_data" — the catch-all branch
       must not swallow the already-at-goal signal.
"""
from __future__ import annotations

import datetime

import pytest

from backend.services.goal_arrival_caller import build_arrival_projection_response


TODAY = datetime.date(2026, 6, 21)
REQUIRED_KEYS = {"projected_arrival_date", "projected_rate", "recent_rate", "reason"}


def _trend(n_days, start_weight, weekly_change_kg):
    entries = []
    for i in range(n_days):
        d = TODAY - datetime.timedelta(days=n_days - 1 - i)
        w = start_weight + (weekly_change_kg / 7.0) * i
        entries.append({"date": d, "weight_kg": w})
    return entries


def _assert_shape(result):
    missing = REQUIRED_KEYS - result.keys()
    assert not missing, f"Missing keys in response: {missing}"


# ── AC1: Exactly at goal weight ───────────────────────────────────────────────

def test_exactly_at_goal_returns_already_at_goal_reason():
    """AC1: User whose last weight exactly equals goal gets reason='already_at_goal'."""
    # Flat trend ending exactly at goal weight
    goal = 80.0
    trend = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": goal}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=goal,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["reason"] == "already_at_goal", (
        f"Expected 'already_at_goal', got {result['reason']!r}. "
        "User at goal must not receive 'insufficient_data'."
    )


def test_exactly_at_goal_not_insufficient_data():
    """AC6: already-at-goal must NOT return 'insufficient_data'."""
    goal = 80.0
    trend = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": goal}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=goal,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["reason"] != "insufficient_data", (
        "already-at-goal must not be misreported as 'insufficient_data'"
    )


# ── AC2: Past goal (overshot — still losing below a loss target) ──────────────

def test_past_goal_returns_already_at_goal_reason():
    """AC2: User who has overshot goal (below a loss target) gets reason='already_at_goal'."""
    # User aims for 80 kg but is now at 79 kg and still losing
    goal = 80.0
    trend = _trend(21, start_weight=81.0, weekly_change_kg=-0.4)
    # Last entry will be slightly below 81, which may or may not be below goal.
    # Build a trend that clearly ends below goal.
    trend_past = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": 79.5 - i * 0.05}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend_past,
        goal_weight_kg=goal,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["reason"] == "already_at_goal", (
        f"Expected 'already_at_goal' for past-goal scenario, got {result['reason']!r}"
    )


def test_past_goal_not_insufficient_data():
    """AC6: past-goal must NOT return 'insufficient_data'."""
    goal = 80.0
    trend_past = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": 79.5 - i * 0.05}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend_past,
        goal_weight_kg=goal,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["reason"] != "insufficient_data"


# ── AC3: recent_rate populated in already_at_goal case ───────────────────────

def test_already_at_goal_recent_rate_is_populated():
    """AC3: recent_rate must be non-null in the already_at_goal response."""
    goal = 80.0
    trend = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": goal}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=goal,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["recent_rate"] is not None, (
        "recent_rate should be populated even when user is already at goal"
    )


def test_past_goal_recent_rate_is_populated():
    """AC3: recent_rate is non-null even when user has overshot."""
    goal = 80.0
    trend_past = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": 79.5 - i * 0.05}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend_past,
        goal_weight_kg=goal,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["recent_rate"] is not None


# ── AC4: projected fields are null in already_at_goal case ───────────────────

def test_already_at_goal_projected_arrival_is_null():
    """AC4: projected_arrival_date must be null when user is already at goal."""
    goal = 80.0
    trend = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": goal}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=goal,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    assert result["projected_arrival_date"] is None
    assert result["projected_rate"] is None


# ── AC5: Response shape is consistent ────────────────────────────────────────

def test_already_at_goal_shape():
    """AC5: All four response keys must be present in the already_at_goal response."""
    goal = 80.0
    trend = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": goal}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=goal,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    _assert_shape(result)


def test_past_goal_shape():
    """AC5: All four response keys must be present in the past-goal (overshot) response."""
    goal = 80.0
    trend_past = [
        {"date": TODAY - datetime.timedelta(days=20 - i), "weight_kg": 79.5 - i * 0.05}
        for i in range(21)
    ]
    result = build_arrival_projection_response(
        trend=trend_past,
        goal_weight_kg=goal,
        today=TODAY,
        no_active_plan=False,
        no_active_goal=False,
    )
    _assert_shape(result)
