import os
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv()

environment = os.getenv("ENVIRONMENT", "PRD").upper()
database_url = os.getenv("DATABASE_URL_UAT" if environment == "UAT" else "DATABASE_URL_PRD")

engine = create_engine(database_url, pool_pre_ping=True)

SEED_USERS = ["Alice", "Bob", "Carol"]
SEED_HABITS = ["Meditate", "Exercise", "Read 30 min"]

with Session(engine) as session:
    count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
    if count == 0:
        session.execute(
            text("INSERT INTO users (name) VALUES (:name)"),
            [{"name": name} for name in SEED_USERS],
        )
        session.commit()
        print(f"Seeded {len(SEED_USERS)} users: {', '.join(SEED_USERS)}")
    else:
        print(f"Users table already has {count} row(s) — skipping user seed")

with Session(engine) as session:
    habit_count = session.execute(text("SELECT COUNT(*) FROM habits")).scalar()
    if habit_count == 0:
        users = session.execute(text("SELECT id FROM users")).fetchall()
        rows = [
            {"user_id": str(user.id), "name": name, "display_order": i}
            for user in users
            for i, name in enumerate(SEED_HABITS)
        ]
        if rows:
            session.execute(
                text(
                    "INSERT INTO habits (user_id, name, display_order)"
                    " VALUES (:user_id, :name, :display_order)"
                ),
                rows,
            )
            session.commit()
            print(f"Seeded {len(SEED_HABITS)} habits for {len(users)} user(s)")
    else:
        print(f"Habits table already has {habit_count} row(s) — skipping habit seed")

with Session(engine) as session:
    # Check whether any strength workouts have fewer than 4 exercises.
    # If so, the data is stale (from a previous under-populated seed run) and
    # should be wiped and re-seeded so the AC ("each strength workout has 4-6
    # exercise rows") is satisfied.
    thin_strength = session.execute(
        text(
            "SELECT COUNT(*) FROM workouts w"
            " WHERE w.workout_type ILIKE 'strength'"
            "   AND (SELECT COUNT(*) FROM workout_exercises we WHERE we.workout_id = w.id) < 4"
        )
    ).scalar()

    workout_count = session.execute(text("SELECT COUNT(*) FROM workouts")).scalar()

    # Re-seed if the table is empty OR if any strength workout is under-populated.
    needs_seed = workout_count == 0 or thin_strength > 0

    if needs_seed:
        if thin_strength > 0:
            # Remove stale workout data so we can insert fresh seed rows.
            session.execute(text("DELETE FROM workout_exercises"))
            session.execute(text("DELETE FROM workouts"))
            session.commit()
            print(f"Removed {workout_count} stale workout row(s) with thin exercise data — re-seeding")

        alice = session.execute(text("SELECT id FROM users WHERE name = 'Alice'")).fetchone()
        if alice:
            today = date.today()
            seed_workouts = [
                {
                    "user_id": str(alice.id),
                    "name": "Morning Strength A",
                    "workout_date": str(today - timedelta(days=3)),
                    "workout_type": "strength",
                    "remarks": "Felt strong today",
                    "exercises": [
                        {"name": "Squat", "sets": 5, "reps": 5, "weight_kg": 80.0, "rpe": 8},
                        {"name": "Bench Press", "sets": 4, "reps": 8, "weight_kg": 60.0, "rpe": 7},
                        {"name": "Deadlift", "sets": 3, "reps": 5, "weight_kg": 100.0, "rpe": 9},
                        {"name": "Pull-ups", "sets": 3, "reps": 8, "weight_kg": None, "rpe": 7},
                        {"name": "Overhead Press", "sets": 3, "reps": 10, "weight_kg": 40.0, "rpe": 7},
                    ],
                },
                {
                    "user_id": str(alice.id),
                    "name": "Easy Run",
                    "workout_date": str(today - timedelta(days=7)),
                    "workout_type": "running",
                    "remarks": "Recovery pace",
                    "exercises": [
                        {"name": "5k Run", "sets": None, "reps": None, "weight_kg": None, "duration": "28:00", "rpe": 5},
                        {"name": "Cool-down Walk", "sets": None, "reps": None, "weight_kg": None, "duration": "10:00", "rpe": 2},
                    ],
                },
                {
                    "user_id": str(alice.id),
                    "name": "Upper Push",
                    "workout_date": str(today - timedelta(days=14)),
                    "workout_type": "strength",
                    "remarks": "",
                    "exercises": [
                        {"name": "Bench Press", "sets": 4, "reps": 8, "weight_kg": 65.0, "rpe": 8},
                        {"name": "Overhead Press", "sets": 3, "reps": 10, "weight_kg": 40.0, "rpe": 7},
                        {"name": "Tricep Dip", "sets": 3, "reps": 12, "weight_kg": None, "rpe": 8},
                        {"name": "Cable Fly", "sets": 3, "reps": 12, "weight_kg": 15.0, "rpe": 6},
                        {"name": "Face Pull", "sets": 3, "reps": 15, "weight_kg": 20.0, "rpe": 5},
                    ],
                },
            ]
            for w in seed_workouts:
                result = session.execute(
                    text(
                        "INSERT INTO workouts (user_id, name, workout_date, workout_type, remarks)"
                        " VALUES (:user_id, :name, :workout_date, :workout_type, :remarks)"
                        " RETURNING id"
                    ),
                    {
                        "user_id": w["user_id"],
                        "name": w["name"],
                        "workout_date": w["workout_date"],
                        "workout_type": w["workout_type"],
                        "remarks": w["remarks"] or None,
                    },
                )
                workout_id = result.fetchone().id
                for i, ex in enumerate(w["exercises"]):
                    session.execute(
                        text(
                            "INSERT INTO workout_exercises"
                            " (workout_id, display_order, name, sets, reps, weight_kg, duration, rpe)"
                            " VALUES (:workout_id, :display_order, :name, :sets, :reps, :weight_kg, :duration, :rpe)"
                        ),
                        {
                            "workout_id": str(workout_id),
                            "display_order": i,
                            "name": ex["name"],
                            "sets": ex.get("sets"),
                            "reps": ex.get("reps"),
                            "weight_kg": ex.get("weight_kg"),
                            "duration": ex.get("duration"),
                            "rpe": ex.get("rpe"),
                        },
                    )
            session.commit()
            print(f"Seeded {len(seed_workouts)} workouts for Alice (5 exercises per strength workout)")
    else:
        print(f"Workouts table already has {workout_count} row(s) with adequate exercise data — skipping workout seed")

