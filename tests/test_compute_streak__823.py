"""Tests for issue #823: compute_streak pure function for habit streak logic.

Unit tests anchored to each Acceptance Criterion and UAT test step.
"""

import types
from datetime import date, timedelta


# ── Helpers ───────────────────────────────────────────────────────────────────

def _habit(
    habit_type="binary",
    schedule_type="daily",
    schedule_target=None,
    target_value=None,
):
    return types.SimpleNamespace(
        habit_type=habit_type,
        schedule_type=schedule_type,
        schedule_target=schedule_target,
        target_value=target_value,
    )


def _log(log_date, value=1):
    return types.SimpleNamespace(log_date=log_date, value=value)


TODAY = date(2024, 6, 14)  # Friday — stable reference date for all tests


def _days_back(n, base=TODAY):
    return base - timedelta(days=n)


def _daily_logs(n_days, ending_on=TODAY, value=1):
    """Return n_days consecutive daily logs ending on ending_on."""
    return [_log(_days_back(i, base=ending_on), value=value) for i in range(n_days)]


def _monday_of(d):
    return d - timedelta(days=d.weekday())


def _week_logs(week_start, n_days, value=1):
    """Return n_days consecutive logs starting from week_start (Monday)."""
    return [_log(week_start + timedelta(days=i), value=value) for i in range(n_days)]


# ── Import smoke test ─────────────────────────────────────────────────────────

def test_module_is_importable():
    """compute_streak must be importable from backend.services.habit_streak."""
    from backend.services.habit_streak import compute_streak  # noqa: F401


# ── AC1: function signature and purity ───────────────────────────────────────

def test_function_accepts_three_args():
    """AC1: compute_streak(habit, logs, today) accepts exactly three positional args."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    result = compute_streak(h, _daily_logs(1), TODAY)
    assert isinstance(result, dict)


def test_function_is_deterministic():
    """AC1: identical inputs produce identical outputs (purity check)."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    logs = _daily_logs(3)
    r1 = compute_streak(h, logs, TODAY)
    r2 = compute_streak(h, logs, TODAY)
    assert r1 == r2


# ── AC2: return shape ─────────────────────────────────────────────────────────

def test_return_has_exactly_three_keys():
    """AC2: return value contains exactly current_streak, longest_streak, debug."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    result = compute_streak(h, _daily_logs(1), TODAY)
    assert set(result.keys()) == {"current_streak", "longest_streak", "debug"}


def test_return_types_are_correct():
    """AC2: current_streak and longest_streak are ints, debug is a dict."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    result = compute_streak(h, _daily_logs(1), TODAY)
    assert isinstance(result["current_streak"], int)
    assert isinstance(result["longest_streak"], int)
    assert isinstance(result["debug"], dict)


# ── AC8 / UAT 5 & 6: guard on invalid inputs ─────────────────────────────────

def test_habit_none_returns_zeros_with_reason():
    """AC8 / UAT5: compute_streak(None, [], today) → 0, 0, debug.reason non-empty."""
    from backend.services.habit_streak import compute_streak
    result = compute_streak(None, [], TODAY)
    assert result["current_streak"] == 0
    assert result["longest_streak"] == 0
    assert isinstance(result["debug"].get("reason"), str)
    assert len(result["debug"]["reason"]) > 0


def test_logs_none_returns_zeros_with_reason():
    """AC8: logs=None → 0, 0, debug.reason mentions logs."""
    from backend.services.habit_streak import compute_streak
    result = compute_streak(_habit(), None, TODAY)
    assert result["current_streak"] == 0
    assert result["longest_streak"] == 0
    reason = result["debug"].get("reason", "")
    assert "log" in reason.lower()


def test_logs_empty_returns_zeros_with_reason():
    """AC8 / UAT6: empty logs → 0, 0, debug.reason references empty logs."""
    from backend.services.habit_streak import compute_streak
    result = compute_streak(_habit(), [], TODAY)
    assert result["current_streak"] == 0
    assert result["longest_streak"] == 0
    reason = result["debug"].get("reason", "")
    assert "log" in reason.lower()


