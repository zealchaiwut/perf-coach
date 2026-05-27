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
    workout_count = session.execute(text("SELECT COUNT(*) FROM workouts")).scalar()
    if workout_count == 0:
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
                        {"name": "Shoulder Press", "sets": 4, "reps": "10,8,8,6", "weight": "BB 40kg", "rpe": 8},
                        {"name": "DB Row", "sets": 4, "reps": "10", "weight": "DB 24kg", "rpe": 7},
                        {"name": "Squat", "sets": 4, "reps": "6", "weight": "BB 80kg", "rpe": 8},
                        {"name": "Lateral Raise", "sets": 3, "reps": "15", "weight": "DB 8kg", "rpe": 6},
                    ],
                },
                {
                    "user_id": str(alice.id),
                    "name": "Easy Run",
                    "workout_date": str(today - timedelta(days=7)),
                    "workout_type": "running",
                    "remarks": "Recovery pace",
                    "exercises": [
                        {"name": "5k Run", "sets": None, "reps": None, "weight": None, "duration": "28 min", "rpe": 5},
                        {"name": "Cool-down Walk", "sets": None, "reps": None, "weight": None, "duration": "10 min", "rpe": 2},
                    ],
                },
                {
                    "user_id": str(alice.id),
                    "name": "Upper Push",
                    "workout_date": str(today - timedelta(days=14)),
                    "workout_type": "strength",
                    "remarks": "",
                    "exercises": [
                        {"name": "Bench Press", "sets": 4, "reps": "8", "weight": "BB 60kg", "rpe": 7},
                        {"name": "Overhead Press", "sets": 3, "reps": "10", "weight": "BB 40kg", "rpe": 7},
                        {"name": "Tricep Dip", "sets": 3, "reps": "AMRAP", "weight": "BW", "rpe": 8},
                        {"name": "Cable Fly", "sets": 3, "reps": "12", "weight": "15kg", "rpe": 6},
                        {"name": "Face Pull", "sets": 3, "reps": "15", "weight": "20kg", "rpe": 5},
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
                            " (workout_id, display_order, name, sets, reps, weight, duration, rpe)"
                            " VALUES (:workout_id, :display_order, :name, :sets, :reps, :weight, :duration, :rpe)"
                        ),
                        {
                            "workout_id": str(workout_id),
                            "display_order": i,
                            "name": ex["name"],
                            "sets": ex.get("sets"),
                            "reps": ex.get("reps"),
                            "weight": ex.get("weight"),
                            "duration": ex.get("duration"),
                            "rpe": ex.get("rpe"),
                        },
                    )
            session.commit()
            print(f"Seeded {len(seed_workouts)} workouts for Alice")
    else:
        print(f"Workouts table already has {workout_count} row(s) — skipping workout seed")
