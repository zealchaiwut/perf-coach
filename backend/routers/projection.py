"""projection.py — routes for /plans/{plan_id}/races, checkpoints, and projection.

Route paths, the ``training_plans`` table, and the ``TrainingPlan`` model are
UNCHANGED — this file was renamed from ``plan.py`` (feature/performance-tab-rework).
All business logic and DB interaction is delegated to projection_service or the
projection payload module; no domain logic lives in this router.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date as _date, timedelta as _timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
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
    attempts: int, orch: "single"|"plain"|"langgraph"|"pydantic_ai"}. The
    orchestrator is chosen by the PLAN_ORCH env var (default "single"); switch
    it and re-request to A/B the three implementations on the same facts.
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

    result = _get_suggestions(
        str(user.id),
        week_start=week_start,
        preferred_rest_days=rest_days,
        strength_emphasis=strength_emphasis,
        notes=notes,
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

    if body.workout_type is not None and body.workout_type not in ("run", "strength", "plyo", "rest"):
        raise HTTPException(status_code=422, detail="workout_type must be run, strength, plyo, or rest")

    session = _generate_single_session(
        str(user.id),
        day_offset,
        (body.note or "").strip(),
        workout_type=body.workout_type,
        current_session=body.current_session,
        week_start=week_start,
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
            _cur = _scores_as_of(_sdb, user.id, _date.today())
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
        }
        for r in races
    ]

    # Find the most recent past B race with an actual result (issue #1162).
    # This re-anchors forward projections to the expressed race-day fitness.
    # Querying at request time means delete/edit propagates naturally (AC4).
    today = _date.today()
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
    return JSONResponse(payload)
