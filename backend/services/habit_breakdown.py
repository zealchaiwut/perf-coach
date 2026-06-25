"""Pure function for computing per-habit adherence breakdown over a date window.

No database access. No network I/O. No mutations to inputs. No global state.
Caller passes already-fetched habit row and logs.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from backend.services.habit_completion import is_period_met

_WEEKDAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]

_EMPTY_WEEKDAY_BREAKDOWN: dict = {"strongest_day": None, "weakest_day": None}

_DEFAULT_RESULT: dict = {
    "consistency_percent": 0,
    "met_count": 0,
    "scheduled_count": 0,
    "weekday_breakdown": _EMPTY_WEEKDAY_BREAKDOWN,
    "debug": {},
}


def _parse_window(window):
    """Extract (start_date, end_date, error_reason) from a window argument.

    Accepts a tuple or list of two dates, or an object with start/end
    (or start_date/end_date) attributes.  Returns (None, None, reason_str) when
    the window is structurally invalid.
    """
    if window is None:
        return None, None, "missing required input: window"
    if isinstance(window, (tuple, list)):
        if len(window) < 2:
            return None, None, "window sequence must have at least 2 elements: (start, end)"
        return window[0], window[1], None
    start = getattr(window, "start", None) or getattr(window, "start_date", None)
    end = getattr(window, "end", None) or getattr(window, "end_date", None)
    if start is None or end is None:
        return (
            None,
            None,
            "window object must have start/end or start_date/end_date attributes",
        )
    return start, end, None


def _get_scheduled_weekday_indices(habit) -> list[int] | None:
    """Return a sorted list of scheduled weekday integers (0 equals Monday, 6 equals Sunday).

    Returns None when the schedule cannot be determined from the habit's attributes.
    Reads schedule_days (list) first; falls back to schedule_type and schedule_target.
    """
    schedule_days = getattr(habit, "schedule_days", None)
    if schedule_days is not None:
        return sorted(int(d) for d in schedule_days)

    schedule_type = getattr(habit, "schedule_type", None)
    if schedule_type == "daily":
        return list(range(7))
    if schedule_type == "weekly":
        target = getattr(habit, "schedule_target", None)
        if target is None:
            return None
        return [int(target)]
    if schedule_type == "times_per_week":
        # All weekdays are candidates for a times-per-week habit
        return list(range(7))
    return None


def compute_adherence_breakdown(habit: Any, logs, window) -> dict:
    """Compute per-weekday adherence breakdown for a single habit over a date window.

    Pure function — no database calls, no mutations to inputs, no global state.
    The schedule definition is read entirely from the habit argument; no day,
    frequency, or recurrence value is hardcoded here.

    Example: a habit scheduled every day of the week that is met on all days
    except Fridays over a fourteen-day evaluation window produces
    weakest_day equal to Friday and a consistency_percent below 100, because
    Friday has zero met occurrences out of its two scheduled occurrences while
    every other weekday has two met occurrences out of two scheduled.

    Parameters
    ----------
    habit:
        A habit row (or any object) containing the schedule definition via
        schedule_type ('daily', 'weekly', or 'times_per_week') and
        schedule_target (integer weekday 0 through 6 for 'weekly', or N for
        'times_per_week').  Optionally a schedule_days attribute (list of
        integers) to specify exactly which weekdays are scheduled.
        Also used by is_period_met: habit_type and target_value.
    logs:
        List of log objects with a log_date (date) and value attribute.
        All database queries are the caller's responsibility.
    window:
        A tuple or list of (start_date, end_date), or an object with
        start/end or start_date/end_date attributes (both date objects).

    Returns
    -------
    dict
        consistency_percent: met_count divided by scheduled_count multiplied
            by one hundred. Zero when scheduled_count is zero.
        met_count: total scheduled occurrences across the window that were met.
        scheduled_count: total scheduled occurrences in the window.
        weekday_breakdown: mapping of each scheduled weekday name to a dict
            with met_count and scheduled_count for that weekday, plus two
            top-level keys strongest_day (weekday name with highest met rate)
            and weakest_day (weekday name with lowest met rate). Ties are
            broken by earliest weekday index.
        debug: dict with evaluated_dates (list of per-date dicts), window_start,
            window_end, and scheduled_weekdays; enough to reproduce the final
            consistency_percent by hand.
        reason: present only when a required input is missing or structurally
            invalid; explains what was missing.
    """
    # Guard: habit must be a non-None object
    if habit is None:
        return {**_DEFAULT_RESULT, "reason": "missing required input: habit"}

    # Guard: logs must be provided (None is invalid; empty list is valid)
    if logs is None:
        return {**_DEFAULT_RESULT, "reason": "missing required input: logs"}

    # Parse window into start and end dates
    start_date, end_date, window_err = _parse_window(window)
    if window_err:
        return {**_DEFAULT_RESULT, "reason": window_err}

    # Derive which weekday indices are scheduled from the habit schedule definition
    scheduled_wd_indices = _get_scheduled_weekday_indices(habit)
    if scheduled_wd_indices is None:
        schedule_type = getattr(habit, "schedule_type", None)
        return {
            **_DEFAULT_RESULT,
            "reason": (
                f"cannot determine scheduled weekdays from habit "
                f"schedule_type={schedule_type!r}"
            ),
        }

    scheduled_wd_set = set(scheduled_wd_indices)

    # Group logs by log_date for O(1) lookup per day
    logs_by_date: dict = defaultdict(list)
    try:
        for log in logs:
            logs_by_date[log.log_date].append(log)
    except (TypeError, AttributeError) as exc:
        return {**_DEFAULT_RESULT, "reason": f"logs are not iterable or malformed: {exc}"}

    # Accumulate per-weekday scheduled and met counts while iterating the window
    wd_scheduled: dict[int, int] = defaultdict(int)
    wd_met: dict[int, int] = defaultdict(int)
    evaluated_dates = []

    current = start_date
    while current <= end_date:
        wd = current.weekday()
        if wd in scheduled_wd_set:
            wd_scheduled[wd] += 1
            day_logs = logs_by_date.get(current, [])
            # Delegate the met determination to the H1 met-logic helper
            met, met_debug = is_period_met(habit, day_logs)
            evaluated_dates.append(
                {
                    "date": str(current),
                    "weekday": _WEEKDAY_NAMES[wd],
                    "met": met,
                    "debug": met_debug,
                }
            )
            if met:
                wd_met[wd] += 1
        current += timedelta(days=1)

    total_scheduled = sum(wd_scheduled.values())
    total_met = sum(wd_met.values())

    if total_scheduled == 0:
        return {
            "consistency_percent": 0,
            "met_count": 0,
            "scheduled_count": 0,
            "weekday_breakdown": _EMPTY_WEEKDAY_BREAKDOWN,
            "debug": {
                "reason": "no scheduled occurrences found in the given window",
                "evaluated_dates": evaluated_dates,
                "window_start": str(start_date),
                "window_end": str(end_date),
                "scheduled_weekdays": [_WEEKDAY_NAMES[wd] for wd in scheduled_wd_indices],
            },
        }

    # consistency_percent is met_count divided by scheduled_count multiplied by one hundred
    consistency_percent = total_met / total_scheduled * 100

    # Build weekday_breakdown: one entry per scheduled weekday that appears in the window
    weekday_breakdown: dict = {}
    days_with_data: list[tuple[int, int, int]] = []  # (weekday_index, met, scheduled)

    for wd in scheduled_wd_indices:
        sched = wd_scheduled[wd]
        if sched == 0:
            continue
        day_name = _WEEKDAY_NAMES[wd]
        met_n = wd_met[wd]
        weekday_breakdown[day_name] = {
            "met_count": met_n,
            "scheduled_count": sched,
        }
        days_with_data.append((wd, met_n, sched))

    # Determine strongest and weakest day; tie-break by earliest weekday index
    strongest_day = None
    weakest_day = None

    if days_with_data:
        # met_rate is met_count divided by scheduled_count for that weekday
        def _rate(entry):
            _, met_n, sched_n = entry
            return met_n / sched_n if sched_n > 0 else 0.0

        # Strongest: highest rate first, then lowest weekday index on tie
        by_strongest = sorted(days_with_data, key=lambda e: (-_rate(e), e[0]))
        # Weakest: lowest rate first, then lowest weekday index on tie
        by_weakest = sorted(days_with_data, key=lambda e: (_rate(e), e[0]))

        strongest_day = _WEEKDAY_NAMES[by_strongest[0][0]]
        weakest_day = _WEEKDAY_NAMES[by_weakest[0][0]]

    weekday_breakdown["strongest_day"] = strongest_day
    weekday_breakdown["weakest_day"] = weakest_day

    return {
        "consistency_percent": round(consistency_percent, 2),
        "met_count": total_met,
        "scheduled_count": total_scheduled,
        "weekday_breakdown": weekday_breakdown,
        "debug": {
            "evaluated_dates": evaluated_dates,
            "window_start": str(start_date),
            "window_end": str(end_date),
            "scheduled_weekdays": [_WEEKDAY_NAMES[wd] for wd in scheduled_wd_indices],
        },
    }
