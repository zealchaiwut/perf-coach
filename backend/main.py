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
from backend.models import DailyMetric, Habit, HabitLog, PersonalRecord, User, WeightEntry, Workout, WorkoutExercise, WorkoutSplit

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


@app.get("/api/calendar/month")
def get_calendar_month(
    user_id: str,
    year: int = Query(...),
    month: int = Query(...),
):
    """Return per-day calendar data for the given month.

    Response shape: a list of objects, one per calendar day in the month:
      {
        date: "YYYY-MM-DD",
        weight: float | null,
        habits_done: int,
        workouts: int,
        energy: int | null,        # 1–5
        sleep_quality: int | null  # 1–5
      }
    """
    from datetime import date as _date, timedelta
    import calendar as _cal

    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1–12")

    days_in_month = _cal.monthrange(year, month)[1]
    from_d = _date(year, month, 1)
    to_d = _date(year, month, days_in_month)

    with Session(engine) as session:
        # Weight entries
        weight_rows = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.recorded_date >= from_d,
                WeightEntry.recorded_date <= to_d,
            )
            .all()
        )
        weight_by_date = {str(w.recorded_date): float(w.weight_kg) for w in weight_rows}

        # Habit log counts per date
        log_rows = (
            session.query(HabitLog.logged_date)
            .filter(
                HabitLog.user_id == uid,
                HabitLog.logged_date >= from_d,
                HabitLog.logged_date <= to_d,
            )
            .all()
        )
        habits_by_date: dict = {}
        for (ld,) in log_rows:
            key = str(ld)
            habits_by_date[key] = habits_by_date.get(key, 0) + 1

        # Workout counts per date
        workout_rows = (
            session.query(Workout.workout_date)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
            )
            .all()
        )
        workouts_by_date: dict = {}
        for (wd,) in workout_rows:
            key = str(wd)
            workouts_by_date[key] = workouts_by_date.get(key, 0) + 1

        # Daily metrics (energy + sleep_quality)
        metric_rows = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= from_d,
                DailyMetric.metric_date <= to_d,
            )
            .all()
        )
        metrics_by_date: dict = {}
        for m in metric_rows:
            metrics_by_date[str(m.metric_date)] = {
                "energy": m.energy,
                "sleep_quality": m.sleep_quality,
            }

    days = []
    for day in range(1, days_in_month + 1):
        d = str(_date(year, month, day))
        m = metrics_by_date.get(d, {})
        days.append({
            "date": d,
            "weight": weight_by_date.get(d),
            "habits_done": habits_by_date.get(d, 0),
            "workouts": workouts_by_date.get(d, 0),
            "energy": m.get("energy"),
            "sleep_quality": m.get("sleep_quality"),
        })

    return JSONResponse(days)


@app.get("/log.html")
def log_page():
    return FileResponse(str(_static_root / "training-log.html"))


@app.get("/log")
def log_redirect():
    return FileResponse(str(_static_root / "training-log.html"))


@app.get("/trends.html")
def trends_page():
    return FileResponse(str(_static_root / "trends.html"))


@app.get("/trends")
def trends_redirect():
    return FileResponse(str(_static_root / "trends.html"))


# ── Workout endpoints ─────────────────────────────────────────────────────────

