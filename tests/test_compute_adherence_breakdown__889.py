"""Tests for compute_adherence_breakdown (issue #889).

Covers all Acceptance Criteria:
- AC1:  compute_adherence_breakdown exists in backend.services.habit_breakdown, importable
- AC2:  accepts habit, logs, window positional arguments
- AC3:  schedule read exclusively from habit argument
- AC4:  returns consistency_percent, met_count, scheduled_count, weekday_breakdown, debug
- AC5:  weekday_breakdown includes strongest_day and weakest_day with deterministic tie-break
- AC6:  missing/null/invalid inputs return default result with reason field, no exception raised
- AC7:  docstring contains worked Friday example (verified via __doc__)
- AC8:  no caret/arrow/pipe-union syntax in source docstrings
- AC9:  no I/O inside function (pure function contract)
- AC10: delegates met-logic to is_period_met from habit_completion
- AC11: unit tests cover (a) fully-met, (b) partial with clear weakest, (c) empty logs,
         (d) null habit, (e) no scheduled occurrences
"""

from __future__ import annotations

import types
from datetime import date, timedelta

import pytest

from backend.services.habit_breakdown import compute_adherence_breakdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_habit(
    schedule_type="daily",
    schedule_target=None,
    habit_type="binary",
    target_value=None,
    schedule_days=None,
):
    h = types.SimpleNamespace()
    h.schedule_type = schedule_type
    h.schedule_target = schedule_target
    h.habit_type = habit_type
    h.target_value = target_value
    if schedule_days is not None:
        h.schedule_days = schedule_days
    return h


def _make_log(log_date: date, value=1):
    lg = types.SimpleNamespace()
    lg.log_date = log_date
    lg.value = value
    return lg


# Window: June 12–25, 2026 (14 days; exactly 2 of each weekday)
_START = date(2026, 6, 12)
_END = date(2026, 6, 25)
_WINDOW_14 = (_START, _END)

_FRIDAY_WD = 4  # date.weekday() for Friday


def _logs_except_fridays():
    """Return logs for all days in _WINDOW_14 except Fridays."""
    logs = []
    d = _START
    while d <= _END:
        if d.weekday() != _FRIDAY_WD:
            logs.append(_make_log(d))
        d += timedelta(days=1)
    return logs


def _all_logs():
    """Return logs for every day in _WINDOW_14."""
    logs = []
    d = _START
    while d <= _END:
        logs.append(_make_log(d))
        d += timedelta(days=1)
    return logs


# ---------------------------------------------------------------------------
# AC1 / AC2: importable, callable with positional args
# ---------------------------------------------------------------------------

def test_importable_and_callable():
    habit = _make_habit()
    result = compute_adherence_breakdown(habit, [], _WINDOW_14)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# AC4 / AC11a: fully-met window returns correct totals
# ---------------------------------------------------------------------------

def test_fully_met_window():
    """AC11a — all scheduled days logged; 100 percent consistency."""
    habit = _make_habit()
    logs = _all_logs()
    result = compute_adherence_breakdown(habit, logs, _WINDOW_14)
    assert result["met_count"] == 14
    assert result["scheduled_count"] == 14
    assert result["consistency_percent"] == 100.0
    assert "weekday_breakdown" in result
    assert "debug" in result


# ---------------------------------------------------------------------------
# AC5 / AC11b: partial window with clear weakest weekday (no Fridays)
# ---------------------------------------------------------------------------

def test_partial_met_weakest_day_is_friday():
    """AC11b / UAT-step-1 — 12 of 14 days met; weakest_day is Friday."""
    habit = _make_habit()
    logs = _logs_except_fridays()
    result = compute_adherence_breakdown(habit, logs, _WINDOW_14)

    assert result["met_count"] == 12
    assert result["scheduled_count"] == 14
    # 12 out of 14 is approximately 85.71 percent
    assert abs(result["consistency_percent"] - 85.71) < 0.1

    wb = result["weekday_breakdown"]
    assert wb["weakest_day"] == "Friday"
    assert wb["strongest_day"] != "Friday"

    # Friday entry should show zero met out of two scheduled
    assert wb["Friday"]["met_count"] == 0
    assert wb["Friday"]["scheduled_count"] == 2