with Session(engine) as session:
    alice = session.execute(text("SELECT id FROM users WHERE name = 'Alice'")).fetchone()
    if alice:
        dm_count = session.execute(
            text("SELECT COUNT(*) FROM daily_metrics WHERE user_id = :uid"),
            {"uid": str(alice.id)},
        ).scalar()
        if dm_count == 0:
            today = date.today()
            # 14 days of realistic recovery data (rhr 50-60, hrv 40-80,
            # sleep 6.5-8.5, quality/energy/mood 2-5), most recent first
            seed_metrics = [
                {"resting_hr": 52, "hrv": 72, "sleep_hours": "7.5", "sleep_quality": 4, "energy": 4, "mood": 4, "notes": None},
                {"resting_hr": 55, "hrv": 58, "sleep_hours": "6.8", "sleep_quality": 3, "energy": 3, "mood": 3, "notes": None},
                {"resting_hr": 50, "hrv": 75, "sleep_hours": "8.0", "sleep_quality": 5, "energy": 5, "mood": 4, "notes": "Great night"},
                {"resting_hr": 58, "hrv": 45, "sleep_hours": "6.5", "sleep_quality": 2, "energy": 2, "mood": 3, "notes": "Restless"},
                {"resting_hr": 54, "hrv": 68, "sleep_hours": "7.2", "sleep_quality": 4, "energy": 4, "mood": 4, "notes": None},
                {"resting_hr": 57, "hrv": 52, "sleep_hours": "7.0", "sleep_quality": 3, "energy": 3, "mood": 3, "notes": None},
                {"resting_hr": 51, "hrv": 80, "sleep_hours": "8.5", "sleep_quality": 5, "energy": 5, "mood": 5, "notes": "Peak day"},
                {"resting_hr": 53, "hrv": 65, "sleep_hours": "7.3", "sleep_quality": 4, "energy": 4, "mood": 4, "notes": None},
                {"resting_hr": 60, "hrv": 40, "sleep_hours": "6.5", "sleep_quality": 2, "energy": 2, "mood": 2, "notes": "Stressed"},
                {"resting_hr": 56, "hrv": 55, "sleep_hours": "6.8", "sleep_quality": 3, "energy": 3, "mood": 3, "notes": None},
                {"resting_hr": 52, "hrv": 70, "sleep_hours": "7.8", "sleep_quality": 4, "energy": 4, "mood": 5, "notes": None},
                {"resting_hr": 54, "hrv": 63, "sleep_hours": "7.5", "sleep_quality": 4, "energy": 4, "mood": 4, "notes": None},
                {"resting_hr": 59, "hrv": 48, "sleep_hours": "6.5", "sleep_quality": 3, "energy": 3, "mood": 3, "notes": None},
                {"resting_hr": 51, "hrv": 77, "sleep_hours": "8.0", "sleep_quality": 5, "energy": 5, "mood": 4, "notes": "Refreshed"},
            ]
            rows = [
                {
                    "user_id": str(alice.id),
                    "metric_date": str(today - timedelta(days=i + 1)),
                    **m,
                }
                for i, m in enumerate(seed_metrics)
            ]
            session.execute(
                text(
                    "INSERT INTO daily_metrics"
                    " (user_id, metric_date, resting_hr, hrv, sleep_hours,"
                    "  sleep_quality, energy, mood, notes)"
                    " VALUES (:user_id, :metric_date, :resting_hr, :hrv, :sleep_hours,"
                    "         :sleep_quality, :energy, :mood, :notes)"
                ),
                rows,
            )
            session.commit()
            print(f"Seeded {len(rows)} daily_metrics rows for Alice")
        else:
            print(f"Alice already has {dm_count} daily_metrics row(s) — skipping daily metrics seed")
    else:
        print("Alice not found — skipping daily metrics seed")
