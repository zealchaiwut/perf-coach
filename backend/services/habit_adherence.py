"""Pure functions for computing per-habit adherence breakdowns and detecting slipping habits.

No database access. No network I/O. No side effects. Caller supplies all data.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any


# Minimum number of log-days required to surface a meaningful breakdown.
_MIN_HISTORY_DAYS: int = 7

# A habit is "slipping" when adherence dropped at least this many percentage
# points from the previous window to the current window.
_SLIP_THRESHOLD: float = 10.0


def _iter_days(start: date, end: date):
    """Yield each date from start through end inclusive."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def compute_adherence_breakdown(
    habits: list[Any],
    logs_by_habit: dict,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Compute per-habit adherence breakdowns over a date range.

    Pure function — no I/O, no DB access, no mutations.

    Parameters
    ----------
    habits:
        List of habit objects with ``.id`` (UUID or str) and ``.name`` (str).
    logs_by_habit:
        Mapping of str(habit_id) -> list of log objects with a ``.log_date``
        (date) attribute.
    start_date:
        First date of the evaluation window (inclusive).
    end_date:
        Last date of the evaluation window (inclusive).

    Returns
    -------
    dict
        Two keys:

        ``per_habit``
            List of per-habit dicts (one per habit), each with:
            - ``habit_id`` (str)
            - ``name`` (str)
            - ``completion_rate`` (float 0–100)
            - ``streak`` (int) — current consecutive logged days
            - ``missed_days`` (int)
            - ``total_days`` (int) — window length in days
            - ``logged_days`` (int)
            - ``weekday_pct`` (dict[int, float]) — adherence % per weekday (0=Mon)
            - ``overall_avg`` (float) — mean weekday adherence %

        ``building_state``
            Dict with ``active`` (bool) and ``reason`` (str or None).
            ``active`` is True when history is too short to be meaningful.
    """
    all_dates = list(_iter_days(start_date, end_date))
    total_days = len(all_dates)

    # Check global history length
    all_log_dates: set[date] = set()
    for logs in logs_by_habit.values():
        for log in logs:
            all_log_dates.add(log.log_date)

    if len(all_log_dates) < _MIN_HISTORY_DAYS:
        return {
            "per_habit": [],
            "building_state": {
                "active": True,
                "reason": (
                    f"Not enough history yet "
                    f"({len(all_log_dates)} of {_MIN_HISTORY_DAYS} required days logged)."
                ),
            },
        }

    per_habit = []

    for habit in habits:
        habit_id_str = str(habit.id)
        logs = logs_by_habit.get(habit_id_str, [])

        # Index logs by date (any log on a date counts as completion)
        logged_date_set: set[date] = {log.log_date for log in logs if start_date <= log.log_date <= end_date}
        logged_days = len(logged_date_set)
        missed_days = total_days - logged_days
        completion_rate = (logged_days / total_days * 100.0) if total_days > 0 else 0.0

        # Current streak: consecutive days back from end_date
        streak = 0
        d = end_date
        while d >= start_date:
            if d in logged_date_set:
                streak += 1
                d -= timedelta(days=1)
            else:
                break

        # Weekday adherence: group scheduled days by weekday and count completion
        weekday_scheduled: dict[int, int] = defaultdict(int)
        weekday_logged: dict[int, int] = defaultdict(int)
        for day in all_dates:
            wd = day.weekday()
            weekday_scheduled[wd] += 1
            if day in logged_date_set:
                weekday_logged[wd] += 1

        weekday_pct: dict[int, float] = {}
        for wd in range(7):
            sched = weekday_scheduled.get(wd, 0)
            if sched > 0:
                weekday_pct[wd] = weekday_logged.get(wd, 0) / sched * 100.0
            else:
                weekday_pct[wd] = 0.0

        overall_avg = sum(weekday_pct.values()) / 7.0 if weekday_pct else 0.0

        per_habit.append({
            "habit_id": habit_id_str,
            "name": habit.name,
            "completion_rate": round(completion_rate, 2),
            "streak": streak,
            "missed_days": missed_days,
            "total_days": total_days,
            "logged_days": logged_days,
            "weekday_pct": weekday_pct,
            "overall_avg": round(overall_avg, 2),
        })

    return {
        "per_habit": per_habit,
        "building_state": {"active": False, "reason": None},
    }


def detect_slipping_habits(
    current_breakdown: list[dict[str, Any]],
    prev_breakdown: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Identify habits whose adherence dropped materially between two windows.

    Pure function — no I/O, no DB access, no mutations.

    Parameters
    ----------
    current_breakdown:
        ``per_habit`` list from :func:`compute_adherence_breakdown` for the
        current window.
    prev_breakdown:
        ``per_habit`` list from :func:`compute_adherence_breakdown` for the
        previous (comparison) window.

    Returns
    -------
    list of dict
        Each dict has:
        - ``habit_id`` (str)
        - ``name`` (str)
        - ``prev_percent`` (float) — completion_rate in the prior window
        - ``current_percent`` (float) — completion_rate in the current window
        - ``drop`` (float) — how much it dropped (positive = worse)

        Only habits whose drop >= ``_SLIP_THRESHOLD`` are included.
        If prev_breakdown is empty (brand-new data), returns [].
    """
    if not current_breakdown or not prev_breakdown:
        return []

    prev_by_id = {h["habit_id"]: h for h in prev_breakdown}

    slipping = []
    for habit in current_breakdown:
        hid = habit["habit_id"]
        prev = prev_by_id.get(hid)
        if prev is None:
            continue
        prev_pct = float(prev["completion_rate"])
        curr_pct = float(habit["completion_rate"])
        drop = prev_pct - curr_pct
        if drop >= _SLIP_THRESHOLD:
            slipping.append({
                "habit_id": hid,
                "name": habit["name"],
                "prev_percent": round(prev_pct, 2),
                "current_percent": round(curr_pct, 2),
                "drop": round(drop, 2),
            })

    return slipping
