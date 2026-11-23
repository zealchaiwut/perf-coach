"""performance_axes.py — Phase 4 revamp Performance endpoints.

Grouped by resource under ``/api/performance/*`` (hyphenated, session-resolved
user — never a client-supplied id). Later P4 tickets add the radar, focus,
projection and race-list routes here.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import resolve_user
from backend.db import engine
from backend.models import User, UserPreferences
from backend.utils.query_log import logged as _query_logged

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
@_query_logged("/api/performance/anchor-lifts")
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
@_query_logged("/api/performance/mobility-tests")
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
@_query_logged("/api/performance/radar")
def get_performance_radar(size: str = "large", user: User = Depends(resolve_user)):
    """One payload (and its rendered inline SVG) for the Home and Performance radars."""
    from backend.services.focus_ranking import rank_axes
    from backend.services.radar_cache import get_radar_payload
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

        payload = get_radar_payload(db, user.id, today, focus_ranker=ranker)
    payload["size"] = size
    payload["svg"] = render_radar_svg(payload, size)
    return JSONResponse(payload)


# ── Focus ranking and queue (P4-7) ───────────────────────────────────────────

class _QueueBody(BaseModel):
    axis: str | None = None


@router.get("/api/performance/focus")
@_query_logged("/api/performance/focus")
def get_performance_focus(user: User = Depends(resolve_user)):
    from backend.services import focus_ranking as fr
    from backend.services.radar_cache import get_radar_payload
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    with Session(engine) as db:
        km = _a_race_distance_km(db, user.id, today)
        axes = get_radar_payload(db, user.id, today)["axes"]
        out = fr.rank_axes(axes, km)
        queued = {r.axis: fr.item_dict(r) for r in fr.queued_items(db, user.id)}
        phase = fr._phase_lookup(db, user.id, today)
        ew = fr.earliest_queue_week(phase, today)
        out["suggested_queue_week"] = ew.isoformat() if ew else None
    out["queue"] = queued
    out["queued_focus"] = bool(out["focus"] and out["focus"]["axis"] in queued)
    out["advice"] = {a: w["advice"] for a, w in fr.WORK_MAP.items()}
    return JSONResponse(out)


@router.post("/api/performance/focus/queue")
def queue_performance_focus(body: _QueueBody, user: User = Depends(resolve_user)):
    """Queue the focus axis' work (or an explicit ``axis``) into the next build/rebuild week."""
    from backend.services import focus_ranking as fr
    from backend.services.radar_cache import get_radar_payload
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    with Session(engine) as db:
        axis = body.axis
        if axis is None:
            km = _a_race_distance_km(db, user.id, today)
            focus = fr.rank_axes(get_radar_payload(db, user.id, today)["axes"], km)["focus"]
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


# ── Performance bundle (one session, warm cache) ───────────────────────────

@router.get("/api/performance/bundle")
def get_performance_bundle(user: User = Depends(resolve_user)):
    """Single round-trip for the v2 Performance page (reduces pool fan-out)."""
    from backend.services import focus_ranking as fr
    from backend.services.derived_cache import get_or_compute
    from backend.services.projection_view import build_projection
    from backend.services.race_hero import build_hero
    from backend.services.race_list import build_race_list
    from backend.services.radar_cache import get_radar_payload
    from backend.services.radar_svg import render_radar_svg
    from backend.services.score_cards import build_cards
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    with Session(engine) as db:
        km = _a_race_distance_km(db, user.id, today)
        radar = get_radar_payload(db, user.id, today)
        radar["size"] = "large"
        radar["svg"] = render_radar_svg(radar, "large")
        focus = fr.rank_axes(radar["axes"], km)
        hero = get_or_compute(
            db, user.id, "derived:hero", today,
            lambda: build_hero(db, user.id, today),
        )
        projection = get_or_compute(
            db, user.id, "derived:projection", today,
            lambda: build_projection(db, user.id, today),
        )
        races = get_or_compute(
            db, user.id, "derived:race_list", today,
            lambda: build_race_list(db, user.id, today),
        )
    return JSONResponse({
        "radar": radar,
        "focus": focus,
        "hero": hero,
        "projection": projection,
        "races": races,
        "score_cards": build_cards(user.id, as_of=today),
    })


# ── Combined page (one session, shared context) ──────────────────────────────

@router.get("/api/performance/page")
@_query_logged("/api/performance/page")
def get_performance_page(
    sections: str | None = None,
    size: str = "large",
    user: User = Depends(resolve_user),
):
    """One Performance-tab boot: selected sections share one session (#1939)."""
    from backend.services.performance_page import (
        UnknownSectionError,
        build_page,
        parse_sections,
    )
    from backend.utils.time import today_bangkok

    if size not in ("large", "small"):
        raise HTTPException(status_code=422, detail="size must be 'large' or 'small'")
    try:
        wanted = parse_sections(sections)
    except UnknownSectionError as exc:
        raise HTTPException(
            status_code=422,
            detail={"unknown": exc.unknown, "allowed": exc.allowed},
        )
    with Session(engine) as db:
        return JSONResponse(build_page(db, user.id, today_bangkok(), wanted, size=size))


# ── A-race hero + after-the-race card (P4-8) ─────────────────────────────────

@router.get("/api/performance/hero")
@_query_logged("/api/performance/hero")
def get_performance_hero(user: User = Depends(resolve_user)):
    from backend.services.race_hero import build_hero
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(build_hero(db, user.id, today_bangkok()))


