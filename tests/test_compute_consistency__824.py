"""Tests for issue #824: compute_consistency pure function for habit schedule adherence.

Each test is anchored to one Acceptance Criterion item or UAT test step.
All tests are pure unit tests — no DB access.
"""

import types
from datetime import date, timedelta


# ── Helpers ───────────────────────────────────────────────────────────────────

def _habit(habit_type="binary", schedule_type="daily", schedule_target=None, target_value=None):
    return types.SimpleNamespace(
        habit_type=habit_type,
        schedule_type=schedule_type,
        schedule_target=schedule_target,
        target_value=target_value,
    )


def _log(log_date, value=1):
    return types.SimpleNamespace(log_date=log_date, value=value)


def _logs_for_dates(date_list, value=1):
    return [_log(d, value) for d in date_list]


# ── AC: importable ────────────────────────────────────────────────────────────

def test_module_is_importable():
    """AC: compute_consistency is importable from backend.services.habit_consistency."""
    from backend.services.habit_consistency import compute_consistency  # noqa: F401


# ── AC: return shape ──────────────────────────────────────────────────────────

def test_return_shape_contains_required_keys():
    """AC: Returns dict with consistency_percent, met_count, scheduled_count, debug."""
    from backend.services.habit_consistency import compute_consistency

    habit = _habit(schedule_type="daily")
    start = date(2026, 6, 1)
    end = date(2026, 6, 5)
    result = compute_consistency(habit, [], start, end)
    assert "consistency_percent" in result
    assert "met_count" in result
    assert "scheduled_count" in result
    assert "debug" in result


# ── UAT 1: daily habit, 10 days, 7 met ───────────────────────────────────────

def test_daily_10_days_7_met():
    """UAT 1: daily habit, 10 days, 7 met → scheduled_count=10, met_count=7, percent=70."""
    from backend.services.habit_consistency import compute_consistency

    start = date(2026, 6, 1)
    end = date(2026, 6, 10)
    met_dates = [start + timedelta(days=i) for i in range(7)]
    habit = _habit(habit_type="binary", schedule_type="daily")
    result = compute_consistency(habit, _logs_for_dates(met_dates), start, end)

    assert result["scheduled_count"] == 10
    assert result["met_count"] == 7
    assert result["consistency_percent"] == 70.0


# ── UAT 2: weekly habit, Mondays, 4-week range, 3 of 4 met ───────────────────

def test_weekly_mondays_4_weeks_3_met():
    """UAT 2: weekly habit (Mondays), 4-week range, 3 Mondays met → percent=75."""
    from backend.services.habit_consistency import compute_consistency

    # 4 Mondays: June 1, 8, 15, 22 — 2026 (June 1 is Monday)
    mondays = [date(2026, 6, 1), date(2026, 6, 8), date(2026, 6, 15), date(2026, 6, 22)]
    start = mondays[0]
    end = mondays[-1]

    # Logs for 3 of 4 Mondays
    logs = _logs_for_dates(mondays[:3])
    habit = _habit(habit_type="binary", schedule_type="weekly", schedule_target=0)  # 0=Monday

    result = compute_consistency(habit, logs, start, end)

    assert result["scheduled_count"] == 4
    assert result["met_count"] == 3
    assert result["consistency_percent"] == 75.0


# ── UAT 3: empty logs — scheduled_count still reflects periods ────────────────

def test_empty_logs_daily_habit():
    """UAT 3: valid daily habit, empty logs, 5-day range → met=0, percent=0, scheduled=5, no debug reason."""
    from backend.services.habit_consistency import compute_consistency

    start = date(2026, 6, 1)
    end = date(2026, 6, 5)
    habit = _habit(habit_type="binary", schedule_type="daily")
    result = compute_consistency(habit, [], start, end)

    assert result["met_count"] == 0
    assert result["consistency_percent"] == 0
    assert result["scheduled_count"] == 5
    assert "reason" not in result["debug"]


# ── UAT 4: habit=None → zero result with debug.reason ────────────────────────

def test_null_habit_returns_zero_result_with_reason():
    """UAT 4: habit=None → zero-value result, debug.reason names missing habit input."""
    from backend.services.habit_consistency import compute_consistency

    result = compute_consistency(None, [], date(2026, 6, 1), date(2026, 6, 5))

    assert result["met_count"] == 0
    assert result["scheduled_count"] == 0
    assert result["consistency_percent"] == 0
    assert "reason" in result["debug"]
    assert "habit" in result["debug"]["reason"]


# ── UAT 5: start_date == end_date, scheduled and met ─────────────────────────

def test_single_day_scheduled_and_met():
    """UAT 5: start_date == end_date on a scheduled met day → scheduled=1, met=1, percent=100."""
    from backend.services.habit_consistency import compute_consistency

    d = date(2026, 6, 1)
    habit = _habit(habit_type="binary", schedule_type="daily")
    result = compute_consistency(habit, [_log(d)], d, d)

    assert result["scheduled_count"] == 1
    assert result["met_count"] == 1
    assert result["consistency_percent"] == 100.0


# ── UAT 6: no matching periods in range ──────────────────────────────────────

def test_no_matching_periods_weekly_no_mondays():
    """UAT 6: Monday-only habit over a range with no Mondays → scheduled=0, percent=0, debug.reason."""
    from backend.services.habit_consistency import compute_consistency

    # Tuesday June 3 through Saturday June 7 — no Mondays
    start = date(2026, 6, 3)
    end = date(2026, 6, 7)
    habit = _habit(habit_type="binary", schedule_type="weekly", schedule_target=0)  # Monday=0

    result = compute_consistency(habit, [], start, end)

    assert result["scheduled_count"] == 0
    assert result["consistency_percent"] == 0
    assert "reason" in result["debug"]


