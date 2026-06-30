"""sessions.py — CRUD routes for /api/strength-sessions and /api/plyo-sessions.

Each row represents one exercise entry within a session; the UI groups entries
by session_date to form a "session" view with multiple exercises.
"""
from __future__ import annotations

import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as _Session

from backend.auth import COOKIE_NAME, get_current_user
from backend.db import engine as _engine
from backend.models import PlyoSession as _PlyoSession, StrengthSession as _StrengthSession, User

router = APIRouter()

_PLYO_PHASES = ("intro", "build", "maintain")
_LOAD_UNITS = ("kg", "lbs")


# ── Auth dependency ───────────────────────────────────────────────────────────

async def _resolve_user(request: Request) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return await get_current_user(request)
    raise HTTPException(status_code=401, detail="Not authenticated")


# ── ID parsing ────────────────────────────────────────────────────────────────

def _parse_id(value: str, field: str = "id") -> _uuid.UUID:
    try:
        return _uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"invalid {field}")


# ── Serializers ───────────────────────────────────────────────────────────────

def _strength_dict(s: _StrengthSession) -> dict:
    return {
        "id": str(s.id),
        "session_date": str(s.session_date),
        "exercise_name": s.exercise_name,
        "sets": s.sets,
        "reps": s.reps,
        "load": float(s.load) if s.load is not None else None,
        "load_unit": s.load_unit,
        "session_rpe": s.session_rpe,
        "duration_minutes": s.duration_minutes,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _plyo_dict(p: _PlyoSession) -> dict:
    return {
        "id": str(p.id),
        "session_date": str(p.session_date),
        "exercise_name": p.exercise_name,
        "foot_contacts": p.foot_contacts,
        "plyo_phase": p.plyo_phase,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ── Request bodies ────────────────────────────────────────────────────────────

class _StrengthCreateBody(BaseModel):
    session_date: str
    exercise_name: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    load: Optional[float] = None
    load_unit: Optional[str] = None
    session_rpe: Optional[int] = None
    duration_minutes: Optional[int] = None


class _StrengthPatchBody(BaseModel):
    session_date: Optional[str] = None
    exercise_name: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[int] = None
    load: Optional[float] = None
    load_unit: Optional[str] = None
    session_rpe: Optional[int] = None
    duration_minutes: Optional[int] = None


class _PlyoCreateBody(BaseModel):
    session_date: str
    exercise_name: str
    foot_contacts: int
    plyo_phase: str


class _PlyoPatchBody(BaseModel):
    session_date: Optional[str] = None
    exercise_name: Optional[str] = None
    foot_contacts: Optional[int] = None
    plyo_phase: Optional[str] = None


# ── Validation helpers ────────────────────────────────────────────────────────

def _validate_session_date(date_str: str):
    from datetime import date
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail={"field": "session_date", "error": "must be YYYY-MM-DD"},
        )


def _validate_load_unit(unit: Optional[str]) -> Optional[str]:
    if unit is not None and unit not in _LOAD_UNITS:
        raise HTTPException(
            status_code=422,
            detail={"field": "load_unit", "error": f"must be one of: {', '.join(_LOAD_UNITS)}"},
        )
    return unit


def _validate_plyo_phase(phase: str) -> str:
    if phase not in _PLYO_PHASES:
        raise HTTPException(
            status_code=422,
            detail={"field": "plyo_phase", "error": f"must be one of: {', '.join(_PLYO_PHASES)}"},
        )
    return phase


def _validate_exercise_name(name: Optional[str]) -> str:
    if not name or not name.strip():
        raise HTTPException(
            status_code=422,
            detail={"field": "exercise_name", "error": "exercise_name is required"},
        )
    return name.strip()


# ── Strength session endpoints ────────────────────────────────────────────────

@router.get("/api/strength-sessions")
async def list_strength_sessions(user: User = Depends(_resolve_user)):
    with _Session(_engine) as db:
        rows = (
            db.query(_StrengthSession)
            .filter(_StrengthSession.user_id == user.id)
            .order_by(_StrengthSession.session_date.desc())
            .all()
        )
        return JSONResponse([_strength_dict(r) for r in rows])


@router.post("/api/strength-sessions", status_code=201)
async def create_strength_session(
    body: _StrengthCreateBody,
    user: User = Depends(_resolve_user),
):
    session_date = _validate_session_date(body.session_date)
    exercise_name = _validate_exercise_name(body.exercise_name)
    _validate_load_unit(body.load_unit)

    with _Session(_engine) as db:
        row = _StrengthSession(
            user_id=user.id,
            session_date=session_date,
            exercise_name=exercise_name,
            sets=body.sets,
            reps=body.reps,
            load=body.load,
            load_unit=body.load_unit,
            session_rpe=body.session_rpe,
            duration_minutes=body.duration_minutes,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return JSONResponse(status_code=201, content=_strength_dict(row))


@router.put("/api/strength-sessions/{entry_id}")
async def update_strength_session(
    entry_id: str,
    body: _StrengthPatchBody,
    user: User = Depends(_resolve_user),
):
    eid = _parse_id(entry_id)
    with _Session(_engine) as db:
        row = db.get(_StrengthSession, eid)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="entry not found")

        if body.session_date is not None:
            row.session_date = _validate_session_date(body.session_date)
        if body.exercise_name is not None:
            row.exercise_name = _validate_exercise_name(body.exercise_name)
        if "sets" in body.model_fields_set:
            row.sets = body.sets
        if "reps" in body.model_fields_set:
            row.reps = body.reps
        if "load" in body.model_fields_set:
            row.load = body.load
        if body.load_unit is not None:
            _validate_load_unit(body.load_unit)
            row.load_unit = body.load_unit
        if "session_rpe" in body.model_fields_set:
            row.session_rpe = body.session_rpe
        if "duration_minutes" in body.model_fields_set:
            row.duration_minutes = body.duration_minutes

        db.commit()
        db.refresh(row)
        return JSONResponse(_strength_dict(row))


@router.delete("/api/strength-sessions/{entry_id}", status_code=204)
async def delete_strength_session(
    entry_id: str,
    user: User = Depends(_resolve_user),
):
    eid = _parse_id(entry_id)
    with _Session(_engine) as db:
        row = db.get(_StrengthSession, eid)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="entry not found")
        db.delete(row)
        db.commit()
    return Response(status_code=204)


