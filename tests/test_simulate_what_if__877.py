"""TDD tests for simulate_what_if pure function (issue #877)."""
from __future__ import annotations

import datetime
import importlib

import pytest

from backend.services.weight_what_if import simulate_what_if


TODAY = datetime.date(2026, 6, 21)


def _trend(weight_on_today: float):
    """Return a dict usable as actual_trend anchored at TODAY."""
    return {TODAY: weight_on_today}


# ── AC: normal case — arrival date returned ───────────────────────────────────

def test_normal_case_arrival_date_returned():
    """Normal invocation returns projected_line, arrival_date, and non-empty debug."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    assert result["arrival_date"] is not None
    assert isinstance(result["arrival_date"], datetime.date)
    assert result["arrival_date"] > TODAY
    assert len(result["projected_line"]) > 0
    assert result["debug"]


def test_projected_line_structure():
    """Each entry in projected_line has 'date' and 'weight' keys."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    for entry in result["projected_line"]:
        assert "date" in entry
        assert "weight" in entry
        assert isinstance(entry["date"], datetime.date)
        assert isinstance(entry["weight"], float)


def test_projected_line_first_entry_is_today():
    """First projected_line entry is anchored at today's weight."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    first = result["projected_line"][0]
    assert first["date"] == TODAY
    assert abs(first["weight"] - 90.0) < 0.001


def test_projected_line_steps_weekly():
    """Projected line steps forward one week at a time."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    line = result["projected_line"]
    for i in range(1, len(line)):
        days_diff = (line[i]["date"] - line[i - 1]["date"]).days
        assert days_diff == 7


def test_rate_subtracted_each_week():
    """Each step subtracts assumed_rate_kg_per_week from the running weight."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    line = result["projected_line"]
    for i in range(1, len(line)):
        expected_weight = line[i - 1]["weight"] + (-0.3)
        assert abs(line[i]["weight"] - expected_weight) < 0.0001


def test_arrival_date_33_to_34_weeks_at_0point3():
    """At -0.3 kg/week from 90 to 80 kg, arrival is approximately 33–34 weeks out."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    weeks_out = (result["arrival_date"] - TODAY).days / 7
    assert 33 <= weeks_out <= 35


def test_arrival_date_25_weeks_at_0point4():
    """At -0.4 kg/week from 90 to 80 kg, arrival is approximately 25 weeks out."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.4,
        today=TODAY,
    )
    weeks_out = (result["arrival_date"] - TODAY).days / 7
    assert 24 <= weeks_out <= 26


def test_faster_rate_arrives_earlier():
    """Faster weekly rate produces an earlier arrival_date."""
    r1 = simulate_what_if(_trend(90.0), 80.0, -0.3, TODAY)
    r2 = simulate_what_if(_trend(90.0), 80.0, -0.4, TODAY)
    assert r2["arrival_date"] < r1["arrival_date"]


def test_last_projected_entry_reaches_or_crosses_goal():
    """The final projected_line entry has weight ≤ goal_weight_kg."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    last_weight = result["projected_line"][-1]["weight"]
    assert last_weight <= 80.0


# ── AC: missing / None inputs return safe empty result ────────────────────────

def test_missing_goal_returns_empty():
    """Missing goal_weight_kg returns empty result with reason mentioning goal_weight_kg."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=None,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    assert result["projected_line"] == []
    assert result["arrival_date"] is None
    assert "goal_weight_kg" in result["reason"].lower() or "goal" in result["reason"].lower()


def test_missing_trend_returns_empty():
    """Missing actual_trend returns empty result with reason mentioning actual_trend."""
    result = simulate_what_if(
        actual_trend=None,
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    assert result["projected_line"] == []
    assert result["arrival_date"] is None
    assert "actual_trend" in result["reason"].lower() or "trend" in result["reason"].lower()


def test_missing_rate_returns_empty():
    """Missing assumed_rate_kg_per_week returns empty result with reason."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=None,
        today=TODAY,
    )
    assert result["projected_line"] == []
    assert result["arrival_date"] is None
    assert result["reason"]


def test_missing_today_returns_empty():
    """Missing today returns empty result with reason."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=None,
    )
    assert result["projected_line"] == []
    assert result["arrival_date"] is None
    assert result["reason"]


def test_all_none_returns_empty():
    """All None inputs: returns empty result without raising."""
    result = simulate_what_if(None, None, None, None)
    assert result["projected_line"] == []
    assert result["arrival_date"] is None
    assert result["reason"]


# ── AC: rate of zero returns empty with reason ────────────────────────────────

def test_rate_zero_returns_empty():
    """Rate of zero (no change) returns empty result with reason; no infinite loop."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=0,
        today=TODAY,
    )
    assert result["projected_line"] == []
    assert result["arrival_date"] is None
    assert result["reason"]


# ── AC: rate in wrong direction (goal already passed / diverging) ─────────────

def test_rate_wrong_direction_returns_empty():
    """Rate in wrong direction (gaining when loss needed) returns empty with reason."""
    result = simulate_what_if(
        actual_trend=_trend(90.0),
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=0.3,   # positive = gaining, but goal is lower
        today=TODAY,
    )
    assert result["projected_line"] == []
    assert result["arrival_date"] is None
    assert result["reason"]


def test_goal_already_reached_returns_empty():
    """If starting weight is already at or below goal, returns empty with reason."""
    result = simulate_what_if(
        actual_trend=_trend(79.0),      # already below goal of 80
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    assert result["projected_line"] == []
    assert result["arrival_date"] is None
    assert result["reason"]


# ── AC: no database / I/O imports ────────────────────────────────────────────

def test_no_db_imports():
    """weight_what_if module must not import from any database or ORM module."""
    import backend.services.weight_what_if as mod
    source_file = mod.__file__
    with open(source_file) as f:
        source = f.read()
    forbidden = [
        "sqlalchemy", "backend.db", "backend.models",
        "database_url", "get_db", "SessionLocal",
    ]
    for kw in forbidden:
        assert kw not in source, f"weight_what_if.py must not reference '{kw}'"


# ── AC: debug field is non-empty on successful run ───────────────────────────

def test_debug_non_empty_on_success():
    """debug dict is non-empty on a successful simulation."""
    result = simulate_what_if(_trend(90.0), 80.0, -0.3, TODAY)
    assert result["debug"]
    assert isinstance(result["debug"], dict)


# ── AC: all values come from parameters, nothing hardcoded ───────────────────

def test_different_starting_weights_give_different_results():
    """Starting weight from actual_trend, not hardcoded — different inputs give different outputs."""
    r1 = simulate_what_if(_trend(90.0), 80.0, -0.3, TODAY)
    r2 = simulate_what_if(_trend(85.0), 80.0, -0.3, TODAY)
    assert r2["arrival_date"] < r1["arrival_date"]


def test_different_goal_weights_give_different_results():
    """goal_weight_kg from parameter, not hardcoded."""
    r1 = simulate_what_if(_trend(90.0), 80.0, -0.3, TODAY)
    r2 = simulate_what_if(_trend(90.0), 85.0, -0.3, TODAY)
    assert r2["arrival_date"] < r1["arrival_date"]


# ── AC: callable actual_trend also accepted ───────────────────────────────────

def test_callable_actual_trend():
    """actual_trend can be a callable(date) -> float."""
    def trend_fn(date):
        return 90.0

    result = simulate_what_if(
        actual_trend=trend_fn,
        goal_weight_kg=80.0,
        assumed_rate_kg_per_week=-0.3,
        today=TODAY,
    )
    assert result["arrival_date"] is not None
    assert result["projected_line"][0]["weight"] == pytest.approx(90.0)
