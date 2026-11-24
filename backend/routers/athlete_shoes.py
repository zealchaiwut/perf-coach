"""Athlete shoe CRUD (revamp P6-14)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import resolve_user
from backend.db import engine
from backend.models import AthleteShoe, User
from backend.services.athlete_shoes import default_shoe_id, list_shoes, recompute_shoe_stats, shoe_dict

router = APIRouter()


class _ShoeIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_race_shoe: bool = False
    retired: bool = False


class _ShoePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_race_shoe: bool | None = None
    retired: bool | None = None


@router.get("/api/athlete-shoes")
def get_athlete_shoes(user: User = Depends(resolve_user)):
    with Session(engine) as db:
        return JSONResponse({"shoes": list_shoes(db, user.id), "default_shoe_id": default_shoe_id(db, user.id)})


@router.post("/api/athlete-shoes", status_code=201)
def post_athlete_shoe(body: _ShoeIn, user: User = Depends(resolve_user)):
    with Session(engine) as db:
        row = AthleteShoe(user_id=user.id, name=body.name.strip(), is_race_shoe=body.is_race_shoe, retired=body.retired)
        db.add(row)
        db.commit()
        db.refresh(row)
        return JSONResponse(shoe_dict(row), status_code=201)


@router.patch("/api/athlete-shoes/{shoe_id}")
def patch_athlete_shoe(shoe_id: str, body: _ShoePatch, user: User = Depends(resolve_user)):
    try:
        sid = uuid.UUID(shoe_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid shoe_id") from None
    with Session(engine) as db:
        row = db.get(AthleteShoe, sid)
        if row is None:
            raise HTTPException(status_code=404, detail="Shoe not found")
        if row.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        if body.name is not None:
            row.name = body.name.strip()
        if body.is_race_shoe is not None:
            row.is_race_shoe = body.is_race_shoe
        if body.retired is not None:
            row.retired = body.retired
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        recompute_shoe_stats(db, user.id, row.id)
        db.commit()
        db.refresh(row)
        return JSONResponse(shoe_dict(row))
