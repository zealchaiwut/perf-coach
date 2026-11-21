"""performance_axes.py — Phase 4 revamp Performance endpoints.

Grouped by resource under ``/api/performance/*`` (hyphenated, session-resolved
user — never a client-supplied id). Later P4 tickets add the radar, focus,
projection and race-list routes here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import resolve_user
from backend.db import engine
from backend.models import User, UserPreferences

router = APIRouter()
_log = logging.getLogger(__name__)

MAX_ANCHORS = 8


# ── Strength anchor lifts (P4-4) ─────────────────────────────────────────────

class _AnchorLiftBody(BaseModel):
    label: str
    target_factor: float
    match: list[str] | None = None
    key: str | None = None


class _AnchorLiftsBody(BaseModel):
    anchors: list[_AnchorLiftBody]


@router.get("/api/performance/anchor-lifts")
def get_anchor_lifts(user: User = Depends(resolve_user)):
    from backend.services.axis_strength import get_anchor_lifts as _get

    with Session(engine) as db:
        return JSONResponse({"anchors": _get(db, user.id)})


@router.put("/api/performance/anchor-lifts")
def put_anchor_lifts(body: _AnchorLiftsBody, user: User = Depends(resolve_user)):
    from backend.services.axis_strength import normalize_anchor_lifts

    if not body.anchors:
        raise HTTPException(status_code=422, detail="anchors must contain at least one lift")
    if len(body.anchors) > MAX_ANCHORS:
        raise HTTPException(status_code=422, detail=f"anchors is limited to {MAX_ANCHORS} lifts")
    for a in body.anchors:
        if not a.label.strip():
            raise HTTPException(status_code=422, detail="anchor label is required")
        if not (0 < a.target_factor <= 5):
            raise HTTPException(status_code=422, detail="target_factor must be > 0 and <= 5")
    cleaned = normalize_anchor_lifts([a.model_dump() for a in body.anchors])
    with Session(engine) as db:
        prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
        if prefs is None:
            prefs = UserPreferences(user_id=user.id)
            db.add(prefs)
        prefs.anchor_lifts = cleaned
        db.commit()
    return JSONResponse({"anchors": cleaned})
