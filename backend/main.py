import os
import uuid as _uuid
from datetime import date as _date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from backend.db import check_db, engine, environment
from backend.models import Habit, HabitLog, User, WeightEntry

__version__ = "0.1.0"

app = FastAPI()

# Serve static files (index.html, weight.html, habits.html, css/, js/)
_static_root = Path(__file__).parent.parent
app.mount("/css", StaticFiles(directory=str(_static_root / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(_static_root / "js")), name="js")


@app.get("/api/health")
def health():
    return JSONResponse({"status": "ok", "database": check_db(), "environment": environment})


@app.get("/api/environment")
def get_environment():
    return JSONResponse({"environment": environment, "version": __version__})


@app.get("/api/users")
def get_users():
    with Session(engine) as session:
        users = session.query(User).order_by(User.name).all()
        return JSONResponse([{"id": str(u.id), "name": u.name} for u in users])


# ── Weight endpoints (AC-1 through AC-4) ─────────────────────────────────────

class WeightEntryIn(BaseModel):
    weight_kg: float
    recorded_date: str  # YYYY-MM-DD


@app.get("/api/weight")
def get_weight(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        rows = (
            session.query(WeightEntry)
            .filter(WeightEntry.user_id == uid)
            .order_by(WeightEntry.recorded_date)
            .all()
        )
        return JSONResponse([
            {
                "id": str(r.id),
                "weight_kg": float(r.weight_kg),
                "recorded_date": str(r.recorded_date),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ])


@app.post("/api/weight", status_code=201)
def post_weight(user_id: str, body: WeightEntryIn):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        entry = WeightEntry(
            user_id=uid,
            weight_kg=body.weight_kg,
            recorded_date=body.recorded_date,
        )
        session.add(entry)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": "Entry exists for this date"},
            )
        session.refresh(entry)
        return JSONResponse(
            status_code=201,
            content={
                "id": str(entry.id),
                "weight_kg": float(entry.weight_kg),
                "recorded_date": str(entry.recorded_date),
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            },
        )


@app.delete("/api/weight/{entry_id}", status_code=204)
def delete_weight(entry_id: str):
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id")
    with Session(engine) as session:
        entry = session.get(WeightEntry, eid)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        session.delete(entry)
        session.commit()
    return Response(status_code=204)


# ── Habit endpoints ───────────────────────────────────────────────────────────

class HabitIn(BaseModel):
    user_id: str
    name: str


class HabitPatch(BaseModel):
    name: Optional[str] = None
    archived: Optional[bool] = None


class HabitLogIn(BaseModel):
    habit_id: str
    user_id: str
    logged_date: str  # YYYY-MM-DD


@app.get("/api/habits")
def get_habits(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        rows = (
            session.query(Habit)
            .filter(Habit.user_id == uid, Habit.archived_at.is_(None))
            .order_by(Habit.display_order, Habit.created_at)
            .all()
        )
        return JSONResponse([
            {
                "id": str(r.id),
                "name": r.name,
                "display_order": r.display_order,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ])


@app.post("/api/habits", status_code=201)
def post_habit(body: HabitIn):
    try:
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        habit = Habit(user_id=uid, name=body.name.strip())
        session.add(habit)
        session.commit()
        session.refresh(habit)
        return JSONResponse(
            status_code=201,
            content={
                "id": str(habit.id),
                "name": habit.name,
                "display_order": habit.display_order,
                "created_at": habit.created_at.isoformat() if habit.created_at else None,
            },
        )


@app.patch("/api/habits/{habit_id}")
def patch_habit(habit_id: str, body: HabitPatch):
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    with Session(engine) as session:
        habit = session.get(Habit, hid)
        if habit is None:
            raise HTTPException(status_code=404, detail="Habit not found")
        if body.name is not None:
            habit.name = body.name.strip()
        session.commit()
        session.refresh(habit)
        return JSONResponse({
            "id": str(habit.id),
            "name": habit.name,
            "display_order": habit.display_order,
        })


@app.delete("/api/habits/{habit_id}", status_code=204)
def delete_habit(habit_id: str):
    try:
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id")
    from datetime import datetime, timezone
    with Session(engine) as session:
        habit = session.get(Habit, hid)
        if habit is None:
            raise HTTPException(status_code=404, detail="Habit not found")
        habit.archived_at = datetime.now(timezone.utc)
        session.commit()
    return Response(status_code=204)


@app.get("/api/habits/logs")
def get_habit_logs(
    user_id: str,
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    try:
        from_d = _date.fromisoformat(from_date)
        to_d = _date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    with Session(engine) as session:
        rows = (
            session.query(HabitLog)
            .filter(
                HabitLog.user_id == uid,
                HabitLog.logged_date >= from_d,
                HabitLog.logged_date <= to_d,
            )
            .all()
        )
        return JSONResponse([
            {
                "id": str(r.id),
                "habit_id": str(r.habit_id),
                "user_id": str(r.user_id),
                "logged_date": str(r.logged_date),
            }
            for r in rows
        ])


@app.post("/api/habits/logs", status_code=201)
def post_habit_log(body: HabitLogIn):
    try:
        hid = _uuid.UUID(body.habit_id)
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid habit_id or user_id")
    with Session(engine) as session:
        log = HabitLog(habit_id=hid, user_id=uid, logged_date=body.logged_date)
        session.add(log)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": "Log already exists for this habit on this date"},
            )
        session.refresh(log)
        return JSONResponse(
            status_code=201,
            content={
                "id": str(log.id),
                "habit_id": str(log.habit_id),
                "user_id": str(log.user_id),
                "logged_date": str(log.logged_date),
            },
        )


@app.delete("/api/habits/logs/{log_id}", status_code=204)
def delete_habit_log(log_id: str):
    try:
        lid = _uuid.UUID(log_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid log_id")
    with Session(engine) as session:
        log = session.get(HabitLog, lid)
        if log is None:
            raise HTTPException(status_code=404, detail="Log not found")
        session.delete(log)
        session.commit()
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(str(_static_root / "index.html"))


@app.get("/weight.html")
def weight():
    return FileResponse(str(_static_root / "weight.html"))


@app.get("/habits.html")
def habits():
    return FileResponse(str(_static_root / "habits.html"))
