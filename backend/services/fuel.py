"""Fuel (calorie budget) service — see docs/calculations/fuel.md.

Exposes:
  get_or_create_settings(user_id) / update_settings(user_id, **fields)
  get_or_create_entry(user_id, entry_date) / upsert_entry(user_id, entry_date, **fields)
  compute_food_totals(entry)                — pure: kcal + macros from the 5 rows + other_*
  training_burn_kcal(user_id, target_date, db=None) — §2.2 burn estimate
  compute_day_type(sessions)                 — pure: rest | lift | easy_run | long_run
  compute_budget(settings, burn)             — pure: §1.3 budget + EA-floor guard
  compute_targets(settings, budget)          — pure: protein/carb/fat targets
  compute_suggestion(settings, targets, eaten) — pure: §1.6 fill-protein-then-carbs
  get_today_payload(user_id, target_date, db=None)
  get_week_payload(user_id, week_start, db=None)
  calibrate(user_id, db=None)                — §1.5

Every number here is an ESTIMATE, never a fact — see fuel.md §0. Maintenance
was falsified once for this athlete (5 flat weeks vs a Mifflin-St Jeor
prediction ~700 kcal/day off); the calibrate flow exists to correct that,
not to make the estimate look more authoritative than it is.
"""
from __future__ import annotations

from datetime import date as _date, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as _pg_insert

from backend.db import engine
from backend.models import FuelSettings, FuelEntry, Workout, PlannedSession
from backend.services.training_load import (
    _planned_duration_minutes,
    estimate_historical_pace_and_tss,
    estimate_planned_session_metrics,
)

# ── Food coefficients — per gram, COOKED weight (except eggs: per egg; oil:
# per tsp). Approximations (±10-15% error), deliberately chosen over a food
# database for a 5-row benchmark — see fuel.md. Meat/rice are COOKED
# weight: raw→cooked is a ~25% error on the biggest protein source.
FOOD = {
    "meat":  {"kcal": 1.65, "p": 0.310, "c": 0.000, "f": 0.036},  # lean: chicken breast, pork loin
    "rice":  {"kcal": 1.30, "p": 0.027, "c": 0.280, "f": 0.003},
    "egg":   {"kcal": 70.0, "p": 6.300, "c": 0.400, "f": 5.000},  # per whole egg (~50 g)
    "fruit": {"kcal": 0.60, "p": 0.008, "c": 0.150, "f": 0.002},
    "oil":   {"kcal": 45.0, "p": 0.000, "c": 0.000, "f": 5.000},  # per teaspoon
}

# ── MET table for non-run burn (run uses distance x mass instead — see
# training_burn_kcal). Approximations; adjust per-user via run_kcal_per_kg_per_km
# for runs, there is no per-user override for these yet (see fuel.md "Known
# weaknesses").
MET_TABLE = {
    "lift": 5.0,
    "strength": 5.0,
    "plyo": 8.0,
    "bike": 8.0,
    "wod": 8.0,
    "rest": 0.0,
}
_MET_FALLBACK = 5.0  # unrecognized workout_type — generic moderate activity

_LONG_RUN_MINUTES = 75  # mirrors training_load._RUN_DURATION_BUCKETS' "long" bucket

# Validation ranges (see §3 — never let settings imply an unsafe deficit or
# protein target).
DEFICIT_KCAL_MAX = 750
PROTEIN_G_PER_KG_MAX = 2.5
PROTEIN_G_PER_KG_MIN = 0.25

CALIBRATE_MIN_DAYS = 14
CALIBRATE_MIN_ENTRIES = 10
_KCAL_PER_KG = 7700


def _normalize_type(workout_type: Optional[str]) -> str:
    t = (workout_type or "").lower().strip()
    if t.startswith("run") or t == "race":
        return "run"
    if t.startswith("lift") or t.startswith("strength"):
        return "lift"
    if t.startswith("bike") or t.startswith("ride") or t.startswith("cycl"):
        return "bike"
    if t.startswith("wod") or t.startswith("crossfit"):
        return "wod"
    return t


# ── Settings ─────────────────────────────────────────────────────────────────