# ── Plyo session endpoints ────────────────────────────────────────────────────

@router.get("/api/plyo-sessions")
async def list_plyo_sessions(user: User = Depends(_resolve_user)):
    with _Session(_engine) as db:
        rows = (
            db.query(_PlyoSession)
            .filter(_PlyoSession.user_id == user.id)
            .order_by(_PlyoSession.session_date.desc())
            .all()
        )
        return JSONResponse([_plyo_dict(r) for r in rows])


@router.post("/api/plyo-sessions", status_code=201)
async def create_plyo_session(
    body: _PlyoCreateBody,
    user: User = Depends(_resolve_user),
):
    session_date = _validate_session_date(body.session_date)
    exercise_name = _validate_exercise_name(body.exercise_name)
    _validate_plyo_phase(body.plyo_phase)

    with _Session(_engine) as db:
        row = _PlyoSession(
            user_id=user.id,
            session_date=session_date,
            exercise_name=exercise_name,
            foot_contacts=body.foot_contacts,
            plyo_phase=body.plyo_phase,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return JSONResponse(status_code=201, content=_plyo_dict(row))


@router.put("/api/plyo-sessions/{entry_id}")
async def update_plyo_session(
    entry_id: str,
    body: _PlyoPatchBody,
    user: User = Depends(_resolve_user),
):
    eid = _parse_id(entry_id)
    with _Session(_engine) as db:
        row = db.get(_PlyoSession, eid)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="entry not found")

        if body.session_date is not None:
            row.session_date = _validate_session_date(body.session_date)
        if body.exercise_name is not None:
            row.exercise_name = _validate_exercise_name(body.exercise_name)
        if "foot_contacts" in body.model_fields_set:
            row.foot_contacts = body.foot_contacts
        if body.plyo_phase is not None:
            _validate_plyo_phase(body.plyo_phase)
            row.plyo_phase = body.plyo_phase

        db.commit()
        db.refresh(row)
        return JSONResponse(_plyo_dict(row))


@router.delete("/api/plyo-sessions/{entry_id}", status_code=204)
async def delete_plyo_session(
    entry_id: str,
    user: User = Depends(_resolve_user),
):
    eid = _parse_id(entry_id)
    with _Session(_engine) as db:
        row = db.get(_PlyoSession, eid)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="entry not found")
        db.delete(row)
        db.commit()
    return Response(status_code=204)
