"""Apply canonical strength session payload: TSS, versions, pending, replay queue."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import UserPreferences, Workout, WorkoutExercise
from backend.services import job_queue
from backend.services.pending_exercises import upsert_custom_names
from backend.services.session_exercises import validate_session_exercises
from backend.services.session_tss import session_tss
from backend.services.session_versions import snapshot_version
from backend.services.strength_tss import STRENGTH_METHODS, is_strength_workout
from backend.services.weekly_rollup import normalize_week_start, weekly_rollup
from backend.utils.time import today_bangkok


def sync_workout_exercises(session: Session, workout_id: uuid.UUID, exercises: list[dict[str, Any]]) -> None:
    session.query(WorkoutExercise).filter(WorkoutExercise.workout_id == workout_id).delete()
    for i, ex in enumerate(exercises):
        sets = ex.get("sets") or []
        session.add(
            WorkoutExercise(
                workout_id=workout_id,
                display_order=i,
                name=ex["name"],
                sets=len(sets) if isinstance(sets, list) else None,
                sets_json=json.dumps(sets),
            )
        )


def apply_strength_tss(
    session: Session,
    workout: Workout,
    exercises: list[dict[str, Any]],
    *,
    prefs: Optional[UserPreferences] = None,
) -> dict[str, Any]:
    tss_block = session_tss(workout, prefs=prefs, session=session, exercises=exercises)
    if tss_block.get("tss") is not None:
        workout.tss = float(tss_block["tss"])
        workout.tss_source = "calculated"
        workout.tss_method = tss_block.get("method")
    return tss_block


def enqueue_training_load_replay(user_id: uuid.UUID, workout_ids: list[uuid.UUID], from_date) -> Optional[str]:
    dedupe = f"training_load_replay:{user_id}"
    return job_queue.enqueue(
        "training_load_replay",
        {
            "user_id": str(user_id),
            "from_date": str(from_date),
            "workout_ids": [str(w) for w in workout_ids],
        },
        enqueued_by="web",
        dedupe_key=dedupe,
    )


def apply_strength_session_fields(
    session: Session,
    workout: Workout,
    *,
    exercises: list[dict[str, Any]],
    duration_seconds: Optional[int],
    session_effort: Optional[int],
    strength_tss_method: Optional[str],
    record_version: bool = True,
    enqueue_replay: bool = True,
) -> dict[str, Any]:
    if duration_seconds is not None:
        workout.duration_seconds = duration_seconds
    if session_effort is not None:
        workout.session_effort = session_effort
    if strength_tss_method in STRENGTH_METHODS:
        workout.strength_tss_method = strength_tss_method

    workout.exercises_json = exercises
    sync_workout_exercises(session, workout.id, exercises)
    prefs = session.query(UserPreferences).filter(UserPreferences.user_id == workout.user_id).first()
    tss_block = apply_strength_tss(session, workout, exercises, prefs=prefs)
    workout.updated_at = datetime.now(timezone.utc)

    custom_names: list[str] = []
    if record_version:
        snapshot_version(
            session,
            workout.id,
            exercises=exercises,
            duration_seconds=workout.duration_seconds,
            session_effort=workout.session_effort,
            tss=tss_block.get("tss"),
        )
    custom_names = upsert_custom_names(session, workout_id=workout.id, exercises=exercises)

    if enqueue_replay:
        workout.recompute_pending = datetime.now(timezone.utc)
        ws = normalize_week_start(workout.workout_date)
        enqueue_training_load_replay(workout.user_id, [workout.id], ws)

    return {"tss_block": tss_block, "custom_names": custom_names}


def validate_and_apply_json(
    session: Session,
    workout: Workout,
    *,
    exercises: list[Any],
    source_text: Optional[str] = None,
    **fields,
) -> tuple[Optional[dict[str, Any]], Optional[list[dict[str, Any]]]]:
    v = validate_session_exercises(session, exercises=exercises, text=source_text)
    if not v.get("valid"):
        return None, v.get("errors")
    canonical = v["exercises"]
    result = apply_strength_session_fields(session, workout, exercises=canonical, **fields)
    result["formatted"] = v.get("formatted")
    result["resolutions"] = v.get("resolutions")
    return result, None


def dry_run_strength_session(
    session: Session,
    user_id: uuid.UUID,
    *,
    workout_id: Optional[uuid.UUID],
    workout_date,
    duration_seconds: Optional[int],
    session_effort: Optional[int],
    strength_tss_method: Optional[str],
    exercises: list[Any],
    source_text: Optional[str] = None,
) -> dict[str, Any]:
    """Preview TSS and week total without persisting (rolls back any ORM writes)."""
    from backend.services.training_load import current_load

    v = validate_session_exercises(session, exercises=exercises, text=source_text)
    if not v.get("valid"):
        return {"valid": False, "errors": v.get("errors")}

    canonical = v["exercises"]
    trans = session.begin_nested()
    try:
        old_tss = 0.0
        old_week = None
        workout: Optional[Workout] = None
        if workout_id:
            workout = session.get(Workout, workout_id)
            if workout is None or workout.user_id != user_id:
                trans.rollback()
                return {"valid": False, "errors": [{"line": 1, "message": "workout not found"}]}
            old_tss = float(session_tss(workout, session=session).get("tss") or 0)
            old_week = normalize_week_start(workout.workout_date)
            apply_strength_session_fields(
                session,
                workout,
                exercises=canonical,
                duration_seconds=duration_seconds,
                session_effort=session_effort,
                strength_tss_method=strength_tss_method,
                record_version=False,
                enqueue_replay=False,
            )
            new_tss = float(session_tss(workout, session=session, exercises=canonical).get("tss") or 0)
            target_date = workout.workout_date
        else:
            workout = Workout(
                user_id=user_id,
                name="Draft",
                workout_date=workout_date,
                workout_type="strength",
                duration_seconds=duration_seconds,
                session_effort=session_effort,
                strength_tss_method=strength_tss_method,
            )
            session.add(workout)
            session.flush()
            apply_strength_session_fields(
                session,
                workout,
                exercises=canonical,
                duration_seconds=duration_seconds,
                session_effort=session_effort,
                strength_tss_method=strength_tss_method,
                record_version=False,
                enqueue_replay=False,
            )
            new_tss = float(session_tss(workout, session=session, exercises=canonical).get("tss") or 0)
            target_date = workout_date

        ws = normalize_week_start(target_date)
        rollup = weekly_rollup(user_id, ws, session=session, today=today_bangkok())
        week_total = float(rollup.get("tss_total") or 0)
        if workout_id and old_week == ws:
            week_total = week_total - old_tss + new_tss
        elif not workout_id:
            week_total = week_total + new_tss

        tss_block = session_tss(workout, session=session, exercises=canonical)
        load = current_load(str(user_id), as_of=today_bangkok())
        trans.rollback()
        return {
            "valid": True,
            "session_tss": int(tss_block["tss"]) if tss_block.get("tss") is not None else None,
            "tss_exercises": tss_block.get("tss_exercises"),
            "tss_effort_time": tss_block.get("tss_effort_time"),
            "strength_tss_method": tss_block.get("strength_tss_method") or strength_tss_method,
            "per_exercise": tss_block.get("per_exercise") or [],
            "week_tss_total": round(week_total, 1),
            "week_target_tss": rollup.get("target_tss"),
            "ctl": round(float(load.get("ctl") or 0), 1) if load.get("ctl") is not None else None,
            "resolutions": v.get("resolutions"),
        }
    except Exception:
        trans.rollback()
        raise


def strength_type_allowed(workout_type: str) -> bool:
    t = (workout_type or "").strip().lower()
    return t.startswith(("lift", "strength", "wod", "crossfit", "plyo", "mobility", "support"))