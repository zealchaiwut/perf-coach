"""strength_sessions.py — CRUD routes for /api/strength-sessions and /api/plyo-sessions (issue #1144).

All DB work is delegated to strength_sessions_service; no raw ORM calls live here.
"""
from __future__ import annotations

import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, validator

from backend.auth import resolve_user
from backend.services import strength_sessions_service as _svc

router = APIRouter()

_VALID_PLYO_PHASES = ("intro", "build", "maintain")


def _parse_session_id(session_id: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(session_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid session id")


# ── Strength request bodies ────────────────────────────────────────────────────

class _StrengthCreateBody(BaseModel):
    session_date: str
    exercise_name: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    load: Optional[float] = None
    load_unit: Optional[str] = None
    session_rpe: Optional[int] = None
    duration_minutes: Optional[int] = None

    @validator("session_date")
    def _validate_date(cls, v):  # noqa: N805
        try:
            from datetime import date
            date.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError("session_date must be ISO format YYYY-MM-DD")
        return v

    @validator("sets")
    def _sets_positive(cls, v):  # noqa: N805
        if v is not None and v <= 0:
            raise ValueError("sets must be positive")
        return v

    @validator("reps")
    def _reps_positive(cls, v):  # noqa: N805
        if v is not None and v <= 0:
            raise ValueError("reps must be positive")
        return v

    @validator("load")
    def _load_non_negative(cls, v):  # noqa: N805
        if v is not None and v < 0:
            raise ValueError("load must be non-negative")
        return v

    @validator("session_rpe")
    def _rpe_range(cls, v):  # noqa: N805
        if v is not None and not (1 <= v <= 10):
            raise ValueError("session_rpe must be between 1 and 10")
        return v

    @validator("duration_minutes")
    def _duration_positive(cls, v):  # noqa: N805
        if v is not None and v <= 0:
            raise ValueError("duration_minutes must be positive")
        return v


class _StrengthPatchBody(BaseModel):
    session_date: Optional[str] = None
    exercise_name: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[int] = None
    load: Optional[float] = None
    load_unit: Optional[str] = None
    session_rpe: Optional[int] = None
    duration_minutes: Optional[int] = None

    @validator("session_date")
    def _validate_date(cls, v):  # noqa: N805
        if v is not None:
            try:
                from datetime import date
                date.fromisoformat(v)
            except (ValueError, TypeError):
                raise ValueError("session_date must be ISO format YYYY-MM-DD")
        return v

    @validator("sets")
    def _sets_positive(cls, v):  # noqa: N805
        if v is not None and v <= 0:
            raise ValueError("sets must be positive")
        return v

    @validator("reps")
    def _reps_positive(cls, v):  # noqa: N805
        if v is not None and v <= 0:
            raise ValueError("reps must be positive")
        return v

    @validator("load")
    def _load_non_negative(cls, v):  # noqa: N805
        if v is not None and v < 0:
            raise ValueError("load must be non-negative")
        return v

    @validator("session_rpe")
    def _rpe_range(cls, v):  # noqa: N805
        if v is not None and not (1 <= v <= 10):
            raise ValueError("session_rpe must be between 1 and 10")
        return v

    @validator("duration_minutes")
    def _duration_positive(cls, v):  # noqa: N805
        if v is not None and v <= 0:
            raise ValueError("duration_minutes must be positive")
        return v


# ── Plyo request bodies ────────────────────────────────────────────────────────

class _PlyoCreateBody(BaseModel):
    session_date: str
    exercise_name: str
    foot_contacts: int
    plyo_phase: str

    @validator("session_date")
    def _validate_date(cls, v):  # noqa: N805
        try:
            from datetime import date
            date.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError("session_date must be ISO format YYYY-MM-DD")
        return v

    @validator("foot_contacts")
    def _foot_contacts_non_negative(cls, v):  # noqa: N805
        if v < 0:
            raise ValueError("foot_contacts must be non-negative")
        return v

    @validator("plyo_phase")
    def _phase_valid(cls, v):  # noqa: N805
        if v not in _VALID_PLYO_PHASES:
            raise ValueError(f"plyo_phase must be one of {_VALID_PLYO_PHASES}")
        return v


class _StrengthBatchBody(BaseModel):
    exercises: list[_StrengthCreateBody]

    @validator("exercises")
    def _not_empty(cls, v):  # noqa: N805
        if not v:
            raise ValueError("exercises must not be empty")
        return v


class _PlyoBatchBody(BaseModel):
    exercises: list[_PlyoCreateBody]

    @validator("exercises")
    def _not_empty(cls, v):  # noqa: N805
        if not v:
            raise ValueError("exercises must not be empty")
        return v


class _PlyoPatchBody(BaseModel):
    session_date: Optional[str] = None
    exercise_name: Optional[str] = None
    foot_contacts: Optional[int] = None
    plyo_phase: Optional[str] = None

    @validator("session_date")
    def _validate_date(cls, v):  # noqa: N805
        if v is not None:
            try:
                from datetime import date
                date.fromisoformat(v)
            except (ValueError, TypeError):
                raise ValueError("session_date must be ISO format YYYY-MM-DD")
        return v

    @validator("foot_contacts")
    def _foot_contacts_non_negative(cls, v):  # noqa: N805
        if v is not None and v < 0:
            raise ValueError("foot_contacts must be non-negative")
        return v

    @validator("plyo_phase")
    def _phase_valid(cls, v):  # noqa: N805
        if v is not None and v not in _VALID_PLYO_PHASES:
            raise ValueError(f"plyo_phase must be one of {_VALID_PLYO_PHASES}")
        return v


# ── Strength session endpoints ─────────────────────────────────────────────────

@router.post("/api/strength-sessions/batch", status_code=201)
async def create_strength_sessions_batch(body: _StrengthBatchBody, request: Request):
    user = await resolve_user(request)
    exercises = [ex.dict() for ex in body.exercises]
    result = _svc.create_strength_sessions_batch(user_id=user.id, exercises=exercises)
    return JSONResponse(result, status_code=201)


@router.get("/api/strength-sessions")
async def list_strength_sessions(request: Request):
    user = await resolve_user(request)
    sessions = _svc.list_strength_sessions(user_id=user.id)
    return JSONResponse(sessions)


@router.get("/api/strength-sessions/{session_id}")
async def get_strength_session(session_id: str, request: Request):
    user = await resolve_user(request)
    sid = _parse_session_id(session_id)
    result = _svc.get_strength_session(session_id=sid, user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="strength session not found")
    return JSONResponse(result)


@router.post("/api/strength-sessions", status_code=201)
async def create_strength_session(body: _StrengthCreateBody, request: Request):
    user = await resolve_user(request)
    result = _svc.create_strength_session(
        user_id=user.id,
        session_date=body.session_date,
        exercise_name=body.exercise_name,
        sets=body.sets,
        reps=body.reps,
        load=body.load,
        load_unit=body.load_unit,
        session_rpe=body.session_rpe,
        duration_minutes=body.duration_minutes,
    )
    return JSONResponse(result, status_code=201)


@router.patch("/api/strength-sessions/{session_id}")
async def update_strength_session(session_id: str, body: _StrengthPatchBody, request: Request):
    user = await resolve_user(request)
    sid = _parse_session_id(session_id)
    fields = body.dict(exclude_unset=True)
    result = _svc.update_strength_session(session_id=sid, user_id=user.id, fields=fields)
    if result is None:
        raise HTTPException(status_code=404, detail="strength session not found")
    return JSONResponse(result)


@router.delete("/api/strength-sessions/{session_id}", status_code=204)
async def delete_strength_session(session_id: str, request: Request):
    user = await resolve_user(request)
    sid = _parse_session_id(session_id)
    deleted = _svc.delete_strength_session(session_id=sid, user_id=user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="strength session not found")
    return Response(status_code=204)


# ── Plyo session endpoints ─────────────────────────────────────────────────────

@router.post("/api/plyo-sessions/batch", status_code=201)
async def create_plyo_sessions_batch(body: _PlyoBatchBody, request: Request):
    user = await resolve_user(request)
    exercises = [ex.dict() for ex in body.exercises]
    result = _svc.create_plyo_sessions_batch(user_id=user.id, exercises=exercises)
    return JSONResponse(result, status_code=201)


@router.get("/api/plyo-sessions")
async def list_plyo_sessions(request: Request):
    user = await resolve_user(request)
    sessions = _svc.list_plyo_sessions(user_id=user.id)
    return JSONResponse(sessions)


@router.get("/api/plyo-sessions/{session_id}")
async def get_plyo_session(session_id: str, request: Request):
    user = await resolve_user(request)
    sid = _parse_session_id(session_id)
    result = _svc.get_plyo_session(session_id=sid, user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="plyo session not found")
    return JSONResponse(result)


@router.post("/api/plyo-sessions", status_code=201)
async def create_plyo_session(body: _PlyoCreateBody, request: Request):
    user = await resolve_user(request)
    result = _svc.create_plyo_session(
        user_id=user.id,
        session_date=body.session_date,
        exercise_name=body.exercise_name,
        foot_contacts=body.foot_contacts,
        plyo_phase=body.plyo_phase,
    )
    return JSONResponse(result, status_code=201)


@router.patch("/api/plyo-sessions/{session_id}")
async def update_plyo_session(session_id: str, body: _PlyoPatchBody, request: Request):
    user = await resolve_user(request)
    sid = _parse_session_id(session_id)
    fields = body.dict(exclude_unset=True)
    result = _svc.update_plyo_session(session_id=sid, user_id=user.id, fields=fields)
    if result is None:
        raise HTTPException(status_code=404, detail="plyo session not found")
    return JSONResponse(result)


@router.delete("/api/plyo-sessions/{session_id}", status_code=204)
async def delete_plyo_session(session_id: str, request: Request):
    user = await resolve_user(request)
    sid = _parse_session_id(session_id)
    deleted = _svc.delete_plyo_session(session_id=sid, user_id=user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="plyo session not found")
    return Response(status_code=204)
