"""
Pure function for projecting when a user will reach their goal weight (issue #876).

project_arrival(actual_trend, goal_weight_kg, today) is a side-effect-free function
that estimates the arrival date from the recent weight trend.  A separate thin caller
(fetch_and_project_arrival) handles all database access and passes data in.
"""
from __future__ import annotations

import datetime


# Window over which the recent weekly rate is derived.  Between 14 and 28 days.
ARRIVAL_WINDOW_DAYS = 21


def project_arrival(
    actual_trend: list | None,
    goal_weight_kg: float | None,
    today: datetime.date | None,
) -> dict:
    """
    Estimate the date at which the user will reach goal_weight_kg given their
    recent weight trend.

    Parameters
        actual_trend   -- list of dicts, each with 'date' (datetime.date) and
                          'weight_kg' (float), ordered oldest-first or any order.
        goal_weight_kg -- target weight in kilograms.
        today          -- reference date for the projection.

    Returns on success:
        {
          "arrival_date":   datetime.date,  the projected date of arrival,
          "weekly_rate_kg": float,          signed weekly rate used (negative means losing),
          "debug":          dict,           intermediate values used in the calculation,
        }

    Returns on any failure without raising:
        {
          "arrival_date":   None,
          "weekly_rate_kg": None (or the computed rate for flat and diverging cases),
          "debug":          {},
          "reason":         str describing what prevented the projection,
        }

    Worked example:
        A user weighs 93 kg with a goal of 80 kg, giving 13 kg remaining.  Their
        recent rate is minus 0.4 kg per week.  The days needed equal 13 divided by 0.4
        multiplied by 7, which is 227.5 days, approximately 32 weeks from today.

    Edge cases:
        When the trend is flat or moving away from the goal, arrival_date is None and
        reason is "not trending toward goal".
        When the user is already at or past their goal weight, reason is
        "already at or past goal".
        When any required input is missing, reason describes which input was missing.
        When fewer entries are available than ARRIVAL_WINDOW_DAYS, the function uses
        all available entries and records how many were used in the debug object.
    """
    _null = {"arrival_date": None, "weekly_rate_kg": None, "debug": {}}

    # ── Validate inputs ───────────────────────────────────────────────────────
    if actual_trend is None:
        return {**_null, "reason": "actual_trend is required"}
    if not isinstance(actual_trend, (list, tuple)) or len(actual_trend) == 0:
        return {**_null, "reason": "actual_trend is empty or not a list"}
    if goal_weight_kg is None:
        return {**_null, "reason": "goal_weight_kg is required"}
    if today is None:
        return {**_null, "reason": "today is required"}

    # ── Sort and extract window ───────────────────────────────────────────────
    try:
        sorted_trend = sorted(actual_trend, key=lambda e: e["date"])
    except (KeyError, TypeError):
        return {**_null, "reason": "actual_trend entries must have 'date' and 'weight_kg' fields"}

    window = sorted_trend[-ARRIVAL_WINDOW_DAYS:]

    if len(window) < 2:
        return {**_null, "reason": f"insufficient data: need at least 2 entries, got {len(window)}"}

    # ── Compute weekly rate from first to last entry in window ────────────────
    try:
        first = window[0]
        last = window[-1]
        days_span = (last["date"] - first["date"]).days
        if days_span == 0:
            weekly_rate: float = 0.0
        else:
            weekly_rate = (last["weight_kg"] - first["weight_kg"]) / days_span * 7.0
    except (KeyError, TypeError, AttributeError):
        return {**_null, "reason": "actual_trend entries must have 'date' and 'weight_kg' fields"}

    most_recent_weight: float = float(last["weight_kg"])
    remaining_kg: float = most_recent_weight - float(goal_weight_kg)

    debug = {
        "window_days_used": len(window),
        "first_date": str(first["date"]),
        "first_weight_kg": float(first["weight_kg"]),
        "last_date": str(last["date"]),
        "last_weight_kg": most_recent_weight,
        "remaining_kg": remaining_kg,
        "weekly_rate_kg": weekly_rate,
    }

    # ── Already at or past goal ───────────────────────────────────────────────
    # remaining_kg <= 0 for a loss goal means at or below goal.
    # remaining_kg < 0 with a negative rate means the user has overshot downward.
    # Check: if the trend direction and remaining_kg both indicate goal has been reached/passed.
    if remaining_kg == 0.0:
        return {
            "arrival_date": None,
            "weekly_rate_kg": weekly_rate,
            "debug": debug,
            "reason": "already at or past goal",
        }

    # Converging means remaining_kg and weekly_rate have opposite signs.
    # remaining_kg > 0 (need to lose) requires weekly_rate < 0 (losing).
    # remaining_kg < 0 (need to gain) requires weekly_rate > 0 (gaining).
    converging = (remaining_kg > 0 and weekly_rate < 0) or (remaining_kg < 0 and weekly_rate > 0)

    if not converging:
        # Determine whether the user is already past goal or simply not trending toward it.
        # If both remaining_kg and weekly_rate are negative: user is below goal while still
        # losing, meaning they have overshot a loss target.
        if remaining_kg < 0 and weekly_rate <= 0:
            return {
                "arrival_date": None,
                "weekly_rate_kg": weekly_rate,
                "debug": debug,
                "reason": "already at or past goal",
            }
        return {
            "arrival_date": None,
            "weekly_rate_kg": weekly_rate,
            "debug": debug,
            "reason": "not trending toward goal",
        }

    # ── Compute arrival date ──────────────────────────────────────────────────
    days_to_arrival = int((abs(remaining_kg) / abs(weekly_rate)) * 7)
    arrival_date = today + datetime.timedelta(days=days_to_arrival)

    return {
        "arrival_date": arrival_date,
        "weekly_rate_kg": weekly_rate,
        "debug": debug,
    }


# ── Thin caller ───────────────────────────────────────────────────────────────

def fetch_and_project_arrival(
    user_id: int,
    goal_weight_kg: float,
    today: datetime.date,
    session,
) -> dict:
    """
    Thin caller: fetches the recent weight trend from the database and delegates
    all math to project_arrival.  No computation happens here.
    """
    from backend.models import WeightEntry  # local import; caller owns DB access

    window_start = today - datetime.timedelta(days=ARRIVAL_WINDOW_DAYS)
    entries = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date >= window_start,
            WeightEntry.entry_date <= today,
        )
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )

    actual_trend = [
        {"date": e.entry_date, "weight_kg": float(e.weight_kg)}
        for e in entries
    ]

    return project_arrival(actual_trend, goal_weight_kg, today)
