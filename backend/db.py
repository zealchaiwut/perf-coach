import concurrent.futures
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

environment = os.getenv("ENVIRONMENT", "local").lower()

if environment == "uat":
    database_url = os.getenv("DATABASE_URL_UAT")
else:
    database_url = os.getenv("DATABASE_URL_PRD")

engine = create_engine(database_url, pool_pre_ping=True)


def _execute_select_1() -> str:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


def check_db() -> str:
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_execute_select_1)
            return future.result(timeout=2)
    except Exception:
        return "error"
