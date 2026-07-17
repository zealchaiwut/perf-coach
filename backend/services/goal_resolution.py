"""Active-goal resolver — PerformanceGoal first, Race adapter fallback (issue #1541)."""
from __future__ import annotations

from datetime import date
from typing import Any

_BUCKETS: list[tuple[float, str]] = [
    (5.0, "5k"),
    (10.0, "10k"),
    (21.0975, "half"),
    (42.195, "marathon"),
]


def _distance_bucket(distance_km: float) -> str:
    """Map distance_km to the nearest standard race-distance label."""
    return min(_BUCKETS, key=lambda b: abs(b[0] - distance_km))[1]


class _RaceGoalAdapter:
    """Duck-typed wrapper giving a Race the same attribute shape as PerformanceGoal."""

    __slots__ = ("user_id", "race_date", "race_distance", "target_time")

    def __init__(self, race: Any) -> None:
        self.user_id = race.user_id
        self.race_date: date | None = race.race_date
        dk = race.distance_km
        self.race_distance: str = _distance_bucket(float(dk)) if dk is not None else "half"
        self.target_time: int = int(race.goal_time_seconds)


def resolve_active_goal(user_id, db) -> Any:
    """Return the active PerformanceGoal, a Race-backed adapter, or None.

    Resolution order:
    1. Active PerformanceGoal for user_id (no change for users who use that form).
    2. First A-priority Race with status 'planned' or 'active', non-null
       goal_time_seconds, ordered by race_date ascending nulls-last.
    3. None when neither exists.
    """
    from backend.models import PerformanceGoal, Race

    goal = (
        db.query(PerformanceGoal)
        .filter_by(user_id=user_id, active=True)
        .first()
    )
    if goal is not None:
        return goal

    candidates = (
        db.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.priority == "A",
            Race.status.in_(("planned", "active")),
        )
        .order_by(Race.race_date.asc().nullslast())
        .all()
    )
    for race in candidates:
        if race.goal_time_seconds is not None:
            return _RaceGoalAdapter(race)

    return None
