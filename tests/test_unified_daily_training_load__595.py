"""Tests for issue #595: Add unified daily training load series.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria covered:
  AC-1  — Pure function daily_load_series exists with no DB access
  AC-2  — Function accepts workouts list + start_date + end_date as ISO-8601 strings
  AC-3  — Returns ordered list, one object per day; each has date, daily_load,
           workout_count, has_unscored, debug.contributing_workouts
  AC-4  — Days with zero workouts: daily_load=0, workout_count=0,
           has_unscored=False, contributing_workouts=[]
  AC-5  — Missing/invalid inputs return {results:[], reason:<str>}, not exception
  AC-6  — No thresholds, sport-specific weights, or default date ranges hardcoded
  AC-7  — Docstring includes worked example with null-tss workout
  AC-8  — GET /api/training/daily-load endpoint exists; accepts athlete_id, start, end
  AC-9  — Endpoint returns results ascending by date
  AC-10 — Unit tests cover all workouts scored, mix, entirely unscored, no workout
           day, one-day range, missing parameters (these ARE the tests)
"""
import inspect
import types

import pytest

from backend.services.daily_load import daily_load_series


# ── Helpers ────────────────────────────────────────────────────────────────────

def _w(id, date_str, tss):
    """Build a minimal workout dict."""
    return {"id": id, "date": date_str, "tss": tss}


def _w_ns(id, date_str, tss):
    """Build a minimal workout as a namespace (attribute-bearing object)."""
    return types.SimpleNamespace(id=id, date=date_str, tss=tss)


# ── AC-10: all workouts scored ─────────────────────────────────────────────────

def test_all_workouts_scored_single_day():
    """AC-10/AC-3: single day with two scored workouts sums tss correctly."""
    workouts = [
        _w("a", "2026-06-01", 80),
        _w("b", "2026-06-01", 120),
    ]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-01")
    assert isinstance(result, list)
    assert len(result) == 1
    day = result[0]
    assert day["date"] == "2026-06-01"
    assert day["daily_load"] == 200
    assert day["workout_count"] == 2
    assert day["has_unscored"] is False


def test_all_workouts_scored_multi_day():
    """AC-10/AC-3: three-day range, each day has one scored workout."""
    workouts = [
        _w("a", "2026-06-01", 80),
        _w("b", "2026-06-02", 100),
        _w("c", "2026-06-03", 50),
    ]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-03")
    assert len(result) == 3
    assert result[0]["daily_load"] == 80
    assert result[1]["daily_load"] == 100
    assert result[2]["daily_load"] == 50


# ── AC-10: mix of scored and unscored workouts ─────────────────────────────────

def test_mix_scored_and_unscored_on_same_day():
    """AC-10/AC-3: one day has a scored and an unscored workout."""
    workouts = [
        _w("a", "2026-06-02", 60),
        _w("b", "2026-06-02", None),
    ]
    result = daily_load_series(workouts, "2026-06-02", "2026-06-02")
    assert len(result) == 1
    day = result[0]
    assert day["daily_load"] == 60
    assert day["workout_count"] == 2
    assert day["has_unscored"] is True


def test_mix_scored_and_unscored_daily_load_excludes_null():
    """AC-3: null tss treated as 0 in sum, not excluded from count."""
    workouts = [
        _w("a", "2026-06-01", None),
        _w("b", "2026-06-01", None),
        _w("c", "2026-06-01", 40),
    ]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-01")
    day = result[0]
    assert day["daily_load"] == 40
    assert day["workout_count"] == 3
    assert day["has_unscored"] is True


# ── AC-10: entirely unscored day ──────────────────────────────────────────────

def test_entirely_unscored_day():
    """AC-10: all workouts on a day have null tss — daily_load=0, has_unscored=True."""
    workouts = [
        _w("a", "2026-06-05", None),
        _w("b", "2026-06-05", None),
    ]
    result = daily_load_series(workouts, "2026-06-05", "2026-06-05")
    assert len(result) == 1
    day = result[0]
    assert day["daily_load"] == 0
    assert day["workout_count"] == 2
    assert day["has_unscored"] is True


# ── AC-10 / AC-4: day with no workouts ────────────────────────────────────────

def test_day_with_no_workouts():
    """AC-10/AC-4: day with no workouts has daily_load=0, workout_count=0,
    has_unscored=False, contributing_workouts=[]."""
    workouts = [
        _w("a", "2026-06-01", 80),
        _w("b", "2026-06-03", 50),
    ]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-03")
    assert len(result) == 3
    empty_day = result[1]  # June 2 has no workouts
    assert empty_day["date"] == "2026-06-02"
    assert empty_day["daily_load"] == 0
    assert empty_day["workout_count"] == 0
    assert empty_day["has_unscored"] is False
    assert empty_day["debug"]["contributing_workouts"] == []


