"""coach.py — Routes for /api/coach/* (issues #1501, #1504)."""
from __future__ import annotations

import logging
from datetime import date as _date, datetime as _datetime, timezone as _timezone
from backend.utils.time import today_bangkok as _today_bangkok

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from backend.auth import resolve_user
from backend.db import engine
from backend.models import PerformanceGoal, User

router = APIRouter()

_log = logging.getLogger(__name__)

_VALID_DISTANCES = ("5k", "10k", "half", "marathon")


def _goal_dict(g: PerformanceGoal) -> dict:
    return {
        "id": str(g.id),
        "race_distance": g.race_distance,
        "target_time": g.target_time,
        "race_date": g.race_date.isoformat(),
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "active": g.active,
    }


class _GoalBody(BaseModel):
    race_distance: str
    target_time: int
    race_date: str

    @validator("race_distance")
    def _distance_valid(cls, v):  # noqa: N805
        if v not in _VALID_DISTANCES:
            raise ValueError(
                f"race_distance must be one of {_VALID_DISTANCES}, got {v!r}"
            )
        return v

    @validator("target_time")
    def _time_positive(cls, v):  # noqa: N805
        if v <= 0:
            raise ValueError("target_time must be a positive integer (seconds)")
        return v

    @validator("race_date")
    def _date_future(cls, v):  # noqa: N805
        try:
            d = _date.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError("race_date must be ISO format YYYY-MM-DD")
        if d <= _today_bangkok():
            raise ValueError("race_date must be a future date")
        return v


@router.get("/api/coach/goal")
async def get_active_goal(user: User = Depends(resolve_user)):
    with Session(engine) as db:
        goal = (
            db.query(PerformanceGoal)
            .filter(
                PerformanceGoal.user_id == user.id,
                PerformanceGoal.active.is_(True),
            )
            .first()
        )
    if goal is None:
        return JSONResponse({"goal": None})
    return JSONResponse({"goal": _goal_dict(goal)})