class ExerciseIn(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    duration: Optional[str] = None
    rpe: Optional[int] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_hr: Optional[int] = None


class WorkoutIn(BaseModel):
    user_id: str
    name: str
    workout_date: str  # YYYY-MM-DD
    workout_type: str
    remarks: Optional[str] = None
    tss: Optional[float] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    elevation_m: Optional[int] = None
    exercises: list[ExerciseIn] = []


class WorkoutPatch(BaseModel):
    name: Optional[str] = None
    workout_date: Optional[str] = None
    workout_type: Optional[str] = None
    remarks: Optional[str] = None
    tss: Optional[float] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    elevation_m: Optional[int] = None


class ExercisePatchIn(BaseModel):
    name: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    duration: Optional[str] = None
    rpe: Optional[int] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_hr: Optional[int] = None


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
    if ex.distance_km is not None and ex.distance_km < 0:
        raise HTTPException(status_code=422, detail="distance_km must be >= 0")
    if ex.duration_seconds is not None and ex.duration_seconds < 0:
        raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
    if ex.avg_hr is not None and not (20 <= ex.avg_hr <= 250):
        raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")


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
        "distance_km": str(e.distance_km) if e.distance_km is not None else None,
        "duration_seconds": e.duration_seconds,
        "avg_hr": e.avg_hr,
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
        "tss": w.tss,
        "tss_source": w.tss_source,
        "source": w.source,
        "strava_activity_url": w.strava_activity_url,
        "distance_km": float(w.distance_km) if w.distance_km is not None else None,
        "duration_seconds": w.duration_seconds,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "elevation_m": w.elevation_m,
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
        "tss": w.tss,
        "tss_source": w.tss_source,
        "source": w.source,
        "strava_activity_url": w.strava_activity_url,
        "distance_km": float(w.distance_km) if w.distance_km is not None else None,
        "duration_seconds": w.duration_seconds,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "elevation_m": w.elevation_m,
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
    if body.tss is not None and body.tss < 0:
        raise HTTPException(status_code=422, detail="tss must be >= 0")
    if body.distance_km is not None and body.distance_km < 0:
        raise HTTPException(status_code=422, detail="distance_km must be >= 0")
    if body.duration_seconds is not None and body.duration_seconds < 0:
        raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
    if body.avg_hr is not None and not (20 <= body.avg_hr <= 250):
        raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")
    if body.max_hr is not None and not (20 <= body.max_hr <= 250):
        raise HTTPException(status_code=422, detail="max_hr must be between 20 and 250")
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
            tss=body.tss,
            tss_source='manual' if body.tss is not None else None,
            distance_km=body.distance_km,
            duration_seconds=body.duration_seconds,
            avg_hr=body.avg_hr,
            max_hr=body.max_hr,
            elevation_m=body.elevation_m,
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
                weight_kg=ex.weight_kg,
                duration=ex.duration,
                rpe=ex.rpe,
                distance_km=ex.distance_km,
                duration_seconds=ex.duration_seconds,
                avg_hr=ex.avg_hr,
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
        if 'tss' in body.model_fields_set:
            if body.tss is None:
                workout.tss = None
                workout.tss_source = None
            else:
                if body.tss < 0:
                    raise HTTPException(status_code=422, detail="tss must be >= 0")
                workout.tss = body.tss
                workout.tss_source = 'manual'
        if 'distance_km' in body.model_fields_set:
            if body.distance_km is not None and body.distance_km < 0:
                raise HTTPException(status_code=422, detail="distance_km must be >= 0")
            workout.distance_km = body.distance_km
        if 'duration_seconds' in body.model_fields_set:
            if body.duration_seconds is not None and body.duration_seconds < 0:
                raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
            workout.duration_seconds = body.duration_seconds
        if 'avg_hr' in body.model_fields_set:
            if body.avg_hr is not None and not (20 <= body.avg_hr <= 250):
                raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")
            workout.avg_hr = body.avg_hr
        if 'max_hr' in body.model_fields_set:
            if body.max_hr is not None and not (20 <= body.max_hr <= 250):
                raise HTTPException(status_code=422, detail="max_hr must be between 20 and 250")
            workout.max_hr = body.max_hr
        if 'elevation_m' in body.model_fields_set:
            workout.elevation_m = body.elevation_m
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
            weight_kg=body.weight_kg,
            duration=body.duration,
            rpe=body.rpe,
            distance_km=body.distance_km,
            duration_seconds=body.duration_seconds,
            avg_hr=body.avg_hr,
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
        if body.weight_kg is not None:
            ex.weight_kg = body.weight_kg
        if body.duration is not None:
            ex.duration = body.duration
        if body.rpe is not None:
            if not (1 <= body.rpe <= 10):
                raise HTTPException(status_code=422, detail="rpe must be between 1 and 10")
            ex.rpe = body.rpe
        if body.distance_km is not None:
            if body.distance_km < 0:
                raise HTTPException(status_code=422, detail="distance_km must be >= 0")
            ex.distance_km = body.distance_km
        if body.duration_seconds is not None:
            if body.duration_seconds < 0:
                raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
            ex.duration_seconds = body.duration_seconds
        if body.avg_hr is not None:
            if not (20 <= body.avg_hr <= 250):
                raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")
            ex.avg_hr = body.avg_hr
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


# ── Workout splits endpoints ──────────────────────────────────────────────────

class SplitIn(BaseModel):
    split_index: int
    distance_km: float
    duration_seconds: int
    avg_hr: Optional[int] = None


class SplitsIn(BaseModel):
    splits: list[SplitIn]


def _split_dict(s: WorkoutSplit) -> dict:
    return {
        "id": str(s.id),
        "workout_id": str(s.workout_id),
        "split_index": s.split_index,
        "distance_km": str(s.distance_km),
        "duration_seconds": s.duration_seconds,
        "avg_hr": s.avg_hr,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@app.get("/api/workouts/{workout_id}/splits")
def get_splits(workout_id: str):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        splits = (
            session.query(WorkoutSplit)
            .filter(WorkoutSplit.workout_id == wid)
            .order_by(WorkoutSplit.split_index)
            .all()
        )
        return JSONResponse([_split_dict(s) for s in splits])


@app.post("/api/workouts/{workout_id}/splits", status_code=201)
def replace_splits(workout_id: str, body: SplitsIn):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    for s in body.splits:
        if s.distance_km < 0:
            raise HTTPException(status_code=422, detail="distance_km must be >= 0")
        if s.duration_seconds < 0:
            raise HTTPException(status_code=422, detail="duration_seconds must be >= 0")
        if s.avg_hr is not None and not (20 <= s.avg_hr <= 250):
            raise HTTPException(status_code=422, detail="avg_hr must be between 20 and 250")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        session.query(WorkoutSplit).filter(WorkoutSplit.workout_id == wid).delete()
        new_splits = []
        for s in body.splits:
            split = WorkoutSplit(
                workout_id=wid,
                split_index=s.split_index,
                distance_km=s.distance_km,
                duration_seconds=s.duration_seconds,
                avg_hr=s.avg_hr,
            )
            session.add(split)
            new_splits.append(split)
        session.commit()
        for split in new_splits:
            session.refresh(split)
        new_splits.sort(key=lambda x: x.split_index)
        return JSONResponse(status_code=201, content=[_split_dict(s) for s in new_splits])


@app.delete("/api/workouts/{workout_id}/splits", status_code=204)
def delete_splits(workout_id: str):
    try:
        wid = _uuid.UUID(workout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workout_id")
    with Session(engine) as session:
        workout = session.get(Workout, wid)
        if workout is None:
            raise HTTPException(status_code=404, detail="Workout not found")
        session.query(WorkoutSplit).filter(WorkoutSplit.workout_id == wid).delete()
        session.commit()
    return Response(status_code=204)


# ── Daily metrics endpoints ────────────────────────────────────────────────────

class DailyMetricIn(BaseModel):
    user_id: str
    metric_date: str  # YYYY-MM-DD
    resting_hr: Optional[int] = None
    hrv: Optional[int] = None
    sleep_hours: Optional[float] = None
    sleep_quality: Optional[int] = None
    energy: Optional[int] = None
    mood: Optional[int] = None
    notes: Optional[str] = None


class DailyMetricBody(BaseModel):
    resting_hr: Optional[int] = None
    hrv: Optional[int] = None
    sleep_hours: Optional[float] = None
    sleep_quality: Optional[int] = None
    energy: Optional[int] = None
    mood: Optional[int] = None
    notes: Optional[str] = None


def _validate_metric_fields(
    resting_hr: Optional[int] = None,
    hrv: Optional[int] = None,
    sleep_hours: Optional[float] = None,
    sleep_quality: Optional[int] = None,
    energy: Optional[int] = None,
    mood: Optional[int] = None,
) -> None:
    if resting_hr is not None and not (20 <= resting_hr <= 200):
        raise HTTPException(status_code=422, detail={"field": "resting_hr", "error": "resting_hr must be between 20 and 200"})
    if hrv is not None and not (0 <= hrv <= 300):
        raise HTTPException(status_code=422, detail={"field": "hrv", "error": "hrv must be between 0 and 300"})
    if sleep_hours is not None and not (0 <= sleep_hours <= 24):
        raise HTTPException(status_code=422, detail={"field": "sleep_hours", "error": "sleep_hours must be between 0 and 24"})
    if sleep_quality is not None and not (1 <= sleep_quality <= 5):
        raise HTTPException(status_code=422, detail={"field": "sleep_quality", "error": "sleep_quality must be between 1 and 5"})
    if energy is not None and not (1 <= energy <= 5):
        raise HTTPException(status_code=422, detail={"field": "energy", "error": "energy must be between 1 and 5"})
    if mood is not None and not (1 <= mood <= 5):
        raise HTTPException(status_code=422, detail={"field": "mood", "error": "mood must be between 1 and 5"})


def _daily_metric_dict(m: DailyMetric) -> dict:
    return {
        "id": str(m.id),
        "user_id": str(m.user_id),
        "metric_date": str(m.metric_date),
        "resting_hr": m.resting_hr,
        "hrv": m.hrv,
        "sleep_hours": float(m.sleep_hours) if m.sleep_hours is not None else None,
        "sleep_quality": m.sleep_quality,
        "energy": m.energy,
        "mood": m.mood,
        "notes": m.notes,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@app.get("/api/daily-metrics")
def list_daily_metrics(
    user_id: str,
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
):
    from datetime import timedelta
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    today = _date.today()
    if from_date is None and to_date is None:
        from_d = today - timedelta(days=29)
        to_d = today
    else:
        try:
            from_d = _date.fromisoformat(from_date) if from_date else today - timedelta(days=29)
            to_d = _date.fromisoformat(to_date) if to_date else today
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    with Session(engine) as session:
        rows = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= from_d,
                DailyMetric.metric_date <= to_d,
            )
            .order_by(DailyMetric.metric_date.desc())
            .all()
        )
        return JSONResponse([_daily_metric_dict(r) for r in rows])


@app.get("/api/daily-metrics/{user_id}/{metric_date}")
def get_daily_metric(user_id: str, metric_date: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    try:
        md = _date.fromisoformat(metric_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid metric_date; use YYYY-MM-DD")
    with Session(engine) as session:
        row = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == md)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Daily metric not found")
        return JSONResponse(_daily_metric_dict(row))


@app.post("/api/daily-metrics", status_code=201)
def create_daily_metric(body: DailyMetricIn):
    try:
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    try:
        md = _date.fromisoformat(body.metric_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid metric_date; use YYYY-MM-DD")
    if md > _date.today():
        raise HTTPException(status_code=422, detail="metric_date cannot be in the future")
    _validate_metric_fields(
        resting_hr=body.resting_hr,
        hrv=body.hrv,
        sleep_hours=body.sleep_hours,
        sleep_quality=body.sleep_quality,
        energy=body.energy,
        mood=body.mood,
    )
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        row = DailyMetric(
            user_id=uid,
            metric_date=md,
            resting_hr=body.resting_hr,
            hrv=body.hrv,
            sleep_hours=body.sleep_hours,
            sleep_quality=body.sleep_quality,
            energy=body.energy,
            mood=body.mood,
            notes=body.notes,
        )
        session.add(row)
        try:
            session.commit()
        except sa_exc.IntegrityError:
            session.rollback()
            return JSONResponse(
                status_code=409,
                content={"error": "A daily metric already exists for this user on this date; use PATCH to update it"},
            )
        session.refresh(row)
        return JSONResponse(status_code=201, content=_daily_metric_dict(row))


@app.patch("/api/daily-metrics/{user_id}/{metric_date}")
def patch_daily_metric(user_id: str, metric_date: str, body: DailyMetricBody):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    try:
        md = _date.fromisoformat(metric_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid metric_date; use YYYY-MM-DD")
    if md > _date.today():
        raise HTTPException(status_code=422, detail="metric_date cannot be in the future")
    _validate_metric_fields(
        resting_hr=body.resting_hr,
        hrv=body.hrv,
        sleep_hours=body.sleep_hours,
        sleep_quality=body.sleep_quality,
        energy=body.energy,
        mood=body.mood,
    )
    with Session(engine) as session:
        row = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == md)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Daily metric not found; use POST to create it")
        if body.resting_hr is not None:
            row.resting_hr = body.resting_hr
        if body.hrv is not None:
            row.hrv = body.hrv
        if body.sleep_hours is not None:
            row.sleep_hours = body.sleep_hours
        if body.sleep_quality is not None:
            row.sleep_quality = body.sleep_quality
        if body.energy is not None:
            row.energy = body.energy
        if body.mood is not None:
            row.mood = body.mood
        if body.notes is not None:
            row.notes = body.notes
        session.commit()
        session.refresh(row)
        return JSONResponse(_daily_metric_dict(row))


@app.put("/api/daily-metrics/{user_id}/{metric_date}")
def upsert_daily_metric(user_id: str, metric_date: str, body: DailyMetricBody):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    try:
        md = _date.fromisoformat(metric_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid metric_date; use YYYY-MM-DD")
    if md > _date.today():
        raise HTTPException(status_code=422, detail="metric_date cannot be in the future")
    _validate_metric_fields(
        resting_hr=body.resting_hr,
        hrv=body.hrv,
        sleep_hours=body.sleep_hours,
        sleep_quality=body.sleep_quality,
        energy=body.energy,
        mood=body.mood,
    )
    with Session(engine) as session:
        row = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == md)
            .first()
        )
        if row is None:
            user = session.get(User, uid)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            row = DailyMetric(
                user_id=uid,
                metric_date=md,
                resting_hr=body.resting_hr,
                hrv=body.hrv,
                sleep_hours=body.sleep_hours,
                sleep_quality=body.sleep_quality,
                energy=body.energy,
                mood=body.mood,
                notes=body.notes,
            )
            session.add(row)
        else:
            row.resting_hr = body.resting_hr
            row.hrv = body.hrv
            row.sleep_hours = body.sleep_hours
            row.sleep_quality = body.sleep_quality
            row.energy = body.energy
            row.mood = body.mood
            row.notes = body.notes
        session.commit()
        session.refresh(row)
        return JSONResponse(_daily_metric_dict(row))


@app.get("/api/daily-metrics/trend")
def get_daily_metrics_trend(
    user_id: str,
    days: int = Query(default=7, ge=1, le=90),
):
    from datetime import timedelta
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    today = _date.today()
    window_start = today - timedelta(days=days - 1)

    with Session(engine) as session:
        rows = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= window_start,
                DailyMetric.metric_date <= today,
            )
            .all()
        )
        by_date = {str(r.metric_date): r for r in rows}

        result = []
        for i in range(days):
            d = window_start + timedelta(days=i)
            d_str = str(d)
            r = by_date.get(d_str)
            result.append({
                "date": d_str,
                "sleep_hours": float(r.sleep_hours) if r and r.sleep_hours is not None else None,
                "energy": r.energy if r else None,
                "mood": r.mood if r else None,
            })

        return JSONResponse(result)


@app.delete("/api/daily-metrics/{user_id}/{metric_date}", status_code=204)
def delete_daily_metric(user_id: str, metric_date: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    try:
        md = _date.fromisoformat(metric_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid metric_date; use YYYY-MM-DD")
    with Session(engine) as session:
        row = (
            session.query(DailyMetric)
            .filter(DailyMetric.user_id == uid, DailyMetric.metric_date == md)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Daily metric not found")
        session.delete(row)
        session.commit()
    return Response(status_code=204)


# ── Trends summary endpoint ────────────────────────────────────────────────────

def _compute_readiness(hrv, resting_hr, sleep_hours, sleep_quality, energy, mood):
    """0-100 readiness score computed from available daily metric fields."""
    components = []
    if hrv is not None:
        # HRV: typical 20-100 ms → map to 0-100
        components.append(min(100.0, max(0.0, (float(hrv) - 20.0) / 80.0 * 100.0)))
    if resting_hr is not None:
        # RHR: lower is better; 40 bpm → 100, 90 bpm → 0
        components.append(max(0.0, min(100.0, (90.0 - float(resting_hr)) * 2.0)))
    if sleep_hours is not None:
        # sleep: 4 h → 0, 9 h → 100
        components.append(max(0.0, min(100.0, (float(sleep_hours) - 4.0) / 5.0 * 100.0)))
    if sleep_quality is not None:
        components.append((float(sleep_quality) - 1.0) / 4.0 * 100.0)
    if energy is not None:
        components.append((float(energy) - 1.0) / 4.0 * 100.0)
    if mood is not None:
        components.append((float(mood) - 1.0) / 4.0 * 100.0)
    if not components:
        return None
    return round(sum(components) / len(components))


def _agg_stats(values):
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None, None, None
    return round(sum(non_null) / len(non_null), 1), min(non_null), max(non_null)


def _delta_int(curr, prev):
    if curr is None or prev is None:
        return None
    diff = round(curr - prev)
    return f"+{diff}" if diff >= 0 else str(diff)


def _delta_hours(curr, prev):
    if curr is None or prev is None:
        return None
    diff = curr - prev
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.1f}h"


def _delta_decimal(curr, prev, places=1):
    if curr is None or prev is None:
        return None
    diff = curr - prev
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.{places}f}"


def _delta_pct(curr, prev):
    if curr is None or prev is None or prev == 0:
        return None
    pct = round((curr - prev) / prev * 100)
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


@app.get("/trends/summary")
def get_trends_summary(
    user_id: str,
    range_preset: Optional[str] = Query(default=None, alias="range"),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
):
    from datetime import timedelta

    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    today = _date.today()

    if from_date and to_date:
        try:
            from_d = _date.fromisoformat(from_date)
            to_d = _date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
        if from_d > to_d:
            raise HTTPException(status_code=400, detail="from must be before to")
    elif range_preset:
        if range_preset not in ("7d", "30d", "90d"):
            raise HTTPException(status_code=400, detail="range must be 7d, 30d, or 90d")
        n = int(range_preset[:-1])
        to_d = today
        from_d = today - timedelta(days=n - 1)
    else:
        to_d = today
        from_d = today - timedelta(days=29)

    days_count = (to_d - from_d).days + 1
    prev_to_d = from_d - timedelta(days=1)
    prev_from_d = prev_to_d - timedelta(days=days_count - 1)

    with Session(engine) as session:
        metrics = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= from_d,
                DailyMetric.metric_date <= to_d,
            )
            .all()
        )
        by_date = {str(m.metric_date): m for m in metrics}

        prev_metrics = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= prev_from_d,
                DailyMetric.metric_date <= prev_to_d,
            )
            .all()
        )
        prev_by_date = {str(m.metric_date): m for m in prev_metrics}

        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= from_d,
                Workout.workout_date <= to_d,
                Workout.tss.isnot(None),
            )
            .all()
        )
        tss_by_date: dict = {}
        for w in workouts:
            d = str(w.workout_date)
            tss_by_date[d] = tss_by_date.get(d, 0.0) + (w.tss or 0.0)

        prev_workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= prev_from_d,
                Workout.workout_date <= prev_to_d,
                Workout.tss.isnot(None),
            )
            .all()
        )
        prev_tss_by_date: dict = {}
        for w in prev_workouts:
            d = str(w.workout_date)
            prev_tss_by_date[d] = prev_tss_by_date.get(d, 0.0) + (w.tss or 0.0)

        baseline_from_d = to_d - timedelta(days=29)
        baseline_metrics = (
            session.query(DailyMetric)
            .filter(
                DailyMetric.user_id == uid,
                DailyMetric.metric_date >= baseline_from_d,
                DailyMetric.metric_date <= to_d,
            )
            .all()
        )

    baseline_hrv_vals = [float(m.hrv) for m in baseline_metrics if m.hrv is not None]
    baseline_rhr_vals = [float(m.resting_hr) for m in baseline_metrics if m.resting_hr is not None]

    def _baseline_stats(vals):
        if not vals:
            return None, None
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        return round(mean, 1), round(sd, 1)

    hrv_baseline_mean, hrv_baseline_sd = _baseline_stats(baseline_hrv_vals)
    rhr_baseline_mean, rhr_baseline_sd = _baseline_stats(baseline_rhr_vals)
    hrv_is_approx = len(baseline_hrv_vals) < 30
    rhr_is_approx = len(baseline_rhr_vals) < 30

    def _date_range(start, end):
        dates = []
        cur = start
        while cur <= end:
            dates.append(str(cur))
            cur += timedelta(days=1)
        return dates

    all_dates = _date_range(from_d, to_d)
    prev_dates = _date_range(prev_from_d, prev_to_d)

    readiness_series, hrv_series, rhr_series, sleep_series, energy_series, mood_series, tss_series = [], [], [], [], [], [], []

    for d in all_dates:
        m = by_date.get(d)
        sh = float(m.sleep_hours) if m and m.sleep_hours is not None else None
        readiness_series.append({"date": d, "score": _compute_readiness(
            m.hrv if m else None, m.resting_hr if m else None, sh,
            m.sleep_quality if m else None, m.energy if m else None, m.mood if m else None,
        )})
        hrv_series.append({"date": d, "value": m.hrv if m else None})
        rhr_series.append({"date": d, "value": m.resting_hr if m else None})
        sleep_series.append({"date": d, "hours": sh, "quality": m.sleep_quality if m else None})
        energy_series.append({"date": d, "value": m.energy if m else None})
        mood_series.append({"date": d, "value": m.mood if m else None})
        tss_val = tss_by_date.get(d)
        tss_series.append({"date": d, "value": round(tss_val, 1) if tss_val is not None else None})

    r_avg, r_min, r_max = _agg_stats([s["score"] for s in readiness_series])
    hrv_avg, hrv_min, hrv_max = _agg_stats([s["value"] for s in hrv_series])
    rhr_avg, rhr_min, rhr_max = _agg_stats([s["value"] for s in rhr_series])
    sleep_avg, sleep_min, sleep_max = _agg_stats([s["hours"] for s in sleep_series])
    energy_avg, energy_min, energy_max = _agg_stats([s["value"] for s in energy_series])
    mood_avg, mood_min, mood_max = _agg_stats([s["value"] for s in mood_series])
    tss_vals = [s["value"] for s in tss_series if s["value"] is not None]
    tss_avg = round(sum(tss_vals) / len(tss_vals), 1) if tss_vals else None
    tss_total = round(sum(tss_vals), 1) if tss_vals else None

    def _prev_metric_avg(field):
        vals = [float(getattr(m, field)) for d in prev_dates if (m := prev_by_date.get(d)) and getattr(m, field) is not None]
        return sum(vals) / len(vals) if vals else None

    def _prev_readiness_avg():
        vals = []
        for d in prev_dates:
            m = prev_by_date.get(d)
            if not m:
                continue
            sh = float(m.sleep_hours) if m.sleep_hours is not None else None
            r = _compute_readiness(m.hrv, m.resting_hr, sh, m.sleep_quality, m.energy, m.mood)
            if r is not None:
                vals.append(r)
        return sum(vals) / len(vals) if vals else None

    prev_tss_vals = [prev_tss_by_date[d] for d in prev_dates if d in prev_tss_by_date]
    prev_tss_avg = sum(prev_tss_vals) / len(prev_tss_vals) if prev_tss_vals else None

    prev_r_avg = _prev_readiness_avg()

    return JSONResponse({
        "range": {"from": str(from_d), "to": str(to_d), "days": days_count},
        "readiness": {"series": readiness_series, "avg": r_avg, "min": r_min, "max": r_max},
        "hrv": {"series": hrv_series, "avg": hrv_avg, "min": hrv_min, "max": hrv_max,
                "baseline_mean": hrv_baseline_mean, "baseline_sd": hrv_baseline_sd, "is_approximate": hrv_is_approx},
        "rhr": {"series": rhr_series, "avg": rhr_avg, "min": rhr_min, "max": rhr_max,
                "baseline_mean": rhr_baseline_mean, "baseline_sd": rhr_baseline_sd, "is_approximate": rhr_is_approx},
        "sleep": {"series": sleep_series, "avg_hours": sleep_avg, "min_hours": sleep_min, "max_hours": sleep_max},
        "energy": {"series": energy_series, "avg": energy_avg, "min": energy_min, "max": energy_max},
        "mood": {"series": mood_series, "avg": mood_avg, "min": mood_min, "max": mood_max},
        "tss": {"series": tss_series, "avg": tss_avg, "total": tss_total},
        "deltas": {
            "readiness": _delta_int(r_avg, prev_r_avg),
            "hrv": _delta_int(hrv_avg, _prev_metric_avg("hrv")),
            "rhr": _delta_int(rhr_avg, _prev_metric_avg("resting_hr")),
            "sleep": _delta_hours(sleep_avg, _prev_metric_avg("sleep_hours")),
            "energy": _delta_decimal(energy_avg, _prev_metric_avg("energy")),
            "mood": _delta_decimal(mood_avg, _prev_metric_avg("mood")),
            "tss": _delta_pct(tss_avg, prev_tss_avg),
        },
    })


