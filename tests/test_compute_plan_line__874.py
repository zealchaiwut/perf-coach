"""TDD tests for compute_plan_line pure function (issue #874)."""
from __future__ import annotations

import datetime

import pytest

from backend.services.weight_plan import compute_plan_line


# ── helpers ─────────────────────────────────────────────────────────────────


def _plan(**kwargs):
    """Return a minimal plan dict with sensible defaults overridden by kwargs."""
    base = {
        "start_date": datetime.date(2024, 1, 1),
        "start_weight": 90.0,
        "goal_weight": None,
        "goal_date": None,
        "target_rate_kg_per_week": None,
    }
    base.update(kwargs)
    return base


# ── AC: explicit rate (loss) ─────────────────────────────────────────────────


def test_explicit_rate_loss_value():
    """Explicit negative rate: planned weight at day 14 = 89.2 (UAT step 1)."""
    plan = _plan(target_rate_kg_per_week=-0.4)
    result = compute_plan_line(plan, datetime.date(2024, 1, 15))
    assert "dates" in result
    assert "debug" in result
    assert datetime.date(2024, 1, 15) in result["dates"] or "2024-01-15" in result["dates"]
    # Accept either date or string keys
    dates = result["dates"]
    key = datetime.date(2024, 1, 15) if datetime.date(2024, 1, 15) in dates else "2024-01-15"
    assert dates[key] == pytest.approx(89.2, abs=0.01)
    assert result["debug"]["method"] == "explicit"


def test_explicit_rate_loss_debug_fields():
    """Debug block includes rate, method, start_date, start_weight."""
    plan = _plan(target_rate_kg_per_week=-0.4)
    result = compute_plan_line(plan, datetime.date(2024, 1, 15))
    debug = result["debug"]
    assert debug["method"] == "explicit"
    assert debug["rate"] == pytest.approx(-0.4, abs=0.001)
    assert "start_date" in debug
    assert "start_weight" in debug


def test_explicit_rate_loss_includes_start_date():
    """Date range includes start_date itself (day 0, no change)."""
    plan = _plan(target_rate_kg_per_week=-0.4)
    result = compute_plan_line(plan, datetime.date(2024, 1, 15))
    dates = result["dates"]
    key = datetime.date(2024, 1, 1) if datetime.date(2024, 1, 1) in dates else "2024-01-01"
    assert key in dates
    assert dates[key] == pytest.approx(90.0, abs=0.001)


# ── AC: explicit rate (gain) ─────────────────────────────────────────────────


def test_explicit_rate_gain_value():
    """Positive rate: planned weight at 4 weeks after start = 62.0 (UAT step 5)."""
    start = datetime.date(2024, 1, 1)
    as_of = start + datetime.timedelta(weeks=4)
    plan = _plan(start_weight=60.0, target_rate_kg_per_week=0.5)
    result = compute_plan_line(plan, as_of)
    dates = result["dates"]
    key = as_of if as_of in dates else str(as_of)
    assert dates[key] == pytest.approx(62.0, abs=0.01)
    assert result["debug"]["method"] == "explicit"


# ── AC: implied rate from goal ───────────────────────────────────────────────


def test_implied_rate_from_goal_value():
    """Implied rate from straight line: 80→85 kg over 8 weeks; at week 4 = 82.5 (UAT step 2)."""
    plan = _plan(
        start_weight=80.0,
        goal_weight=85.0,
        goal_date=datetime.date(2024, 2, 26),  # 56 days = 8 weeks after 2024-01-01
    )
    result = compute_plan_line(plan, datetime.date(2024, 1, 29))  # 28 days = 4 weeks
    assert "dates" in result
    dates = result["dates"]
    key = datetime.date(2024, 1, 29) if datetime.date(2024, 1, 29) in dates else "2024-01-29"
    assert dates[key] == pytest.approx(82.5, abs=0.01)
    assert result["debug"]["method"] == "implied"


def test_implied_rate_debug_fields():
    """Debug block for implied method contains resolved rate and method='implied'."""
    plan = _plan(
        start_weight=80.0,
        goal_weight=85.0,
        goal_date=datetime.date(2024, 2, 26),
    )
    result = compute_plan_line(plan, datetime.date(2024, 1, 29))
    debug = result["debug"]
    assert debug["method"] == "implied"
    assert debug["rate"] == pytest.approx(0.625, abs=0.001)


