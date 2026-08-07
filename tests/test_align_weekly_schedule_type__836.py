"""Tests for issue #836: align 'weekly' schedule_type semantics across habit_streak and habit_consistency.

The divergence: habit_streak.py treated 'weekly' like 'times_per_week' (schedule_target = count of
days per week), while habit_consistency.py treated 'weekly' as "occurs on a specific weekday"
(schedule_target = 0-6 weekday index). This caused contradictory results for the same habit.

Fix: 'weekly' means "scheduled on a specific weekday" (schedule_target = weekday index 0=Mon…6=Sun)
in BOTH modules. 'times_per_week' retains its existing meaning (schedule_target = days per week count).
"""

import types
from datetime import date, timedelta

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _habit(habit_type="binary", schedule_type="daily", schedule_target=None, target_value=None):
    return types.SimpleNamespace(
        habit_type=habit_type,
        schedule_type=schedule_type,
        schedule_target=schedule_target,
        target_value=target_value,
    )


def _log(log_date, value=1):
    return types.SimpleNamespace(log_date=log_date, value=value)


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ═══════════════════════════════════════════════════════════════════════════════
# AC1: 'weekly' streak uses weekday-index semantics (not count semantics)
# ═══════════════════════════════════════════════════════════════════════════════

def test_weekly_streak_schedule_target_zero_is_not_trivially_met():
    """AC1: 'weekly' habit with schedule_target=0 (Monday) must NOT be trivially met each week.

    Before the fix, schedule_target=0 was passed to _weekly_streak which required
    0 days/week — always met. After the fix it requires logs on Monday specifically.
    """
    from backend.services.habit_streak import compute_streak

    # today is Wednesday; log exists on Tuesday (not Monday) — Monday not met
    today = date(2026, 6, 3)  # Wednesday
    assert today.weekday() == 2

    # Log on Tuesday only — Monday (target weekday) has no log
    tuesday = date(2026, 6, 2)
    habit = _habit(schedule_type="weekly", schedule_target=0)  # Monday
    result = compute_streak(habit, [_log(tuesday)], today)

    # Monday is elapsed and unmet — streak must be 0, not 1 or any positive number
    assert result["current_streak"] == 0


def test_weekly_streak_monday_habit_met_on_monday():
    """AC1: 'weekly' habit (Monday) with a log on the most recent Monday → current=1."""
    from backend.services.habit_streak import compute_streak

    today = date(2026, 6, 3)  # Wednesday
    monday = _monday_of(today)  # June 1, 2026 (Mon)

    assert today.weekday() == 2
    assert monday == date(2026, 6, 1)
    assert monday.weekday() == 0

    habit = _habit(schedule_type="weekly", schedule_target=0)
    result = compute_streak(habit, [_log(monday)], today)
    assert result["current_streak"] == 1


def test_weekly_streak_three_consecutive_mondays_met():
    """AC1: three consecutive Mondays met → current_streak=3, longest_streak=3."""
    from backend.services.habit_streak import compute_streak

    today = date(2026, 6, 17)  # Wednesday
    mon_this_week = _monday_of(today)  # June 16

    logs = [
        _log(mon_this_week),
        _log(mon_this_week - timedelta(weeks=1)),
        _log(mon_this_week - timedelta(weeks=2)),
    ]
    habit = _habit(schedule_type="weekly", schedule_target=0)
    result = compute_streak(habit, logs, today)
    assert result["current_streak"] == 3
    assert result["longest_streak"] == 3


def test_weekly_streak_gap_resets_current():
    """AC1: Monday habit — gap two weeks ago breaks the current streak."""
    from backend.services.habit_streak import compute_streak

    today = date(2026, 6, 17)  # Wednesday
    mon_this_week = _monday_of(today)

    # Met this week and last week but NOT two weeks ago
    logs = [
        _log(mon_this_week),
        _log(mon_this_week - timedelta(weeks=1)),
        # gap at mon_this_week - 2 weeks
        _log(mon_this_week - timedelta(weeks=3)),
    ]
    habit = _habit(schedule_type="weekly", schedule_target=0)
    result = compute_streak(habit, logs, today)
    assert result["current_streak"] == 2
    assert result["longest_streak"] >= 2