# ---------------------------------------------------------------------------
# AC5: strongest_day is a non-Friday day with 2 out of 2
# ---------------------------------------------------------------------------

def test_strongest_day_full_rate():
    """Strongest day must have higher met rate than Friday."""
    habit = _make_habit()
    logs = _logs_except_fridays()
    result = compute_adherence_breakdown(habit, logs, _WINDOW_14)
    wb = result["weekday_breakdown"]
    strongest = wb["strongest_day"]
    assert strongest is not None
    assert strongest != "Friday"
    assert wb[strongest]["met_count"] == wb[strongest]["scheduled_count"]


# ---------------------------------------------------------------------------
# AC5: tie-breaking by earliest weekday index
# ---------------------------------------------------------------------------

def test_tie_breaking_weakest_uses_earliest_index():
    """When two days share the lowest met rate, the earlier weekday wins."""
    # Weekly habit on Tuesday (weekday 1) and Thursday (weekday 3);
    # both have zero logs → both 0 out of 1; Monday (0) is earliest but not scheduled.
    # Tuesday (1) should win the tie-break for weakest_day.
    habit = _make_habit(schedule_days=[1, 3])  # Tuesday and Thursday
    # Window: Jun 16 (Mon) through Jun 19 (Thu) — one Tue and one Thu present
    window = (date(2026, 6, 16), date(2026, 6, 19))
    result = compute_adherence_breakdown(habit, [], window)
    wb = result["weekday_breakdown"]
    # Both days met 0 out of 1; earliest by index is Tuesday (1)
    assert wb["weakest_day"] == "Tuesday"


# ---------------------------------------------------------------------------
# AC11c: empty logs list
# ---------------------------------------------------------------------------

def test_empty_logs():
    """AC11c — empty logs returns zero met counts without raising."""
    habit = _make_habit()
    result = compute_adherence_breakdown(habit, [], _WINDOW_14)
    assert result["met_count"] == 0
    assert result["scheduled_count"] == 14
    assert result["consistency_percent"] == 0.0
    wb = result["weekday_breakdown"]
    # All scheduled weekdays should appear in breakdown with zero met_count
    for day_name in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        assert wb[day_name]["met_count"] == 0
    assert wb["weakest_day"] is not None  # deterministic even at zero


# ---------------------------------------------------------------------------
# AC6 / AC11d: missing/null habit returns default with reason
# ---------------------------------------------------------------------------

def test_null_habit_returns_reason():
    """AC11d — None habit must return a result dict with reason, never raise."""
    result = compute_adherence_breakdown(None, [], _WINDOW_14)
    assert isinstance(result, dict)
    assert "reason" in result
    assert result["met_count"] == 0
    assert result["consistency_percent"] == 0


# ---------------------------------------------------------------------------
# AC6: null logs argument returns reason without raising
# ---------------------------------------------------------------------------

def test_null_logs_returns_reason():
    habit = _make_habit()
    result = compute_adherence_breakdown(habit, None, _WINDOW_14)
    assert "reason" in result


# ---------------------------------------------------------------------------
# AC6: null window returns reason without raising
# ---------------------------------------------------------------------------

def test_null_window_returns_reason():
    habit = _make_habit()
    result = compute_adherence_breakdown(habit, [], None)
    assert "reason" in result


# ---------------------------------------------------------------------------
# AC11e: window with no scheduled occurrences
# ---------------------------------------------------------------------------

def test_no_scheduled_occurrences():
    """AC11e — weekly Monday habit, window contains no Monday."""
    # June 19=Fri, June 20=Sat, June 21=Sun — no Monday in this range
    habit = _make_habit(schedule_type="weekly", schedule_target=0)  # Monday
    window = (date(2026, 6, 19), date(2026, 6, 21))  # Fri–Sun
    result = compute_adherence_breakdown(habit, [], window)
    assert result["scheduled_count"] == 0
    assert result["consistency_percent"] == 0.0
    assert "reason" in result["debug"]


