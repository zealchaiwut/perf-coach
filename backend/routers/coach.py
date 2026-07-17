"""coach.py — Routes for /api/coach/* (issues #1501, #1504)."""
from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from backend.auth import resolve_user
from backend.db import engine
from backend.models import PerformanceGoal

router = APIRouter()

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
        if d <= _date.today():
            raise ValueError("race_date must be a future date")
        return v


@router.get("/api/coach/goal")
async def get_active_goal(request: Request):
    user = await resolve_user(request)
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
async def put_active_goal(body: _GoalBody, request: Request):
    user = await resolve_user(request)
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
    return JSONResponse(_goal_dict(goal))


@router.get("/api/coach/weekly-message")
async def get_weekly_message(request: Request):
    """Return the latest weekly coaching message for the authenticated user."""
    user = await resolve_user(request)
    from backend.services.weekly_coach_message import get_latest_for_user
    with Session(engine) as db:
        message = get_latest_for_user(user_id=user.id, db=db)
    if message is None:
        return JSONResponse({"message": None})
    return JSONResponse({"message": message})


@router.get("/api/coach/weekly-messages")
async def get_weekly_messages(
    request: Request,
    limit: int = Query(default=10, ge=1, le=52),
):
    """Return up to `limit` weekly coaching messages newest-first."""
    user = await resolve_user(request)
    from backend.services.weekly_coach_message import get_history_for_user
    with Session(engine) as db:
        messages = get_history_for_user(user_id=user.id, limit=limit, db=db)
    return JSONResponse({"messages": messages})
