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
    try:
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
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable: " + str(exc))


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


@app.get("/api/stats/active-streak")
def get_active_streak(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    from datetime import timedelta
    from sqlalchemy import text as _sql_text
    today = _date.today()

    with Session(engine) as session:
        rows = session.execute(
            _sql_text("""
                SELECT DISTINCT d FROM (
                    SELECT recorded_date AS d FROM weight_entries WHERE user_id = :uid
                    UNION
                    SELECT logged_date AS d FROM habit_logs WHERE user_id = :uid
                    UNION
                    SELECT workout_date AS d FROM workouts WHERE user_id = :uid
                ) sub
                ORDER BY d
            """),
            {"uid": str(uid)},
        ).fetchall()

    if not rows:
        return JSONResponse({"current_streak": 0, "longest_streak": 0, "last_active_date": None})

    sorted_asc = [row[0] for row in rows]
    all_dates = set(sorted_asc)
    last_active = sorted_asc[-1]

    # Longest streak across all time
    longest = run = 1
    for i in range(1, len(sorted_asc)):
        if (sorted_asc[i] - sorted_asc[i - 1]).days == 1:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 1

    # Current streak (forgiving: if today has no entry, start from yesterday)
    check = today if today in all_dates else today - timedelta(days=1)
    current_streak = 0
    while check in all_dates:
        current_streak += 1
        check -= timedelta(days=1)

    return JSONResponse({
        "current_streak": current_streak,
        "longest_streak": longest,
        "last_active_date": str(last_active),
    })


@app.get("/")
def index():
    return FileResponse(str(_static_root / "index.html"))


@app.get("/home.html")
def home():
    return FileResponse(str(_static_root / "home.html"))


@app.get("/weight.html")
def weight():
    return FileResponse(str(_static_root / "weight.html"))


@app.get("/habits.html")
def habits():
    return FileResponse(str(_static_root / "habits.html"))


@app.get("/users.html")
def users_page():
    return FileResponse(str(_static_root / "users.html"))


@app.get("/calendar.html")
def calendar_page():
    return FileResponse(str(_static_root / "calendar.html"))


# ── Workout endpoints ─────────────────────────────────────────────────────────

class ExerciseIn(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[str] = None
    weight: Optional[str] = None
    duration: Optional[str] = None
    rpe: Optional[int] = None


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


class ExercisePatchIn(BaseModel):
    name: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[str] = None
    weight: Optional[str] = None
    duration: Optional[str] = None
    rpe: Optional[int] = None


class ExerciseReorderIn(BaseModel):
    ordered_ids: list[str]


def _validate_exercise(ex: ExerciseIn) -> None:
    name = ex.name.strip() if ex.name else ""
    if not name:
        raise HTTPException(status_code=422, detail="Exercise name is required")
    if ex.sets is not None and ex.sets <= 0:
        raise HTTPException(status_code=422, detail="sets must be > 0")
    if ex.rpe is not None and not (1 <= ex.rpe <= 10):
        raise HTTPException(status_code=422, detail="rpe must be between 1 and 10")


def _exercise_dict(e: WorkoutExercise) -> dict:
    return {
        "id": str(e.id),
        "display_order": e.display_order,
        "name": e.name,
        "sets": e.sets,
        "reps": e.reps,
        "weight": e.weight,
        "duration": e.duration,
        "rpe": e.rpe,
        "created_at": e.created_at.isoformat() if e.created_at else None,
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
        "exercises": [_exercise_dict(e) for e in exercises],
    }


def _workout_list_dict(w: Workout, exercise_count: int) -> dict:
    return {
        "id": str(w.id),
        "workout_date": str(w.workout_date),
        "name": w.name,
        "workout_type": w.workout_type,
        "remarks": w.remarks,
        "exercise_count": exercise_count,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


@app.get("/api/workouts")
def get_workouts(
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
        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
            )
            .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
            .all()
        )
        result = []
        for w in workouts:
            count = (
                session.query(WorkoutExercise)
                .filter(WorkoutExercise.workout_id == w.id)
                .count()
            )
            result.append(_workout_list_dict(w, count))
        return JSONResponse(result)


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


@app.post("/api/workouts", status_code=201)
def post_workout(body: WorkoutIn):
    try:
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workout name is required")
    if not body.workout_type or not body.workout_type.strip():
        raise HTTPException(status_code=422, detail="workout_type is required")
    try:
        workout_date = _date.fromisoformat(body.workout_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid workout_date; use YYYY-MM-DD")
    if workout_date > _date.today():
        raise HTTPException(status_code=422, detail="workout_date cannot be in the future")
    for ex in body.exercises:
        _validate_exercise(ex)
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
        for i, ex in enumerate(body.exercises):
            e = WorkoutExercise(
                workout_id=workout.id,
                display_order=i,
                name=ex.name.strip(),
                sets=ex.sets,
                reps=ex.reps,
                weight=ex.weight,
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


@app.patch("/api/workouts/{workout_id}")
def patch_workout(workout_id: str, body: WorkoutPatch):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=422, detail="Workout name is required")
            workout.name = name
        if body.workout_date is not None:
            try:
                d = _date.fromisoformat(body.workout_date)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid workout_date; use YYYY-MM-DD")
            if d > _date.today():
                raise HTTPException(status_code=422, detail="workout_date cannot be in the future")
            workout.workout_date = d
        if body.workout_type is not None:
            t = body.workout_type.strip()
            if not t:
                raise HTTPException(status_code=422, detail="workout_type is required")
            workout.workout_type = t
        if body.remarks is not None:
            workout.remarks = body.remarks.strip() or None
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
        session.delete(workout)
        session.commit()
    return Response(status_code=204)


@app.post("/api/workouts/{workout_id}/exercises/reorder", status_code=200)
def reorder_exercises(workout_id: str, body: ExerciseReorderIn):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        for order, eid_str in enumerate(body.ordered_ids):
            try:
                eid = _uuid.UUID(eid_str)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid exercise id: {eid_str}")
            ex = session.get(WorkoutExercise, eid)
            if ex is None or ex.workout_id != wid:
                raise HTTPException(status_code=404, detail=f"Exercise {eid_str} not found in this workout")
            ex.display_order = order
        session.commit()
        exercises = (
            session.query(WorkoutExercise)
            .filter(WorkoutExercise.workout_id == wid)
            .order_by(WorkoutExercise.display_order)
            .all()
        )
        session.refresh(workout)
        return JSONResponse(_workout_dict(workout, exercises))


@app.post("/api/workouts/{workout_id}/exercises", status_code=201)
def append_exercise(workout_id: str, body: ExerciseIn):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    _validate_exercise(body)
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        max_order = (
            session.query(WorkoutExercise.display_order)
            .filter(WorkoutExercise.workout_id == wid)
            .order_by(WorkoutExercise.display_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order is not None else 0
        ex = WorkoutExercise(
            workout_id=wid,
            display_order=next_order,
            name=body.name.strip(),
            sets=body.sets,
            reps=body.reps,
            weight=body.weight,
            duration=body.duration,
            rpe=body.rpe,
        )
        session.add(ex)
        session.commit()
        session.refresh(ex)
        return JSONResponse(status_code=201, content=_exercise_dict(ex))


@app.patch("/api/workouts/{workout_id}/exercises/{exercise_id}")
def patch_exercise(workout_id: str, exercise_id: str, body: ExercisePatchIn):
    try:
        wid = _uuid.UUID(workout_id)
        eid = _uuid.UUID(exercise_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id or exercise_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        ex = session.get(WorkoutExercise, eid)
        if ex is None or ex.workout_id != wid:
            raise HTTPException(status_code=404, detail="Exercise not found in this workout")
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=422, detail="Exercise name is required")
            ex.name = name
        if body.sets is not None:
            if body.sets <= 0:
                raise HTTPException(status_code=422, detail="sets must be > 0")
            ex.sets = body.sets
        if body.reps is not None:
            ex.reps = body.reps
        if body.weight is not None:
            ex.weight = body.weight
        if body.duration is not None:
            ex.duration = body.duration
        if body.rpe is not None:
            if not (1 <= body.rpe <= 10):
                raise HTTPException(status_code=422, detail="rpe must be between 1 and 10")
            ex.rpe = body.rpe
        session.commit()
        session.refresh(ex)
        return JSONResponse(_exercise_dict(ex))


@app.delete("/api/workouts/{workout_id}/exercises/{exercise_id}", status_code=204)
def delete_exercise(workout_id: str, exercise_id: str):
    try:
        wid = _uuid.UUID(workout_id)
        eid = _uuid.UUID(exercise_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id or exercise_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        ex = session.get(WorkoutExercise, eid)
        if ex is None or ex.workout_id != wid:
            raise HTTPException(status_code=404, detail="Exercise not found in this workout")
        session.delete(ex)
        session.commit()
    return Response(status_code=204)
