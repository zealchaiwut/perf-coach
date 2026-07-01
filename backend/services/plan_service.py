"""plan_service — DB operations for the plan router (issue #1100).

All DB interaction for /plans/{plan_id}/races and nested checkpoints
lives here; the router itself contains no business logic.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta, timezone as _timezone
from typing import Any, Optional

from sqlalchemy import text as _text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import Race, RaceCheckpoint, compute_goal_pace as _compute_goal_pace


# ── Serialisers ───────────────────────────────────────────────────────────────

def race_to_dict(race: Race) -> dict:
    return {
        "id": str(race.id),
        "plan_id": str(race.user_id),
        "date": str(race.race_date),
        "distance": float(race.distance_km) if race.distance_km is not None else None,
        "duration_seconds": race.duration_seconds,
        "type": race.race_type or "race",
        "priority": race.priority,
        "goal_time_seconds": race.goal_time_seconds,
        "actual_time_seconds": race.actual_time_seconds,
        "status": race.status,
        "name": race.name,
        "created_at": race.created_at.isoformat() if race.created_at else None,
        "updated_at": race.updated_at.isoformat() if race.updated_at else None,
    }


def checkpoint_to_dict(cp: RaceCheckpoint) -> dict:
    return {
        "id": str(cp.id),
        "race_id": str(cp.race_id),
        "type": cp.label,
        "distance": float(cp.target_distance_km) if cp.target_distance_km is not None else None,
        "created_at": cp.created_at.isoformat() if cp.created_at else None,
        "updated_at": cp.updated_at.isoformat() if cp.updated_at else None,
    }


# ── Race operations ───────────────────────────────────────────────────────────

def list_races(plan_id: _uuid.UUID) -> list[dict]:
    with Session(engine) as db:
        rows = (
            db.query(Race)
            .filter(Race.user_id == plan_id)
            .order_by(Race.race_date)
            .all()
        )
        return [race_to_dict(r) for r in rows]


def get_race(plan_id: _uuid.UUID, race_id: _uuid.UUID) -> Optional[dict]:
    with Session(engine) as db:
        race = db.get(Race, race_id)
        if race is None or race.user_id != plan_id:
            return None
        return race_to_dict(race)


def create_race(
    plan_id: _uuid.UUID,
    date: _date,
    distance: Optional[float],
    race_type: str,
    name: str = "",
    goal_time_seconds: Optional[int] = None,
    priority: str = "A",
    status: str = "planned",
    actual_time_seconds: Optional[int] = None,
    duration_seconds: Optional[int] = None,
) -> dict:
    with Session(engine) as db:
        race = Race(
            user_id=plan_id,
            race_date=date,
            distance_km=distance,
            duration_seconds=duration_seconds,
            race_type=race_type,
            name=name,
            goal_time_seconds=goal_time_seconds,
            priority=priority,
            status=status,
            actual_time_seconds=actual_time_seconds,
        )
        db.add(race)
        db.commit()
        db.refresh(race)
        return race_to_dict(race)


def update_race(
    plan_id: _uuid.UUID,
    race_id: _uuid.UUID,
    *,
    date: Optional[_date] = None,
    distance: Optional[float] = None,
    race_type: Optional[str] = None,
    name: Optional[str] = None,
    goal_time_seconds: Optional[int] = None,
    goal_time_set: bool = False,
    priority: Optional[str] = None,
) -> Optional[dict]:
    with Session(engine) as db:
        race = db.get(Race, race_id)
        if race is None or race.user_id != plan_id:
            return None
        if date is not None:
            race.race_date = date
        if distance is not None:
            race.distance_km = distance
        if race_type is not None:
            race.race_type = race_type
        if name is not None:
            race.name = name
        if priority is not None:
            race.priority = priority
        if goal_time_set:
            race.goal_time_seconds = goal_time_seconds
        pace, _ = _compute_goal_pace(
            race.goal_time_seconds,
            float(race.distance_km) if race.distance_km is not None else None,
        )
        race.goal_pace_seconds_per_km = pace
        race.updated_at = _datetime.now(_timezone.utc)
        db.commit()
        db.refresh(race)
        return race_to_dict(race)


def delete_race(plan_id: _uuid.UUID, race_id: _uuid.UUID) -> bool:
    with Session(engine) as db:
        race = db.get(Race, race_id)
        if race is None or race.user_id != plan_id:
            return False
        db.delete(race)
        db.commit()
        return True


# ── Checkpoint operations ─────────────────────────────────────────────────────

def list_checkpoints(plan_id: _uuid.UUID, race_id: _uuid.UUID) -> Optional[list[dict]]:
    with Session(engine) as db:
        race = db.get(Race, race_id)
        if race is None or race.user_id != plan_id:
            return None
        rows = (
            db.query(RaceCheckpoint)
            .filter(RaceCheckpoint.race_id == race_id)
            .order_by(RaceCheckpoint.target_date)
            .all()
        )
        return [checkpoint_to_dict(cp) for cp in rows]


def create_checkpoint(
    plan_id: _uuid.UUID,
    race_id: _uuid.UUID,
    cp_type: str,
    distance: Optional[float] = None,
) -> Optional[dict]:
    with Session(engine) as db:
        race = db.get(Race, race_id)
        if race is None or race.user_id != plan_id:
            return None
        cp = RaceCheckpoint(
            race_id=race_id,
            user_id=plan_id,
            label=cp_type,
            target_date=race.race_date,
            target_distance_km=distance,
        )
        db.add(cp)
        db.commit()
        db.refresh(cp)
        return checkpoint_to_dict(cp)


def update_checkpoint(
    plan_id: _uuid.UUID,
    race_id: _uuid.UUID,
    checkpoint_id: _uuid.UUID,
    *,
    cp_type: Optional[str] = None,
    distance: Optional[float] = None,
    distance_set: bool = False,
) -> Optional[dict]:
    with Session(engine) as db:
        race = db.get(Race, race_id)
        if race is None or race.user_id != plan_id:
            return None
        cp = db.get(RaceCheckpoint, checkpoint_id)
        if cp is None or cp.race_id != race_id:
            return None
        if cp_type is not None:
            cp.label = cp_type
        if distance_set:
            cp.target_distance_km = distance
        cp.updated_at = _datetime.now(_timezone.utc)
        db.commit()
        db.refresh(cp)
        return checkpoint_to_dict(cp)


def delete_checkpoint(
    plan_id: _uuid.UUID,
    race_id: _uuid.UUID,
    checkpoint_id: _uuid.UUID,
) -> bool:
    with Session(engine) as db:
        race = db.get(Race, race_id)
        if race is None or race.user_id != plan_id:
            return False
        cp = db.get(RaceCheckpoint, checkpoint_id)
        if cp is None or cp.race_id != race_id:
            return False
        db.delete(cp)
        db.commit()
        return True


# ── Planned-load schedule generation (issue #1102) ────────────────────────────

def _taper_factor(position: float, shape: str) -> float:
    """Return a reduction factor (≤ 1.0) for the given taper position and shape.

    position: 0.0 at the first taper day, 1.0 at race day.
    """
    if shape == "step":
        return 0.70
    if shape == "exponential":
        return pow(0.5, position)
    # linear (default)
    return 1.0 - 0.5 * position


def generate_planned_load_schedule(
    today: _date,
    race_date: _date,
    base_tss: float,
    ramp_rate: float,
    taper_length: int,
    taper_shape: str = "linear",
) -> list[dict[str, Any]]:
    """Generate a daily planned-TSS series from *today* through *race_date* (both inclusive).

    The series has a ramp phase followed by a taper window:
    - Ramp: TSS increases by *ramp_rate* each day starting from *base_tss*.
    - Taper: the final *taper_length* days (including race day) use a
      shape-governed reduction from the peak ramp TSS.

    Returns a list of dicts with ``date`` (datetime.date) and
    ``planned_tss`` (float, rounded to 2 decimal places), one per calendar day.
    Does not perform any fitness projection (no CTL/ATL/TSB).
    """
    if race_date < today:
        raise ValueError("race_date must be >= today")

    n_days = (race_date - today).days + 1
    ramp_days = max(0, n_days - taper_length)

    schedule: list[dict[str, Any]] = []
    for i in range(n_days):
        current_date = today + _timedelta(days=i)
        if i < ramp_days:
            tss = base_tss + i * ramp_rate
        else:
            peak_tss = base_tss + ramp_days * ramp_rate
            taper_n = n_days - ramp_days  # total taper days
            taper_i = i - ramp_days       # 0-indexed within taper window
            # position: 1/N (first taper day) → 1.0 (race day), never 0
            position = (taper_i + 1) / taper_n
            tss = peak_tss * _taper_factor(position, taper_shape)
        schedule.append({"date": current_date, "planned_tss": round(tss, 2)})

    return schedule


def persist_planned_load_schedule(schedule: list[dict[str, Any]]) -> None:
    """Upsert *schedule* entries to the ``planned_load`` table.

    Only the dates in *schedule* are written; rows outside the generated
    range are not touched (AC8).  Calling twice with identical inputs is
    idempotent (AC4).
    """
    if not schedule:
        return

    with Session(engine) as db:
        for entry in schedule:
            db.execute(
                _text(
                    "INSERT INTO planned_load (date, planned_tss) "
                    "VALUES (:d, :tss) "
                    "ON CONFLICT (date) DO UPDATE SET planned_tss = EXCLUDED.planned_tss"
                ),
                {"d": entry["date"], "tss": entry["planned_tss"]},
            )
        db.commit()
