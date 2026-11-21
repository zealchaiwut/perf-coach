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


# ── Radar (P4-6) ─────────────────────────────────────────────────────────────

def _a_race_distance_km(db, user_id, as_of):
    from backend.services.perf_a_race import next_a_race

    race = next_a_race(db, user_id, as_of)
    return float(race.distance_km) if race is not None and race.distance_km else None


@router.get("/api/performance/radar")
def get_performance_radar(size: str = "large", user: User = Depends(resolve_user)):
    """One payload (and its rendered inline SVG) for the Home and Performance radars."""
    from backend.services.focus_ranking import rank_axes
    from backend.services.radar_payload import build_radar
    from backend.services.radar_svg import render_radar_svg
    from backend.utils.time import today_bangkok

    if size not in ("large", "small"):
        raise HTTPException(status_code=422, detail="size must be 'large' or 'small'")
    today = today_bangkok()
    with Session(engine) as db:
        km = _a_race_distance_km(db, user.id, today)

        def ranker(axes):
            f = rank_axes(axes, km)["focus"]
            return f["axis"] if f else None

        payload = build_radar(db, user.id, today, focus_ranker=ranker)
    payload["size"] = size
    payload["svg"] = render_radar_svg(payload, size)
    return JSONResponse(payload)


# ── Focus ranking and queue (P4-7) ───────────────────────────────────────────

class _QueueBody(BaseModel):
    axis: str | None = None


@router.get("/api/performance/focus")
def get_performance_focus(user: User = Depends(resolve_user)):
    from backend.services import focus_ranking as fr
    from backend.services.radar_payload import build_radar
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    with Session(engine) as db:
        km = _a_race_distance_km(db, user.id, today)
        axes = build_radar(db, user.id, today)["axes"]
        out = fr.rank_axes(axes, km)
        queued = {r.axis: fr.item_dict(r) for r in fr.queued_items(db, user.id)}
    out["queue"] = queued
    out["queued_focus"] = bool(out["focus"] and out["focus"]["axis"] in queued)
    out["advice"] = {a: w["advice"] for a, w in fr.WORK_MAP.items()}
    return JSONResponse(out)


@router.post("/api/performance/focus/queue")
def queue_performance_focus(body: _QueueBody, user: User = Depends(resolve_user)):
    """Queue the focus axis' work (or an explicit ``axis``) into the next build/rebuild week."""
    from backend.services import focus_ranking as fr
    from backend.services.radar_payload import build_radar
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    with Session(engine) as db:
        axis = body.axis
        if axis is None:
            km = _a_race_distance_km(db, user.id, today)
            focus = fr.rank_axes(build_radar(db, user.id, today)["axes"], km)["focus"]
            if focus is None:
                raise HTTPException(status_code=409, detail="No fresh, measured axis to focus on yet")
            axis = focus["axis"]
        try:
            row, created = fr.queue_focus_work(db, user.id, axis, today)
        except fr.QueueError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail)
        return JSONResponse({"item": fr.item_dict(row), "created": created}, status_code=201 if created else 200)


@router.delete("/api/performance/focus/queue/{item_id}", status_code=204)
def cancel_performance_queue_item(item_id: str, user: User = Depends(resolve_user)):
    import uuid as _uuid
    from fastapi import Response
    from backend.services import focus_ranking as fr

    try:
        iid = _uuid.UUID(item_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid item id")
    with Session(engine) as db:
        if not fr.cancel_item(db, user.id, iid):
            raise HTTPException(status_code=404, detail="queue item not found")
    return Response(status_code=204)


# ── A-race hero + after-the-race card (P4-8) ─────────────────────────────────

@router.get("/api/performance/hero")
def get_performance_hero(user: User = Depends(resolve_user)):
    from backend.services.race_hero import build_hero
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(build_hero(db, user.id, today_bangkok()))


# ── Endurance and Speed score cards (P4-9) ───────────────────────────────────

@router.get("/api/performance/score-cards")
def get_performance_score_cards(user: User = Depends(resolve_user)):
    from backend.services.score_cards import build_cards
    from backend.utils.time import today_bangkok

    return JSONResponse(build_cards(user.id, as_of=today_bangkok()))


# ── Races and projections (P4-10) ────────────────────────────────────────────

@router.get("/api/performance/projection")
def get_performance_projection(user: User = Depends(resolve_user)):
    from backend.services.projection_view import build_projection
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(build_projection(db, user.id, today_bangkok()))


# ── Race list (P4-11) ────────────────────────────────────────────────────────

@router.get("/api/performance/races")
def get_performance_races(user: User = Depends(resolve_user)):
    from backend.services.race_list import build_race_list
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(build_race_list(db, user.id, today_bangkok()))


# ── Coach block (P4-12) ──────────────────────────────────────────────────────

@router.get("/api/performance/coach-block")
def get_performance_coach_block(user: User = Depends(resolve_user)):
    from backend.services.coach_block import fetch_coach_block
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(fetch_coach_block(db, user.id, today_bangkok()))