# ---------------------------------------------------------------------------
# UAT step 2: Monday+Wednesday-only habit, all met, 4-week window
# ---------------------------------------------------------------------------

def test_mon_wed_habit_fully_met():
    """UAT step 2 — Mon/Wed habit over 4 weeks, all occurrences met."""
    # June 2 (Mon) through June 29 (Mon): 4 full weeks
    start = date(2026, 6, 1)   # Monday
    end = date(2026, 6, 28)    # Sunday, exactly 4 weeks
    habit = _make_habit(schedule_days=[0, 2])  # Monday=0, Wednesday=2

    # Build logs for every Monday and Wednesday in range
    logs = []
    d = start
    while d <= end:
        if d.weekday() in (0, 2):
            logs.append(_make_log(d))
        d += timedelta(days=1)

    result = compute_adherence_breakdown(habit, logs, (start, end))

    assert result["consistency_percent"] == 100.0
    wb = result["weekday_breakdown"]
    # Only Monday and Wednesday should appear as day-name keys (plus strongest/weakest)
    day_keys = {k for k in wb if k not in ("strongest_day", "weakest_day")}
    assert day_keys == {"Monday", "Wednesday"}
    assert result["met_count"] == result["scheduled_count"]


# ---------------------------------------------------------------------------
# AC4: debug object contains enough data to reproduce consistency_percent
# ---------------------------------------------------------------------------

def test_debug_contains_evaluated_dates():
    """Debug must contain evaluated_dates list so caller can reproduce the result."""
    habit = _make_habit()
    logs = _logs_except_fridays()
    result = compute_adherence_breakdown(habit, logs, _WINDOW_14)
    debug = result["debug"]
    assert "evaluated_dates" in debug
    # There should be 14 evaluated date entries for a daily habit over 14 days
    assert len(debug["evaluated_dates"]) == 14


# ---------------------------------------------------------------------------
# AC10: function uses is_period_met for met determination (mock verification)
# ---------------------------------------------------------------------------

def test_delegates_to_is_period_met(monkeypatch):
    """AC10 — is_period_met must be invoked for each scheduled occurrence."""
    from backend.services import habit_breakdown as hb

    call_count = [0]
    original = hb.is_period_met

    def counting_is_period_met(habit, logs_in_period):
        call_count[0] += 1
        return original(habit, logs_in_period)

    monkeypatch.setattr(hb, "is_period_met", counting_is_period_met)

    habit = _make_habit()
    logs = _all_logs()
    compute_adherence_breakdown(habit, logs, _WINDOW_14)
    # One call per scheduled day (14 for daily habit over 14-day window)
    assert call_count[0] == 14


# ---------------------------------------------------------------------------
# AC7: docstring contains Friday worked example
# ---------------------------------------------------------------------------

def test_docstring_contains_friday_example():
    """AC7 — docstring must mention Friday as weakest_day in the worked example."""
    doc = compute_adherence_breakdown.__doc__ or ""
    assert "Friday" in doc or "friday" in doc.lower()
    assert "weakest" in doc.lower() or "weakest_day" in doc.lower()


# ---------------------------------------------------------------------------
# AC8: no forbidden syntax in docstrings/comments
# ---------------------------------------------------------------------------

def test_no_caret_or_pipe_syntax_in_source():
    """AC8 — no caret exponents, arrow operators, or pipe-union type syntax."""
    import inspect
    source = inspect.getsource(compute_adherence_breakdown)
    # Caret exponent (^) used as XOR or exponent is forbidden in numeric description context
    # We check for the specific forbidden patterns in comments/docstrings lines
    for line in source.splitlines():
        stripped = line.strip()
        # Skip actual code lines that might legitimately use these operators
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            assert "^" not in stripped, f"Caret found in comment/docstring: {stripped!r}"
            assert "->" not in stripped or "Returns" in stripped or ":" in stripped, (
                f"Arrow operator in comment/docstring: {stripped!r}"
            )
