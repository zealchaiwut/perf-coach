import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv()

environment = os.getenv("ENVIRONMENT", "PRD").upper()
database_url = os.getenv("DATABASE_URL_UAT" if environment == "UAT" else "DATABASE_URL_PRD")

engine = create_engine(database_url, pool_pre_ping=True)

SEED_USERS = ["Alice", "Bob", "Carol"]

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
        print(f"Users table already has {count} row(s) — skipping seed")
