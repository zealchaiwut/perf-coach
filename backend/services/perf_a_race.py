"""Shared lookup of the athlete's target A race for the Performance axes (P4)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional


def next_a_race(session, user_id: uuid.UUID, as_of: date):
    """Next upcoming, not-yet-done A race (earliest date), or None."""
    from backend.models import Race

    return (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.priority == "A",
            Race.status != "done",
            Race.race_date >= as_of,
        )
        .order_by(Race.race_date.asc())
        .first()
    )
