"""TDD tests for recompute_plan_from_progress and compute_plan_line (issue #863)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.services.weight_plan import compute_plan_line, recompute_plan_from_progress


# ── helpers ──────────────────────────────────────────────────────────────────

START_DATE = datetime.date(2026, 1, 5)   # week 0
GOAL_DATE = START_DATE + datetime.timedelta(weeks=12)  # 2026-03-30
WEEK_4 = START_DATE + datetime.timedelta(weeks=4)      # 2026-02-02


def _plan(
    start_weight_kg=90.0,
    goal_weight_kg=86.0,
    target_rate_kg_per_week=0.33,
    start_date=START_DATE,
    goal_date=GOAL_DATE,
):
    return SimpleNamespace(
        start_date=start_date,
        start_weight_kg=Decimal(str(start_weight_kg)),
        goal_weight_kg=Decimal(str(goal_weight_kg)),
        goal_date=goal_date,
        target_rate_kg_per_week=(
            Decimal(str(target_rate_kg_per_week))
            if target_rate_kg_per_week is not None
            else None
        ),
    )


def _plan_no_rate(**kw):
    """Plan without an explicit target rate — rate must be derived."""
    p = _plan(**kw)
    p.target_rate_kg_per_week = None
    return p


# ── (a) on-track: gap equals zero ────────────────────────────────────────────

def test_on_track_gap_is_zero():
    """When actual_trend equals plan value at today, gap_kg is 0.0."""
    plan = _plan()
    # plan at week 4: 90 - 4*0.33 = 88.68
    # Use derived interpolation: (86-90)/12 weeks * 4 = -1.333; 90 - 1.333 = 88.667
    # Use the plan's own at-week-4 value as actual to guarantee zero gap
    # Linear: 90 + (86 - 90) * (28 / 84) = 90 - 4/3 = 88.667
    plan_value_at_week4 = 90.0 + (86.0 - 90.0) * (28 / 84)
    points, debug = recompute_plan_from_progress(plan, plan_value_at_week4, WEEK_4)

    assert debug["gap_kg"] == pytest.approx(0.0, abs=0.01)
    assert debug["reason"] == ""
    assert len(points) > 0


def test_on_track_forward_segment_exists():
    """On-track: returned points include a recomputed forward segment."""
    plan = _plan()
    plan_value_at_week4 = 90.0 + (86.0 - 90.0) * (28 / 84)
    points, debug = recompute_plan_from_progress(plan, plan_value_at_week4, WEEK_4)

    recomputed = [p for p in points if p["segment"] == "recomputed"]
    assert len(recomputed) > 0
    assert recomputed[0]["date"] == str(WEEK_4)
    assert recomputed[0]["weight_kg"] == pytest.approx(plan_value_at_week4, abs=0.01)


# ── (b) behind by 1 kg at week four ─────────────────────────────────────────

def test_behind_by_1kg_at_week_four():
    """When actual_trend is 1 kg above the loss plan value, gap_kg is +1.0."""
    plan = _plan()
    plan_value_at_week4 = 90.0 + (86.0 - 90.0) * (28 / 84)
    actual = plan_value_at_week4 + 1.0  # heavier → behind on a loss plan
    points, debug = recompute_plan_from_progress(plan, actual, WEEK_4)

    assert debug["gap_kg"] == pytest.approx(1.0, abs=0.01)
    assert debug["actual_trend_used"] == pytest.approx(actual, abs=0.001)
    assert debug["reason"] == ""

    # Forward segment starts at today with actual trend weight
    recomputed = [p for p in points if p["segment"] == "recomputed"]
    assert recomputed[0]["date"] == str(WEEK_4)
    assert recomputed[0]["weight_kg"] == pytest.approx(actual, abs=0.01)

    # Original segment exists (days before today)
    original = [p for p in points if p["segment"] == "original"]
    assert len(original) > 0
    assert all(p["date"] < str(WEEK_4) for p in original)


def test_behind_rate_source_is_plan():
    """When target_rate_kg_per_week is set, rate_source is 'plan', magnitude is 0.33."""
    plan = _plan(target_rate_kg_per_week=0.33)
    plan_value_at_week4 = 90.0 + (86.0 - 90.0) * (28 / 84)
    points, debug = recompute_plan_from_progress(plan, plan_value_at_week4 + 1.0, WEEK_4)
    assert debug["rate_source"] == "plan"
    # rate_used_kg_per_week is signed: negative for loss plans, positive for gain
    assert abs(debug["rate_used_kg_per_week"]) == pytest.approx(0.33, abs=0.001)


# ── (c) ahead of plan ────────────────────────────────────────────────────────

def test_ahead_of_plan():
    """When actual_trend is below the loss plan value, gap_kg is negative (ahead)."""
    plan = _plan()
    plan_value_at_week4 = 90.0 + (86.0 - 90.0) * (28 / 84)
    actual = plan_value_at_week4 - 1.0  # lighter → ahead on a loss plan
    points, debug = recompute_plan_from_progress(plan, actual, WEEK_4)

    assert debug["gap_kg"] == pytest.approx(-1.0, abs=0.01)
    assert debug["reason"] == ""

    recomputed = [p for p in points if p["segment"] == "recomputed"]
    assert recomputed[0]["weight_kg"] == pytest.approx(actual, abs=0.01)


# ── (d) missing actual_trend returns empty with reason ───────────────────────

def test_missing_actual_trend_returns_empty():
    """When actual_trend is None, returns ([], reason) without raising."""
    plan = _plan()
    result = recompute_plan_from_progress(plan, None, WEEK_4)

    points, debug = result
    assert points == []
    assert "actual_trend" in debug.get("reason", "").lower()


def test_missing_actual_trend_no_exception():
    """None actual_trend must not raise any exception."""
    plan = _plan()
    try:
        recompute_plan_from_progress(plan, None, WEEK_4)
    except Exception as exc:
        pytest.fail(f"Unexpected exception: {exc}")


# ── (e) missing plan.goal_date returns empty with reason ─────────────────────

def test_missing_goal_date_returns_empty():
    """When plan.goal_date is None, returns ([], reason) without raising."""
    plan = _plan()
    plan.goal_date = None

    points, debug = recompute_plan_from_progress(plan, 89.0, WEEK_4)
    assert points == []
    assert "goal_date" in debug.get("reason", "").lower()


def test_missing_goal_date_no_exception():
    """None plan.goal_date must not raise any exception."""
    plan = _plan()
    plan.goal_date = None
    try:
        recompute_plan_from_progress(plan, 89.0, WEEK_4)
    except Exception as exc:
        pytest.fail(f"Unexpected exception: {exc}")


# ── point structure ───────────────────────────────────────────────────────────

def test_all_points_have_required_keys():
    """Every point in the returned list has date, weight_kg, and segment keys."""
    plan = _plan()
    points, _ = recompute_plan_from_progress(plan, 88.5, WEEK_4)

    for pt in points:
        assert "date" in pt, f"Missing 'date' in {pt}"
        assert "weight_kg" in pt, f"Missing 'weight_kg' in {pt}"
        assert "segment" in pt, f"Missing 'segment' in {pt}"


def test_segment_boundary_falls_on_today():
    """Points before today have segment='original'; from today onward 'recomputed'."""
    plan = _plan()
    today = WEEK_4
    points, _ = recompute_plan_from_progress(plan, 88.5, today)

    for pt in points:
        if pt["date"] < str(today):
            assert pt["segment"] == "original", f"Expected original but got {pt['segment']} for {pt['date']}"
        else:
            assert pt["segment"] == "recomputed", f"Expected recomputed but got {pt['segment']} for {pt['date']}"


def test_no_point_missing_any_key():
    """No point is missing date, weight_kg, or segment."""
    plan = _plan()
    points, _ = recompute_plan_from_progress(plan, 88.0, WEEK_4)
    required = {"date", "weight_kg", "segment"}
    for pt in points:
        missing = required - pt.keys()
        assert not missing, f"Point {pt} missing keys: {missing}"


# ── debug dict structure ──────────────────────────────────────────────────────

def test_debug_dict_has_all_required_keys():
    """Debug dict contains all required keys when inputs are valid."""
    plan = _plan()
    _, debug = recompute_plan_from_progress(plan, 88.5, WEEK_4)

    for key in ("actual_trend_used", "rate_used_kg_per_week", "rate_source", "gap_kg", "reason"):
        assert key in debug, f"Missing key '{key}' in debug: {debug}"


def test_debug_reason_empty_on_valid_inputs():
    """debug.reason is empty string when all inputs are valid."""
    plan = _plan()
    _, debug = recompute_plan_from_progress(plan, 88.5, WEEK_4)
    assert debug["reason"] == ""


# ── derived rate fallback ─────────────────────────────────────────────────────

def test_derived_rate_when_no_target_rate():
    """When target_rate_kg_per_week is None, rate is derived and rate_source is 'derived'."""
    plan = _plan_no_rate(start_weight_kg=90.0, goal_weight_kg=86.0)
    # weeks between START_DATE and GOAL_DATE = 12
    # derived rate = (86 - 90) / 12 = -0.3333 kg/week; magnitude = 0.3333
    points, debug = recompute_plan_from_progress(plan, 88.5, WEEK_4)

    assert debug["rate_source"] == "derived"
    assert abs(debug["rate_used_kg_per_week"]) == pytest.approx(4.0 / 12.0, abs=0.01)
    assert len(points) > 0


# ── compute_plan_line ─────────────────────────────────────────────────────────

def test_compute_plan_line_returns_original_tagged_points():
    """compute_plan_line returns a list of points all tagged segment='original'."""
    plan = _plan()
    today = WEEK_4
    points = compute_plan_line(plan, today)

    assert isinstance(points, list)
    assert len(points) > 0
    for pt in points:
        assert pt["segment"] == "original"
        assert "date" in pt
        assert "weight_kg" in pt


def test_compute_plan_line_ends_before_today():
    """compute_plan_line output covers start_date up to (but not including) today."""
    plan = _plan()
    today = WEEK_4
    points = compute_plan_line(plan, today)

    dates = [p["date"] for p in points]
    assert str(START_DATE) in dates or len(dates) == 0
    assert all(d < str(today) for d in dates), "compute_plan_line should not include today or later"


def test_compute_plan_line_monotone_for_loss_plan():
    """For a loss plan, plan line weight decreases (or stays flat) across days."""
    plan = _plan()
    points = compute_plan_line(plan, WEEK_4)

    weights = [p["weight_kg"] for p in points]
    for i in range(1, len(weights)):
        assert weights[i] <= weights[i - 1] + 0.001, (
            f"Expected non-increasing for loss plan, got {weights[i-1]} → {weights[i]}"
        )
