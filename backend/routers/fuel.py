"""fuel.py — routes for /api/fuel/* (Weight tab: Fuel today + Fuel week).

All arithmetic is delegated to backend.services.fuel; no raw ORM calls or
formulas live here. See docs/calculations/fuel.md.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from backend.auth import resolve_user
from backend.db import engine
from backend.models import FuelEntry, WeightEntry
from backend.services import fuel as _svc
from backend.services import weight_plans_repo as _wp_repo

router = APIRouter()


def _parse_date(value: Optional[str], *, param: str) -> _date:
    if not value:
        return _date.today()
    try:
        return _date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{param} must be ISO format YYYY-MM-DD")


# ── Request bodies ───────────────────────────────────────────────────────────

class _EntryBody(BaseModel):
    entry_date: Optional[str] = None
    meat_g: Optional[int] = None
    rice_g: Optional[int] = None
    eggs: Optional[int] = None
    fruit_g: Optional[int] = None
    oil_tsp: Optional[float] = None
    other_kcal: Optional[int] = None
    other_protein_g: Optional[float] = None
    other_carbs_g: Optional[float] = None
    other_fat_g: Optional[float] = None

    @validator("entry_date")
    def _validate_date(cls, v):  # noqa: N805
        if v is None:
            return v
        try:
            _date.fromisoformat(v)
        except ValueError:
            raise ValueError("entry_date must be ISO format YYYY-MM-DD")
        return v

    @validator("meat_g", "rice_g", "eggs", "fruit_g", "other_kcal")
    def _non_negative_int(cls, v):  # noqa: N805
        if v is not None and v < 0:
            raise ValueError("must be non-negative")
        return v

    @validator("oil_tsp", "other_protein_g", "other_carbs_g", "other_fat_g")
    def _non_negative_float(cls, v):  # noqa: N805
        if v is not None and v < 0:
            raise ValueError("must be non-negative")
        return v


class _SettingsBody(BaseModel):
    weight_kg: Optional[float] = None
    lean_mass_kg: Optional[float] = None
    base_kcal: Optional[int] = None
    deficit_kcal: Optional[int] = None
    protein_g_per_kg: Optional[float] = None
    fat_g: Optional[int] = None
    ea_floor: Optional[float] = None
    run_kcal_per_kg_per_km: Optional[float] = None


# ── Fuel today ───────────────────────────────────────────────────────────────

def _settings_payload(user_id, db) -> dict:
    """Build the full fuel settings payload including plan linkage fields."""
    settings_row = _svc.get_or_create_settings(user_id, db=db)
    active_plan = _wp_repo.get_active_plan(db, user_id)
    payload = _svc.settings_to_dict(settings_row)
    payload.update(_svc.plan_linkage(active_plan, settings_row.deficit_kcal))
    return payload


@router.get("/api/fuel/settings")
async def get_fuel_settings(request: Request):
    user = await resolve_user(request)
    with Session(engine) as db:
        return JSONResponse(_settings_payload(user.id, db))


@router.get("/api/fuel/today")
async def get_fuel_today(request: Request, date: Optional[str] = None):
    user = await resolve_user(request)
    target_date = _parse_date(date, param="date")
    with Session(engine) as db:
        return JSONResponse(_svc.get_today_payload(user.id, target_date, db=db))


@router.put("/api/fuel/entry")
async def put_fuel_entry(body: _EntryBody, request: Request):
    user = await resolve_user(request)
    entry_date = _parse_date(body.entry_date, param="entry_date")
    fields = body.dict(exclude={"entry_date"}, exclude_unset=True)
    with Session(engine) as db:
        _svc.upsert_entry(user.id, entry_date, db=db, **fields)
        return JSONResponse(_svc.get_today_payload(user.id, entry_date, db=db))


@router.put("/api/fuel/settings")
async def put_fuel_settings(body: _SettingsBody, request: Request):
    user = await resolve_user(request)
    fields = body.dict(exclude_unset=True)
    with Session(engine) as db:
        try:
            _svc.update_settings(user.id, db=db, **fields)
        except _svc.SettingsValidationError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return JSONResponse(_svc.get_today_payload(user.id, _date.today(), db=db))


@router.post("/api/fuel/settings/sync-deficit")
async def post_fuel_sync_deficit(request: Request):
    """AC3: set deficit_kcal to the implied value from the active weight plan.

    Returns 409 when no active plan exists.
    """
    user = await resolve_user(request)
    with Session(engine) as db:
        active_plan = _wp_repo.get_active_plan(db, user.id)
        if active_plan is None or active_plan.target_rate_kg_per_week is None:
            raise HTTPException(status_code=409, detail="no_active_plan")
        new_deficit = _svc.implied_deficit_kcal(float(active_plan.target_rate_kg_per_week))
        _svc.update_settings(user.id, db=db, deficit_kcal=new_deficit)
        return JSONResponse(_settings_payload(user.id, db))


@router.post("/api/fuel/calibrate")
async def post_fuel_calibrate(request: Request):
    user = await resolve_user(request)
    with Session(engine) as db:
        from datetime import timedelta
        window_start = _date.today() - timedelta(days=_svc.CALIBRATE_MIN_DAYS + 7)

        weight_rows = (
            db.query(WeightEntry)
            .filter(WeightEntry.user_id == user.id, WeightEntry.entry_date >= window_start)
            .order_by(WeightEntry.entry_date.asc())
            .all()
        )
        # One weight per day (last entry of the day if multiple).
        by_day = {}
        for w in weight_rows:
            by_day[w.entry_date] = float(w.weight_kg)
        weight_entries = sorted(by_day.items())

        entry_rows = (
            db.query(FuelEntry)
            .filter(FuelEntry.user_id == user.id, FuelEntry.entry_date >= window_start)
            .order_by(FuelEntry.entry_date.asc())
            .all()
        )
        settings = _svc.settings_to_dict(_svc.get_or_create_settings(user.id, db=db))
        fuel_entries_and_burn = []
        for e in entry_rows:
            eaten = _svc.compute_food_totals(e)["kcal"]
            burn_info = _svc.training_burn_kcal(
                user.id, e.entry_date, settings["weight_kg"], settings["run_kcal_per_kg_per_km"],
                today=_date.today(), db=db,
            )
            fuel_entries_and_burn.append((e.entry_date, eaten, settings["base_kcal"], burn_info["burn"]))

        try:
            result = _svc.calibrate(weight_entries, fuel_entries_and_burn)
        except _svc.CalibrateNeedsMoreData as e:
            return JSONResponse(
                status_code=422,
                content={
                    "error_code": "needs_more_data",
                    "days_logged": e.days_logged,
                    "entries_logged": e.entries_logged,
                    "required_days": _svc.CALIBRATE_MIN_DAYS,
                    "required_entries": _svc.CALIBRATE_MIN_ENTRIES,
                },
            )

        _svc.update_settings(
            user.id, db=db, base_kcal=result["new_base_kcal"], maintenance_source="measured",
        )
        return JSONResponse(result)


# ── Fuel week ────────────────────────────────────────────────────────────────

@router.get("/api/fuel/week")
async def get_fuel_week(request: Request, week_start: Optional[str] = None):
    user = await resolve_user(request)
    ws = _parse_date(week_start, param="week_start")
    with Session(engine) as db:
        return JSONResponse(_svc.get_week_payload(user.id, ws, db=db))
