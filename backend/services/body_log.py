"""Body log (P6-9): daily weight, lunch rule, feet, steps — stats and rollups."""
from __future__ import annotations

import datetime as _dt
from statistics import median
from typing import Any, Optional, Sequence


MIN_WEIGHT_SAMPLES_7D = 3


def _window_weights(
    rows: Sequence[tuple[_dt.date, float]],
    as_of: _dt.date,
    *,
    start_days_ago: int,
    end_days_ago: int,
) -> list[float]:
    lo = as_of - _dt.timedelta(days=end_days_ago)
    hi = as_of - _dt.timedelta(days=start_days_ago)
    return [w for d, w in rows if lo <= d <= hi]


def seven_day_avg(
    rows: Sequence[tuple[_dt.date, float]],
    as_of: _dt.date,
    *,
    min_samples: int = MIN_WEIGHT_SAMPLES_7D,
) -> Optional[float]:
    """Mean of weight readings in [as_of-6, as_of]; None if fewer than min_samples."""
    vals = _window_weights(rows, as_of, start_days_ago=0, end_days_ago=6)
    if len(vals) < min_samples:
        return None
    return round(sum(vals) / len(vals), 2)


def weekly_rate_kg(
    rows: Sequence[tuple[_dt.date, float]],
    as_of: _dt.date,
) -> Optional[float]:
    """Today's 7-day average minus the 7-day average from 7 days ago."""
    cur = seven_day_avg(rows, as_of)
    prev = seven_day_avg(rows, as_of - _dt.timedelta(days=7))
    if cur is None or prev is None:
        return None
    return round(cur - prev, 2)


def sparkline_six_weeks(
    rows: Sequence[tuple[_dt.date, float]],
    as_of: _dt.date,
) -> list[dict[str, Any]]:
    """Six weekly 7-day average points ending on as_of (one per week)."""
    out: list[dict[str, Any]] = []
    for wk in range(5, -1, -1):
        day = as_of - _dt.timedelta(days=7 * wk)
        avg = seven_day_avg(rows, day)
        out.append({"date": day.isoformat(), "value": avg})
    return out


def weekly_body_rollup(
    *,
    week_start: _dt.date,
    week_end: _dt.date,
    lunch_by_date: dict[_dt.date, Optional[bool]],
    steps_by_date: dict[_dt.date, Optional[int]],
    feet_by_date: dict[_dt.date, Optional[int]],
) -> dict[str, Any]:
    """Check-in rollup: lunch yes count, steps average, feet max (logged days only)."""
    days = []
    d = week_start
    while d <= week_end:
        days.append(d)
        d += _dt.timedelta(days=1)

    lunch_logged = [d for d in days if d in lunch_by_date and lunch_by_date[d] is not None]
    lunch_yes = sum(1 for d in lunch_logged if lunch_by_date[d] is True)

    steps_vals = [steps_by_date[d] for d in days if d in steps_by_date and steps_by_date[d] is not None]
    feet_vals = [feet_by_date[d] for d in days if d in feet_by_date and feet_by_date[d] is not None]

    steps_avg = round(sum(steps_vals) / len(steps_vals), 1) if steps_vals else None
    feet_max = max(feet_vals) if feet_vals else None

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "lunch_rule_yes_count": lunch_yes,
        "lunch_rule_logged_days": len(lunch_logged),
        "steps_avg": steps_avg,
        "feet_max": feet_max,
    }