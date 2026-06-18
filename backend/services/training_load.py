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
import uuid as _uuid_mod
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import TrainingLoadSnapshot

# ── Form-zone band constants ───────────────────────────────────────────────────
# TSB (Training Stress Balance) below this threshold = overreached / buried.
FORM_BURIED_CEILING: float = -10.0
# TSB above this threshold = well-rested / fresh.
FORM_FRESH_FLOOR: float = 5.0


def _ewma_alpha(days: int) -> float:
    """Exponential weighted moving average alpha factor."""
    return 1 - math.exp(-1 / days)


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

    ctl_alpha = _ewma_alpha(ctl_days)
    atl_alpha = _ewma_alpha(atl_days)

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


def daily_update(
    user_id: str,
    target_date: Optional[date] = None,
) -> dict:
    """Compute CTL/ATL/TSB for target_date and UPSERT into training_load_snapshots.

    Uses a 6-month warmup window for EWMA convergence. Safe to re-run (idempotent).

    Args:
        user_id: the user's ID.
        target_date: date to compute and store (default: today).

    Returns:
        dict with keys: date, tss, ctl, atl, tsb.
    """
    target = target_date if target_date is not None else date.today()
    start = target - timedelta(days=180)
    series = daily_tss_series(user_id, start, target)
    curves = compute_load_curves(series)
    last = curves[-1]

    uid = _uuid_mod.UUID(str(user_id))
    row = {
        "user_id": uid,
        "snapshot_date": target,
        "tss_for_day": last["tss"],
        "ctl": round(last["ctl"], 2),
        "atl": round(last["atl"], 2),
        "tsb": round(last["tsb"], 2),
    }

    stmt = _pg_insert(TrainingLoadSnapshot).values([row])
    upsert = stmt.on_conflict_do_update(
        index_elements=["user_id", "snapshot_date"],
        set_={
            "tss_for_day": stmt.excluded.tss_for_day,
            "ctl": stmt.excluded.ctl,
            "atl": stmt.excluded.atl,
            "tsb": stmt.excluded.tsb,
            "computed_at": datetime.now(tz=timezone.utc),
        },
    )
    with Session(engine) as session:
        session.execute(upsert)
        session.commit()

    return {
        "date": target,
        "tss": last["tss"],
        "ctl": row["ctl"],
        "atl": row["atl"],
        "tsb": row["tsb"],
    }


def _classify_zone(tsb: float) -> str:
    """Return the zone name for a single TSB value using named band constants."""
    if tsb < FORM_BURIED_CEILING:
        return "buried"
    if tsb >= FORM_FRESH_FLOOR:
        return "fresh"
    return "neutral"


def performance_curve(fitness_series) -> dict:
    """Reinterpret a fitness series into per-day form zones and today's summary.

    This is a pure function: it reads the TSB values already present in
    fitness_series and classifies each day into a zone. It does not recompute
    CTL, ATL, or TSB, and it does not access the database.

    Zone bands (defined by FORM_BURIED_CEILING and FORM_FRESH_FLOOR):
        buried  -- form is below the buried ceiling (athlete is over-reached)
        neutral -- form is at or above the buried ceiling and below the fresh floor
        fresh   -- form is at or above the fresh floor (athlete is well-rested)

    Args:
        fitness_series: a list of dicts, each containing at least 'date' and
            'tsb' keys -- typically the output of compute_load_curves(). The
            'ctl' and 'atl' fields are accepted but not required for zone
            classification. A thin caller can perform the DB access and series
            computation, then pass the result directly to this function.

    Returns:
        A dict with:
            curve       -- list of per-day records, each with 'date', 'form'
                          (the TSB value, unmodified), and 'zone' (one of
                          'buried', 'neutral', 'fresh').
            today_form  -- TSB value for today's date, or None if today is not
                          present in the series.
            today_zone  -- zone string for today's date, or None if today is not
                          present in the series.
            reason      -- empty string on success; a human-readable explanation
                          when the input was invalid or missing.

        On any invalid input (None, empty list, or missing required columns) the
        function returns an empty result with a non-empty reason string. It never
        raises an exception.

    Worked example:

        Suppose three consecutive days have TSB values of -15, 0, and 10.
        FORM_BURIED_CEILING is -10 and FORM_FRESH_FLOOR is 5.

        Day 1: TSB is -15, which is below the buried ceiling of -10.
               Zone is 'buried'.
        Day 2: TSB is 0, which is at or above the buried ceiling and below the
               fresh floor of 5.
               Zone is 'neutral'.
        Day 3: TSB is 10, which is at or above the fresh floor of 5.
               Zone is 'fresh'.

        If Day 3 is today, today_form is 10 and today_zone is 'fresh'.
    """
    _empty = {"curve": [], "today_form": None, "today_zone": None, "reason": ""}

    if not fitness_series:
        return {**_empty, "reason": "fitness_series is None or empty"}

    first = fitness_series[0]
    if not isinstance(first, dict):
        return {**_empty, "reason": "fitness_series items must be dicts"}
    if "tsb" not in first:
        return {**_empty, "reason": "fitness_series items are missing required 'tsb' column"}
    if "date" not in first:
        return {**_empty, "reason": "fitness_series items are missing required 'date' column"}

    today = date.today()
    today_form = None
    today_zone = None
    curve = []

    for row in fitness_series:
        try:
            day = row["date"]
            tsb = row["tsb"]
        except (KeyError, TypeError):
            return {**_empty, "reason": "fitness_series contains rows with missing date or tsb"}
        zone = _classify_zone(tsb)
        curve.append({"date": day, "form": tsb, "zone": zone})
        if day == today:
            today_form = tsb
            today_zone = zone

    return {
        "curve": curve,
        "today_form": today_form,
        "today_zone": today_zone,
        "reason": "",
    }