def _default_settings_dict(user_id) -> dict:
    return {
        "user_id": user_id,
        "weight_kg": 70.0,
        "lean_mass_kg": None,
        "base_kcal": 2000,
        "maintenance_source": "estimated",
        "deficit_kcal": 300,
        "protein_g_per_kg": 2.0,
        "fat_g": 70,
        "ea_floor": 30.0,
        "run_kcal_per_kg_per_km": 1.0,
    }


def get_or_create_settings(user_id, db: Optional[Session] = None) -> FuelSettings:
    owns_db = db is None
    db = db or Session(engine)
    try:
        row = db.query(FuelSettings).filter(FuelSettings.user_id == user_id).first()
        if row is None:
            row = FuelSettings(**_default_settings_dict(user_id))
            db.add(row)
            db.commit()
            db.refresh(row)
        return row
    finally:
        if owns_db:
            db.close()


class SettingsValidationError(ValueError):
    pass


def validate_settings_fields(fields: dict) -> None:
    deficit = fields.get("deficit_kcal")
    if deficit is not None and (deficit < 0 or deficit > DEFICIT_KCAL_MAX):
        raise SettingsValidationError(
            f"deficit_kcal must be between 0 and {DEFICIT_KCAL_MAX} "
            "(0.25-0.75% bodyweight/week loss)"
        )
    ppk = fields.get("protein_g_per_kg")
    if ppk is not None and (ppk < PROTEIN_G_PER_KG_MIN or ppk > PROTEIN_G_PER_KG_MAX):
        raise SettingsValidationError(
            f"protein_g_per_kg must be between {PROTEIN_G_PER_KG_MIN} and "
            f"{PROTEIN_G_PER_KG_MAX} g/kg protein"
        )


def update_settings(user_id, db: Optional[Session] = None, **fields) -> FuelSettings:
    validate_settings_fields(fields)
    owns_db = db is None
    db = db or Session(engine)
    try:
        row = get_or_create_settings(user_id, db=db)
        for k, v in fields.items():
            if v is not None:
                setattr(row, k, v)
        db.commit()
        db.refresh(row)
        return row
    finally:
        if owns_db:
            db.close()


def settings_to_dict(s: FuelSettings) -> dict:
    return {
        "weight_kg": float(s.weight_kg),
        "lean_mass_kg": float(s.lean_mass_kg) if s.lean_mass_kg is not None else round(float(s.weight_kg) * 0.76, 1),
        "base_kcal": s.base_kcal,
        "maintenance_source": s.maintenance_source,
        "deficit_kcal": s.deficit_kcal,
        "protein_g_per_kg": float(s.protein_g_per_kg),
        "fat_g": s.fat_g,
        "ea_floor": float(s.ea_floor),
        "run_kcal_per_kg_per_km": float(s.run_kcal_per_kg_per_km),
    }


# ── Entries ──────────────────────────────────────────────────────────────────

_ENTRY_FIELDS = (
    "meat_g", "rice_g", "eggs", "fruit_g", "oil_tsp",
    "other_kcal", "other_protein_g", "other_carbs_g", "other_fat_g",
)


def get_entry(user_id, entry_date: _date, db: Optional[Session] = None) -> Optional[FuelEntry]:
    owns_db = db is None
    db = db or Session(engine)
    try:
        return (
            db.query(FuelEntry)
            .filter(FuelEntry.user_id == user_id, FuelEntry.entry_date == entry_date)
            .first()
        )
    finally:
        if owns_db:
            db.close()


def upsert_entry(user_id, entry_date: _date, db: Optional[Session] = None, **fields) -> FuelEntry:
    """Upsert today's fuel_entries row — two PUTs for the same date produce
    ONE row (uq_fuel_entries_user_date + ON CONFLICT DO UPDATE)."""
    owns_db = db is None
    db = db or Session(engine)
    try:
        values = {"user_id": user_id, "entry_date": entry_date}
        for f in _ENTRY_FIELDS:
            if f in fields and fields[f] is not None:
                values[f] = fields[f]
        conflict_updates = {f: values[f] for f in _ENTRY_FIELDS if f in values}
        conflict_updates["updated_at"] = _now_text()
        stmt = (
            _pg_insert(FuelEntry)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["user_id", "entry_date"],
                set_=conflict_updates,
            )
            .returning(FuelEntry.__table__.c.id)
        )
        row_id = db.execute(stmt).scalar_one()
        db.commit()
        return db.query(FuelEntry).filter(FuelEntry.id == row_id).first()
    finally:
        if owns_db:
            db.close()


