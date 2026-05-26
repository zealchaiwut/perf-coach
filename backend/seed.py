import os
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
