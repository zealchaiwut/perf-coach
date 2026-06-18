"""
Unified daily training load series.

Aggregates workout TSS values by calendar day over a requested date range.
The core function is a pure computation — all database work is done by callers
that fetch workouts and pass them in.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def daily_load_series(workouts, start_date, end_date) -> Any:
    """Compute daily load aggregates for a list of workouts over a date range.

    This is a pure function — it performs no database access. The caller
    fetches workouts from the database and passes them as plain objects or
    dicts.

    Parameters
    ----------
    workouts:
        List of workout objects (dicts or attribute-bearing objects) each having
        at minimum ``id`` (any), ``date`` (ISO-8601 date string, e.g.
        ``"2026-06-01"``), and ``tss`` (numeric or None).  The list may be
        ordered or unordered.
    start_date:
        ISO-8601 date string for the start of the requested range (inclusive).
    end_date:
        ISO-8601 date string for the end of the requested range (inclusive).

    Returns
    -------
    On success:
        list — ordered ascending by date, one object per calendar day in
        [start_date, end_date]. Each object has:

            date                ISO-8601 date string for that day
            daily_load          sum of tss values on that day; null tss is
                                treated as 0
            workout_count       count of workouts on that day (including
                                unscored ones)
            has_unscored        True when at least one workout had null tss
            debug               dict containing ``contributing_workouts`` — a
                                list of ``{id, tss}`` objects (tss null
                                preserved as None, not coerced to 0)

    On validation failure:
        dict — ``{"results": [], "reason": "<human-readable explanation>"}``
        Returned (not raised) when any required input is missing or when
        start_date is after end_date.

    Worked example
    --------------
    Inputs:

        workouts = [
            {"id": "a1", "date": "2026-06-01", "tss": 80},
            {"id": "b1", "date": "2026-06-01", "tss": 120},
            {"id": "c1", "date": "2026-06-03", "tss": None},
        ]
        start_date = "2026-06-01"
        end_date   = "2026-06-03"

    Call:

        result = daily_load_series(workouts, "2026-06-01", "2026-06-03")

    Expected output:

        [
            {
                "date": "2026-06-01",
                "daily_load": 200,
                "workout_count": 2,
                "has_unscored": False,
                "debug": {
                    "contributing_workouts": [
                        {"id": "a1", "tss": 80},
                        {"id": "b1", "tss": 120},
                    ]
                }
            },
            {
                "date": "2026-06-02",
                "daily_load": 0,
                "workout_count": 0,
                "has_unscored": False,
                "debug": {"contributing_workouts": []}
            },
            {
                "date": "2026-06-03",
                "daily_load": 0,
                "workout_count": 1,
                "has_unscored": True,
                "debug": {
                    "contributing_workouts": [{"id": "c1", "tss": None}]
                }
            },
        ]
    """
    def _fail(reason: str) -> dict:
        return {"results": [], "reason": reason}

    def _get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    if workouts is None:
        return _fail("workouts is required")
    if start_date is None:
        return _fail("start_date is required")
    if end_date is None:
        return _fail("end_date is required")

    try:
        start = date.fromisoformat(str(start_date))
    except ValueError:
        return _fail(f"start_date is not a valid ISO-8601 date: {start_date!r}")

    try:
        end = date.fromisoformat(str(end_date))
    except ValueError:
        return _fail(f"end_date is not a valid ISO-8601 date: {end_date!r}")

    if start > end:
        return _fail(
            f"start_date ({start_date}) must not be after end_date ({end_date})"
        )

    by_date: dict[str, list] = {}
    for w in workouts:
        w_date = _get(w, "date")
        if w_date is None:
            continue
        key = str(w_date)
        if key not in by_date:
            by_date[key] = []
        by_date[key].append(w)

    result = []
    current = start
    while current <= end:
        date_str = current.isoformat()
        day_workouts = by_date.get(date_str, [])
        daily_load = sum(_get(w, "tss") or 0 for w in day_workouts)
        has_unscored = any(_get(w, "tss") is None for w in day_workouts)
        contributing = [
            {"id": _get(w, "id"), "tss": _get(w, "tss")} for w in day_workouts
        ]
        result.append({
            "date": date_str,
            "daily_load": daily_load,
            "workout_count": len(day_workouts),
            "has_unscored": has_unscored,
            "debug": {"contributing_workouts": contributing},
        })
        current += timedelta(days=1)

    return result