# ── Readiness compute endpoint ────────────────────────────────────────────────

@app.post("/api/readiness/compute", status_code=200)
def compute_readiness_score(
    user_id: str = Query(...),
    date: Optional[str] = Query(default=None),
):
    """
    Trigger readiness computation for a user on a given date (defaults to today).
    Idempotent: existing rows are upserted with freshly computed values.
    """
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    target_date = _date.today()
    if date is not None:
        try:
            target_date = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")

    from services.readiness.job import compute_and_store
    row = compute_and_store(str(uid), target_date)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No daily_metrics row found for this user on this date",
        )
    return JSONResponse(row)


# ── Readiness GET endpoints ───────────────────────────────────────────────────

@app.get("/api/readiness/today")
def get_readiness_today(user_id: str = Query(...)):
    """
    Return today's readiness record for a user.

    Response shape:
      { date, score, missing_data: { hrv, rhr, sleep, energy },
        hrv_contribution, rhr_contribution, sleep_contribution, energy_contribution }

    Returns 404 when no readiness row exists for today (card falls back to mock data).
    """
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    today = _date.today()
    from sqlalchemy import text as _text
    with Session(engine) as session:
        row = session.execute(
            _text(
                "SELECT dr.date, dr.score, dr.components, "
                "       dm.hrv, dm.resting_hr, dm.sleep_quality, dm.energy "
                "FROM daily_readiness dr "
                "LEFT JOIN daily_metrics dm ON dm.id = dr.daily_metric_id "
                "WHERE dr.user_id = :uid AND dr.date = :d"
            ),
            {"uid": str(uid), "d": str(today)},
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="No readiness record for today")

    comp = row.components or {}
    return JSONResponse({
        "date": str(row.date),
        "score": float(row.score),
        "hrv_contribution": comp.get("hrv_contribution"),
        "rhr_contribution": comp.get("rhr_contribution"),
        "sleep_contribution": comp.get("sleep_contribution"),
        "energy_contribution": comp.get("energy_contribution"),
        "missing_data": {
            "hrv": row.hrv is None,
            "rhr": row.resting_hr is None,
            "sleep": row.sleep_quality is None,
            "energy": row.energy is None,
        },
    })


