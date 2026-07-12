"""injury_log.py — CRUD routes for /api/injury-log (issue #1350).

kind: injury | illness | niggle
severity: 1 (minor) | 2 (moderate) | 3 (severe)
ended_on: null = still active
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, validator

from backend.auth import resolve_user
from backend.services import injury_log_service as _svc

router = APIRouter()

_VALID_KINDS = ("injury", "illness", "niggle")


def _parse_id(entry_id: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(entry_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid entry id")


def _parse_date(value: Optional[str], field: str) -> Optional[_date]:
    if value is None:
        return None
    try:
        return _date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{field} must be ISO format YYYY-MM-DD")


# ── Request bodies ─────────────────────────────────────────────────────────────

class _CreateBody(BaseModel):
    kind: str
    body_area: Optional[str] = None
    severity: int
    started_on: str
    ended_on: Optional[str] = None
    notes: Optional[str] = None

    @validator("kind")
    def _kind_valid(cls, v):  # noqa: N805
        if v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {_VALID_KINDS}")
        return v

    @validator("severity")
    def _severity_range(cls, v):  # noqa: N805
        if v not in (1, 2, 3):
            raise ValueError("severity must be 1 (minor), 2 (moderate), or 3 (severe)")
        return v

    @validator("started_on")
    def _started_on_valid(cls, v):  # noqa: N805
        try:
            _date.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError("started_on must be ISO format YYYY-MM-DD")
        return v

    @validator("ended_on")
    def _ended_on_valid(cls, v, values):  # noqa: N805
        if v is None:
            return v
        try:
            ended = _date.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError("ended_on must be ISO format YYYY-MM-DD")
        started_raw = values.get("started_on")
        if started_raw:
            try:
                started = _date.fromisoformat(started_raw)
                if ended < started:
                    raise ValueError("ended_on must not be before started_on")
            except (ValueError, TypeError) as exc:
                raise ValueError(str(exc)) from exc
        return v


class _PatchBody(BaseModel):
    kind: Optional[str] = None
    body_area: Optional[str] = None
    severity: Optional[int] = None
    started_on: Optional[str] = None
    ended_on: Optional[str] = None
    notes: Optional[str] = None

    @validator("kind")
    def _kind_valid(cls, v):  # noqa: N805
        if v is not None and v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {_VALID_KINDS}")
        return v

    @validator("severity")
    def _severity_range(cls, v):  # noqa: N805
        if v is not None and v not in (1, 2, 3):
            raise ValueError("severity must be 1, 2, or 3")
        return v

    @validator("started_on")
    def _started_on_valid(cls, v):  # noqa: N805
        if v is not None:
            try:
                _date.fromisoformat(v)
            except (ValueError, TypeError):
                raise ValueError("started_on must be ISO format YYYY-MM-DD")
        return v

    @validator("ended_on")
    def _ended_on_valid(cls, v):  # noqa: N805
        if v is not None:
            try:
                _date.fromisoformat(v)
            except (ValueError, TypeError):
                raise ValueError("ended_on must be ISO format YYYY-MM-DD")
        return v


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/injury-log/active")
async def list_active_injury_log(request: Request):
    user = await resolve_user(request)
    return JSONResponse(_svc.list_active(user_id=user.id))


@router.get("/api/injury-log")
async def list_injury_log(
    request: Request,
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = Query(default=None),
):
    user = await resolve_user(request)
    from_date = _parse_date(from_, "from")
    to_date = _parse_date(to, "to")
    return JSONResponse(_svc.list_entries(user_id=user.id, from_date=from_date, to_date=to_date))


@router.post("/api/injury-log", status_code=201)
async def create_injury_log(body: _CreateBody, request: Request):
    user = await resolve_user(request)
    result = _svc.create_entry(
        user_id=user.id,
        kind=body.kind,
        body_area=body.body_area,
        severity=body.severity,
        started_on=body.started_on,
        ended_on=body.ended_on,
        notes=body.notes,
    )
    return JSONResponse(result, status_code=201)


@router.patch("/api/injury-log/{entry_id}")
async def patch_injury_log(entry_id: str, body: _PatchBody, request: Request):
    user = await resolve_user(request)
    eid = _parse_id(entry_id)
    fields = body.dict(exclude_unset=True)
    result = _svc.update_entry(entry_id=eid, user_id=user.id, fields=fields)
    if result is None:
        raise HTTPException(status_code=404, detail="injury log entry not found")
    return JSONResponse(result)


@router.delete("/api/injury-log/{entry_id}", status_code=204)
async def delete_injury_log(entry_id: str, request: Request):
    user = await resolve_user(request)
    eid = _parse_id(entry_id)
    deleted = _svc.delete_entry(entry_id=eid, user_id=user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="injury log entry not found")
    return Response(status_code=204)
