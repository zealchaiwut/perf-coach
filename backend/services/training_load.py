"""
Training load aggregation service — Banister impulse-response model.

Math:
    CTL (Chronic Training Load) and ATL (Acute Training Load) are computed via
    exponential weighted moving averages (EWMA) of daily TSS:

        new = prev + (tss - prev) * (1 - exp(-1 / days))

    where `days` is the time constant (default: CTL=42, ATL=7).

    TSB (Training Stress Balance) = CTL - ATL.

Reference: Banister EW (1991) "Modeling elite athletic performance" in
    MacDougall JD et al. (eds) Physiological Testing of Elite Athletes.

Cold-start assumption (noted in compute_load_curves): CTL=0 and ATL=0 on day 0
(the day before the series begins). This means early values are underestimated
until the EWMA "charges up" over several weeks.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text

from backend.db import engine


def daily_tss_series(
    user_id: str,
    from_date: date,
    to_date: date,
) -> list[tuple[date, int]]:
    """Query workouts table, sum TSS per day, fill zero-TSS days.

    Returns list of (date, tss) tuples ordered ascending from from_date to
    to_date inclusive. Days with no workout get tss=0.

    Raises:
        ValueError: if from_date > to_date or from_date is in the future.
    """
    today = date.today()
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} must not be after to_date {to_date}")
    if from_date > today:
        raise ValueError(f"from_date {from_date} is in the future")

    sql = text(
        """
        SELECT workout_date, COALESCE(SUM(tss), 0)::int AS total_tss
        FROM workouts
        WHERE user_id = :user_id
          AND workout_date BETWEEN :from_date AND :to_date
          AND tss IS NOT NULL
        GROUP BY workout_date
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {"user_id": str(user_id), "from_date": from_date, "to_date": to_date},
        ).fetchall()

    tss_by_date: dict[date, int] = {row[0]: row[1] for row in rows}

    series: list[tuple[date, int]] = []
    current = from_date
    while current <= to_date:
        series.append((current, tss_by_date.get(current, 0)))
        current += timedelta(days=1)
    return series


def compute_load_curves(
    daily_series: list[tuple[date, int]],
    ctl_days: int = 42,
    atl_days: int = 7,
) -> list[dict]:
    """Compute CTL, ATL, TSB for each day in daily_series using EWMA.

    Cold-start assumption: CTL=0 and ATL=0 before the first day in the series.
    Early values will be underestimated until the EWMA has enough history.

    Args:
        daily_series: list of (date, tss) tuples ordered ascending.
        ctl_days: EWMA time constant for CTL (default 42). Must be > atl_days.
        atl_days: EWMA time constant for ATL (default 7). Must be > 0.

    Returns:
        list of dicts with keys: date, tss, ctl, atl, tsb.

    Raises:
        ValueError: if ctl_days <= atl_days or atl_days <= 0.
    """
    if atl_days <= 0:
        raise ValueError(f"atl_days must be > 0, got {atl_days}")
    if ctl_days <= atl_days:
        raise ValueError(
            f"ctl_days ({ctl_days}) must be greater than atl_days ({atl_days})"
        )

    ctl_alpha = 1 - math.exp(-1 / ctl_days)
    atl_alpha = 1 - math.exp(-1 / atl_days)

    ctl = 0.0
    atl = 0.0
    result = []
    for day, tss in daily_series:
        ctl = ctl + (tss - ctl) * ctl_alpha
        atl = atl + (tss - atl) * atl_alpha
        tsb = ctl - atl
        result.append({"date": day, "tss": tss, "ctl": round(ctl, 2), "atl": round(atl, 2), "tsb": round(tsb, 2)})
    return result


def current_load(
    user_id: str,
    as_of: Optional[date] = None,
) -> dict:
    """Return CTL, ATL, TSB as of a given date (default: today).

    Queries workouts from 6 months before as_of to give the EWMA time to
    charge up. Returns a dict with keys: date, ctl, atl, tsb.

    Args:
        user_id: the user's ID.
        as_of: restrict series to this date (default: today).

    Returns:
        dict with keys date, ctl, atl, tsb for the last day of the series.
    """
    end = as_of if as_of is not None else date.today()
    # 6-month warm-up window so EWMA is reasonably converged by end date
    start = end - timedelta(days=180)

    series = daily_tss_series(user_id, start, end)
    curves = compute_load_curves(series)
    last = curves[-1]
    return {
        "date": last["date"],
        "ctl": last["ctl"],
        "atl": last["atl"],
        "tsb": last["tsb"],
    }
