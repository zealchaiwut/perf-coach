"""
Caller module for the arrival-projection endpoint (issue #878).

``build_arrival_projection_response`` is a pure function: it takes a weight-entry
trend, a goal weight, and flags for missing-data states, delegates to
``project_arrival``, and returns a consistently shaped response dict.

``resolve_arrival_projection`` is the thin DB caller: it fetches the active
WeightTarget and weight entries from the database, then calls the pure function.
"""
from __future__ import annotations

import datetime

from backend.services.goal_arrival import ARRIVAL_WINDOW_DAYS, project_arrival
from backend.utils.time import today_bangkok


def build_arrival_projection_response(
    trend: list,
    goal_weight_kg: float | None,
    today: datetime.date,
    no_active_plan: bool,
    no_active_goal: bool,
) -> dict:
    """
    Pure function: map project_arrival output and data-availability flags into a
    consistent endpoint response dict.

    Always returns all four keys: projected_arrival_date, projected_rate,
    recent_rate, reason.  Never raises; missing-data cases return null projection
    fields with a descriptive reason string.
    """
    _empty = {
        "projected_arrival_date": None,
        "projected_rate": None,
        "recent_rate": None,
        "reason": None,
    }

    if no_active_plan:
        return {**_empty, "reason": "no_active_plan"}

    if no_active_goal:
        return {**_empty, "reason": "no_active_goal"}

    result = project_arrival(trend, goal_weight_kg, today)

    reason_from_fn = result.get("reason", "")

    # Map project_arrival reason strings to endpoint reason strings.
    # "insufficient data" prefix covers both the empty-list and <2-entries cases.
    if reason_from_fn and (
        reason_from_fn.startswith("insufficient data")
        or reason_from_fn.startswith("actual_trend is empty")
        or reason_from_fn.startswith("actual_trend is required")
    ):
        return {**_empty, "reason": "insufficient_data"}

    # Not trending toward goal — return recent_rate so the chart can annotate pace.
    if reason_from_fn == "not trending toward goal":
        weekly_rate = result.get("weekly_rate_kg")
        return {
            "projected_arrival_date": None,
            "projected_rate": None,
            "recent_rate": weekly_rate,
            "reason": "not_trending_toward_goal",
        }

    # User is already at or past their goal — distinct from insufficient data.
    if reason_from_fn == "already at or past goal":
        weekly_rate = result.get("weekly_rate_kg")
        return {
            "projected_arrival_date": None,
            "projected_rate": None,
            "recent_rate": weekly_rate,
            "reason": "already_at_goal",
        }

    # Any other reason from project_arrival (bad input, etc.)
    # — surface as insufficient_data since the chart cannot project.
    if reason_from_fn:
        weekly_rate = result.get("weekly_rate_kg")
        return {
            "projected_arrival_date": None,
            "projected_rate": None,
            "recent_rate": weekly_rate,
            "reason": "insufficient_data",
        }

    # Happy path: converging trend with a valid arrival date.
    arrival_date = result["arrival_date"]
    weekly_rate = result["weekly_rate_kg"]
    return {
        "projected_arrival_date": arrival_date.isoformat() if arrival_date is not None else None,
        "projected_rate": weekly_rate,
        "recent_rate": weekly_rate,
        "reason": None,
    }


def resolve_arrival_projection(
    user_id,
    session,
    today: datetime.date | None = None,
) -> dict:
    """
    Thin DB caller: resolves the user's active WeightTarget (plan + goal) and
    their recent weight entries from the database, then delegates entirely to
    ``build_arrival_projection_response``.  No computation happens here.
    """
    from backend.models import WeightEntry, WeightTarget  # local — caller owns DB

    if today is None:
        today = today_bangkok()

    active_target = (
        session.query(WeightTarget)
        .filter(WeightTarget.user_id == user_id, WeightTarget.status == "active")
        .first()
    )

    if active_target is None:
        return build_arrival_projection_response(
            trend=[],
            goal_weight_kg=None,
            today=today,
            no_active_plan=True,
            no_active_goal=False,
        )

    goal_weight_kg = (
        float(active_target.target_weight_kg)
        if active_target.target_weight_kg is not None
        else None
    )

    if goal_weight_kg is None:
        return build_arrival_projection_response(
            trend=[],
            goal_weight_kg=None,
            today=today,
            no_active_plan=False,
            no_active_goal=True,
        )

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

    trend = [
        {"date": e.entry_date, "weight_kg": float(e.weight_kg)}
        for e in entries
    ]

    return build_arrival_projection_response(
        trend=trend,
        goal_weight_kg=goal_weight_kg,
        today=today,
        no_active_plan=False,
        no_active_goal=False,
    )
