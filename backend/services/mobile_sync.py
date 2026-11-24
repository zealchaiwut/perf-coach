"""POST /api/mobile/sync — apply queued phone ops (PWA P0-4)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlannedSession, Workout
from backend.services.body_log_store import patch_body_log
from backend.services.data_version import bump_data_version
from backend.services.muscle_load import recompute_strength_load_for_date
from backend.services.processed_mutations import apply_once
from backend.services.session_exercises import validate_sections
from backend.services.session_strength_save import apply_strength_session_fields, strength_type_allowed
from backend.services.session_tss import session_tss
from backend.services.session_versions import list_versions
from backend.services.worker_client import delegate_precompute, precompute_on_write_enabled
from backend.utils.time import today_bangkok

SUPPORTED_OPS = frozenset({"session_log", "session_meta", "weigh_in"})


def _parse_dt(raw) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not raw:
        return datetime.now(timezone.utc)
    text = str(raw).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _as_uuid(value) -> Optional[uuid.UUID]:
    if value is None:
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _server_version(session: Session, workout: Workout) -> dict[str, Any]:
    versions = list_versions(session, workout.id)
    latest = versions[0] if versions else None
    return {
        "workout_id": str(workout.id),
        "updated_at": workout.updated_at.isoformat() if workout.updated_at else None,
        "version_id": latest["id"] if latest else None,
        "exercises": workout.exercises_json,
        "name": workout.name,
        "remarks": workout.remarks,
    }


def _resolve_workout(session: Session, user_id, payload: dict) -> tuple[Optional[Workout], Optional[str]]:
    wid = _as_uuid(payload.get("workout_id") or payload.get("matched_workout_id"))
    if wid:
        w = session.get(Workout, wid)
        if w is None or w.user_id != user_id:
            return None, "workout not found"
        return w, None
    sid = _as_uuid(payload.get("session_id") or payload.get("planned_session_id"))
    planned = session.get(PlannedSession, sid) if sid else None
    if planned is not None and planned.user_id == user_id and planned.matched_workout_id:
        w = session.get(Workout, planned.matched_workout_id)
        if w is not None:
            return w, None
    day_raw = payload.get("date") or payload.get("workout_date")
    try:
        day = date.fromisoformat(str(day_raw)) if day_raw else today_bangkok()
    except ValueError:
        return None, "invalid date"
    name = (payload.get("name") or "Strength").strip() or "Strength"
    w = Workout(
        user_id=user_id,
        workout_date=day,
        name=name[:200],
        workout_type="strength",
        source="pwa",
    )
    session.add(w)
    session.flush()
    if planned is not None and planned.user_id == user_id:
        planned.matched_workout_id = w.id
        planned.status = "done_manual"
    return w, None


def _apply_session_log(session: Session, user_id, payload: dict) -> dict[str, Any]:
    exercises = payload.get("exercises") or payload.get("sections") or []
    if not isinstance(exercises, list):
        raise ValueError("exercises must be a list")
    section_errors = validate_sections(exercises)
    if section_errors:
        raise ValueError("; ".join(section_errors))
    workout, err = _resolve_workout(session, user_id, payload)
    if err or workout is None:
        raise ValueError(err or "workout not found")
    if not strength_type_allowed(workout.workout_type or ""):
        workout.workout_type = "strength"
    duration = payload.get("duration_seconds")
    effort = payload.get("session_rpe") or payload.get("session_effort")
    apply_strength_session_fields(
        session,
        workout,
        exercises=exercises,
        duration_seconds=int(duration) if duration is not None else workout.duration_seconds,
        session_effort=int(effort) if effort is not None else workout.session_effort,
        strength_tss_method=payload.get("strength_tss_method"),
        record_version=True,
        enqueue_replay=True,
    )
    if payload.get("notes"):
        workout.remarks = str(payload["notes"])[:2000]
    if payload.get("name"):
        workout.name = str(payload["name"])[:200]
    tss_block = session_tss(workout, session=session, exercises=exercises)
    bump_data_version(session, user_id)
    try:
        recompute_strength_load_for_date(user_id, workout.workout_date)
    except Exception:
        pass
    queued = False
    if precompute_on_write_enabled():
        res = delegate_precompute(str(user_id), dates=[workout.workout_date])
        queued = bool((res or {}).get("queued"))
    if not queued:
        try:
            from backend.services.precompute import precompute_user

            precompute_user(str(user_id), dates=[workout.workout_date])
        except Exception:
            pass
    versions = list_versions(session, workout.id)
    if payload.get("apply_to_future"):
        from backend.services.session_template_overrides import upsert_from_edit_log

        upsert_from_edit_log(
            session,
            user_id,
            str(payload.get("template_key") or payload.get("name") or ""),
            payload.get("edit_log") or [],
        )
    return {
        "workout_id": str(workout.id),
        "version_id": versions[0]["id"] if versions else None,
        "tss": tss_block.get("tss"),
        "apply_to_future": bool(payload.get("apply_to_future")),
    }


def _desktop_edited_after(session: Session, workout: Workout, base_version: Optional[str]) -> bool:
    if not base_version:
        return False
    versions = list_versions(session, workout.id)
    if not versions:
        return False
    latest = versions[0]
    return str(latest["id"]) != str(base_version)


def _apply_session_meta(session: Session, user_id, payload: dict, created_at: datetime) -> dict[str, Any]:
    workout, err = _resolve_workout(session, user_id, payload)
    if err or workout is None:
        raise ValueError(err or "workout not found")
    incoming = _parse_dt(payload.get("updated_at") or created_at)
    current = workout.updated_at
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if current is not None and current > incoming:
        return {"applied": False, "reason": "older_meta", "workout_id": str(workout.id)}
    if payload.get("name"):
        workout.name = str(payload["name"])[:200]
    if "notes" in payload:
        workout.remarks = (str(payload["notes"])[:2000] if payload["notes"] else None)
    workout.updated_at = incoming
    bump_data_version(session, user_id)
    return {"workout_id": str(workout.id), "name": workout.name}


def _apply_weigh_in(session: Session, user_id, payload: dict) -> dict[str, Any]:
    day_raw = payload.get("date")
    kg = payload.get("kg") or payload.get("weight_kg")
    if kg is None:
        raise ValueError("kg is required")
    try:
        day = date.fromisoformat(str(day_raw)) if day_raw else today_bangkok()
        weight = float(kg)
    except (TypeError, ValueError):
        raise ValueError("invalid weigh_in")
    patch_body_log(session, user_id, day, weight_kg=weight)
    bump_data_version(session, user_id)
    return {"date": day.isoformat(), "kg": weight}


def apply_op(session: Session, user_id, op: dict[str, Any]) -> dict[str, Any]:
    op_type = str(op.get("op_type") or "")
    mid = op.get("client_mutation_id")
    if not mid:
        return {"status": "invalid", "error": "client_mutation_id is required", "op_type": op_type}
    if op_type not in SUPPORTED_OPS:
        return {"status": "invalid", "error": f"unsupported op_type {op_type}", "client_mutation_id": str(mid)}
    payload = op.get("payload") or {}
    created_at = _parse_dt(op.get("created_at"))
    base_version = op.get("base_version")

    def _run():
        if op_type == "session_log":
            workout, err = _resolve_workout(session, user_id, payload)
            if err:
                raise ValueError(err)
            if workout is not None and _desktop_edited_after(session, workout, base_version):
                raise _Conflict(workout)
            return _apply_session_log(session, user_id, payload)
        if op_type == "session_meta":
            return _apply_session_meta(session, user_id, payload, created_at)
        return _apply_weigh_in(session, user_id, payload)

    try:
        result = apply_once(session, user_id, mid, op_type, _run)
    except _Conflict as conflict:
        return {
            "status": "conflict",
            "client_mutation_id": str(mid),
            "op_type": op_type,
            "server_version": _server_version(session, conflict.workout),
        }
    except ValueError as exc:
        return {
            "status": "invalid",
            "client_mutation_id": str(mid),
            "op_type": op_type,
            "error": str(exc),
        }
    if result is None:
        return {"status": "duplicate", "client_mutation_id": str(mid), "op_type": op_type}
    # apply_once returns the stored dict; a second call is a duplicate when we
    # already had a row. Callers distinguish via the `seen` flag below.
    return {
        "status": "applied",
        "client_mutation_id": str(mid),
        "op_type": op_type,
        "result": result,
    }


class _Conflict(Exception):
    def __init__(self, workout: Workout):
        super().__init__("conflict")
        self.workout = workout


def apply_ops(session: Session, user_id, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(ops or [], key=lambda o: _parse_dt(o.get("created_at")))
    seen_before = set()
    from backend.models import ProcessedMutation

    existing = {
        str(r.client_mutation_id)
        for r in session.query(ProcessedMutation)
        .filter(ProcessedMutation.user_id == user_id)
        .all()
        if r.result is not None
    }
    out = []
    for op in ordered:
        mid = str(op.get("client_mutation_id") or "")
        was_seen = mid in existing
        row = apply_op(session, user_id, op)
        if was_seen and row.get("status") == "applied":
            row["status"] = "duplicate"
        if row.get("status") in ("applied", "duplicate") and mid:
            existing.add(mid)
        out.append(row)
        seen_before.add(mid)
    return out
