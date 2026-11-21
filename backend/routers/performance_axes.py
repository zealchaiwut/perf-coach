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


# ── Mobility self-test (P4-5) ────────────────────────────────────────────────

class _MobilityTestBody(BaseModel):
    test_date: str | None = None
    knee_to_wall_left_cm: float | None = None
    knee_to_wall_right_cm: float | None = None
    sit_and_reach_cm: float | None = None


def _parse_iso_date(value: str | None, field: str):
    from datetime import date as _date

    if value is None:
        return None
    try:
        return _date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{field} must be ISO format YYYY-MM-DD")


@router.get("/api/performance/mobility-tests")
def list_mobility_tests(user: User = Depends(resolve_user)):
    from backend.models import MobilityTest
    from backend.services import axis_mobility as _mob
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    with Session(engine) as db:
        rows = (
            db.query(MobilityTest)
            .filter(MobilityTest.user_id == user.id)
            .order_by(MobilityTest.test_date.desc(), MobilityTest.created_at.desc())
            .limit(12)
            .all()
        )
        axis = _mob.get_mobility(db, user.id, today)
        return JSONResponse({"axis": axis, "tests": [_mob.mobility_test_dict(r) for r in rows]})


@router.post("/api/performance/mobility-tests", status_code=201)
def create_mobility_test(body: _MobilityTestBody, user: User = Depends(resolve_user)):
    from backend.models import MobilityTest
    from backend.services import axis_mobility as _mob
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    test_date = _parse_iso_date(body.test_date, "test_date") if body.test_date else today
    try:
        _mob.validate_test_input(
            body.knee_to_wall_left_cm, body.knee_to_wall_right_cm, body.sit_and_reach_cm, test_date, today
        )
    except _mob.MobilityValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    with Session(engine) as db:
        row = MobilityTest(
            user_id=user.id,
            test_date=test_date,
            knee_to_wall_left_cm=body.knee_to_wall_left_cm,
            knee_to_wall_right_cm=body.knee_to_wall_right_cm,
            sit_and_reach_cm=body.sit_and_reach_cm,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        axis = _mob.get_mobility(db, user.id, today)
        return JSONResponse({"test": _mob.mobility_test_dict(row), "axis": axis}, status_code=201)


@router.delete("/api/performance/mobility-tests/{test_id}", status_code=204)
def delete_mobility_test(test_id: str, user: User = Depends(resolve_user)):
    import uuid as _uuid
    from fastapi import Response
    from backend.models import MobilityTest

    try:
        tid = _uuid.UUID(test_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid test id")
    with Session(engine) as db:
        row = db.get(MobilityTest, tid)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="mobility test not found")
        db.delete(row)
        db.commit()
    return Response(status_code=204)
