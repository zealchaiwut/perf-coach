"""decisions.py — Routes for /api/decisions/*, the consult loop's system of record.

A consult produces a ``CHANGES TO APPLY`` block. That block is pasted verbatim
into one textarea and stored here. **There is no parser** — deliberately. A
parser is a project; a textarea is an afternoon, and the value is in having the
history at all: the coach export carries the most recent rows so the next consult
can reference what was already tried instead of re-proposing it.

The only structure asked for beyond the raw text is optional: ``tags`` for
grouping, ``review_on`` for "check whether this worked on this date", and
``outcome_note`` filled in later once the answer is known.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import date as _date, timedelta as _timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import resolve_user
from backend.db import engine
from backend.models import Decision, User

router = APIRouter()

_log = logging.getLogger(__name__)

RAW_TEXT_MAX_CHARS = 8000
MAX_TAGS = 12
TAG_MAX_CHARS = 40
OUTCOME_NOTE_MAX_CHARS = 1000
# Default review horizon when the consult didn't name one: long enough for a
# weight-trend or fitness signal to actually move.
DEFAULT_REVIEW_DAYS = 14
DEFAULT_LIST_LIMIT = 25


def _decision_dict(d: Decision) -> dict:
    return {
        "id": str(d.id),
        "decided_on": d.decided_on.isoformat(),
        "source": d.source,
        "raw_text": d.raw_text,
        "tags": list(d.tags or []),
        "applied": bool(d.applied),
        "outcome_note": d.outcome_note,
        "review_on": d.review_on.isoformat() if d.review_on else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


class _DecisionBody(BaseModel):
    raw_text: str
    decided_on: str | None = None
    tags: list[str] | None = None
    applied: bool | None = None
    review_on: str | None = None
    outcome_note: str | None = None


class _DecisionPatchBody(BaseModel):
    applied: bool | None = None
    outcome_note: str | None = None
    review_on: str | None = None
    tags: list[str] | None = None


def _parse_date(raw: str | None, field: str, errors: list) -> _date | None:
    if raw is None:
        return None
    try:
        return _date.fromisoformat(str(raw))
    except (ValueError, TypeError):
        errors.append({"field": field, "msg": f"{field} must be ISO YYYY-MM-DD"})
        return None


def _clean_tags(tags: list | None, errors: list) -> list[str] | None:
    if tags is None:
        return None
    if not isinstance(tags, list):
        errors.append({"field": "tags", "msg": "tags must be a list of strings"})
        return None
    cleaned = [str(t).strip()[:TAG_MAX_CHARS] for t in tags if str(t).strip()]
    if len(cleaned) > MAX_TAGS:
        errors.append({"field": "tags", "msg": f"at most {MAX_TAGS} tags"})
        return None
    return cleaned


@router.post("/api/decisions", status_code=201)
async def create_decision(body: _DecisionBody, user: User = Depends(resolve_user)):
    """Store one consult decision. The MVP is a single textarea — paste the
    ``CHANGES TO APPLY`` block raw."""
    errors: list = []

    raw_text = (body.raw_text or "").strip()
    if not raw_text:
        errors.append({"field": "raw_text", "msg": "raw_text is required"})
    elif len(raw_text) > RAW_TEXT_MAX_CHARS:
        errors.append({
            "field": "raw_text",
            "msg": f"raw_text must be ≤ {RAW_TEXT_MAX_CHARS} characters",
        })

    decided_on = _parse_date(body.decided_on, "decided_on", errors) or _date.today()
    review_on = _parse_date(body.review_on, "review_on", errors)
    tags = _clean_tags(body.tags, errors)

    outcome_note = (body.outcome_note or "").strip() or None
    if outcome_note and len(outcome_note) > OUTCOME_NOTE_MAX_CHARS:
        errors.append({
            "field": "outcome_note",
            "msg": f"outcome_note must be ≤ {OUTCOME_NOTE_MAX_CHARS} characters",
        })

    if body.decided_on and decided_on and decided_on > _date.today():
        errors.append({"field": "decided_on", "msg": "decided_on cannot be in the future"})

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    # A decision with no review date is one nobody ever checks. Default it.
    if review_on is None:
        review_on = decided_on + _timedelta(days=DEFAULT_REVIEW_DAYS)

    with Session(engine) as db:
        decision = Decision(
            # Generated here rather than leaning on the server default so the
            # insert round-trips identically on every backend.
            id=_uuid.uuid4(),
            user_id=user.id,
            decided_on=decided_on,
            source="consult",
            raw_text=raw_text,
            tags=tags,
            applied=True if body.applied is None else bool(body.applied),
            outcome_note=outcome_note,
            review_on=review_on,
        )
        db.add(decision)
        db.commit()
        db.refresh(decision)
        return JSONResponse(_decision_dict(decision), status_code=201)


@router.get("/api/decisions")
async def list_decisions(
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=200),
    user: User = Depends(resolve_user),
):
    """Return decisions newest-first — the log view and the export both read this."""
    with Session(engine) as db:
        rows = (
            db.query(Decision)
            .filter(Decision.user_id == user.id)
            .order_by(Decision.decided_on.desc(), Decision.created_at.desc())
            .limit(limit)
            .all()
        )
        return JSONResponse({"decisions": [_decision_dict(d) for d in rows]})


@router.patch("/api/decisions/{decision_id}")
async def update_decision(
    decision_id: str,
    body: _DecisionPatchBody,
    user: User = Depends(resolve_user),
):
    """Record how a decision turned out — the half of the loop that closes it.

    Only the outcome fields are editable. ``raw_text`` is what the consult
    actually said and stays immutable, so the history can't be rewritten after
    the fact.
    """
    try:
        did = _uuid.UUID(decision_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid decision id")

    errors: list = []
    review_on = _parse_date(body.review_on, "review_on", errors)
    tags = _clean_tags(body.tags, errors)
    outcome_note = None
    if body.outcome_note is not None:
        outcome_note = body.outcome_note.strip() or None
        if outcome_note and len(outcome_note) > OUTCOME_NOTE_MAX_CHARS:
            errors.append({
                "field": "outcome_note",
                "msg": f"outcome_note must be ≤ {OUTCOME_NOTE_MAX_CHARS} characters",
            })
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    with Session(engine) as db:
        decision = (
            db.query(Decision)
            .filter(Decision.id == did, Decision.user_id == user.id)
            .first()
        )
        if decision is None:
            raise HTTPException(status_code=404, detail="decision not found")

        if body.applied is not None:
            decision.applied = bool(body.applied)
        if body.outcome_note is not None:
            decision.outcome_note = outcome_note
        if body.review_on is not None:
            decision.review_on = review_on
        if tags is not None:
            decision.tags = tags

        db.commit()
        db.refresh(decision)
        return JSONResponse(_decision_dict(decision))


@router.delete("/api/decisions/{decision_id}", status_code=204)
async def delete_decision(decision_id: str, user: User = Depends(resolve_user)):
    """Remove a mis-pasted entry. Rare, but the alternative is a log you stop
    trusting because it has junk in it."""
    try:
        did = _uuid.UUID(decision_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid decision id")

    with Session(engine) as db:
        decision = (
            db.query(Decision)
            .filter(Decision.id == did, Decision.user_id == user.id)
            .first()
        )
        if decision is None:
            raise HTTPException(status_code=404, detail="decision not found")
        db.delete(decision)
        db.commit()
    return JSONResponse(content=None, status_code=204)


# ── Calibration sprints (lean program Phase 4) ───────────────────────────────
# A bounded measurement week, never a diet. Lives alongside decisions because
# both are the athlete's own deliberate acts rather than derived state.


class _SprintBody(BaseModel):
    days: int | None = None
    start_date: str | None = None


@router.get("/api/calibration-sprint")
async def get_calibration_sprint(user: User = Depends(resolve_user)):
    """Current sprint status: countdown, logged days, and whether one is due."""
    from backend.services.calibration_sprint import sprint_status

    with Session(engine) as db:
        return JSONResponse(sprint_status(db, user.id))


@router.post("/api/calibration-sprint", status_code=201)
async def start_calibration_sprint(
    body: _SprintBody, user: User = Depends(resolve_user)
):
    """Open a 5-7 day measurement window with a visible end date."""
    from backend.services.calibration_sprint import (
        DEFAULT_SPRINT_DAYS,
        SprintError,
        sprint_status,
        start_sprint,
    )

    start_date = None
    if body.start_date:
        try:
            start_date = _date.fromisoformat(body.start_date)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422,
                detail=[{"field": "start_date", "msg": "start_date must be ISO YYYY-MM-DD"}],
            )

    with Session(engine) as db:
        try:
            start_sprint(
                db,
                user.id,
                start_date=start_date,
                days=body.days or DEFAULT_SPRINT_DAYS,
            )
        except SprintError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        db.commit()
        return JSONResponse(sprint_status(db, user.id), status_code=201)


@router.post("/api/calibration-sprint/close")
async def close_calibration_sprint(
    abandon: bool = Query(default=False),
    user: User = Depends(resolve_user),
):
    """End the sprint and recalibrate maintenance when enough days landed.

    A sprint that fell short is completed, not failed — there is no penalty
    state, because a measurement that didn't take is not a moral event.
    """
    from backend.services.calibration_sprint import close_sprint

    with Session(engine) as db:
        result = close_sprint(db, user.id, abandon=abandon)
        if not result.get("closed"):
            raise HTTPException(status_code=404, detail="no measurement week running")
        db.commit()
        return JSONResponse(result)


@router.get("/api/weight-hypothesis")
async def get_weight_hypothesis(user: User = Depends(resolve_user)):
    """Where performance scores have been highest — a hypothesis, not a target.

    The response deliberately carries no ``target_kg``: "as lean as I can" has no
    stopping rule, and a number off a chart is a guess dressed as a goal.
    """
    from backend.services.weight_hypothesis import hypothesis_for_user

    with Session(engine) as db:
        return JSONResponse(hypothesis_for_user(db, user.id))
