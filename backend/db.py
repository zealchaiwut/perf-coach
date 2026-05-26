import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

environment = os.getenv("ENVIRONMENT", "PRD").upper()

if environment == "UAT":
    database_url = os.getenv("DATABASE_URL_UAT")
else:
    database_url = os.getenv("DATABASE_URL_PRD")

engine = create_engine(database_url, pool_pre_ping=True)


def check_db() -> str:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"
