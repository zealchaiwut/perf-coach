"""Pure function for computing habit schedule adherence over a date range.

No database access. No network I/O. No mutations to inputs. No global state.
Caller passes already-fetched habit row and logs.
"""

from collections import defaultdict
from datetime import date, timedelta

from backend.services.habit_completion import is_period_met


def _week_start_for(d: date) -> date:
    """Return the Monday that begins the week containing date d."""
    return d - timedelta(days=d.weekday())


def _iter_daily_periods(start_date: date, end_date: date):
    """Yield each date from start_date through end_date (inclusive)."""
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _iter_weekly_periods(start_date: date, end_date: date, target_weekday: int):
    """Yield each occurrence of target_weekday within start_date through end_date."""
    days_ahead = (target_weekday - start_date.weekday()) % 7
    current = start_date + timedelta(days=days_ahead)
    while current <= end_date:
        yield current
        current += timedelta(days=7)


def _iter_times_per_week_periods(start_date: date, end_date: date):
    """Yield the Monday start of each week that overlaps start_date through end_date."""
    ws = _week_start_for(start_date)
    while ws <= end_date:
        yield ws
        ws += timedelta(days=7)


def compute_consistency(habit, logs, start_date, end_date) -> dict:
    """Compute how consistently a habit was followed over a date range.

    Pure function — no database calls, no mutations to inputs, no global state.
    Schedule configuration is read entirely from habit.schedule_type and
    habit.schedule_target; no schedule values are hardcoded here.

    Example: ten scheduled days with seven days met returns seventy percent.

    Parameters
    ----------
    habit:
        A habit row with schedule_type ('daily', 'weekly', or 'times_per_week'),
        schedule_target (integer day-of-week 0 through 6 for 'weekly',
        unused for 'daily', or N times per week for 'times_per_week'),
        habit_type, and target_value. Read by is_period_met.
    logs:
        List of log objects with a log_date (date) and value attribute.
        All database queries are the caller's responsibility.
    start_date:
        First date of the range to evaluate (inclusive).
    end_date:
        Last date of the range to evaluate (inclusive).

    Returns
    -------
    dict
        consistency_percent: met_count divided by scheduled_count multiplied
            by one hundred. Zero when scheduled_count is zero.
        met_count: number of scheduled periods for which is_period_met returned True.
        scheduled_count: number of periods in the range targeted by this habit's schedule.
        debug: dict with an optional 'reason' key explaining edge cases.
    """
    # Guard: any missing or null required input returns a zero-value result
    for name, val in [
        ("habit", habit),
        ("logs", logs),
        ("start_date", start_date),
        ("end_date", end_date),
    ]:
        if val is None:
            return {
                "consistency_percent": 0,
                "met_count": 0,
                "scheduled_count": 0,
                "debug": {"reason": f"missing required input: {name}"},
            }

    schedule_type = getattr(habit, "schedule_type", None)
    schedule_target = getattr(habit, "schedule_target", None)

    # Build the list of periods and group logs by period key
    if schedule_type == "daily":
        periods = list(_iter_daily_periods(start_date, end_date))
        logs_by_period = defaultdict(list)
        for log in logs:
            logs_by_period[log.log_date].append(log)

    elif schedule_type == "weekly":
        if schedule_target is None:
            return {
                "consistency_percent": 0,
                "met_count": 0,
                "scheduled_count": 0,
                "debug": {"reason": "schedule_target is required for weekly schedule type"},
            }
        periods = list(_iter_weekly_periods(start_date, end_date, schedule_target))
        logs_by_period = defaultdict(list)
        for log in logs:
            logs_by_period[log.log_date].append(log)

    elif schedule_type == "times_per_week":
        periods = list(_iter_times_per_week_periods(start_date, end_date))
        logs_by_period = defaultdict(list)
        for log in logs:
            logs_by_period[_week_start_for(log.log_date)].append(log)

    else:
        return {
            "consistency_percent": 0,
            "met_count": 0,
            "scheduled_count": 0,
            "debug": {"reason": f"unknown schedule_type: {schedule_type!r}"},
        }

    scheduled_count = len(periods)

    if scheduled_count == 0:
        return {
            "consistency_percent": 0,
            "met_count": 0,
            "scheduled_count": 0,
            "debug": {"reason": "no scheduled periods found in the given date range"},
        }

    # Count periods met using is_period_met as the sole completion evaluator
    met_count = 0
    for period in periods:
        period_logs = logs_by_period.get(period, [])
        met, _ = is_period_met(habit, period_logs)
        if met:
            met_count += 1

    consistency_percent = met_count / scheduled_count * 100

    return {
        "consistency_percent": consistency_percent,
        "met_count": met_count,
        "scheduled_count": scheduled_count,
        "debug": {},
    }
