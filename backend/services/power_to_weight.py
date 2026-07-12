"""Power-to-weight series computation (issue #1360).

Builds a daily W/kg series from EWMA weight entries and the user's threshold
power (ftp_w from user_preferences).  Pure function — no DB access.

power_basis values
------------------
"flat_current"
    ftp_w is a single scalar (the user's current threshold setting).  It is
    applied as a constant across every day in the range.  This is the only
    supported mode for now; the field is included in the payload so clients can
    display a caveat or future code can add a time-series basis.
"""
from __future__ import annotations

import datetime
from typing import Optional


def compute_power_to_weight_series(
    ewma_entries: list,
    power_w: Optional[int],
    from_d: datetime.date,
    to_d: datetime.date,
) -> dict:
    """Return a W/kg payload for the given range.

    Parameters
    ----------
    ewma_entries:
        Dense daily series dicts with ``date`` (datetime.date | str) and
        ``weight_kg`` (float | None).  Should cover [from_d, to_d].
    power_w:
        Threshold/critical power in watts.  None → ``available: False``.
    from_d, to_d:
        Inclusive date range (both datetime.date objects).

    Returns
    -------
    dict with keys:
        available     bool
        power_basis   "flat_current" | None
        series        list of {date, power_w, weight_kg, w_per_kg}
        current       {w_per_kg, power_w, weight_kg, delta_30d} | None
    """
    if not power_w or power_w <= 0:
        return {"available": False, "power_basis": None, "series": [], "current": None}

    # Index ewma_entries by date for O(1) lookup.
    ewma_by_date: dict[datetime.date, Optional[float]] = {}
    for pt in ewma_entries:
        d = pt["date"]
        if isinstance(d, str):
            d = datetime.date.fromisoformat(d)
        ewma_by_date[d] = pt.get("weight_kg")

    num_days = (to_d - from_d).days + 1
    series = []
    last_ewma: Optional[float] = None

    for i in range(num_days):
        day = from_d + datetime.timedelta(days=i)
        if day in ewma_by_date and ewma_by_date[day] is not None:
            last_ewma = ewma_by_date[day]

        if last_ewma is not None and last_ewma > 0:
            w_per_kg = round(power_w / last_ewma, 3)
            wkg_val: Optional[float] = w_per_kg
        else:
            wkg_val = None

        series.append({
            "date": str(day),
            "power_w": power_w,
            "weight_kg": round(last_ewma, 4) if last_ewma is not None else None,
            "w_per_kg": wkg_val,
        })

    # Current stat: last non-null point
    current = None
    last_valid = next((p for p in reversed(series) if p["w_per_kg"] is not None), None)
    if last_valid is not None:
        # Delta vs 30 days ago: find the w_per_kg from ~30 days before the last valid point
        cutoff = to_d - datetime.timedelta(days=30)
        delta_pt = None
        for p in series:
            pd = datetime.date.fromisoformat(p["date"])
            if pd <= cutoff and p["w_per_kg"] is not None:
                delta_pt = p
        delta_30d = (
            round(last_valid["w_per_kg"] - delta_pt["w_per_kg"], 3)
            if delta_pt is not None
            else None
        )
        current = {
            "w_per_kg": last_valid["w_per_kg"],
            "power_w": last_valid["power_w"],
            "weight_kg": last_valid["weight_kg"],
            "delta_30d": delta_30d,
        }

    return {
        "available": True,
        "power_basis": "flat_current",
        "series": series,
        "current": current,
    }