# ── UAT 7: start_date=None → zero result with debug.reason ───────────────────

def test_null_start_date_returns_zero_result_with_reason():
    """UAT 7: start_date=None → zero-value result, debug.reason identifies start_date."""
    from backend.services.habit_consistency import compute_consistency

    habit = _habit(habit_type="binary", schedule_type="daily")
    result = compute_consistency(habit, [], None, date(2026, 6, 5))

    assert result["met_count"] == 0
    assert result["scheduled_count"] == 0
    assert result["consistency_percent"] == 0
    assert "reason" in result["debug"]
    assert "start_date" in result["debug"]["reason"]


# ── AC: null logs → zero result with debug.reason ────────────────────────────

def test_null_logs_returns_zero_result_with_reason():
    """AC: logs=None → zero-value result, debug.reason identifies missing logs input."""
    from backend.services.habit_consistency import compute_consistency

    habit = _habit(habit_type="binary", schedule_type="daily")
    result = compute_consistency(habit, None, date(2026, 6, 1), date(2026, 6, 5))

    assert result["met_count"] == 0
    assert result["scheduled_count"] == 0
    assert result["consistency_percent"] == 0
    assert "reason" in result["debug"]
    assert "logs" in result["debug"]["reason"]


# ── AC: null end_date → zero result with debug.reason ────────────────────────

def test_null_end_date_returns_zero_result_with_reason():
    """AC: end_date=None → zero-value result, debug.reason identifies end_date."""
    from backend.services.habit_consistency import compute_consistency

    habit = _habit(habit_type="binary", schedule_type="daily")
    result = compute_consistency(habit, [], date(2026, 6, 1), None)

    assert result["met_count"] == 0
    assert result["scheduled_count"] == 0
    assert result["consistency_percent"] == 0
    assert "reason" in result["debug"]
    assert "end_date" in result["debug"]["reason"]


# ── AC: schedule read exclusively from habit.schedule_type / schedule_target ──

def test_schedule_read_from_habit_not_hardcoded():
    """AC: No schedule values are hardcoded; daily schedule gives count equal to range length."""
    from backend.services.habit_consistency import compute_consistency

    start = date(2026, 6, 1)
    end = date(2026, 6, 30)  # 30 days
    habit = _habit(habit_type="binary", schedule_type="daily")
    result = compute_consistency(habit, [], start, end)
    assert result["scheduled_count"] == 30


# ── AC: met_count derived solely from is_period_met ──────────────────────────

def test_met_count_uses_is_period_met():
    """AC: is_period_met is the sole mechanism; no duplicate completion logic."""
    import inspect
    from backend.services import habit_consistency
    source = inspect.getsource(habit_consistency)
    assert "is_period_met" in source, "compute_consistency must call is_period_met"
    # Must not re-implement value comparison
    assert "value >= 1" not in source
    assert "target_value" not in source or "is_period_met" in source


# ── AC: no DB calls ───────────────────────────────────────────────────────────

def test_no_db_calls_in_module():
    """AC: habit_consistency module must not import db or session."""
    import importlib
    import inspect
    mod = importlib.import_module("backend.services.habit_consistency")
    source = inspect.getsource(mod)
    assert "from backend.db" not in source
    assert "import db" not in source
    assert "session" not in source


# ── AC: docstring worked example ─────────────────────────────────────────────

def test_docstring_contains_worked_example():
    """AC: docstring includes worked example: 10 scheduled days, 7 met = 70 percent."""
    from backend.services.habit_consistency import compute_consistency
    doc = compute_consistency.__doc__ or ""
    assert "ten" in doc.lower() or "10" in doc
    assert "seven" in doc.lower() or "7" in doc
    assert "seventy" in doc.lower() or "70" in doc


# ── AC: docstring plain words (no caret / arrow / pipe) ──────────────────────

def test_docstring_no_special_notation():
    """AC: docstring uses plain words — no caret, arrow, or pipe-union notation."""
    from backend.services.habit_consistency import compute_consistency
    doc = compute_consistency.__doc__ or ""
    assert "^" not in doc
    assert "->" not in doc
    assert "|" not in doc


# ── AC: consistency_percent = met / scheduled * 100 ──────────────────────────

def test_consistency_percent_formula():
    """AC: consistency_percent equals met_count divided by scheduled_count times 100."""
    from backend.services.habit_consistency import compute_consistency

    start = date(2026, 6, 1)
    end = date(2026, 6, 4)  # 4 days
    met_dates = [date(2026, 6, 1), date(2026, 6, 3)]  # 2 of 4
    habit = _habit(habit_type="binary", schedule_type="daily")
    result = compute_consistency(habit, _logs_for_dates(met_dates), start, end)

    assert result["scheduled_count"] == 4
    assert result["met_count"] == 2
    assert result["consistency_percent"] == 50.0


# ── AC: is_period_met is sole mechanism — no duplicate code ──────────────────

def test_consistency_module_imports_habit_completion():
    """AC: habit_consistency imports from habit_completion (no duplicate met-rule)."""
    import inspect
    from backend.services import habit_consistency
    source = inspect.getsource(habit_consistency)
    assert "habit_completion" in source


# ── AC: times_per_week — each week is a period ───────────────────────────────

def test_times_per_week_scheduled_count_is_weeks():
    """AC: times_per_week schedule — scheduled_count equals number of weeks in range."""
    from backend.services.habit_consistency import compute_consistency

    # 14-day range spanning exactly 2 full weeks (Mon June 1 – Sun June 14)
    start = date(2026, 6, 1)   # Monday
    end = date(2026, 6, 14)    # Sunday
    habit = _habit(habit_type="binary", schedule_type="times_per_week", schedule_target=3)
    result = compute_consistency(habit, [], start, end)

    assert result["scheduled_count"] == 2