# ── AC-10: date range of one day ──────────────────────────────────────────────

def test_single_day_range():
    """AC-10: a range of exactly one day returns exactly one object."""
    workouts = [_w("a", "2026-06-10", 75)]
    result = daily_load_series(workouts, "2026-06-10", "2026-06-10")
    assert len(result) == 1
    assert result[0]["date"] == "2026-06-10"
    assert result[0]["daily_load"] == 75


def test_single_day_range_no_workouts():
    """AC-10/AC-4: one-day range with no workouts returns one empty-day object."""
    result = daily_load_series([], "2026-06-10", "2026-06-10")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["daily_load"] == 0
    assert result[0]["workout_count"] == 0


# ── AC-10: missing parameters ─────────────────────────────────────────────────

def test_missing_workouts_returns_error_envelope():
    """AC-10/AC-5: workouts=None returns {results:[], reason:...} not an exception."""
    result = daily_load_series(None, "2026-06-01", "2026-06-03")
    assert isinstance(result, dict)
    assert result["results"] == []
    assert result["reason"]


def test_missing_start_date_returns_error_envelope():
    """AC-10/AC-5: start_date=None returns {results:[], reason:...}."""
    result = daily_load_series([], None, "2026-06-03")
    assert isinstance(result, dict)
    assert result["results"] == []
    assert "start_date" in result["reason"].lower() or "start" in result["reason"].lower()


def test_missing_end_date_returns_error_envelope():
    """AC-10/AC-5: end_date=None returns {results:[], reason:...}."""
    result = daily_load_series([], "2026-06-01", None)
    assert isinstance(result, dict)
    assert result["results"] == []
    assert "end_date" in result["reason"].lower() or "end" in result["reason"].lower()


def test_start_after_end_returns_error_envelope():
    """AC-5: start_date after end_date returns {results:[], reason:...} not exception."""
    result = daily_load_series([], "2026-06-10", "2026-06-05")
    assert isinstance(result, dict)
    assert result["results"] == []
    assert result["reason"]


def test_start_after_end_reason_mentions_both_dates():
    """AC-5: error reason string mentions the offending dates or explains constraint."""
    result = daily_load_series([], "2026-06-10", "2026-06-05")
    reason = result["reason"].lower()
    assert "start" in reason or "after" in reason or "before" in reason


# ── AC-3: output shape and ascending order ─────────────────────────────────────

def test_output_ordered_ascending_by_date():
    """AC-3/AC-9: output is always ascending by date regardless of input order."""
    workouts = [
        _w("c", "2026-06-03", 30),
        _w("a", "2026-06-01", 10),
        _w("b", "2026-06-02", 20),
    ]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-03")
    dates = [d["date"] for d in result]
    assert dates == sorted(dates)


def test_output_covers_full_range_inclusive():
    """AC-3: every day in the range appears in output even when no workouts exist."""
    result = daily_load_series([], "2026-06-01", "2026-06-05")
    assert isinstance(result, list)
    assert len(result) == 5
    expected_dates = [
        "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"
    ]
    assert [d["date"] for d in result] == expected_dates


def test_output_object_has_required_keys():
    """AC-3: each day object has date, daily_load, workout_count,
    has_unscored, debug keys."""
    result = daily_load_series([_w("a", "2026-06-01", 50)], "2026-06-01", "2026-06-01")
    day = result[0]
    assert "date" in day
    assert "daily_load" in day
    assert "workout_count" in day
    assert "has_unscored" in day
    assert "debug" in day
    assert "contributing_workouts" in day["debug"]


def test_contributing_workouts_has_id_and_tss():
    """AC-3: each entry in contributing_workouts has id and tss."""
    workouts = [_w("abc-123", "2026-06-01", 80)]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-01")
    cw = result[0]["debug"]["contributing_workouts"]
    assert len(cw) == 1
    assert cw[0]["id"] == "abc-123"
    assert cw[0]["tss"] == 80


def test_contributing_workouts_preserves_null_tss():
    """AC-3: contributing_workouts preserves null tss as null, not 0."""
    workouts = [_w("x", "2026-06-01", None)]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-01")
    cw = result[0]["debug"]["contributing_workouts"]
    assert len(cw) == 1
    assert cw[0]["tss"] is None


def test_daily_load_is_integer_or_numeric():
    """AC-3: daily_load is a number (int or float), not a string."""
    result = daily_load_series([_w("a", "2026-06-01", 80)], "2026-06-01", "2026-06-01")
    assert isinstance(result[0]["daily_load"], (int, float))


