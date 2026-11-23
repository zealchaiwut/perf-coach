"""Conditional GET for Log-tab range endpoints (#1921)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any, Optional, Sequence

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import LoadPlanWeekSnapshot, PlannedSession, Race, RevampLoadSettings, Workout

CACHE_CONTROL = "private, no-cache"


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def make_etag(*parts: Any) -> str:
    raw = "|".join(_iso(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f'"{digest}"'


def max_range_updated_at(
    session: Session,
    user_id,
    range_start: date,
    range_end: date,
) -> tuple[Any, Any]:
    """MAX(updated_at/created_at) for workouts and planned sessions in range."""
    workout_max = (
        session.query(func.max(func.coalesce(Workout.updated_at, Workout.created_at)))
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= range_start,
            Workout.workout_date <= range_end,
        )
        .scalar()
    )
    planned_max = (
        session.query(func.max(func.coalesce(PlannedSession.updated_at, PlannedSession.created_at)))
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= range_start,
            PlannedSession.planned_date <= range_end,
        )
        .scalar()
    )
    return workout_max, planned_max


def range_etag(
    session: Session,
    user_id,
    range_start: date,
    range_end: date,
    today: date,
    params: str,
) -> str:
    w_max, p_max = max_range_updated_at(session, user_id, range_start, range_end)
    return make_etag(user_id, params, range_start, range_end, today, w_max, p_max)


def revamp_week_etag(
    session: Session,
    user_id,
    today: date,
    week_start: date,
    sections: Sequence[str],
) -> str:
    """ETag for GET /api/plan/revamp-week (#1931). Reuses make_etag from #1921."""
    week_end = week_start + timedelta(days=6)
    w_max, p_max = max_range_updated_at(session, user_id, week_start, week_end)
    settings = session.get(RevampLoadSettings, user_id)
    settings_at = getattr(settings, "updated_at", None) if settings is not None else None
    race_max = (
        session.query(func.max(func.coalesce(Race.updated_at, Race.created_at)))
        .filter(Race.user_id == user_id)
        .scalar()
    )
    snap_max = (
        session.query(func.max(LoadPlanWeekSnapshot.created_at))
        .filter(LoadPlanWeekSnapshot.user_id == user_id)
        .scalar()
    )
    return make_etag(
        user_id,
        today,
        ",".join(sections),
        week_start,
        w_max,
        p_max,
        settings_at,
        race_max,
        snap_max,
    )


def etag_headers(etag: str) -> dict[str, str]:
    return {"ETag": etag, "Cache-Control": CACHE_CONTROL}


def not_modified(request: Request, etag: str) -> bool:
    inm = request.headers.get("if-none-match")
    return bool(inm) and inm == etag


def not_modified_response(etag: str) -> Response:
    return Response(status_code=304, headers=etag_headers(etag))
