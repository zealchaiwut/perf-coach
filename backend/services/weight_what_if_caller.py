"""Caller module: fetches actual_trend from the DB and delegates to simulate_what_if.

This module owns all I/O.  The pure projection logic lives in
``weight_what_if.py`` and is kept free of database dependencies.
"""
from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from backend.models import WeightEntry
from backend.services.weight_what_if import simulate_what_if


def run_what_if(
    session: Session,
    user_id: int,
    goal_weight_kg: float,
    assumed_rate_kg_per_week: float,
    today: datetime.date | None = None,
    lookback_days: int = 30,
) -> dict:
    """Fetch the user's recent weight trend and run a what-if projection.

    Builds ``actual_trend`` as a dict of {date: weight_kg} from the most
    recent ``lookback_days`` entries for the user, then calls
    :func:`~backend.services.weight_what_if.simulate_what_if` with those
    values.  Returns whatever ``simulate_what_if`` returns.

    Parameters
    ----------
    session:
        SQLAlchemy database session.
    user_id:
        ID of the user whose weight entries are fetched.
    goal_weight_kg:
        Target weight in kilograms.
    assumed_rate_kg_per_week:
        Assumed weekly rate of weight change (negative = loss).
    today:
        Anchor date for the simulation; defaults to :func:`datetime.date.today`.
    lookback_days:
        How many days back to include when building the trend dict.
    """
    if today is None:
        today = datetime.date.today()

    window_start = today - datetime.timedelta(days=lookback_days)

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

    actual_trend = {e.entry_date: float(e.weight_kg) for e in entries}

    return simulate_what_if(
        actual_trend=actual_trend,
        goal_weight_kg=goal_weight_kg,
        assumed_rate_kg_per_week=assumed_rate_kg_per_week,
        today=today,
    )