def test_today_none_returns_zeros_with_reason():
    """AC8: today=None → 0, 0, debug.reason mentions today."""
    from backend.services.habit_streak import compute_streak
    result = compute_streak(_habit(), _daily_logs(1), None)
    assert result["current_streak"] == 0
    assert result["longest_streak"] == 0
    reason = result["debug"].get("reason", "")
    assert len(reason) > 0


# ── AC3: schedule config always from habit row ────────────────────────────────

def test_target_value_read_from_habit_not_hardcoded():
    """AC3: count habit uses target_value from the habit row, not any hardcoded value."""
    from backend.services.habit_streak import compute_streak
    # target=5; log only 3 → period NOT met → no streak
    h = _habit(habit_type="count", target_value=5)
    logs = [_log(TODAY, value=3)]
    result = compute_streak(h, logs, TODAY)
    assert result["current_streak"] == 0

    # same date, but now log meets the target
    h2 = _habit(habit_type="count", target_value=3)
    result2 = compute_streak(h2, [_log(TODAY, value=3)], TODAY)
    assert result2["current_streak"] == 1


# ── AC4 / UAT1: daily — exact streak ending on today ─────────────────────────

def test_daily_five_consecutive_days_ending_today():
    """AC4 / UAT1: 5 consecutive met days ending on today → current=5, longest=5."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    logs = _daily_logs(5, ending_on=TODAY)
    result = compute_streak(h, logs, TODAY)
    assert result["current_streak"] == 5
    assert result["longest_streak"] == 5


def test_daily_single_day_log_on_today():
    """AC4: single log on today → current=1, longest=1."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    result = compute_streak(h, [_log(TODAY)], TODAY)
    assert result["current_streak"] == 1
    assert result["longest_streak"] == 1


# ── AC6 / UAT2: in-progress period (today) does not break the streak ─────────

def test_daily_streak_ending_yesterday_today_pending():
    """AC6 / UAT2: 5 met days ending yesterday; today missing → current=5, longest=5."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    yesterday = TODAY - timedelta(days=1)
    logs = _daily_logs(5, ending_on=yesterday)
    result = compute_streak(h, logs, TODAY)
    assert result["current_streak"] == 5
    assert result["longest_streak"] == 5


def test_daily_gap_yesterday_breaks_streak():
    """AC6: if yesterday is a fully-elapsed unmet period, streak resets to 0."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    # log on today only (yesterday has no log)
    # streak from today = 1, but to test a gap: log 5 days ago, skip yesterday
    day_minus_5 = _days_back(5)
    day_minus_3 = _days_back(3)
    logs = [_log(day_minus_5), _log(day_minus_3)]
    # current streak: today not met (pending), yesterday not met (elapsed) → break → 0
    result = compute_streak(h, logs, TODAY)
    assert result["current_streak"] == 0


def test_daily_unmet_elapsed_period_resets_streak():
    """AC6: a fully elapsed unmet day in the backward walk resets current streak."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    # 3 days met, then a gap of 1 day, then 2 more met days ending today
    # walking backward from today: today met, yesterday met, d-2 met, d-3 gap → stop
    logs = [
        _log(TODAY),
        _log(_days_back(1)),
        _log(_days_back(2)),
        # gap at d-3
        _log(_days_back(4)),
        _log(_days_back(5)),
    ]
    result = compute_streak(h, logs, TODAY)
    assert result["current_streak"] == 3


# ── AC7: longest_streak across full history ───────────────────────────────────

def test_longest_streak_non_contiguous_historical_run():
    """AC7 / unit: longest_streak captures the max run even when non-contiguous."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    # Best run: days 10-14 ago (5 days). Broken at day 9. Then 3 days ending today.
    logs = (
        [_log(_days_back(i)) for i in range(3)]           # 3 days ending today
        # gap at day 3
        + [_log(_days_back(i)) for i in range(5, 10)]     # 5 days: d-5..d-9
    )
    result = compute_streak(h, logs, TODAY)
    assert result["longest_streak"] == 5
    assert result["current_streak"] == 3


def test_longest_streak_equals_current_when_streak_is_unbroken():
    """AC7: longest_streak >= current_streak always."""
    from backend.services.habit_streak import compute_streak
    h = _habit()
    logs = _daily_logs(10)
    result = compute_streak(h, logs, TODAY)
    assert result["longest_streak"] >= result["current_streak"]
    assert result["longest_streak"] == 10