def test_weekly_streak_pending_when_today_is_target_weekday_and_no_log():
    """AC1: if today IS the target weekday and no log yet, today is pending (does not break streak)."""
    from backend.services.habit_streak import compute_streak

    # today is Monday (target weekday = 0), no log today
    today = date(2026, 6, 15)  # Monday
    assert today.weekday() == 0

    # Logs only on the two prior Mondays
    logs = [
        _log(today - timedelta(weeks=1)),
        _log(today - timedelta(weeks=2)),
    ]
    habit = _habit(schedule_type="weekly", schedule_target=0)
    result = compute_streak(habit, logs, today)
    # Today is the target weekday and not logged — treat as pending, streak stays at 2
    assert result["current_streak"] == 2


def test_weekly_streak_today_is_target_weekday_and_met():
    """AC1: if today IS the target weekday and already logged, it counts toward current streak."""
    from backend.services.habit_streak import compute_streak

    today = date(2026, 6, 15)  # Monday
    assert today.weekday() == 0

    logs = [
        _log(today),
        _log(today - timedelta(weeks=1)),
        _log(today - timedelta(weeks=2)),
    ]
    habit = _habit(schedule_type="weekly", schedule_target=0)
    result = compute_streak(habit, logs, today)
    assert result["current_streak"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# AC2: 'times_per_week' streak behavior is unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def test_times_per_week_streak_unchanged():
    """AC2: 'times_per_week' with schedule_target=3 still requires 3 days/week (unchanged)."""
    from backend.services.habit_streak import compute_streak

    today = date(2026, 6, 17)  # Wednesday
    mon = _monday_of(today)

    # Current week: 2 days (pending — not yet at target 3); prior 2 weeks: 3 days each
    logs = [
        _log(mon), _log(mon + timedelta(days=1)),  # 2 days this week
        _log(mon - timedelta(weeks=1)), _log(mon - timedelta(weeks=1) + timedelta(days=1)),
        _log(mon - timedelta(weeks=1) + timedelta(days=2)),  # 3 days last week
        _log(mon - timedelta(weeks=2)), _log(mon - timedelta(weeks=2) + timedelta(days=1)),
        _log(mon - timedelta(weeks=2) + timedelta(days=2)),  # 3 days 2 weeks ago
    ]
    habit = _habit(schedule_type="times_per_week", schedule_target=3)
    result = compute_streak(habit, logs, today)
    assert result["current_streak"] == 2  # current week pending, 2 prior weeks met


# ═══════════════════════════════════════════════════════════════════════════════
# AC3: compute_consistency 'weekly' semantics unchanged (regression guard)
# ═══════════════════════════════════════════════════════════════════════════════

def test_consistency_weekly_monday_semantics_preserved():
    """AC3: compute_consistency 'weekly' still treats schedule_target as weekday index."""
    from backend.services.habit_consistency import compute_consistency

    # 4 Mondays: June 1, 8, 15, 22 — 2026 (June 1 is Monday)
    mondays = [date(2026, 6, 1) + timedelta(weeks=i) for i in range(4)]
    logs = [_log(m) for m in mondays[:3]]  # 3 of 4 Mondays met
    habit = _habit(schedule_type="weekly", schedule_target=0)

    result = compute_consistency(habit, logs, mondays[0], mondays[-1])
    assert result["scheduled_count"] == 4
    assert result["met_count"] == 3
    assert result["consistency_percent"] == 75.0


# ═══════════════════════════════════════════════════════════════════════════════
# AC4: concrete divergence from the issue is resolved
# ═══════════════════════════════════════════════════════════════════════════════

def test_concrete_divergence_case_resolved():
    """AC4: weekly habit schedule_target=0 yields consistent results in both modules.

    Before fix: streak said 'met' (trivially, 0 days/week), consistency said
    only met on Mondays. After fix both agree: the habit is met only on Mondays.
    """
    from backend.services.habit_streak import compute_streak
    from backend.services.habit_consistency import compute_consistency

    # Range: Mon Jun 1 through Sun Jun 14 (2 full weeks, 2 Mondays)
    start = date(2026, 6, 1)   # Monday
    end = date(2026, 6, 14)    # Sunday
    today = end

    habit = _habit(schedule_type="weekly", schedule_target=0)  # Monday habit

    # Log on June 1 (Monday) only; June 8 Monday not logged
    logs = [_log(date(2026, 6, 1))]

    streak_result = compute_streak(habit, logs, today)
    consistency_result = compute_consistency(habit, logs, start, end)

    # Both should reflect that exactly 1 of 2 Monday periods was met
    # Consistency: 1/2 = 50%
    assert consistency_result["met_count"] == 1
    assert consistency_result["scheduled_count"] == 2
    assert consistency_result["consistency_percent"] == 50.0

    # Streak: June 8 Monday not met, June 1 Monday was met → current streak = 0
    # (June 8 is a past Monday in the range and not met → breaks streak)
    assert streak_result["current_streak"] == 0
    assert streak_result["longest_streak"] == 1


def test_divergence_resolved_all_mondays_met():
    """AC4: both modules agree when all scheduled Mondays are met."""
    from backend.services.habit_streak import compute_streak
    from backend.services.habit_consistency import compute_consistency

    start = date(2026, 6, 1)   # Monday
    end = date(2026, 6, 14)    # Sunday
    today = end

    habit = _habit(schedule_type="weekly", schedule_target=0)
    # Both Mondays met
    logs = [_log(date(2026, 6, 1)), _log(date(2026, 6, 8))]

    streak_result = compute_streak(habit, logs, today)
    consistency_result = compute_consistency(habit, logs, start, end)

    assert consistency_result["met_count"] == 2
    assert consistency_result["consistency_percent"] == 100.0
    assert streak_result["current_streak"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# AC5: schedule_target=None for 'weekly' returns graceful zero result
# ═══════════════════════════════════════════════════════════════════════════════

def test_weekly_streak_no_schedule_target_returns_zero_with_reason():
    """AC5: 'weekly' with schedule_target=None → zeros with a debug reason."""
    from backend.services.habit_streak import compute_streak

    today = date(2026, 6, 3)
    habit = _habit(schedule_type="weekly", schedule_target=None)
    result = compute_streak(habit, [_log(today)], today)

    assert result["current_streak"] == 0
    assert result["longest_streak"] == 0
    assert isinstance(result["debug"].get("reason"), str)
    assert len(result["debug"]["reason"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# AC6: longest_streak covers full history
# ═══════════════════════════════════════════════════════════════════════════════

def test_weekly_streak_longest_covers_historical_run():
    """AC6: longest_streak reflects the best run even if current streak is lower."""
    from backend.services.habit_streak import compute_streak

    today = date(2026, 6, 17)  # Wednesday
    mon = _monday_of(today)    # June 16

    # Best historical run: 4 consecutive Mondays ending 2 weeks ago
    # Then a gap, then 1 Monday this week
    logs = [
        _log(mon),                               # this week: 1 (current=1)
        # gap at mon - 1 week
        _log(mon - timedelta(weeks=2)),
        _log(mon - timedelta(weeks=3)),
        _log(mon - timedelta(weeks=4)),
        _log(mon - timedelta(weeks=5)),          # run of 4
    ]
    habit = _habit(schedule_type="weekly", schedule_target=0)
    result = compute_streak(habit, logs, today)

    assert result["current_streak"] == 1
    assert result["longest_streak"] == 4


# ═══════════════════════════════════════════════════════════════════════════════
# AC7: non-Monday weekday targets work correctly
# ═══════════════════════════════════════════════════════════════════════════════

def test_weekly_streak_friday_habit():
    """AC7: 'weekly' habit on Friday (schedule_target=4) counts Friday logs, not other days."""
    from backend.services.habit_streak import compute_streak

    today = date(2026, 6, 20)  # Saturday
    assert today.weekday() == 5

    friday_this_week = date(2026, 6, 19)
    friday_last_week = date(2026, 6, 12)
    assert friday_this_week.weekday() == 4
    assert friday_last_week.weekday() == 4

    # Log on both Fridays; Wednesday log between them should NOT affect streak
    logs = [
        _log(friday_this_week),
        _log(friday_last_week),
        _log(date(2026, 6, 17)),  # Wednesday — should be ignored for period matching
    ]
    habit = _habit(schedule_type="weekly", schedule_target=4)  # Friday
    result = compute_streak(habit, logs, today)

    assert result["current_streak"] == 2


def test_weekly_streak_wednesday_habit_when_today_is_tuesday():
    """AC7: Wednesday habit when today is Tuesday — most recent Wed is last week."""
    from backend.services.habit_streak import compute_streak

    today = date(2026, 6, 16)  # Tuesday
    assert today.weekday() == 1

    last_wednesday = date(2026, 6, 10)
    assert last_wednesday.weekday() == 2

    logs = [_log(last_wednesday)]
    habit = _habit(schedule_type="weekly", schedule_target=2)  # Wednesday
    result = compute_streak(habit, logs, today)
    assert result["current_streak"] == 1