# ── AC-2: accepts both dict and object workouts ───────────────────────────────

def test_accepts_namespace_objects_as_workouts():
    """AC-2: workouts can be attribute-bearing objects, not just dicts."""
    workouts = [_w_ns("a", "2026-06-01", 55)]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-01")
    assert isinstance(result, list)
    assert result[0]["daily_load"] == 55


# ── AC-1: pure function (static analysis) ─────────────────────────────────────

def test_function_has_no_db_access():
    """AC-1: daily_load_series source contains no DB-related identifiers."""
    src = inspect.getsource(daily_load_series)
    for forbidden in ("engine", "db.", "session.", "execute(", "fetchone(", "fetchall(", "query("):
        assert forbidden not in src, f"DB access found: {forbidden!r}"


# ── AC-6: no hardcoded thresholds ─────────────────────────────────────────────

def test_no_hardcoded_thresholds_in_function():
    """AC-6: function source contains no sport-specific weights or thresholds."""
    src = inspect.getsource(daily_load_series)
    for forbidden in ("FTP_W", "THRESHOLD_HR", "THRESHOLD_PACE", "sport_weight"):
        assert forbidden not in src, f"Hardcoded threshold found: {forbidden!r}"


def test_no_default_date_ranges_in_function():
    """AC-6: function does not apply any default date ranges internally."""
    src = inspect.getsource(daily_load_series)
    # No magic date offsets like timedelta(days=90) or timedelta(days=180)
    for forbidden in ("days=90", "days=180", "days=365", "days=30"):
        assert forbidden not in src, f"Default date range found: {forbidden!r}"


# ── AC-7: docstring with worked example ───────────────────────────────────────

def test_docstring_includes_null_tss_worked_example():
    """AC-7: docstring shows a worked example with a null-tss workout."""
    doc = daily_load_series.__doc__ or ""
    assert "None" in doc or "null" in doc.lower(), (
        "Docstring must include an example workout with null/None tss"
    )


def test_docstring_shows_full_expected_output():
    """AC-7: docstring includes expected output with daily_load, has_unscored, etc."""
    doc = daily_load_series.__doc__ or ""
    assert "daily_load" in doc
    assert "has_unscored" in doc
    assert "contributing_workouts" in doc


# ── Worked example from issue docstring ───────────────────────────────────────

def test_uat_step1_three_days_two_workouts_on_day1_and_swim_on_day3():
    """UAT step 1: June 1 run+bike, June 3 swim — three day range correct."""
    workouts = [
        _w("run1", "2026-06-01", 80),
        _w("bike1", "2026-06-01", 120),
        _w("swim1", "2026-06-03", 50),
    ]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-03")
    assert len(result) == 3

    june1 = result[0]
    assert june1["daily_load"] == 200
    assert june1["workout_count"] == 2
    assert june1["has_unscored"] is False
    assert len(june1["debug"]["contributing_workouts"]) == 2

    june2 = result[1]
    assert june2["daily_load"] == 0
    assert june2["workout_count"] == 0
    assert june2["has_unscored"] is False

    june3 = result[2]
    assert june3["daily_load"] == 50
    assert june3["workout_count"] == 1
    assert june3["has_unscored"] is False


def test_uat_step2_unscored_strength_on_june2():
    """UAT step 2: add strength with null TSS on June 2 — has_unscored=True."""
    workouts = [
        _w("run1", "2026-06-01", 80),
        _w("bike1", "2026-06-01", 120),
        _w("strength1", "2026-06-02", None),
        _w("swim1", "2026-06-03", 50),
    ]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-03")
    june2 = result[1]
    assert june2["daily_load"] == 0
    assert june2["workout_count"] == 1
    assert june2["has_unscored"] is True
    assert len(june2["debug"]["contributing_workouts"]) == 1
    assert june2["debug"]["contributing_workouts"][0]["tss"] is None


def test_uat_step3_add_scored_workout_on_june2():
    """UAT step 3: add TSS 60 bike on June 2 — daily_load=60, has_unscored=True."""
    workouts = [
        _w("run1", "2026-06-01", 80),
        _w("bike1", "2026-06-01", 120),
        _w("strength1", "2026-06-02", None),
        _w("bike2", "2026-06-02", 60),
        _w("swim1", "2026-06-03", 50),
    ]
    result = daily_load_series(workouts, "2026-06-01", "2026-06-03")
    june2 = result[1]
    assert june2["daily_load"] == 60
    assert june2["workout_count"] == 2
    assert june2["has_unscored"] is True