def _now_text():
    from sqlalchemy import text as _text
    return _text("now()")


def compute_food_totals(entry: Optional[FuelEntry]) -> dict:
    """kcal + macros eaten today from the 5 tracked rows + other_*. Pure."""
    if entry is None:
        return {"kcal": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    meat_g = entry.meat_g or 0
    rice_g = entry.rice_g or 0
    eggs = entry.eggs or 0
    fruit_g = entry.fruit_g or 0
    oil_tsp = float(entry.oil_tsp or 0)

    kcal = (
        meat_g * FOOD["meat"]["kcal"] + rice_g * FOOD["rice"]["kcal"]
        + eggs * FOOD["egg"]["kcal"] + fruit_g * FOOD["fruit"]["kcal"]
        + oil_tsp * FOOD["oil"]["kcal"] + (entry.other_kcal or 0)
    )
    protein_g = (
        meat_g * FOOD["meat"]["p"] + rice_g * FOOD["rice"]["p"]
        + eggs * FOOD["egg"]["p"] + fruit_g * FOOD["fruit"]["p"]
        + oil_tsp * FOOD["oil"]["p"] + float(entry.other_protein_g or 0)
    )
    carbs_g = (
        meat_g * FOOD["meat"]["c"] + rice_g * FOOD["rice"]["c"]
        + eggs * FOOD["egg"]["c"] + fruit_g * FOOD["fruit"]["c"]
        + oil_tsp * FOOD["oil"]["c"] + float(entry.other_carbs_g or 0)
    )
    fat_g = (
        meat_g * FOOD["meat"]["f"] + rice_g * FOOD["rice"]["f"]
        + eggs * FOOD["egg"]["f"] + fruit_g * FOOD["fruit"]["f"]
        + oil_tsp * FOOD["oil"]["f"] + float(entry.other_fat_g or 0)
    )
    return {
        "kcal": round(kcal),
        "protein_g": round(protein_g, 1),
        "carbs_g": round(carbs_g, 1),
        "fat_g": round(fat_g, 1),
    }


# ── Day type + burn ──────────────────────────────────────────────────────────

def compute_day_type(sessions: list) -> str:
    """sessions: list of {"type": <normalized-or-raw workout_type str>,
    "duration_min": float|None}. rest | lift | easy_run | long_run."""
    if not sessions:
        return "rest"
    run_minutes = 0.0
    saw_run = False
    saw_other = False
    for s in sessions:
        wt = _normalize_type(s.get("type"))
        if wt == "run":
            saw_run = True
            run_minutes = max(run_minutes, float(s.get("duration_min") or 0))
        elif wt != "rest":
            saw_other = True
    if saw_run:
        return "long_run" if run_minutes >= _LONG_RUN_MINUTES else "easy_run"
    if saw_other:
        return "lift"
    return "rest"


def _workout_burn_kcal(w: Workout, weight_kg: float, run_kcal_per_kg_per_km: float) -> float:
    wt = _normalize_type(w.workout_type)
    if wt == "run":
        dist = float(w.distance_km or 0)
        return weight_kg * dist * run_kcal_per_kg_per_km
    dur_min = (w.duration_seconds or 0) / 60.0
    met = MET_TABLE.get(wt, _MET_FALLBACK)
    return dur_min * met * weight_kg / 60.0


def _planned_burn_kcal(p: PlannedSession, weight_kg: float, run_kcal_per_kg_per_km: float, baseline: dict) -> float:
    wt = _normalize_type(p.session_type)
    if wt == "run":
        est = estimate_planned_session_metrics(baseline, p.session_type, p.structure)
        dist = est.get("estimated_distance_km") or 0.0
        return weight_kg * dist * run_kcal_per_kg_per_km
    dur_min = _planned_duration_minutes(p.session_type, p.structure) or 0.0
    met = MET_TABLE.get(wt, _MET_FALLBACK)
    return dur_min * met * weight_kg / 60.0


def _logged_sessions_and_burn(user_id, target_date: _date, weight_kg: float,
                               run_kcal_per_kg_per_km: float, db: Session) -> tuple:
    workouts = (
        db.query(Workout)
        .filter(Workout.user_id == user_id, Workout.workout_date == target_date)
        .all()
    )
    sessions = [
        {"type": w.workout_type, "duration_min": (w.duration_seconds or 0) / 60.0}
        for w in workouts
    ]
    burn = sum(_workout_burn_kcal(w, weight_kg, run_kcal_per_kg_per_km) for w in workouts)
    return sessions, burn, bool(workouts)


def _planned_sessions_and_burn(user_id, target_date: _date, weight_kg: float,
                                run_kcal_per_kg_per_km: float, baseline: dict, db: Session) -> tuple:
    planned = (
        db.query(PlannedSession)
        .filter(PlannedSession.user_id == user_id, PlannedSession.planned_date == target_date)
        .all()
    )
    non_rest = [p for p in planned if _normalize_type(p.session_type) != "rest"]
    sessions = [
        {"type": p.session_type, "duration_min": _planned_duration_minutes(p.session_type, p.structure)}
        for p in non_rest
    ]
    burn = sum(_planned_burn_kcal(p, weight_kg, run_kcal_per_kg_per_km, baseline) for p in non_rest)
    return sessions, burn, bool(non_rest)


def _day_sessions_and_burn(
    user_id, target_date: _date, today: _date, weight_kg: float,
    run_kcal_per_kg_per_km: float, baseline: dict, db: Session,
) -> tuple:
    """Returns (sessions_for_day_type, burn_kcal, session_status). Past days
    (< today) read logged workouts; today reads logged workouts if any exist
    (session already done), else the plan; future reads the plan — see
    fuel.md §"Past vs. future".

    A PAST day with no logged workout but a non-rest planned session that
    was never matched/done is a SKIPPED session: it must not keep granting
    calories it never earned, so it gets the rest-day budget (burn=0), not
    the plan's estimated burn."""
    if target_date <= today:
        sessions, burn, has_logged = _logged_sessions_and_burn(
            user_id, target_date, weight_kg, run_kcal_per_kg_per_km, db,
        )
        if has_logged:
            return sessions, burn, "done"

        p_sessions, p_burn, has_planned = _planned_sessions_and_burn(
            user_id, target_date, weight_kg, run_kcal_per_kg_per_km, baseline, db,
        )
        if not has_planned:
            return [], 0.0, None
        if target_date < today:
            return [], 0.0, "skipped"
        return p_sessions, p_burn, "planned"  # today, not yet done — use the plan's estimate.

    sessions, burn, has_planned = _planned_sessions_and_burn(
        user_id, target_date, weight_kg, run_kcal_per_kg_per_km, baseline, db,
    )
    return sessions, burn, ("planned" if has_planned else None)


def training_burn_kcal(
    user_id, target_date: _date, weight_kg: float, run_kcal_per_kg_per_km: float,
    today: Optional[_date] = None, db: Optional[Session] = None,
) -> dict:
    """§2.2 burn estimate for one date. Returns {"burn": float, "day_type":
    str, "session_status": str|None, "is_actual": bool}."""
    today = today or _date.today()
    owns_db = db is None
    db = db or Session(engine)
    try:
        baseline = estimate_historical_pace_and_tss(str(user_id), db=db)
        sessions, burn, status = _day_sessions_and_burn(
            user_id, target_date, today, weight_kg, run_kcal_per_kg_per_km, baseline, db,
        )
        day_type = compute_day_type(sessions)
        return {
            "burn": round(burn),
            "day_type": day_type,
            "session_status": status,
            "is_actual": target_date < today or (target_date == today and status == "done"),
        }
    finally:
        if owns_db:
            db.close()


# ── Budget (§1.3) ─────────────────────────────────────────────────────────────

def compute_budget(settings: dict, burn: float) -> dict:
    """base + burn - deficit, floored at the energy-availability minimum.
    The EA floor is a HARD STOP: when it binds, the deficit is reduced
    (never the athlete's choice) — see fuel.md / spec §1.3."""
    base_kcal = settings["base_kcal"]
    deficit_kcal = settings["deficit_kcal"]
    lean_mass_kg = settings["lean_mass_kg"]
    ea_floor = settings["ea_floor"]

    raw_budget = base_kcal + burn - deficit_kcal
    ea_floor_kcal = ea_floor * lean_mass_kg + burn
    budget = max(raw_budget, ea_floor_kcal)
    deficit_applied = base_kcal + burn - budget
    deficit_reduced = budget > raw_budget

    ea = (budget - burn) / lean_mass_kg if lean_mass_kg else None

    return {
        "budget": round(budget),
        "deficit_target": deficit_kcal,
        "deficit_applied": round(deficit_applied),
        "deficit_reduced": deficit_reduced,
        "ea": round(ea, 1) if ea is not None else None,
        "ea_floor_kcal": round(ea_floor_kcal),
    }


def compute_targets(settings: dict, budget: float) -> dict:
    """Protein is identical every day (fixed, g/kg); carbs are the dial —
    they scale with the budget (i.e. with training load)."""
    protein_g = round(settings["weight_kg"] * settings["protein_g_per_kg"])
    fat_g = settings["fat_g"]
    carbs_g = max(0.0, (budget - protein_g * 4 - fat_g * 9) / 4)
    return {"protein_g": protein_g, "carbs_g": round(carbs_g), "fat_g": fat_g}


# ── Suggestion (§1.6) ────────────────────────────────────────────────────────

def compute_suggestion(targets: dict, eaten: dict, remaining_kcal: float) -> dict:
    """Fill protein first, then carbs; round to plate-sized portions. Never
    renders a negative portion — spec §1.6/§3."""
    if remaining_kcal <= 0:
        return {"meat_g": 0, "rice_g": 0, "closes_protein_g": 0, "closes_carbs_g": 0, "text": None,
                "message": "Budget spent — fine on a long-run day if protein is met."}

    need_p = max(0.0, targets["protein_g"] - eaten["protein_g"])
    need_c = max(0.0, targets["carbs_g"] - eaten["carbs_g"])

    meat_g = round(need_p / FOOD["meat"]["p"] / 25) * 25 if need_p > 0 else 0
    rice_g = round(need_c / FOOD["rice"]["c"] / 50) * 50 if need_c > 0 else 0

    suggested_kcal = meat_g * FOOD["meat"]["kcal"] + rice_g * FOOD["rice"]["kcal"]
    if suggested_kcal > remaining_kcal and suggested_kcal > 0:
        scale = remaining_kcal / suggested_kcal
        meat_g = max(0, round(meat_g * scale / 25) * 25)
        rice_g = max(0, round(rice_g * scale / 50) * 50)

    closes_p = round(meat_g * FOOD["meat"]["p"])
    closes_c = round(rice_g * FOOD["rice"]["c"])
    text = f"{meat_g} g meat · {rice_g} g rice → closes {closes_p} g protein · {closes_c} g carbs"
    return {"meat_g": meat_g, "rice_g": rice_g, "closes_protein_g": closes_p, "closes_carbs_g": closes_c,
            "text": text, "message": None}


# ── Today payload ────────────────────────────────────────────────────────────

def get_today_payload(user_id, target_date: _date, db: Optional[Session] = None) -> dict:
    owns_db = db is None
    db = db or Session(engine)
    try:
        settings_row = get_or_create_settings(user_id, db=db)
        settings = settings_to_dict(settings_row)

        burn_info = training_burn_kcal(
            user_id, target_date, settings["weight_kg"], settings["run_kcal_per_kg_per_km"],
            today=_date.today(), db=db,
        )
        budget_info = compute_budget(settings, burn_info["burn"])
        targets = compute_targets(settings, budget_info["budget"])

        entry = get_entry(user_id, target_date, db=db)
        eaten = compute_food_totals(entry)
        remaining = max(0, budget_info["budget"] - eaten["kcal"])

        suggestion = compute_suggestion(targets, eaten, remaining)

        return {
            "date": target_date.isoformat(),
            "day_type": burn_info["day_type"],
            "burn": burn_info["burn"],
            "base_kcal": settings["base_kcal"],
            "budget": budget_info["budget"],
            "deficit_target": budget_info["deficit_target"],
            "deficit_applied": budget_info["deficit_applied"],
            "deficit_reduced": budget_info["deficit_reduced"],
            "ea": budget_info["ea"],
            "ea_floor_kcal": budget_info["ea_floor_kcal"],
            "eaten": eaten,
            "remaining": remaining,
            "targets": targets,
            "suggestion": suggestion,
            "maintenance_source": settings["maintenance_source"],
            "entry": {
                "meat_g": entry.meat_g if entry else 0,
                "rice_g": entry.rice_g if entry else 0,
                "eggs": entry.eggs if entry else 0,
                "fruit_g": entry.fruit_g if entry else 0,
                "oil_tsp": float(entry.oil_tsp) if entry else 0.0,
                "other_kcal": entry.other_kcal if entry else 0,
            },
        }
    finally:
        if owns_db:
            db.close()


# ── Week payload (Part 2) ────────────────────────────────────────────────────

def get_week_payload(user_id, week_start: _date, db: Optional[Session] = None) -> dict:
    owns_db = db is None
    db = db or Session(engine)
    try:
        settings_row = get_or_create_settings(user_id, db=db)
        settings = settings_to_dict(settings_row)
        today = _date.today()

        days = []
        weekly_budget_total = 0.0
        weekly_maintenance_total = 0.0
        for i in range(7):
            d = week_start + timedelta(days=i)
            burn_info = training_burn_kcal(
                user_id, d, settings["weight_kg"], settings["run_kcal_per_kg_per_km"],
                today=today, db=db,
            )
            budget_info = compute_budget(settings, burn_info["burn"])
            entry = get_entry(user_id, d, db=db)
            eaten = compute_food_totals(entry)

            weekly_budget_total += budget_info["budget"]
            weekly_maintenance_total += settings["base_kcal"] + burn_info["burn"]

            days.append({
                "date": d.isoformat(),
                "day_type": burn_info["day_type"],
                "burn": burn_info["burn"],
                "budget": budget_info["budget"],
                "eaten": eaten["kcal"],
                "is_actual": burn_info["is_actual"],
                "session_status": burn_info["session_status"],
            })

        weekly_deficit = weekly_maintenance_total - weekly_budget_total
        return {
            "week_start": week_start.isoformat(),
            "days": days,
            "weekly_budget_total": round(weekly_budget_total),
            "weekly_maintenance_total": round(weekly_maintenance_total),
            "projected_kg_per_week": round(weekly_deficit / _KCAL_PER_KG, 2),
        }
    finally:
        if owns_db:
            db.close()


# ── Calibrate (§1.5) ─────────────────────────────────────────────────────────

class CalibrateNeedsMoreData(Exception):
    def __init__(self, days_logged: int, entries_logged: int):
        self.days_logged = days_logged
        self.entries_logged = entries_logged
        super().__init__("needs_more_data")


def calibrate(weight_entries: list, fuel_entries_and_burn: list) -> dict:
    """Pure calculation given the caller's already-fetched inputs.

    weight_entries: list of (date, weight_kg) covering the last >=14 days.
    fuel_entries_and_burn: list of (date, eaten_kcal, base_kcal, burn_kcal)
        for each day a fuel_entries row exists in the last >=14 days.

    Uses WEEKLY-AVERAGE weights on both ends — daily weight is mostly
    glycogen/water and would produce garbage (spec §1.5).
    """
    days_span = len(weight_entries)
    n_entries = len(fuel_entries_and_burn)
    if days_span < CALIBRATE_MIN_DAYS or n_entries < CALIBRATE_MIN_ENTRIES:
        raise CalibrateNeedsMoreData(days_span, n_entries)

    weight_entries = sorted(weight_entries, key=lambda t: t[0])
    n = len(weight_entries)
    week_n = min(7, n)  # first/last CALENDAR week on each end, not entry count
    first_week = weight_entries[:week_n]
    last_week = weight_entries[-week_n:]
    weekly_avg_start = sum(w for _, w in first_week) / len(first_week)
    weekly_avg_end = sum(w for _, w in last_week) / len(last_week)
    actual_delta_kg = weekly_avg_end - weekly_avg_start

    total_delta_kcal = sum(eaten - (base + burn) for _, eaten, base, burn in fuel_entries_and_burn)
    predicted_delta_kg = total_delta_kcal / _KCAL_PER_KG

    days = len(fuel_entries_and_burn)
    error_kcal_per_day = (predicted_delta_kg - actual_delta_kg) * _KCAL_PER_KG / days

    base_kcal_sample = fuel_entries_and_burn[0][2]
    new_base_kcal = round(base_kcal_sample - error_kcal_per_day)

    return {
        "new_base_kcal": new_base_kcal,
        "predicted_delta_kg": round(predicted_delta_kg, 2),
        "actual_delta_kg": round(actual_delta_kg, 2),
        "error_kcal_per_day": round(error_kcal_per_day, 1),
        "maintenance_source": "measured",
    }
