"""TDD tests: compute_plan_line must guard against plan.goal_date=None (issue #896)."""
from __future__ import annotations

import datetime
import types

import pytest

from backend.services.weight_plan import compute_plan_line


def _plan(**kwargs):
    """Return a simple namespace (attr-access) plan with sensible defaults."""
    defaults = dict(
        start_date=datetime.date(2026, 1, 1),
        start_weight_kg=90.0,
        goal_weight_kg=86.0,
        goal_date=datetime.date(2026, 3, 31),
        target_rate_kg_per_week=-0.33,
    )
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


# ── AC1: goal_date=None returns empty list, does not raise ───────────────────


def test_goal_date_none_returns_empty_list():
    """compute_plan_line returns [] when plan.goal_date is None."""
    plan = _plan(goal_date=None)
    result = compute_plan_line(plan, datetime.date(2026, 2, 1))
    assert result == []


def test_goal_date_none_does_not_raise():
    """compute_plan_line must not raise TypeError or AttributeError when goal_date=None."""
    plan = _plan(goal_date=None)
    try:
        compute_plan_line(plan, datetime.date(2026, 2, 1))
    except (TypeError, AttributeError) as exc:
        pytest.fail(f"compute_plan_line raised unexpectedly with goal_date=None: {exc}")


def test_goal_date_missing_attribute_returns_empty_list():
    """compute_plan_line returns [] when plan has no goal_date attribute at all."""
    plan = types.SimpleNamespace(
        start_date=datetime.date(2026, 1, 1),
        start_weight_kg=90.0,
        goal_weight_kg=86.0,
        target_rate_kg_per_week=-0.33,
    )
    result = compute_plan_line(plan, datetime.date(2026, 2, 1))
    assert result == []


# ── AC2: normal (valid goal_date) path still works ───────────────────────────


def test_valid_plan_returns_points():
    """compute_plan_line with a valid goal_date still returns a non-empty list."""
    plan = _plan()
    today = datetime.date(2026, 1, 15)
    result = compute_plan_line(plan, today)
    assert isinstance(result, list)
    assert len(result) > 0


def test_valid_plan_point_shape():
    """Each returned point has date (ISO string), weight_kg (float), segment='original'."""
    plan = _plan()
    today = datetime.date(2026, 1, 15)
    result = compute_plan_line(plan, today)
    for pt in result:
        assert "date" in pt
        assert "weight_kg" in pt
        assert pt["segment"] == "original"
