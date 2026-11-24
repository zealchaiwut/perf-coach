"""Phone PWA bundle, sync, ping, and device-session routes (PWA phase 0)."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, Response as RawResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import resolve_user
from backend.db import engine
from backend.models import DeviceSession, User
from backend.services.device_sessions import (
    attach_rotated_csrf,
    issue_device_session,
    list_devices,
    revoke_device,
    set_device_cookie,
    touch_device,
)
from backend.services.mobile_bundle import build_bundle, bundle_etag
from backend.services.mobile_sync import apply_ops
from backend.utils.time import today_bangkok

router = APIRouter()


class _SyncIn(BaseModel):
    ops: list[dict[str, Any]] = Field(default_factory=list)


class _RememberDeviceIn(BaseModel):
    label: Optional[str] = None


def _attach_csrf(response: Response, request: Request, db: Session) -> None:
    row = getattr(request.state, "device_session_row", None)
    if row is None:
        return
    live = db.get(DeviceSession, row.id)
    if live is None:
        return
    attach_rotated_csrf(response, live)
    touch_device(live)
    db.commit()


@router.get("/api/mobile/ping")
def mobile_ping():
    """Cheap wake hook for Hermes. No database work."""
    return RawResponse(status_code=204)


@router.get("/api/mobile/bundle")
def mobile_bundle(
    request: Request,
    days: int = 7,
    user: User = Depends(resolve_user),
):
    if days < 1 or days > 14:
        raise HTTPException(status_code=422, detail="days must be between 1 and 14")
    with Session(engine) as db:
        payload = build_bundle(db, user.id, days=days)
        etag = bundle_etag(payload)
        inm = request.headers.get("if-none-match") or request.headers.get("If-None-Match")
        if inm and inm.strip('"') == etag:
            resp = RawResponse(status_code=304)
            resp.headers["ETag"] = etag
            _attach_csrf(resp, request, db)
            return resp
        resp = JSONResponse(payload)
        resp.headers["ETag"] = etag
        _attach_csrf(resp, request, db)
        return resp


@router.post("/api/mobile/sync")
def mobile_sync(body: _SyncIn, request: Request, user: User = Depends(resolve_user)):
    with Session(engine) as db:
        results = apply_ops(db, user.id, body.ops)
        db.commit()
        resp = JSONResponse({"ops": results})
        _attach_csrf(resp, request, db)
        return resp


@router.get("/api/mobile/today-link")
def mobile_today_link(user: User = Depends(resolve_user)):
    from backend.services.revamp_home import build_today_hero
    from backend.services.revamp_week_board import week_board
    from backend.services.weekly_rollup import normalize_week_start

    today = today_bangkok()
    with Session(engine) as db:
        board = week_board(user.id, normalize_week_start(today), session=db, today=today)
        hero = build_today_hero(db, user.id, today, board=board)
    session = (hero or {}).get("session") or {}
    kind = (session.get("kind") or "").lower()
    return JSONResponse(
        {
            "date": today.isoformat(),
            "kind": kind or hero.get("state"),
            "session_id": session.get("id"),
            "session_name": session.get("name"),
            "gym_url": f"/m/gym/{session['id']}" if session.get("id") and "strength" in kind else None,
            "today_url": "/m/today",
            "weigh_in_url": "/m/body/weigh-in",
        }
    )


@router.post("/api/auth/remember-device")
def remember_device(body: _RememberDeviceIn, user: User = Depends(resolve_user)):
    with Session(engine) as db:
        row, raw, csrf = issue_device_session(db, user.id, label=body.label)
        db.commit()
        resp = JSONResponse({"id": str(row.id), "label": row.label, "csrf": csrf})
        set_device_cookie(resp, raw)
        from backend.auth import set_csrf_cookie

        set_csrf_cookie(resp, csrf)
        return resp


@router.get("/api/mobile/devices")
def get_mobile_devices(user: User = Depends(resolve_user)):
    with Session(engine) as db:
        return JSONResponse({"devices": list_devices(db, user.id)})


@router.delete("/api/mobile/devices/{device_id}")
def delete_mobile_device(device_id: str, user: User = Depends(resolve_user)):
    try:
        did = uuid.UUID(device_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad device id")
    with Session(engine) as db:
        ok = revoke_device(db, user.id, did)
        if not ok:
            raise HTTPException(status_code=404, detail="device not found")
        db.commit()
    return JSONResponse({"ok": True})
