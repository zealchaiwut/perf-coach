"""plan.py — routes for /plans/{plan_id}/races and nested checkpoints (issue #1100).

All business logic and DB interaction is delegated to plan_service.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from backend.auth import COOKIE_NAME, get_current_user
from backend.models import User, RACE_TYPE_VALUES as _RACE_TYPE_VALUES
from backend.services import plan_service as _svc

router = APIRouter()


# ── Auth dependency ───────────────────────────────────────────────────────────

async def _resolve_user(request: Request) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return await get_current_user(request)
    raise HTTPException(status_code=401, detail="Not authenticated")


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
    if plan_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Request bodies ────────────────────────────────────────────────────────────

class _RaceCreateBody(BaseModel):
    date: str
    distance: float
    type: str
    name: Optional[str] = None
    goal_time_seconds: Optional[int] = None


class _RacePatchBody(BaseModel):
    date: Optional[str] = None
    distance: Optional[float] = None
    type: Optional[str] = None
    name: Optional[str] = None
    goal_time_seconds: Optional[int] = None


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


# ── Race endpoints ────────────────────────────────────────────────────────────

@router.get("/plans/{plan_id}/races")
async def list_races(plan_id: str, user: User = Depends(_resolve_user)):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    return JSONResponse(_svc.list_races(pid))


@router.post("/plans/{plan_id}/races", status_code=201)
async def create_race(
    plan_id: str,
    body: _RaceCreateBody,
    user: User = Depends(_resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    date = _validate_date(body.date)
    _validate_distance(body.distance)
    _validate_race_type(body.type)
    data = _svc.create_race(
        plan_id=pid,
        date=date,
        distance=body.distance,
        race_type=body.type,
        name=body.name or "",
        goal_time_seconds=body.goal_time_seconds,
    )
    return JSONResponse(status_code=201, content=data)


@router.get("/plans/{plan_id}/races/{race_id}")
async def get_race(
    plan_id: str,
    race_id: str,
    user: User = Depends(_resolve_user),
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
    user: User = Depends(_resolve_user),
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
    )
    if data is None:
        raise HTTPException(status_code=404, detail="race not found")
    return JSONResponse(data)


@router.delete("/plans/{plan_id}/races/{race_id}", status_code=204)
async def delete_race(
    plan_id: str,
    race_id: str,
    user: User = Depends(_resolve_user),
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
    user: User = Depends(_resolve_user),
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
    user: User = Depends(_resolve_user),
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
    user: User = Depends(_resolve_user),
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
    user: User = Depends(_resolve_user),
):
    pid = _parse_plan_id(plan_id)
    _check_plan_access(pid, user)
    rid = _parse_race_id(race_id)
    cid = _parse_checkpoint_id(checkpoint_id)

    deleted = _svc.delete_checkpoint(pid, rid, cid)
    if not deleted:
        raise HTTPException(status_code=404, detail="checkpoint not found")
    return Response(status_code=204)
