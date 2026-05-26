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
from backend.models import Habit, HabitLog, User, WeightEntry, Workout, WorkoutExercise

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
        result = []
        for u in users:
            wcount = session.query(WeightEntry).filter(WeightEntry.user_id == u.id).count()
            hcount = session.query(Habit).filter(Habit.user_id == u.id, Habit.archived_at.is_(None)).count()
            result.append({
                "id": str(u.id),
                "name": u.name,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "weight_count": wcount,
                "habits_count": hcount,
            })
        return JSONResponse(result)


# ── User management endpoints ─────────────────────────────────────────────────

class UserIn(BaseModel):
    name: str


@app.post("/api/users", status_code=201)
def create_user(body: UserIn):
    name = body.name.strip()
    if not (1 <= len(name) <= 100):
        raise HTTPException(status_code=400, detail="Name must be 1–100 characters")
    with Session(engine) as session:
        user = User(name=name)
        session.add(user)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(status_code=409, content={"error": "Name already exists"})
        session.refresh(user)
        return JSONResponse(
            status_code=201,
            content={
                "id": str(user.id),
                "name": user.name,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
        )


@app.patch("/api/users/{user_id}")
def rename_user(user_id: str, body: UserIn):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    name = body.name.strip()
    if not (1 <= len(name) <= 100):
        raise HTTPException(status_code=400, detail="Name must be 1–100 characters")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.name = name
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(status_code=409, content={"error": "Name already exists"})
        session.refresh(user)
        return JSONResponse({
            "id": str(user.id),
            "name": user.name,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        })


@app.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        total = session.query(User).count()
        if total <= 1:
            return JSONResponse(
                status_code=409,
                content={"error": "At least one user must exist"},
            )
        habit_ids = [h.id for h in session.query(Habit.id).filter(Habit.user_id == uid).all()]
        if habit_ids:
            session.query(HabitLog).filter(HabitLog.habit_id.in_(habit_ids)).delete(synchronize_session=False)
        session.query(HabitLog).filter(HabitLog.user_id == uid).delete(synchronize_session=False)
        session.query(Habit).filter(Habit.user_id == uid).delete(synchronize_session=False)
        session.query(WeightEntry).filter(WeightEntry.user_id == uid).delete(synchronize_session=False)
        session.delete(user)
        session.commit()
    return Response(status_code=204)


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


@app.get("/api/habits/stats")
def get_habit_stats(
    user_id: str,
    habit_id: str,
    days: int = Query(default=30, ge=1, le=365),
):
    try:
        uid = _uuid.UUID(user_id)
        hid = _uuid.UUID(habit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id or habit_id")

    from datetime import timedelta
    today = _date.today()
    window_start = today - timedelta(days=days - 1)

    with Session(engine) as session:
        window_logs = (
            session.query(HabitLog.logged_date)
            .filter(
                HabitLog.habit_id == hid,
                HabitLog.user_id == uid,
                HabitLog.logged_date >= window_start,
                HabitLog.logged_date <= today,
            )
            .all()
        )
        window_dates = {row.logged_date for row in window_logs}
        days_completed = len(window_dates)
        completion_rate = round(days_completed / days, 4)

        # STRICT streak: walk backwards from today.
        # If today not logged but yesterday is, today is "pending" (streak still active).
        check = today
        if check not in window_dates:
            yesterday = today - timedelta(days=1)
            if yesterday not in window_dates:
                return JSONResponse({
                    "streak": 0,
                    "completion_rate": completion_rate,
                    "days_completed": days_completed,
                    "days_total": days,
                })
            check = yesterday

        # Fetch all logs for this habit to count the full streak (may go beyond the window)
        all_logs = (
            session.query(HabitLog.logged_date)
            .filter(HabitLog.habit_id == hid, HabitLog.user_id == uid)
            .all()
        )
        all_dates = {row.logged_date for row in all_logs}

        streak = 0
        while check in all_dates:
            streak += 1
            check = check - timedelta(days=1)

        return JSONResponse({
            "streak": streak,
            "completion_rate": completion_rate,
            "days_completed": days_completed,
            "days_total": days,
        })


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


@app.get("/users.html")
def users_page():
    return FileResponse(str(_static_root / "users.html"))


# ── Workout endpoints ─────────────────────────────────────────────────────────

class ExerciseIn(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    duration: Optional[str] = None
    rpe: Optional[int] = None
    display_order: int = 0


class WorkoutIn(BaseModel):
    user_id: str
    name: str
    workout_date: str  # YYYY-MM-DD
    workout_type: str
    remarks: Optional[str] = None
    exercises: list[ExerciseIn] = []


class WorkoutPatch(BaseModel):
    name: Optional[str] = None
    workout_date: Optional[str] = None
    workout_type: Optional[str] = None
    remarks: Optional[str] = None
    exercises: Optional[list[ExerciseIn]] = None


def _exercise_dict(e: WorkoutExercise) -> dict:
    return {
        "id": str(e.id),
        "display_order": e.display_order,
        "name": e.name,
        "sets": e.sets,
        "reps": e.reps,
        "weight_kg": float(e.weight_kg) if e.weight_kg is not None else None,
        "duration": e.duration,
        "rpe": e.rpe,
    }


def _workout_dict(w: Workout, exercises: list) -> dict:
    return {
        "id": str(w.id),
        "user_id": str(w.user_id),
        "name": w.name,
        "workout_date": str(w.workout_date),
        "workout_type": w.workout_type,
        "remarks": w.remarks,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
        "exercises": [_exercise_dict(e) for e in exercises],
    }


@app.get("/api/workouts")
def get_workouts(user_id: str, days: int = Query(default=30, ge=1, le=365)):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    from datetime import timedelta, datetime, timezone
    cutoff = _date.today() - timedelta(days=days)
    with Session(engine) as session:
        workouts = (
            session.query(Workout)
            .filter(Workout.user_id == uid, Workout.workout_date >= cutoff)
            .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
            .all()
        )
        result = []
        for w in workouts:
            exs = (
                session.query(WorkoutExercise)
                .filter(WorkoutExercise.workout_id == w.id)
                .order_by(WorkoutExercise.display_order)
                .all()
            )
            result.append(_workout_dict(w, exs))
        return JSONResponse(result)


@app.post("/api/workouts", status_code=201)
def post_workout(body: WorkoutIn):
    try:
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Workout name is required")
    if not body.exercises:
        raise HTTPException(status_code=400, detail="At least one exercise is required")
    try:
        workout_date = _date.fromisoformat(body.workout_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_date; use YYYY-MM-DD")
    for ex in body.exercises:
        if ex.rpe is not None and not (1 <= ex.rpe <= 10):
            raise HTTPException(status_code=400, detail="RPE must be between 1 and 10")
    from datetime import datetime, timezone
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        workout = Workout(
            user_id=uid,
            name=name,
            workout_date=workout_date,
            workout_type=body.workout_type.strip(),
            remarks=body.remarks.strip() if body.remarks else None,
        )
        session.add(workout)
        session.flush()
        exercises = []
        for ex in body.exercises:
            e = WorkoutExercise(
                workout_id=workout.id,
                display_order=ex.display_order,
                name=ex.name.strip(),
                sets=ex.sets,
                reps=ex.reps,
                weight_kg=ex.weight_kg,
                duration=ex.duration,
                rpe=ex.rpe,
            )
            session.add(e)
            exercises.append(e)
        session.commit()
        session.refresh(workout)
        for e in exercises:
            session.refresh(e)
        return JSONResponse(status_code=201, content=_workout_dict(workout, exercises))


@app.get("/api/workouts/{workout_id}")
def get_workout(workout_id: str):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        exercises = (
            session.query(WorkoutExercise)
            .filter(WorkoutExercise.workout_id == wid)
            .order_by(WorkoutExercise.display_order)
            .all()
        )
        return JSONResponse(_workout_dict(workout, exercises))


@app.patch("/api/workouts/{workout_id}")
def patch_workout(workout_id: str, body: WorkoutPatch):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    from datetime import datetime, timezone
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Workout name is required")
            workout.name = name
        if body.workout_date is not None:
            try:
                workout.workout_date = _date.fromisoformat(body.workout_date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid workout_date; use YYYY-MM-DD")
        if body.workout_type is not None:
            workout.workout_type = body.workout_type.strip()
        if body.remarks is not None:
            workout.remarks = body.remarks.strip() or None
        workout.updated_at = datetime.now(timezone.utc)
        if body.exercises is not None:
            if not body.exercises:
                raise HTTPException(status_code=400, detail="At least one exercise is required")
            for ex in body.exercises:
                if ex.rpe is not None and not (1 <= ex.rpe <= 10):
                    raise HTTPException(status_code=400, detail="RPE must be between 1 and 10")
            session.query(WorkoutExercise).filter(WorkoutExercise.workout_id == wid).delete()
            exercises = []
            for ex in body.exercises:
                e = WorkoutExercise(
                    workout_id=wid,
                    display_order=ex.display_order,
                    name=ex.name.strip(),
                    sets=ex.sets,
                    reps=ex.reps,
                    weight_kg=ex.weight_kg,
                    duration=ex.duration,
                    rpe=ex.rpe,
                )
                session.add(e)
                exercises.append(e)
            session.commit()
            for e in exercises:
                session.refresh(e)
        else:
            session.commit()
            exercises = (
                session.query(WorkoutExercise)
                .filter(WorkoutExercise.workout_id == wid)
                .order_by(WorkoutExercise.display_order)
                .all()
            )
        session.refresh(workout)
        return JSONResponse(_workout_dict(workout, exercises))


@app.delete("/api/workouts/{workout_id}", status_code=204)
def delete_workout(workout_id: str):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        session.query(WorkoutExercise).filter(WorkoutExercise.workout_id == wid).delete()
        session.delete(workout)
        session.commit()
    return Response(status_code=204)


@app.get("/training.html")
def training():
    return FileResponse(str(_static_root / "training.html"))
