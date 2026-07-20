"""Training preferences API — versioned store, proposals, import/export."""
from __future__ import annotations

import uuid as _uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import resolve_user
from backend.db import engine
from backend.models import User
from backend.services import training_prefs as _prefs
from backend.services.gap_analysis import pref_proposals as _props
from backend.services.pref_catalog import PREF_FIELDS, normalize_payload, validate_payload

router = APIRouter()


def _db() -> Session:
    return Session(engine)


def _proposal_id(raw: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=400, detail="invalid proposal id")


class _PrefsBody(BaseModel):
    payload: dict


class _AdjustBody(BaseModel):
    to: Any


# ── Catalog (UI docs) ─────────────────────────────────────────────────────────

@router.get("/api/preferences/catalog")
def get_catalog(user: User = Depends(resolve_user)):
    return JSONResponse({"fields": PREF_FIELDS})


# ── Active prefs + in-flight proposals ────────────────────────────────────────

@router.get("/api/preferences")
def get_preferences(user: User = Depends(resolve_user)):
    db = _db()
    try:
        _prefs.maybe_carry_forward(db, user.id)
        active = _prefs.active_dict(db, user.id)
        proposals = _props.list_proposals(db, user.id, include_settled=True)
        db.commit()
        return JSONResponse({
            "active": active,
            "proposals": proposals,
            "catalog": {k: {"type": v.get("type"), "min": v.get("min"), "max": v.get("max"),
                            "step": v.get("step"), "reads": v.get("reads")}
                        for k, v in PREF_FIELDS.items()},
        })
    finally:
        db.close()


@router.put("/api/preferences")
def put_preferences(body: _PrefsBody, user: User = Depends(resolve_user)):
    db = _db()
    try:
        errs = validate_payload(body.payload)
        if errs:
            raise HTTPException(status_code=422, detail=errs)
        row = _prefs.update_from_user(db, user.id, body.payload)
        # Decline open proposals whose field the user overrode
        from backend.models import PreferenceProposal
        from datetime import datetime, timezone

        for prop in (
            db.query(PreferenceProposal)
            .filter(
                PreferenceProposal.user_id == user.id,
                PreferenceProposal.status == "proposed",
            )
            .all()
        ):
            field = (prop.delta or {}).get("field")
            if not field:
                continue
            from backend.services.pref_catalog import get_field
            if get_field(row.payload, field) != (prop.delta or {}).get("from"):
                prop.status = "declined"
                prop.decided_at = datetime.now(timezone.utc)
        db.commit()
        return JSONResponse(_prefs.active_dict(db, user.id))
    except ValueError as e:
        db.rollback()
        detail = e.args[0] if e.args else str(e)
        raise HTTPException(status_code=422, detail=detail)
    finally:
        db.close()


@router.post("/api/preferences/confirm")
def confirm_preferences(user: User = Depends(resolve_user)):
    db = _db()
    try:
        _prefs.confirm_active(db, user.id)
        db.commit()
        return JSONResponse(_prefs.active_dict(db, user.id))
    finally:
        db.close()


# ── Proposals ─────────────────────────────────────────────────────────────────

@router.post("/api/preferences/proposals/{proposal_id}/accept")
def accept_proposal(proposal_id: str, user: User = Depends(resolve_user)):
    db = _db()
    try:
        pid = _proposal_id(proposal_id)
        from backend.models import PreferenceProposal
        row = (
            db.query(PreferenceProposal)
            .filter(PreferenceProposal.id == pid, PreferenceProposal.user_id == user.id)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        if row.gap_code == "safety_rollback":
            result = _props.accept_rollback_marks_original(db, user.id, pid)
        else:
            result = _props.accept_proposal(db, user.id, pid)
        db.commit()
        return JSONResponse(result)
    except LookupError:
        db.rollback()
        raise HTTPException(status_code=404, detail="proposal not found")
    except ValueError as e:
        db.rollback()
        detail = e.args[0] if e.args else str(e)
        status = 422 if isinstance(detail, dict) else 409
        raise HTTPException(status_code=status, detail=detail)
    finally:
        db.close()


@router.post("/api/preferences/proposals/{proposal_id}/decline")
def decline_proposal(proposal_id: str, user: User = Depends(resolve_user)):
    db = _db()
    try:
        result = _props.decline_proposal(db, user.id, _proposal_id(proposal_id))
        db.commit()
        return JSONResponse(result)
    except LookupError:
        db.rollback()
        raise HTTPException(status_code=404, detail="proposal not found")
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    finally:
        db.close()


@router.post("/api/preferences/proposals/{proposal_id}/adjust")
def adjust_proposal(
    proposal_id: str,
    body: _AdjustBody,
    user: User = Depends(resolve_user),
):
    db = _db()
    try:
        result = _props.accept_proposal(
            db, user.id, _proposal_id(proposal_id), adjusted_to=body.to
        )
        db.commit()
        return JSONResponse(result)
    except LookupError:
        db.rollback()
        raise HTTPException(status_code=404, detail="proposal not found")
    except ValueError as e:
        db.rollback()
        detail = e.args[0] if e.args else str(e)
        status = 422 if isinstance(detail, dict) else 409
        raise HTTPException(status_code=status, detail=detail)
    finally:
        db.close()


# ── Export / import / AI template ─────────────────────────────────────────────

@router.get("/api/preferences/export")
def export_preferences(user: User = Depends(resolve_user)):
    import json
    db = _db()
    try:
        bundle = _prefs.export_bundle(db, user.id)
        body = json.dumps(bundle, indent=2, sort_keys=True) + "\n"
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="training-preferences.json"',
            },
        )
    finally:
        db.close()


@router.post("/api/preferences/import")
async def import_preferences(request: Request, user: User = Depends(resolve_user)):
    db = _db()
    try:
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail={"": "body must be JSON"})
        result = _prefs.import_bundle(db, user.id, raw)
        db.commit()
        return JSONResponse(result)
    except ValueError as e:
        db.rollback()
        detail = e.args[0] if e.args else str(e)
        raise HTTPException(status_code=422, detail=detail)
    finally:
        db.close()


@router.get("/api/preferences/ai-template")
def ai_template(user: User = Depends(resolve_user)):
    db = _db()
    try:
        text = _prefs.ai_edit_template(db, user.id)
        return PlainTextResponse(text)
    finally:
        db.close()