# ── AC: end date is capped at goal_date when earlier ─────────────────────────


def test_end_date_capped_at_goal_date():
    """When goal_date is before as_of_date, the last date in the range is goal_date."""
    plan = _plan(
        start_weight=90.0,
        goal_weight=88.0,
        goal_date=datetime.date(2024, 1, 8),
    )
    result = compute_plan_line(plan, datetime.date(2024, 1, 20))
    dates = result["dates"]
    date_keys = [d if isinstance(d, datetime.date) else datetime.date.fromisoformat(d) for d in dates]
    assert max(date_keys) <= datetime.date(2024, 1, 8)


# ── AC: missing start_weight returns empty ───────────────────────────────────


def test_missing_start_weight_returns_empty():
    """Missing start_weight → empty dates dict with debug.reason set (UAT step 3)."""
    plan = {
        "start_date": datetime.date(2024, 1, 1),
        "goal_weight": 85.0,
        "goal_date": datetime.date(2024, 3, 1),
        "target_rate_kg_per_week": None,
    }
    result = compute_plan_line(plan, datetime.date(2024, 2, 1))
    assert result["dates"] == {}
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]  # non-empty string


def test_missing_start_weight_does_not_raise():
    """Missing start_weight must not raise an exception."""
    plan = {"start_date": datetime.date(2024, 1, 1)}
    try:
        result = compute_plan_line(plan, datetime.date(2024, 2, 1))
    except Exception as exc:
        pytest.fail(f"compute_plan_line raised unexpectedly: {exc}")
    assert result["dates"] == {}


# ── AC: missing start_date returns empty ─────────────────────────────────────


def test_missing_start_date_returns_empty():
    """Missing start_date → empty dates dict with debug.reason set."""
    plan = {"start_weight": 90.0, "target_rate_kg_per_week": -0.4}
    result = compute_plan_line(plan, datetime.date(2024, 2, 1))
    assert result["dates"] == {}
    assert result["debug"]["reason"]


# ── AC: missing both rate and goal ───────────────────────────────────────────


def test_missing_rate_and_goal_returns_empty():
    """Has start_date and start_weight but no rate and no goal → empty with reason (UAT step 4)."""
    plan = _plan()  # target_rate_kg_per_week=None, goal_weight=None, goal_date=None
    result = compute_plan_line(plan, datetime.date(2024, 2, 1))
    assert result["dates"] == {}
    assert "reason" in result["debug"]
    assert result["debug"]["reason"]


def test_missing_rate_and_goal_does_not_raise():
    """Must never raise even when rate and goal are both absent."""
    plan = _plan()
    try:
        result = compute_plan_line(plan, datetime.date(2024, 2, 1))
    except Exception as exc:
        pytest.fail(f"compute_plan_line raised unexpectedly: {exc}")


# ── AC: missing goal_weight only (can't derive implied rate) ─────────────────


def test_missing_goal_weight_with_goal_date_returns_empty():
    """goal_date present but goal_weight absent → can't derive rate, returns empty."""
    plan = _plan(goal_date=datetime.date(2024, 3, 1))  # no goal_weight
    result = compute_plan_line(plan, datetime.date(2024, 2, 1))
    assert result["dates"] == {}
    assert result["debug"]["reason"]


# ── AC: pure function — no I/O, no mutation ──────────────────────────────────


def test_does_not_mutate_input_plan():
    """Input plan dict must not be mutated by the function."""
    plan = _plan(target_rate_kg_per_week=-0.4)
    original_keys = set(plan.keys())
    original_values = dict(plan)
    compute_plan_line(plan, datetime.date(2024, 1, 15))
    assert set(plan.keys()) == original_keys
    assert plan == original_values


# ── AC: date range is contiguous from start_date to end ──────────────────────


def test_date_range_is_contiguous():
    """Dates dict contains every day from start_date to as_of_date with no gaps."""
    plan = _plan(target_rate_kg_per_week=-0.4)
    as_of = datetime.date(2024, 1, 8)
    result = compute_plan_line(plan, as_of)
    dates = sorted(
        d if isinstance(d, datetime.date) else datetime.date.fromisoformat(d)
        for d in result["dates"]
    )
    expected = [datetime.date(2024, 1, 1) + datetime.timedelta(days=i) for i in range(8)]
    assert dates == expected
