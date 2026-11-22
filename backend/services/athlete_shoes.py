"""Athlete shoe list and per-shoe mileage (revamp P6-14)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import AthleteShoe, Workout
from backend.services.checkpoint_detector import is_run_workout


def shoe_dict(row: AthleteShoe) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "is_race_shoe": bool(row.is_race_shoe),
        "retired": bool(row.retired),
        "total_km": float(row.total_km or 0),
        "longest_run_km": float(row.longest_run_km) if row.longest_run_km is not None else None,
    }


def list_shoes(session: Session, user_id: uuid.UUID, *, include_retired: bool = False) -> list[dict[str, Any]]:
    q = session.query(AthleteShoe).filter(AthleteShoe.user_id == user_id)
    if not include_retired:
        q = q.filter(AthleteShoe.retired.is_(False))
    return [shoe_dict(r) for r in q.order_by(AthleteShoe.name.asc()).all()]


def default_shoe_id(session: Session, user_id: uuid.UUID) -> Optional[str]:
    last = (
        session.query(Workout.shoe_id)
        .filter(Workout.user_id == user_id, Workout.shoe_id.isnot(None))
        .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
        .first()
    )
    if last and last[0]:
        return str(last[0])
    active = (
        session.query(AthleteShoe)
        .filter(AthleteShoe.user_id == user_id, AthleteShoe.retired.is_(False))
        .order_by(AthleteShoe.created_at.desc())
        .first()
    )
    return str(active.id) if active else None


def recompute_shoe_stats(session: Session, user_id: uuid.UUID, shoe_id: uuid.UUID) -> None:
    shoe = session.get(AthleteShoe, shoe_id)
    if shoe is None or shoe.user_id != user_id:
        return
    total = Decimal("0")
    longest: Optional[Decimal] = None
    for w in session.query(Workout).filter(Workout.user_id == user_id, Workout.shoe_id == shoe_id).all():
        if not is_run_workout(w.workout_type or ""):
            continue
        dist = Decimal(str(w.distance_km or 0))
        total += dist
        if dist > 0 and (longest is None or dist > longest):
            longest = dist
    shoe.total_km = total
    shoe.longest_run_km = longest
    shoe.updated_at = datetime.now(timezone.utc)


def fuel_logging_required(workout: Workout, *, is_race: bool = False) -> bool:
    if is_race:
        return True
    return is_run_workout(workout.workout_type or "") and (workout.duration_seconds or 0) >= 90 * 60
