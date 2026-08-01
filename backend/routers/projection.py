"""projection.py — routes for /plans/{plan_id}/races, checkpoints, and projection.

Route paths, the ``training_plans`` table, and the ``TrainingPlan`` model are
UNCHANGED — this file was renamed from ``plan.py`` (feature/performance-tab-rework).
All business logic and DB interaction is delegated to projection_service or the
projection payload module; no domain logic lives in this router.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date as _date, timedelta as _timedelta
from backend.utils.time import today_bangkok as _today_bangkok
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query as _Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as _Session

from backend.auth import resolve_user
from backend.db import engine as _engine
from backend.models import (
    EconomyCeilingSnapshot as _EconomyCeilingSnapshot,
    Race as _Race,
    TrainingPlan as _TrainingPlan,
    User,
    UserPreferences as _UserPreferences,
    RACE_TYPE_VALUES as _RACE_TYPE_VALUES,
)
from backend.services import projection_service as _svc
from backend.services import projection as _proj
from backend.services.training_load import (
    current_load as _current_load,
    daily_tss_series as _daily_tss_series,
)

router = APIRouter(prefix="/api")


def _parse_plan_id(plan_id: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(plan_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid plan_id")


def _parse_race_id(race_id: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(race_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid race_id")


def _parse_checkpoint_id(checkpoint_id: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(checkpoint_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid checkpoint_id")


def _check_plan_access(plan_id: _uuid.UUID, user: User) -> None:
    with _Session(_engine) as db:
        plan = db.get(_TrainingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    if plan.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Request bodies ────────────────────────────────────────────────────────────

class _RaceCreateBody(BaseModel):
    date: str
    distance: Optional[float] = None
    type: str
    name: Optional[str] = None
    goal_time_seconds: Optional[int] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    actual_time_seconds: Optional[int] = None
    duration_seconds: Optional[int] = None


class _RacePatchBody(BaseModel):
    date: Optional[str] = None
    distance: Optional[float] = None
    type: Optional[str] = None
    name: Optional[str] = None
    goal_time_seconds: Optional[int] = None
    priority: Optional[str] = None


class _CheckpointCreateBody(BaseModel):
    distance: Optional[float] = None
    type: str


class _CheckpointPatchBody(BaseModel):
    distance: Optional[float] = None
    type: Optional[str] = None


# ── Validation helpers ────────────────────────────────────────────────────────

def _validate_date(date_str: str) -> _date:
    try:
        return _date.fromisoformat(date_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail={"field": "date", "error": "date must be a valid ISO 8601 date (YYYY-MM-DD)"},
        )


def _validate_distance(distance: float, field: str = "distance") -> None:
    if distance is not None and distance <= 0:
        raise HTTPException(
            status_code=422,
            detail={"field": field, "error": f"{field} must be a positive number (> 0)"},
        )


def _validate_type(type_str: str, field: str = "type") -> None:
    if not type_str or not type_str.strip():
        raise HTTPException(
            status_code=422,
            detail={"field": field, "error": f"{field} must be a non-empty string"},
        )


def _validate_race_type(type_str: str) -> str:
    """Validate race type against allowed enum values."""
    if not type_str or not type_str.strip():
        raise HTTPException(
            status_code=422,
            detail={"field": "type", "error": "type must be a non-empty string"},
        )
    if type_str not in _RACE_TYPE_VALUES:
        raise HTTPException(
            status_code=422,
            detail={
                "field": "type",
                "error": f"type must be one of: {', '.join(_RACE_TYPE_VALUES)}",
            },
        )
    return type_str


def _resolve_priority(race_type: str, priority: Optional[str]) -> str:
    """Resolve/validate race priority. Checkpoints are always 'C'; races take
    the supplied A/B/C (default 'A')."""
    if race_type == "checkpoint":
        return "C"
    if priority is None:
        return "A"
    if priority not in ("A", "B", "C"):
        raise HTTPException(
            status_code=422,
            detail={"field": "priority", "error": "priority must be one of: A, B, C"},
        )
    return priority


# ── Race endpoints ────────────────────────────────────────────────────────────

@router.get("/plans/{plan_id}/races")
async def list_races(plan_id: str, user: User = Depends(resolve_user)):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    return JSONResponse(_svc.list_races(pid))


@router.post("/plans/{plan_id}/races", status_code=201)
async def create_race(
    plan_id: str,
    body: _RaceCreateBody,
    user: User = Depends(resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    date = _validate_date(body.date)
    _validate_race_type(body.type)
    # A checkpoint may be defined by distance OR duration (exactly one); races
    # always require a distance (issue #1226).
    if body.type == "checkpoint":
        has_dist = body.distance is not None
        has_dur = body.duration_seconds is not None
        if has_dist == has_dur:
            raise HTTPException(
                status_code=422,
                detail={"field": "distance", "error": "checkpoint needs exactly one of distance or duration_seconds"},
            )
        if has_dist:
            _validate_distance(body.distance)
        if has_dur and body.duration_seconds <= 0:
            raise HTTPException(
                status_code=422,
                detail={"field": "duration_seconds", "error": "duration_seconds must be positive"},
            )
    else:
        if body.distance is None:
            raise HTTPException(
                status_code=422,
                detail={"field": "distance", "error": "distance is required"},
            )
        _validate_distance(body.distance)
    status = body.status or "planned"
    if status not in ("planned", "done", "abandoned"):
        raise HTTPException(
            status_code=422,
            detail={"field": "status", "error": "status must be one of: planned, done, abandoned"},
        )
    data = _svc.create_race(
        plan_id=pid,
        date=date,
        distance=body.distance,
        race_type=body.type,
        name=body.name or "",
        goal_time_seconds=body.goal_time_seconds,
        priority=_resolve_priority(body.type, body.priority),
        status=status,
        actual_time_seconds=body.actual_time_seconds,
        duration_seconds=body.duration_seconds,
    )
    return JSONResponse(status_code=201, content=data)


@router.get("/plans/{plan_id}/races/{race_id}")
async def get_race(
    plan_id: str,
    race_id: str,
    user: User = Depends(resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    rid = _parse_race_id(race_id)
    data = _svc.get_race(pid, rid)
    if data is None:
        raise HTTPException(status_code=404, detail="race not found")
    return JSONResponse(data)


@router.patch("/plans/{plan_id}/races/{race_id}")
async def patch_race(
    plan_id: str,
    race_id: str,
    body: _RacePatchBody,
    user: User = Depends(resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    rid = _parse_race_id(race_id)

    date = None
    if body.date is not None:
        date = _validate_date(body.date)
    if body.distance is not None:
        _validate_distance(body.distance)
    if body.type is not None:
        _validate_race_type(body.type)
    priority = None
    if body.priority is not None:
        priority = _resolve_priority(body.type or "race", body.priority)

    goal_time_set = "goal_time_seconds" in body.model_fields_set
    data = _svc.update_race(
        pid,
        rid,
        date=date,
        distance=body.distance,
        race_type=body.type,
        name=body.name,
        goal_time_seconds=body.goal_time_seconds,
        goal_time_set=goal_time_set,
        priority=priority,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="race not found")
    return JSONResponse(data)


@router.delete("/plans/{plan_id}/races/{race_id}", status_code=204)
async def delete_race(
    plan_id: str,
    race_id: str,
    user: User = Depends(resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    rid = _parse_race_id(race_id)
    deleted = _svc.delete_race(pid, rid)
    if not deleted:
        raise HTTPException(status_code=404, detail="race not found")
    return Response(status_code=204)


# ── Checkpoint endpoints ──────────────────────────────────────────────────────

@router.get("/plans/{plan_id}/races/{race_id}/checkpoints")
async def list_checkpoints(
    plan_id: str,
    race_id: str,
    user: User = Depends(resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    rid = _parse_race_id(race_id)
    result = _svc.list_checkpoints(pid, rid)
    if result is None:
        raise HTTPException(status_code=404, detail="race not found")
    return JSONResponse(result)


@router.post("/plans/{plan_id}/races/{race_id}/checkpoints", status_code=201)
async def create_checkpoint(
    plan_id: str,
    race_id: str,
    body: _CheckpointCreateBody,
    user: User = Depends(resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    rid = _parse_race_id(race_id)

    _validate_type(body.type)
    if body.distance is not None:
        _validate_distance(body.distance)

    data = _svc.create_checkpoint(pid, rid, cp_type=body.type, distance=body.distance)
    if data is None:
        raise HTTPException(status_code=404, detail="race not found")
    return JSONResponse(status_code=201, content=data)


@router.patch("/plans/{plan_id}/races/{race_id}/checkpoints/{checkpoint_id}")
async def patch_checkpoint(
    plan_id: str,
    race_id: str,
    checkpoint_id: str,
    body: _CheckpointPatchBody,
    user: User = Depends(resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    rid = _parse_race_id(race_id)
    cid = _parse_checkpoint_id(checkpoint_id)

    if body.type is not None:
        _validate_type(body.type)
    if body.distance is not None:
        _validate_distance(body.distance)

    distance_set = "distance" in body.model_fields_set
    data = _svc.update_checkpoint(
        pid,
        rid,
        cid,
        cp_type=body.type,
        distance=body.distance,
        distance_set=distance_set,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="checkpoint not found")
    return JSONResponse(data)


@router.delete("/plans/{plan_id}/races/{race_id}/checkpoints/{checkpoint_id}", status_code=204)
async def delete_checkpoint(
    plan_id: str,
    race_id: str,
    checkpoint_id: str,
    user: User = Depends(resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    rid = _parse_race_id(race_id)
    cid = _parse_checkpoint_id(checkpoint_id)

    deleted = _svc.delete_checkpoint(pid, rid, cid)
    if not deleted:
        raise HTTPException(status_code=404, detail="checkpoint not found")
    return Response(status_code=204)


# ── Projection endpoint ───────────────────────────────────────────────────────

_DEFAULT_PROJECTION_DAYS = 90


class PlanSuggestionsRequest(BaseModel):
    # Monday of the week to suggest for; default (omitted) is the CURRENT week.
    week_start: Optional[str] = None
    # weekday indices (0=Mon..6=Sun) the athlete wants forced to rest.
    rest_days: Optional[list[int]] = None
    strength_emphasis: Optional[str] = None  # "less" | "same" | "more"
    notes: Optional[str] = None
    # Two-rail flow (issue #1417): True returns rule-based schedule slots
    # instantly (no LLM) — habits from the athlete's last 3 weeks, generic
    # template only when there's no history; content per slot is generated
    # later via POST /plan/suggestions/session.
    skeleton: Optional[bool] = None
    # Skeleton only: exact number of strength slots to lay out (0-7);
    # omitted = however many the history shows.
    strength_sessions: Optional[int] = None


@router.get("/plan/draft")
def get_plan_draft(
    week_start: Optional[str] = _Query(None, alias="week_start"),
    user: User = Depends(resolve_user),
):
    """Serve the worker-generated plan draft for a week (pipeline v2)."""
    from backend.services.plan_draft import get_draft, pipeline_status
    from backend.utils.time import today_bangkok

    if week_start:
        try:
            ws = _date.fromisoformat(week_start)
        except ValueError:
            raise HTTPException(status_code=422, detail="week_start must be YYYY-MM-DD")
    else:
        today = today_bangkok()
        ws = today - _timedelta(days=today.weekday())

    db = _Session(_engine)
    try:
        draft = get_draft(db, user.id, ws)
        if draft is None:
            raise HTTPException(status_code=404, detail="no draft for this week")
        out = dict(draft)
        out["pipeline"] = pipeline_status()
        return JSONResponse(out)
    finally:
        db.close()


@router.get("/plan/pipeline")
def get_plan_pipeline(user: User = Depends(resolve_user)):
    """Rollout flag for plan pipeline v2 (legacy | skeleton_v2 | shadow)."""
    from backend.services.plan_draft import pipeline_status

    return JSONResponse(pipeline_status())


@router.get("/plan/draft-status")
def get_plan_draft_status(user: User = Depends(resolve_user)):
    """Badge/chip: whether a reviewable draft exists."""
    from backend.services.plan_draft import draft_status_for_badge, pipeline_enabled
    from backend.utils.time import today_bangkok

    if not pipeline_enabled():
        return JSONResponse({"ready": False, "pipeline_off": True})
    db = _Session(_engine)
    try:
        return JSONResponse(draft_status_for_badge(db, user.id, today=today_bangkok()))
    finally:
        db.close()


@router.post("/plan/draft/refresh")
def refresh_plan_draft(
    body: PlanSuggestionsRequest = Body(default=None),
    user: User = Depends(resolve_user),
):
    """Enqueue a plan_draft job (debounced). Does not wait for generation."""
    from backend.services.plan_draft import enqueue_plan_draft
    from backend.utils.time import today_bangkok

    ws = None
    if body is not None and body.week_start:
        try:
            ws = _date.fromisoformat(body.week_start)
        except ValueError:
            raise HTTPException(status_code=422, detail="week_start must be YYYY-MM-DD")
    if ws is None:
        today = today_bangkok()
        ws = today - _timedelta(days=today.weekday())
    job_id = enqueue_plan_draft(user.id, ws, enqueued_by="web")
    return JSONResponse({"job_id": job_id, "week_start": ws.isoformat()}, status_code=202)


class PlanDraftApplyRequest(BaseModel):
    week_start: Optional[str] = None


class PlanDraftSlotPatch(BaseModel):
    week_start: Optional[str] = None
    day_offset: int
    workout_type: Optional[str] = None
    target_tss: Optional[float] = None
    duration_minutes: Optional[int] = None
    intent: Optional[str] = None
    notes: Optional[str] = None
    blocks: Optional[list] = None
    exercises: Optional[list] = None
    remove: Optional[bool] = None


@router.post("/plan/draft/apply")
def apply_plan_draft(
    body: Optional[PlanDraftApplyRequest] = Body(default=None),
    user: User = Depends(resolve_user),
):
    """Apply draft → planned_sessions for open/future days; mark draft applied."""
    from backend.services.plan_draft import apply_draft
    from backend.utils.time import today_bangkok

    ws = None
    if body is not None and body.week_start:
        try:
            ws = _date.fromisoformat(body.week_start)
        except ValueError:
            raise HTTPException(status_code=422, detail="week_start must be YYYY-MM-DD")
    if ws is None:
        today = today_bangkok()
        ws = today - _timedelta(days=today.weekday())

    db = _Session(_engine)
    try:
        result = apply_draft(db, user.id, ws, today=today_bangkok())
        if not result.get("ok") and result.get("error") == "no_draft":
            raise HTTPException(status_code=404, detail="no draft for this week")
        db.commit()
        return JSONResponse(result)
    finally:
        db.close()


class PlanDraftApplySlotRequest(BaseModel):
    week_start: Optional[str] = None
    slot_id: Optional[str] = None
    day_offset: Optional[int] = None


@router.post("/plan/draft/apply-slot")
def apply_plan_draft_slot(
    body: PlanDraftApplySlotRequest,
    user: User = Depends(resolve_user),
):
    """Apply one draft slot → planned_session; leave the rest of the draft open."""
    from backend.services.plan_draft import apply_draft_slot
    from backend.utils.time import today_bangkok

    if not body.slot_id and body.day_offset is None:
        raise HTTPException(status_code=422, detail="slot_id or day_offset required")
    ws = _parse_week_start(body.week_start)
    db = _Session(_engine)
    try:
        result = apply_draft_slot(
            db, user.id, ws,
            slot_id=body.slot_id,
            day_offset=body.day_offset,
            today=today_bangkok(),
        )
        code = result.get("status_code") or 200
        if not result.get("ok"):
            db.rollback()
            raise HTTPException(status_code=code, detail=result)
        db.commit()
        return JSONResponse(result)
    finally:
        db.close()


class PlanDraftRegenRequest(BaseModel):
    week_start: Optional[str] = None
    slot_id: str
    draft_version: Optional[str] = None


@router.post("/plan/draft/ops/regen")
def draft_op_regen(
    body: PlanDraftRegenRequest,
    user: User = Depends(resolve_user),
):
    """Enqueue async content generation for one draft slot (Generate details)."""
    from backend.services.plan_draft import request_slot_regen

    if not body.slot_id:
        raise HTTPException(status_code=422, detail="slot_id required")
    ws = _parse_week_start(body.week_start)
    db = _Session(_engine)
    try:
        result = request_slot_regen(
            db, user.id, ws,
            slot_id=body.slot_id,
            draft_version=body.draft_version,
        )
        code = result.get("status_code") or 202
        if not result.get("ok"):
            db.rollback()
            raise HTTPException(status_code=code if code >= 400 else 400, detail=result)
        db.commit()
        return JSONResponse(result, status_code=202)
    finally:
        db.close()


@router.patch("/plan/draft/slot")
def patch_plan_draft_slot(
    body: PlanDraftSlotPatch,
    user: User = Depends(resolve_user),
):
    """Edit or remove one draft slot (stamps source=user)."""
    from backend.services.plan_draft import update_draft_slot
    from backend.utils.time import today_bangkok

    if body.day_offset < 0 or body.day_offset > 6:
        raise HTTPException(status_code=422, detail="day_offset must be 0..6")
    ws = None
    if body.week_start:
        try:
            ws = _date.fromisoformat(body.week_start)
        except ValueError:
            raise HTTPException(status_code=422, detail="week_start must be YYYY-MM-DD")
    if ws is None:
        today = today_bangkok()
        ws = today - _timedelta(days=today.weekday())

    patch = None if body.remove else {
        "workout_type": body.workout_type,
        "target_tss": body.target_tss,
        "duration_minutes": body.duration_minutes,
        "intent": body.intent,
        "notes": body.notes,
        "blocks": body.blocks,
        "exercises": body.exercises,
    }
    db = _Session(_engine)
    try:
        draft = update_draft_slot(
            db, user.id, ws, body.day_offset,
            patch=patch, remove=bool(body.remove),
        )
        if draft is None:
            raise HTTPException(status_code=404, detail="no draft for this week")
        db.commit()
        return JSONResponse(draft)
    finally:
        db.close()


class PlanDraftOpBody(BaseModel):
    week_start: Optional[str] = None
    draft_version: Optional[str] = None
    confirm_warnings: Optional[bool] = False
    inline: Optional[bool] = True
    background: Optional[bool] = False
    # move
    slot_id: Optional[str] = None
    to_day: Optional[int] = None
    # swap
    day_a: Optional[int] = None
    day_b: Optional[int] = None
    # remove
    mode: Optional[str] = None  # drop | redistribute
    # add
    day: Optional[int] = None
    kind: Optional[str] = None
    custom: Optional[dict] = None


def _parse_week_start(raw: Optional[str]):
    from backend.utils.time import today_bangkok

    if raw:
        try:
            return _date.fromisoformat(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail="week_start must be YYYY-MM-DD")
    today = today_bangkok()
    return today - _timedelta(days=today.weekday())


def _run_draft_op(op: str, body: PlanDraftOpBody, user: User):
    from backend.services.plan_draft import apply_structure_op, ensure_draft_shell

    ws = _parse_week_start(body.week_start if body else None)
    kwargs = {}
    if op == "move" or op == "preview_move":
        if not body.slot_id or body.to_day is None:
            raise HTTPException(status_code=422, detail="slot_id and to_day required")
        kwargs = {"slot_id": body.slot_id, "to_day": body.to_day}
    elif op == "swap":
        if body.day_a is None or body.day_b is None:
            raise HTTPException(status_code=422, detail="day_a and day_b required")
        kwargs = {"day_a": body.day_a, "day_b": body.day_b}
    elif op == "remove":
        if not body.slot_id:
            raise HTTPException(status_code=422, detail="slot_id required")
        kwargs = {"slot_id": body.slot_id, "mode": body.mode or "drop"}
    elif op == "add":
        if body.day is None:
            raise HTTPException(status_code=422, detail="day required")
        kwargs = {"day": body.day, "kind": body.kind or "easy_run", "custom": body.custom}

    db = _Session(_engine)
    try:
        if op == "add":
            ensure_draft_shell(db, user.id, ws)
        # Structure adds never sync-LLM; Generate details uses /ops/regen.
        use_inline = False if op == "add" else (body.inline is not False)
        result = apply_structure_op(
            db, user.id, ws,
            op=op,
            draft_version=body.draft_version,
            confirm_warnings=bool(body.confirm_warnings),
            inline=use_inline,
            background=bool(body.background),
            **kwargs,
        )
        code = result.get("status_code") or 200
        if not result.get("ok") and code >= 400:
            db.rollback()
            raise HTTPException(status_code=code, detail=result)
        db.commit()
        return JSONResponse(result, status_code=200 if result.get("ok") else code)
    finally:
        db.close()


@router.post("/plan/draft/ops/move")
def draft_op_move(body: PlanDraftOpBody, user: User = Depends(resolve_user)):
    return _run_draft_op("move", body, user)


@router.post("/plan/draft/ops/swap")
def draft_op_swap(body: PlanDraftOpBody, user: User = Depends(resolve_user)):
    return _run_draft_op("swap", body, user)


@router.post("/plan/draft/ops/remove")
def draft_op_remove(body: PlanDraftOpBody, user: User = Depends(resolve_user)):
    return _run_draft_op("remove", body, user)


@router.post("/plan/draft/ops/add")
def draft_op_add(body: PlanDraftOpBody, user: User = Depends(resolve_user)):
    return _run_draft_op("add", body, user)


@router.post("/plan/draft/ops/preview-move")
def draft_op_preview_move(body: PlanDraftOpBody, user: User = Depends(resolve_user)):
    return _run_draft_op("preview_move", body, user)


@router.post("/plan/draft/replan-remaining")
def draft_replan_remaining(
    body: PlanDraftApplyRequest = Body(default=None),
    user: User = Depends(resolve_user),
):
    """Compute replan budget from matched actual TSS + partial skeleton for open days."""
    from backend.services.plan_draft import replan_remaining_budget, upsert_draft, enqueue_plan_draft
    from backend.services.plan_skeleton_ops import ensure_slot_ids, sync_slots_from_sessions
    from backend.services.plan_slot import template_content_for_slot, stamp_session

    ws = _parse_week_start(body.week_start if body else None)
    db = _Session(_engine)
    try:
        plan = replan_remaining_budget(db, user.id, ws)
        sk = plan["skeleton"]
        sessions = []
        for slot in sk["slots"]:
            if slot.get("locked"):
                continue
            if (slot.get("workout_type") or "") == "rest":
                content = {"intent": "Rest", "source": "template"}
            else:
                content = template_content_for_slot(slot)
            sess = stamp_session(slot, content)
            sessions.append(sess)
        sessions = ensure_slot_ids(sessions)
        payload = {
            "week_start": ws.isoformat(),
            "budget": plan["budget"],
            "slots": sync_slots_from_sessions(sessions),
            "sessions": sessions,
            "sanity_errors": [],
            "facts_signature": "",
            "replan": True,
            "matched_actual_tss": plan["matched_actual_tss"],
            "open_offsets": plan["open_offsets"],
            "version": 1,
            "notify_pending": True,
        }
        # Fill facts_signature properly
        from backend.services.plan_draft import facts_signature_for_draft
        from backend.services.plan_prefs_accessor import get_plan_prefs as _gpp
        from backend.services.plan_suggestions import assemble_facts
        prefs = _gpp(db, user.id)
        facts = assemble_facts(
            str(user.id), db, week_start=ws,
            preferred_rest_days=prefs["preferred_rest_days"],
            strength_emphasis=prefs["strength_emphasis"],
            notes=prefs["notes"],
        )
        payload["facts_signature"] = facts_signature_for_draft(facts)
        upsert_draft(db, user.id, ws, payload, status="fresh")
        # Enqueue content fill for non-rest / non-stretch
        need = [
            s["slot_id"] for s in sessions
            if s.get("workout_type") not in ("rest", "stretch") and s.get("source") != "user"
        ]
        job_id = enqueue_plan_draft(user.id, ws, slot_ids=need, enqueued_by="web") if need else None
        db.commit()
        return JSONResponse({
            "ok": True,
            "budget": plan["budget"],
            "matched_actual_tss": plan["matched_actual_tss"],
            "open_offsets": plan["open_offsets"],
            "job_id": job_id,
            "week_start": ws.isoformat(),
        }, status_code=202)
    finally:
        db.close()


@router.post("/plan/suggestions")
def get_plan_suggestions(
    body: PlanSuggestionsRequest = Body(default=None),
    user: User = Depends(resolve_user),
):
    """Return LLM-proposed training suggestions for the OPEN remainder of a week,
    with facts and source tag.

    Only day_offsets not already covered by a logged workout or an existing
    planned session — and not before today, when the target week contains
    today — are eligible; see assemble_facts. Body fields are all optional and
    scope/steer the suggestions: `week_start` (default: current week's
    Monday), `rest_days` (weekday indices the athlete wants off),
    `strength_emphasis` ("less"|"same"|"more"), `notes` (free text, coach-style
    context — e.g. "easing back after a cold").

    Response shape: {facts: {...}, suggestions: [{day_offset, workout_type,
    target_tss, duration_minutes, intent}], source: "llm"|"fallback",
    attempts: int, orch: "single"}. ``orch`` is a constant kept for response-
    shape stability — the PLAN_ORCH switch and its alternative implementations
    were deleted once the single-shot path won.
    """
    from backend.services.plan_suggestions import get_suggestions as _get_suggestions

    week_start = None
    if body is not None and body.week_start:
        try:
            week_start = _date.fromisoformat(body.week_start)
        except ValueError:
            raise HTTPException(status_code=422, detail="week_start must be YYYY-MM-DD")

    rest_days = None
    if body is not None and body.rest_days is not None:
        rest_days = [d for d in body.rest_days if isinstance(d, int) and 0 <= d <= 6]

    strength_emphasis = body.strength_emphasis if body is not None else None
    notes = body.notes if body is not None else None

    strength_sessions = body.strength_sessions if body is not None else None
    if strength_sessions is not None and not (0 <= strength_sessions <= 7):
        raise HTTPException(status_code=422, detail="strength_sessions must be between 0 and 7")

    result = _get_suggestions(
        str(user.id),
        week_start=week_start,
        preferred_rest_days=rest_days,
        strength_emphasis=strength_emphasis,
        notes=notes,
        skeleton=bool(body.skeleton) if body is not None else False,
        strength_sessions=strength_sessions,
    )
    return JSONResponse(result)


class SingleSessionRequest(BaseModel):
    # ISO date (YYYY-MM-DD) the session is FOR — its day_offset is derived
    # from this date's own week (Monday=0), not the caller's current view.
    date: str
    workout_type: Optional[str] = None  # "run"|"strength"|"plyo"|"rest"; hint only
    note: Optional[str] = None
    # Present only when REFINING an already-suggested session (same shape as
    # a suggestions[] item) — omitted when creating a fresh one from scratch.
    current_session: Optional[dict] = None
    # Two-rail flow (issue #1417): the schedule rail's slot budget. When set,
    # generate_single_session takes the plan_slot.py content-only path — the
    # LLM never emits these numbers, Python stamps them onto the response —
    # the athlete owns the schedule; the LLM only fills the content.
    target_tss: Optional[float] = None
    duration_minutes: Optional[int] = None
    # Optional slot flavor (run: easy/long/intervals/tempo; strength:
    # upper/lower/full/light — see plan_suggestions.SESSION_SUBTYPES).
    subtype: Optional[str] = None


@router.post("/plan/suggestions/session")
def generate_plan_session(
    body: SingleSessionRequest,
    user: User = Depends(resolve_user),
):
    """Generate or refine ONE session for a single day via the LLM — shared by
    the Add-session "Ask AI" mode (fresh session from date/type/note) and a
    suggestion row's "Refine" action (revise an existing suggestion with a
    note, e.g. "change strength focus" or "faster intervals").

    No deterministic-template fallback here (unlike the whole-week endpoint
    above) — a single templated session isn't a meaningful substitute for a
    specific athlete request. Returns 422 if the LLM is unavailable or
    couldn't produce a valid session after 2 tries; the caller keeps
    whatever it had before.

    Response: {"session": {day_offset, workout_type, target_tss,
    duration_minutes, intent, notes, exercises, blocks}}.
    """
    from backend.services.plan_suggestions import generate_single_session as _generate_single_session

    try:
        target_date = _date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")

    week_start = target_date - _timedelta(days=target_date.weekday())
    day_offset = (target_date - week_start).days

    if body.workout_type is not None and body.workout_type not in ("run", "strength", "plyo", "stretch", "rest"):
        raise HTTPException(status_code=422, detail="workout_type must be run, strength, plyo, stretch, or rest")

    if body.target_tss is not None and not (0 <= body.target_tss <= 400):
        raise HTTPException(status_code=422, detail="target_tss must be between 0 and 400")
    if body.duration_minutes is not None and not (0 <= body.duration_minutes <= 600):
        raise HTTPException(status_code=422, detail="duration_minutes must be between 0 and 600")
    if body.subtype is not None:
        from backend.services.plan_suggestions import (
            SESSION_SUBTYPES as _SUBTYPES,
            coerce_ui_subtype,
        )
        ui_sub = coerce_ui_subtype(body.workout_type, body.subtype)
        valid = _SUBTYPES.get(body.workout_type or "", {})
        if ui_sub is None or ui_sub not in valid:
            raise HTTPException(
                status_code=422,
                detail="subtype must be one of: " + ", ".join(sorted(valid)) if valid
                else f"workout_type {body.workout_type!r} has no subtypes",
            )
        body.subtype = ui_sub

    session = _generate_single_session(
        str(user.id),
        day_offset,
        (body.note or "").strip(),
        workout_type=body.workout_type,
        current_session=body.current_session,
        week_start=week_start,
        target_tss=body.target_tss,
        duration_minutes=body.duration_minutes,
        subtype=body.subtype,
    )
    if session is None:
        raise HTTPException(status_code=422, detail="Could not generate a session for this request — try again or adjust the note.")
    return JSONResponse({"session": session})


@router.get("/plans/{plan_id}/projection")
async def get_plan_projection(
    plan_id: str,
    user: User = Depends(resolve_user),
):
    """Return CTL/ATL/TSB projection, per-race estimates, and fitness band for a plan."""
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)

    with _Session(_engine) as db:
        prefs = (
            db.query(_UserPreferences)
            .filter(_UserPreferences.user_id == user.id)
            .first()
        )
        thresholds = (
            {"threshold_pace_seconds_per_km": prefs.threshold_pace_seconds_per_km}
            if prefs and prefs.threshold_pace_seconds_per_km is not None
            else None
        )

    races = _svc.list_races(pid)

    # Athlete's current VDOT-band Endurance score (same scale as Performance),
    # so the CTL ceiling stays sane relative to what's demonstrated now.
    _current_score = None
    try:
        from backend.main import _athlete_scores_as_of as _scores_as_of
        with _Session(_engine) as _sdb:
            _cur = _scores_as_of(_sdb, user.id, _today_bangkok())
        _current_score = _cur.get("endurance")
    except Exception:
        _current_score = None

    load_state = _current_load(str(user.id))
    start_date: _date = load_state["date"]
    start_ctl: float = load_state["ctl"]
    start_atl: float = load_state["atl"]

    if races:
        race_dates = [_date.fromisoformat(r["date"]) for r in races]
        last_race_date = max(race_dates)
        n_days = max((last_race_date - start_date).days, 1)
    else:
        n_days = _DEFAULT_PROJECTION_DAYS

    window_start = start_date - _timedelta(days=27)
    recent_series = _daily_tss_series(str(user.id), window_start, start_date)
    avg_load = (
        sum(tss for _, tss in recent_series) / len(recent_series)
        if recent_series else 0.0
    )
    planned_load = [avg_load] * n_days

    race_inputs = [
        {
            "date": r["date"],
            "distance_km": r.get("distance"),
            "name": r.get("name") or "",
            "race_id": r.get("id"),
        }
        for r in races
    ]

    # Find the most recent past B race with an actual result (issue #1162).
    # This re-anchors forward projections to the expressed race-day fitness.
    # Querying at request time means delete/edit propagates naturally (AC4).
    today = _today_bangkok()
    b_race_result = None
    stimulus_history = []
    with _Session(_engine) as db:
        b_race_rows = (
            db.query(_Race)
            .filter(
                _Race.user_id == user.id,
                _Race.priority == "B",
                _Race.actual_time_seconds.isnot(None),
                _Race.race_date <= today,
            )
            .order_by(_Race.race_date.desc())
            .first()
        )
        if b_race_rows is not None:
            b_race_result = {
                "race_date": b_race_rows.race_date,
                "actual_time_seconds": b_race_rows.actual_time_seconds,
                "distance_km": float(b_race_rows.distance_km),
            }

        # Fetch per-user stimulus history from economy_ceiling_snapshots so the
        # economy ceiling bonus is reflected in the projected score ceiling.
        snap_rows = (
            db.query(_EconomyCeilingSnapshot)
            .filter(_EconomyCeilingSnapshot.user_id == user.id)
            .order_by(_EconomyCeilingSnapshot.snapshot_date.asc())
            .all()
        )
        stimulus_history = [
            (row.snapshot_date, row.economy_stimulus) for row in snap_rows
        ]

    from backend.services.body_modifier import get_body_modifier_for_user as _get_bm_plan
    _bm_plan = _get_bm_plan(user.id)

    payload = _proj.build_plan_projection_payload(
        start_ctl=start_ctl,
        start_atl=start_atl,
        start_date=start_date,
        planned_load=planned_load,
        races=race_inputs,
        thresholds=thresholds,
        b_race_result=b_race_result,
        current_score=_current_score,
        stimulus_history=stimulus_history,
        reference_date=today,
        body_modifier=_bm_plan,
    )

    # Persist a forecast snapshot for forecast-vs-actual accuracy (issue #1362).
    # Throttled to once per day: first write wins, same-day recomputes are no-ops.
    try:
        from backend.services.prediction_snapshot import (
            build_snapshot_payload as _build_snap,
            maybe_write_prediction_snapshot as _write_snap,
        )
        snap_payload = _build_snap(
            race_projections=payload.get("races", []),
            ctl_series=payload.get("ctl", []),
            start_date=start_date,
            races_meta=races,
            formula_version="1",
        )
        _write_snap(user.id, today, snap_payload)
    except Exception:
        pass  # snapshot failures must never break the projection response

    return JSONResponse(payload)


@router.get("/projection/snapshots")
async def get_projection_snapshots(
    from_date: Optional[str] = _Query(default=None, alias="from"),
    to_date: Optional[str] = _Query(default=None, alias="to"),
    user: User = Depends(resolve_user),
):
    """Return prediction snapshots for the authenticated user.

    Query params ``from`` and ``to`` (ISO YYYY-MM-DD) bound the date range.
    Response: list of {snapshot_date, payload, created_at}, ordered by date.
    """
    from backend.services.prediction_snapshot import list_snapshots as _list_snaps

    from_d = None
    to_d = None
    if from_date is not None:
        try:
            from_d = _date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=422, detail={"field": "from", "error": "must be YYYY-MM-DD"})
    if to_date is not None:
        try:
            to_d = _date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=422, detail={"field": "to", "error": "must be YYYY-MM-DD"})

    rows = _list_snaps(user.id, from_date=from_d, to_date=to_d)
    return JSONResponse(rows)
