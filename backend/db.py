import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

environment = os.getenv("ENVIRONMENT", "local").lower()

# Render sets DATABASE_URL per service; local dev uses DATABASE_URL_UAT / DATABASE_URL_PRD.
database_url = os.getenv("DATABASE_URL") or (
    os.getenv("DATABASE_URL_UAT") if environment == "uat" else os.getenv("DATABASE_URL_PRD")
)

engine = create_engine(database_url, pool_pre_ping=True)


def check_db() -> str:
    def _ping():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_ping)
        try:
            return fut.result(timeout=2)
        except _FuturesTimeout:
            return "error"