# ── AC5 / UAT3: times_per_week — current week pending does not break streak ───

def test_times_per_week_current_week_pending_does_not_break_streak():
    """AC5 / UAT3: 3 prior met weeks + 2 met days this week (mid-week) → current=3."""
    from backend.services.habit_streak import compute_streak
    h = _habit(schedule_type="times_per_week", schedule_target=3)

    # today is a Wednesday so we're mid-week
    today = date(2024, 6, 12)  # Wednesday
    mon = _monday_of(today)    # 2024-06-10

    logs = []
    # Current week: 2 met days (Mon, Tue) — not yet at target=3
    logs += [_log(mon), _log(mon + timedelta(days=1))]

    # Prior 3 weeks: 3 met days each (Mon, Tue, Wed of each week)
    for w in range(1, 4):
        ws = mon - timedelta(weeks=w)
        logs += [_log(ws), _log(ws + timedelta(days=1)), _log(ws + timedelta(days=2))]

    result = compute_streak(h, logs, today)
    assert result["current_streak"] == 3
    assert result["longest_streak"] >= 3


def test_times_per_week_current_week_met_counts_in_streak():
    """AC5: if current week already meets target, it counts toward current streak."""
    from backend.services.habit_streak import compute_streak
    h = _habit(schedule_type="times_per_week", schedule_target=3)

    today = date(2024, 6, 12)  # Wednesday
    mon = _monday_of(today)

    logs = []
    # Current week: 3 met days (meets target=3)
    logs += [_log(mon), _log(mon + timedelta(days=1)), _log(mon + timedelta(days=2))]

    # Prior 2 weeks: 3 met days each
    for w in range(1, 3):
        ws = mon - timedelta(weeks=w)
        logs += [_log(ws), _log(ws + timedelta(days=1)), _log(ws + timedelta(days=2))]

    result = compute_streak(h, logs, today)
    assert result["current_streak"] == 3


# ── UAT4: unmet completed week resets streak ─────────────────────────────────

def test_times_per_week_unmet_elapsed_week_resets_streak():
    """UAT4: last week fully elapsed with only 2/3 days met, 2 prior weeks met → current=0, longest=2."""
    from backend.services.habit_streak import compute_streak
    h = _habit(schedule_type="times_per_week", schedule_target=3)

    # today is Monday — so last week is fully elapsed
    today = date(2024, 6, 17)  # Monday 2024-06-17
    mon = _monday_of(today)          # 2024-06-17

    logs = []
    # Last week (fully elapsed): only 2 met days — does NOT meet target=3
    last_week_mon = mon - timedelta(weeks=1)
    logs += [_log(last_week_mon), _log(last_week_mon + timedelta(days=1))]

    # Two weeks before that: 3 met days each — would be longest=2
    for w in range(2, 4):
        ws = mon - timedelta(weeks=w)
        logs += [_log(ws), _log(ws + timedelta(days=1)), _log(ws + timedelta(days=2))]

    result = compute_streak(h, logs, today)
    assert result["current_streak"] == 0
    assert result["longest_streak"] == 2


# ── No-logs edge case ─────────────────────────────────────────────────────────

def test_no_logs_returns_zero_zero():
    """AC8: no logs → current=0, longest=0, debug.reason non-empty."""
    from backend.services.habit_streak import compute_streak
    result = compute_streak(_habit(), [], TODAY)
    assert result["current_streak"] == 0
    assert result["longest_streak"] == 0
    assert result["debug"].get("reason")


# ── AC9: docstring has worked examples ────────────────────────────────────────

def test_docstring_has_two_worked_examples():
    """AC9: docstring contains at least two worked examples."""
    from backend.services.habit_streak import compute_streak
    doc = compute_streak.__doc__ or ""
    # Look for daily example and times_per_week example keywords
    assert "daily" in doc.lower() or "consecutive" in doc.lower()
    assert "times_per_week" in doc.lower() or "schedule_target" in doc.lower()


# ── AC11: inline comments ─────────────────────────────────────────────────────

def test_source_contains_inline_comments():
    """AC11: implementation source must contain plain-English inline comments."""
    import inspect
    from backend.services.habit_streak import compute_streak
    src = inspect.getsource(compute_streak)
    assert "#" in src, "compute_streak source must contain inline comments"