@app.get("/api/readiness")
def get_readiness_range(
    user_id: str = Query(...),
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    """
    Return daily readiness scores for a date range (one entry per day, null if missing).

    Response: list of { date, score } or null per day in [from, to].
    """
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    try:
        d_from = _date.fromisoformat(from_date)
        d_to = _date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")

    if d_from > d_to:
        raise HTTPException(status_code=400, detail="from must be <= to")

    from sqlalchemy import text as _text
    with Session(engine) as session:
        rows = session.execute(
            _text(
                "SELECT date, score FROM daily_readiness "
                "WHERE user_id = :uid AND date >= :from_d AND date <= :to_d "
                "ORDER BY date"
            ),
            {"uid": str(uid), "from_d": str(d_from), "to_d": str(d_to)},
        ).fetchall()

    by_date = {str(r.date): float(r.score) for r in rows}

    result = []
    d = d_from
    from datetime import timedelta
    while d <= d_to:
        ds = str(d)
        if ds in by_date:
            result.append({"date": ds, "score": by_date[ds]})
        else:
            result.append(None)
        d += timedelta(days=1)

    return JSONResponse(result)


# ── Training Log endpoint ─────────────────────────────────────────────────────

def _week_key_and_bounds(date_obj):
    from datetime import timedelta
    dow = date_obj.weekday()  # 0=Mon
    mon = date_obj - timedelta(days=dow)
    sun = mon + timedelta(days=6)
    return str(mon), str(sun)


def _week_label(mon_key: str) -> str:
    from datetime import date as _d2, timedelta
    today = _d2.today()
    this_mon = today - timedelta(days=today.weekday())
    mon = _d2.fromisoformat(mon_key)
    if mon == this_mon:
        return "This week"
    sun = mon + timedelta(days=6)
    return mon.strftime("%b %-d") + "–" + str(sun.day)


def _metric_has_data(m: DailyMetric) -> bool:
    return any(
        v is not None
        for v in (m.energy, m.mood, m.resting_hr, m.hrv, m.sleep_hours, m.sleep_quality, m.notes)
    )


@app.get("/api/training-log")
def get_training_log(
    user_id: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    types: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    include_rest: bool = Query(default=True),
):
    from datetime import timedelta
    today = _date.today()

    uid = None
    if user_id:
        try:
            uid = _uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id")

    from_d = today - timedelta(days=29) if from_date is None else None
    if from_date is not None:
        try:
            from_d = _date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from date; use YYYY-MM-DD")

    to_d = today if to_date is None else None
    if to_date is not None:
        try:
            to_d = _date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to date; use YYYY-MM-DD")

    with Session(engine) as session:
        from sqlalchemy import or_
        q = session.query(Workout).filter(
            Workout.workout_date >= from_d,
            Workout.workout_date <= to_d,
        )
        if uid is not None:
            q = q.filter(Workout.user_id == uid)
        if types and types != "all":
            q = q.filter(Workout.workout_type.ilike(types))
        if search:
            like = f"%{search}%"
            q = q.filter(or_(Workout.name.ilike(like), Workout.remarks.ilike(like)))
        workouts = q.order_by(Workout.workout_date.desc(), Workout.created_at.desc()).all()

        workout_dates = {str(w.workout_date) for w in workouts}

        rest_entries: list = []
        if include_rest and (not types or types == "all") and not search:
            mq = session.query(DailyMetric).filter(
                DailyMetric.metric_date >= from_d,
                DailyMetric.metric_date <= to_d,
            )
            if uid is not None:
                mq = mq.filter(DailyMetric.user_id == uid)
            metrics = mq.all()
            for m in metrics:
                if str(m.metric_date) not in workout_dates and _metric_has_data(m):
                    rest_entries.append({
                        "date": str(m.metric_date),
                        "type": "rest",
                        "sleep_hours": float(m.sleep_hours) if m.sleep_hours is not None else None,
                        "energy": m.energy,
                        "mood": m.mood,
                        "resting_hr": m.resting_hr,
                        "metrics": {
                            "energy": m.energy,
                            "mood": m.mood,
                            "sleep_quality": m.sleep_quality,
                            "sleep_hours": float(m.sleep_hours) if m.sleep_hours is not None else None,
                            "resting_hr": m.resting_hr,
                            "hrv": m.hrv,
                            "notes": m.notes,
                        },
                    })

    def _pace(w) -> "float | None":
        t = w.workout_type.lower() if w.workout_type else ""
        if t not in ("run", "bike"):
            return None
        if w.duration_seconds is None or w.distance_km is None or float(w.distance_km) == 0:
            return None
        return round(w.duration_seconds / float(w.distance_km), 2)

    workout_entries = [
        {
            "date": str(w.workout_date),
            "type": w.workout_type,
            "id": str(w.id),
            "title": w.name,
            "duration_seconds": w.duration_seconds,
            "duration_minutes": round(w.duration_seconds / 60, 2) if w.duration_seconds is not None else None,
            "distance_km": float(w.distance_km) if w.distance_km is not None else None,
            "avg_hr": w.avg_hr,
            "elevation_m": w.elevation_m,
            "average_pace_seconds_per_km": _pace(w),
            "tss": float(w.tss) if w.tss is not None else None,
            "source": w.source or w.tss_source or "manual",
            "notes": w.remarks or "",
            "weight_context": w.remarks,
        }
        for w in workouts
    ]

    all_entries = workout_entries + rest_entries
    all_entries.sort(key=lambda e: e["date"], reverse=True)

    weeks_map: dict = {}
    week_order: list = []

    for entry in all_entries:
        d_obj = _date.fromisoformat(entry["date"])
        mon_key, sun_key = _week_key_and_bounds(d_obj)
        if mon_key not in weeks_map:
            weeks_map[mon_key] = {
                "week_start": mon_key,
                "week_end": sun_key,
                "label": _week_label(mon_key),
                "entries": [],
                "workouts": [],
            }
            week_order.append(mon_key)
        weeks_map[mon_key]["entries"].append(entry)
        if entry["type"] != "rest":
            weeks_map[mon_key]["workouts"].append(entry)

    week_order.sort(reverse=True)

    weeks = []
    for key in week_order:
        wk = weeks_map[key]
        ws = wk["workouts"]
        weeks.append({
            "week_start": wk["week_start"],
            "week_end": wk["week_end"],
            "label": wk["label"],
            "entries": wk["entries"],
            "workouts": ws,
            "summary": {
                "workout_count": len(ws),
                "total_distance_km": sum((w.get("distance_km") or 0) for w in ws),
                "total_tss": sum((w.get("tss") or 0) for w in ws),
                "total_time_minutes": sum((w.get("duration_minutes") or 0) for w in ws),
            },
        })

    return JSONResponse({"weeks": weeks})


# ── Personal records endpoints ────────────────────────────────────────────────

VALID_TRACK_TYPES = {"time", "weight"}


class PersonalRecordIn(BaseModel):
    user_id: str
    track_key: str
    track_name: str
    track_type: str
    value_numeric: float
    achieved_on: str  # YYYY-MM-DD
    source: Optional[str] = None


class PersonalRecordPatch(BaseModel):
    track_key: Optional[str] = None
    track_name: Optional[str] = None
    track_type: Optional[str] = None
    value_numeric: Optional[float] = None
    achieved_on: Optional[str] = None
    source: Optional[str] = None


def _pr_dict(pr: PersonalRecord) -> dict:
    return {
        "id": str(pr.id),
        "user_id": str(pr.user_id),
        "track_key": pr.track_key,
        "track_name": pr.track_name,
        "track_type": pr.track_type,
        "value_numeric": float(pr.value_numeric),
        "achieved_on": str(pr.achieved_on),
        "source": pr.source,
        "created_at": pr.created_at.isoformat() if pr.created_at else None,
        "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
    }


@app.get("/api/personal-records")
def list_personal_records(user_id: str):
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    with Session(engine) as session:
        rows = (
            session.query(PersonalRecord)
            .filter(PersonalRecord.user_id == uid)
            .order_by(PersonalRecord.achieved_on.desc())
            .all()
        )
        return JSONResponse([_pr_dict(r) for r in rows])


@app.post("/api/personal-records", status_code=201)
def create_personal_record(body: PersonalRecordIn):
    try:
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if body.track_type not in VALID_TRACK_TYPES:
        raise HTTPException(status_code=422, detail="track_type must be 'time' or 'weight'")
    if body.value_numeric <= 0:
        raise HTTPException(status_code=422, detail="value_numeric must be > 0")
    try:
        achieved = _date.fromisoformat(body.achieved_on)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid achieved_on; use YYYY-MM-DD")
    if achieved > _date.today():
        raise HTTPException(status_code=422, detail="achieved_on cannot be in the future")
    with Session(engine) as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        pr = PersonalRecord(
            user_id=uid,
            track_key=body.track_key.strip(),
            track_name=body.track_name.strip(),
            track_type=body.track_type,
            value_numeric=body.value_numeric,
            achieved_on=achieved,
            source=body.source,
        )
        session.add(pr)
        session.commit()
        session.refresh(pr)
        return JSONResponse(status_code=201, content=_pr_dict(pr))


@app.patch("/api/personal-records/{record_id}")
def patch_personal_record(record_id: str, body: PersonalRecordPatch):
    try:
        rid = _uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid record_id")
    with Session(engine) as session:
        pr = session.get(PersonalRecord, rid)
        if pr is None:
            raise HTTPException(status_code=404, detail="Personal record not found")
        if body.track_type is not None:
            if body.track_type not in VALID_TRACK_TYPES:
                raise HTTPException(status_code=422, detail="track_type must be 'time' or 'weight'")
            pr.track_type = body.track_type
        if body.value_numeric is not None:
            if body.value_numeric <= 0:
                raise HTTPException(status_code=422, detail="value_numeric must be > 0")
            pr.value_numeric = body.value_numeric
        if body.achieved_on is not None:
            try:
                achieved = _date.fromisoformat(body.achieved_on)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid achieved_on; use YYYY-MM-DD")
            if achieved > _date.today():
                raise HTTPException(status_code=422, detail="achieved_on cannot be in the future")
            pr.achieved_on = achieved
        if body.track_key is not None:
            pr.track_key = body.track_key.strip()
        if body.track_name is not None:
            pr.track_name = body.track_name.strip()
        if "source" in body.model_fields_set:
            pr.source = body.source
        from sqlalchemy import text as _sql_text
        session.execute(_sql_text("UPDATE personal_records SET updated_at = now() WHERE id = :id"), {"id": str(rid)})
        session.commit()
        session.refresh(pr)
        return JSONResponse(_pr_dict(pr))


@app.delete("/api/personal-records/{record_id}", status_code=204)
def delete_personal_record(record_id: str):
    try:
        rid = _uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid record_id")
    with Session(engine) as session:
        pr = session.get(PersonalRecord, rid)
        if pr is None:
            raise HTTPException(status_code=404, detail="Personal record not found")
        session.delete(pr)
        session.commit()
    return Response(status_code=204)