@router.put("/api/coach/goal")
async def put_active_goal(body: _GoalBody, user: User = Depends(resolve_user)):
    race_date = _date.fromisoformat(body.race_date)
    with Session(engine) as db:
        db.query(PerformanceGoal).filter(
            PerformanceGoal.user_id == user.id,
            PerformanceGoal.active.is_(True),
        ).update({"active": False})

        goal = PerformanceGoal(
            user_id=user.id,
            race_distance=body.race_distance,
            target_time=body.target_time,
            race_date=race_date,
            active=True,
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
    return JSONResponse({"goal": _goal_dict(goal)})


@router.get("/api/coach/brief")
async def get_coach_brief(
    date: str | None = Query(default=None, alias="date"), user: User = Depends(resolve_user)):
    """Return stored coach brief v4 JSON; build on demand if today's is missing."""
    from datetime import date as _date
    from backend.services.coach_brief import get_or_build_brief

    brief_date = None
    if date:
        try:
            brief_date = _date.fromisoformat(date)
        except ValueError:
            return JSONResponse(
                {"detail": {"date": "must be YYYY-MM-DD"}},
                status_code=422,
            )
    with Session(engine) as db:
        brief = get_or_build_brief(db, user.id, brief_date)
        if brief is not None:
            db.commit()
    if brief is None:
        return JSONResponse({"brief": None})
    return JSONResponse({"brief": brief})


@router.get("/api/coach/daily-message")
async def get_daily_message(user: User = Depends(resolve_user)):
    """Return the shared daily coach payload (sections + nudge) for Home / Hermes SoT."""
    from backend.services.weekly_coach_message import get_coach_payload_for_user
    with Session(engine) as db:
        payload = get_coach_payload_for_user(user_id=user.id, db=db)
    if payload is None:
        return JSONResponse({"message": None, "payload": None})
    return JSONResponse({"message": payload.get("message"), "payload": payload})


@router.get("/api/coach/weekly-message")
async def get_weekly_message(request: Request):
    """Compat alias — same as daily-message (legacy clients)."""
    return await get_daily_message(request)


@router.get("/api/coach/weekly-messages")
async def get_weekly_messages(
    limit: int = Query(default=10, ge=1, le=52), user: User = Depends(resolve_user)):
    """Return up to `limit` coaching messages newest-first."""
    from backend.services.weekly_coach_message import get_history_for_user
    with Session(engine) as db:
        messages = get_history_for_user(user_id=user.id, limit=limit, db=db)
    return JSONResponse({"messages": messages})


@router.get("/api/coach/daily-messages")
async def get_daily_messages(
    request: Request,
    limit: int = Query(default=10, ge=1, le=52),
):
    """Alias of weekly-messages history."""
    return await get_weekly_messages(request, limit=limit)


# ── Coach export (paste-to-Claude loop) ──────────────────────────────────────


def _reject_inline_coach_export_if_queued():
    """When COACH_EXPORT_VIA_QUEUE=1, inline GET export must fail closed (503).

    The nav uses POST /api/coach/export/jobs; allowing GET paste/consult on the
    thin web dyno would reintroduce the heavy in-process path Phase C removes.
    """
    from backend.services import worker_client as wc

    if wc.coach_export_via_queue_enabled():
        return JSONResponse(
            {
                "detail": (
                    "coach export via queue only (COACH_EXPORT_VIA_QUEUE=1); "
                    "use POST /api/coach/export/jobs"
                ),
            },
            status_code=503,
        )
    return None


@router.get("/api/coach/export")
async def get_coach_export(
    window: int = Query(default=None, alias="window"),
    user: User = Depends(resolve_user),
):
    """Return the coach-export payload alone, for inspection and tests.

    Pure assembly over services that already exist — no LLM call, no writes. The
    paste endpoint below is what the nav button uses when queue mode is off.
    """
    blocked = _reject_inline_coach_export_if_queued()
    if blocked is not None:
        return blocked

    from backend.services.coach_export import DEFAULT_WINDOW_DAYS, build_export

    window_days = DEFAULT_WINDOW_DAYS if window is None else window
    try:
        export = build_export(user.id, window_days=window_days)
    except ValueError as exc:
        return JSONResponse({"detail": {"window": str(exc)}}, status_code=422)
    return JSONResponse(export)


@router.get("/api/coach/export/paste", response_class=PlainTextResponse)
async def get_coach_export_paste(
    window: int = Query(default=None, alias="window"),
    user: User = Depends(resolve_user),
):
    """Return the complete paste blob: prompt template first, payload last.

    One request, one clipboard write — the client never assembles the blob, so a
    partial fetch can never be pasted as if it were whole. Serving this also
    stamps ``users.last_coach_export_at``, which the NEXT export reports as
    ``meta.previous_export_date`` so the coach message can skip a season
    re-check when nothing has moved.

    When ``COACH_EXPORT_VIA_QUEUE=1``, returns 503 — use the jobs path instead.
    """
    blocked = _reject_inline_coach_export_if_queued()
    if blocked is not None:
        return blocked

    from backend.services.coach_export import (
        DEFAULT_WINDOW_DAYS,
        build_export,
        build_paste_blob,
    )

    window_days = DEFAULT_WINDOW_DAYS if window is None else window
    try:
        export = build_export(user.id, window_days=window_days)
    except ValueError as exc:
        return JSONResponse({"detail": {"window": str(exc)}}, status_code=422)

    blob = build_paste_blob(export)

    # Stamped only after the blob is successfully built — a failed export must
    # not consume the "nothing moved since last time" signal.
    try:
        with Session(engine) as db:
            db.query(User).filter(User.id == user.id).update(
                {"last_coach_export_at": _datetime.now(_timezone.utc)}
            )
            db.commit()
    except Exception:
        _log.warning("failed to stamp last_coach_export_at", exc_info=True)

    return PlainTextResponse(blob, media_type="text/plain; charset=utf-8")


@router.get("/api/coach/consult", response_class=PlainTextResponse)
async def get_coach_consult(
    window: int = Query(default=None, alias="window"),
    user: User = Depends(resolve_user),
):
    """Return the consult blob: check-in template + the same export payload.

    The consult is the judgment layer and it lives outside the app by design —
    this endpoint just hands over the prompt and the data. Unlike the daily paste
    it does NOT stamp ``last_coach_export_at``: a check-in is a conversation, not
    the daily message, and consuming the "nothing moved since" signal here would
    silence the next day's season check.

    When ``COACH_EXPORT_VIA_QUEUE=1``, returns 503 — use the jobs path instead.
    """
    blocked = _reject_inline_coach_export_if_queued()
    if blocked is not None:
        return blocked

    from backend.services.coach_export import (
        DEFAULT_WINDOW_DAYS,
        build_consult_blob,
        build_export,
    )

    window_days = DEFAULT_WINDOW_DAYS if window is None else window
    try:
        export = build_export(user.id, window_days=window_days)
    except ValueError as exc:
        return JSONResponse({"detail": {"window": str(exc)}}, status_code=422)

    return PlainTextResponse(
        build_consult_blob(export), media_type="text/plain; charset=utf-8"
    )


# ── Coach export jobs (worker queue) ─────────────────────────────────────────


@router.get("/api/coach/export/queue-window")
async def get_coach_export_queue_window(user: User = Depends(resolve_user)):
    """Whether the worker's idle poll is currently in its fast-response window.

    QUEUE_POLL_FAST_WINDOWS must be set the same on the webapp and the worker
    (see backend.services.queue_window) — this endpoint doesn't reach the
    worker itself, it just evaluates the same config the worker uses, so the
    two must agree for the reported window to mean anything. nav.js uses this
    to warn before enqueuing a coach_export job outside those hours, when a
    check-in can take minutes instead of the usual ~10 seconds."""
    from backend.services.queue_window import window_status

    return JSONResponse(window_status())


class _CoachExportJobBody(BaseModel):
    kind: str = "consult"
    window: int | None = None

    @validator("kind")
    def _kind_valid(cls, v):  # noqa: N805
        if v not in ("paste", "consult"):
            raise ValueError("kind must be 'paste' or 'consult'")
        return v


def _coach_export_job_dict(row: dict) -> dict:
    result = row.get("result") or {}
    out = {
        "job_id": str(row["id"]),
        "status": row["status"],
        "error": row.get("error"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "started_at": row["started_at"].isoformat() if row.get("started_at") else None,
        "finished_at": row["finished_at"].isoformat() if row.get("finished_at") else None,
    }
    if row["status"] == "done" and isinstance(result, dict):
        out["char_count"] = result.get("char_count")
        out["built_at"] = result.get("built_at")
        out["degraded"] = result.get("degraded") or []
        out["kind"] = result.get("kind")
    return out


@router.post("/api/coach/export/jobs", status_code=202)
async def post_coach_export_job(
    body: _CoachExportJobBody,
    user: User = Depends(resolve_user),
):
    """Enqueue coach export on the compute worker; poll GET .../jobs/{id} for status."""
    from backend.services import worker_client as wc
    from backend.services.coach_export import (
        DEFAULT_WINDOW_DAYS,
        MAX_WINDOW_DAYS,
        MIN_WINDOW_DAYS,
    )

    if not wc.coach_export_via_queue_enabled():
        return JSONResponse(
            {"detail": "coach export queue disabled (COACH_EXPORT_VIA_QUEUE=0)"},
            status_code=503,
        )

    window_days = DEFAULT_WINDOW_DAYS if body.window is None else body.window
    if window_days < MIN_WINDOW_DAYS or window_days > MAX_WINDOW_DAYS:
        return JSONResponse(
            {"detail": {"window": f"must be between {MIN_WINDOW_DAYS} and {MAX_WINDOW_DAYS}"}},
            status_code=422,
        )

    try:
        res = wc.delegate_coach_export(str(user.id), kind=body.kind, window=window_days)
    except wc.WorkerUnavailable as exc:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    return JSONResponse({"job_id": res.get("job_id"), "status": "queued"}, status_code=202)


@router.get("/api/coach/export/jobs/{job_id}")
async def get_coach_export_job(job_id: str, user: User = Depends(resolve_user)):
    from backend.services import job_queue as jq

    row = jq.get_owned_job(job_id, str(user.id), job_type="coach_export")
    if row is None:
        return JSONResponse({"detail": "job not found"}, status_code=404)
    return JSONResponse(_coach_export_job_dict(row))


@router.get("/api/coach/export/jobs/{job_id}/blob", response_class=PlainTextResponse)
async def get_coach_export_job_blob(job_id: str, user: User = Depends(resolve_user)):
    from backend.services import job_queue as jq

    row = jq.get_owned_job(job_id, str(user.id), job_type="coach_export")
    if row is None:
        return JSONResponse({"detail": "job not found"}, status_code=404)
    if row["status"] != "done":
        return JSONResponse({"detail": f"job status is {row['status']}"}, status_code=409)
    result = row.get("result") or {}
    blob = result.get("blob")
    if not blob:
        return JSONResponse({"detail": "blob not available"}, status_code=404)
    return PlainTextResponse(blob, media_type="text/plain; charset=utf-8")