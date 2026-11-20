"""Custom exercise queue and admin remap (P2-5)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PendingExercise, PlanExercise, Workout
from backend.services.session_exercises import resolve_exercise_names


def normalize_exercise_name(name: str) -> str:
    s = " ".join((name or "").strip().lower().split())
    return s


def upsert_custom_names(
    session: Session,
    *,
    workout_id: uuid.UUID,
    exercises: list[dict[str, Any]],
) -> list[str]:
    """Upsert pending rows for custom names; return list of custom display names."""
    resolutions = resolve_exercise_names(session, exercises)
    custom_names: list[str] = []
    now = datetime.now(timezone.utc)
    for ex, res in zip(exercises, resolutions):
        if not res.get("custom"):
            continue
        display = ex["name"].strip()
        custom_names.append(display)
        key = normalize_exercise_name(display)
        row = session.query(PendingExercise).filter(PendingExercise.normalized_name == key).first()
        if row is None:
            row = PendingExercise(
                normalized_name=key,
                display_name=display,
                first_seen_workout_id=workout_id,
                occurrence_count=1,
                closest_match=res.get("closest_match"),
            )
            session.add(row)
        else:
            row.occurrence_count = int(row.occurrence_count or 0) + 1
            row.updated_at = now
            if res.get("closest_match") and not row.closest_match:
                row.closest_match = res.get("closest_match")
    return custom_names


def list_pending(session: Session) -> list[dict[str, Any]]:
    rows = session.query(PendingExercise).order_by(PendingExercise.updated_at.desc().nullslast()).all()
    return [
        {
            "id": str(r.id),
            "normalized_name": r.normalized_name,
            "display_name": r.display_name,
            "first_seen_workout_id": str(r.first_seen_workout_id) if r.first_seen_workout_id else None,
            "occurrence_count": r.occurrence_count,
            "closest_match": r.closest_match,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


def _workouts_with_name(session: Session, display_name: str) -> list[Workout]:
    key = normalize_exercise_name(display_name)
    rows = session.query(Workout).filter(Workout.exercises_json.isnot(None)).all()
    hits: list[Workout] = []
    for w in rows:
        data = w.exercises_json
        if not isinstance(data, list):
            continue
        for ex in data:
            if not isinstance(ex, dict):
                continue
            if normalize_exercise_name(str(ex.get("name") or "")) == key:
                hits.append(w)
                break
    return hits


def remap_custom(session: Session, *, name: str, library_id: uuid.UUID) -> int:
    """Rewrite custom name to library exercise on all sessions; delete pending row."""
    from backend.services.session_strength_save import apply_strength_session_fields

    lib = session.get(PlanExercise, library_id)
    if lib is None:
        raise ValueError("library exercise not found")
    key = normalize_exercise_name(name)
    pending = session.query(PendingExercise).filter(PendingExercise.normalized_name == key).first()
    if pending is None:
        raise ValueError("pending exercise not found")

    touched = 0
    for workout in _workouts_with_name(session, pending.display_name):
        data = list(workout.exercises_json or [])
        changed = False
        for ex in data:
            if normalize_exercise_name(str(ex.get("name") or "")) == key:
                ex["name"] = lib.name
                changed = True
        if not changed:
            continue
        apply_strength_session_fields(
            session,
            workout,
            exercises=data,
            duration_seconds=workout.duration_seconds,
            session_effort=workout.session_effort,
            strength_tss_method=workout.strength_tss_method,
            record_version=True,
            enqueue_replay=True,
        )
        touched += 1

    session.delete(pending)
    session.flush()
    return touched