@router.get("/api/performance/a-race-readiness")
@_query_logged("/api/performance/a-race-readiness")
def get_a_race_readiness_checklist(user: User = Depends(resolve_user)):
    from backend.services.a_race_readiness_checklist import build_checklist
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(build_checklist(db, user.id, today_bangkok()))


# ── Endurance and Speed score cards (P4-9) ───────────────────────────────────

@router.get("/api/performance/score-cards")
@_query_logged("/api/performance/score-cards")
def get_performance_score_cards(user: User = Depends(resolve_user)):
    from backend.services.derived_cache import DERIVED_SCORE_CARDS, get_or_compute
    from backend.services.score_cards import build_cards
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    with Session(engine) as db:
        return JSONResponse(get_or_compute(
            db, user.id, DERIVED_SCORE_CARDS, today,
            lambda: build_cards(user.id, as_of=today),
        ))


# ── Races and projections (P4-10) ────────────────────────────────────────────

@router.get("/api/performance/projection")
@_query_logged("/api/performance/projection")
def get_performance_projection(user: User = Depends(resolve_user)):
    from backend.services.projection_view import build_projection
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(build_projection(db, user.id, today_bangkok()))


# ── Race list (P4-11) ────────────────────────────────────────────────────────

@router.get("/api/performance/races")
@_query_logged("/api/performance/races")
def get_performance_races(user: User = Depends(resolve_user)):
    from backend.services.race_list import build_race_list
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(build_race_list(db, user.id, today_bangkok()))


# ── Season road (P6-6) ───────────────────────────────────────────────────────

@router.get("/api/performance/season-road")
def get_performance_season_road(user: User = Depends(resolve_user)):
    from backend.services.season_road import build_season_road
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(build_season_road(db, user.id, today_bangkok()))


# ── Coach block (P4-12) ──────────────────────────────────────────────────────

@router.get("/api/performance/coach-block")
@_query_logged("/api/performance/coach-block")
def get_performance_coach_block(user: User = Depends(resolve_user)):
    from backend.services.coach_block import fetch_coach_block
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        return JSONResponse(fetch_coach_block(db, user.id, today_bangkok()))


class _WeeklyCheckInChangePatch(BaseModel):
    id: str
    status: str


class _WeeklyCheckInPatch(BaseModel):
    carried_changes: list[_WeeklyCheckInChangePatch] | None = None
    feet: int | None = None
    bed_bucket: str | None = None
    motivation: str | None = None
    note: str | None = None
    complete: bool | None = None


@router.get("/api/weekly-check-in")
def get_weekly_check_in(user: User = Depends(resolve_user)):
    from backend.services.weekly_checkin import checkin_payload, get_or_create_checkin
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        row, meta = get_or_create_checkin(db, user.id, today_bangkok())
        db.commit()
        return JSONResponse(checkin_payload(db, row, meta, today_bangkok()))


@router.post("/api/weekly-check-in/refresh")
def post_weekly_check_in_refresh(user: User = Depends(resolve_user)):
    from backend.services.weekly_checkin import refresh_snapshot
    from backend.utils.time import today_bangkok

    with Session(engine) as db:
        payload = refresh_snapshot(db, user.id, today_bangkok())
        db.commit()
        return JSONResponse(payload)


class _WeeklyCheckInParseBody(BaseModel):
    raw_text: str


class _WeeklyCheckInApplyBody(BaseModel):
    raw_text: str
    items: list[dict[str, Any]] | None = None


@router.post("/api/weekly-check-in/parse")
def post_weekly_check_in_parse(body: _WeeklyCheckInParseBody, user: User = Depends(resolve_user)):
    from backend.services.checkin_changes import parse_changes_block
    from backend.utils.time import today_bangkok

    return JSONResponse({"items": parse_changes_block(body.raw_text, decided_on=today_bangkok())})


@router.post("/api/weekly-check-in/apply-paste")
def post_weekly_check_in_apply(body: _WeeklyCheckInApplyBody, user: User = Depends(resolve_user)):
    from backend.services.weekly_checkin import apply_paste_back, checkin_payload, get_or_create_checkin
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    with Session(engine) as db:
        row, meta = get_or_create_checkin(db, user.id, today)
        try:
            result = apply_paste_back(db, user.id, row, body.raw_text, today, items=body.items)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        db.commit()
        return JSONResponse({**result, "check_in": checkin_payload(db, row, meta, today)})


@router.patch("/api/weekly-check-in")
def patch_weekly_check_in(body: _WeeklyCheckInPatch, user: User = Depends(resolve_user)):
    from backend.services.weekly_checkin import (
        checkin_payload,
        get_or_create_checkin,
        mark_complete,
        save_carried_statuses,
        save_self_report,
    )
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    with Session(engine) as db:
        row, meta = get_or_create_checkin(db, user.id, today)
        try:
            if body.carried_changes is not None:
                save_carried_statuses(
                    db, row, [{"id": c.id, "status": c.status} for c in body.carried_changes]
                )
            report: dict[str, Any] = {}
            fields = body.model_fields_set
            if "feet" in fields:
                report["feet"] = body.feet
            if "bed_bucket" in fields:
                report["bed_bucket"] = body.bed_bucket
            if "motivation" in fields:
                report["motivation"] = body.motivation
            if "note" in fields:
                report["note"] = body.note
            if report:
                save_self_report(db, row, **report)
            if body.complete:
                mark_complete(db, row)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        db.commit()
        db.refresh(row)
        return JSONResponse(checkin_payload(db, row, meta, today_bangkok()))
