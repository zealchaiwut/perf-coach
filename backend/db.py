import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv(override=True)

environment = os.getenv("ENVIRONMENT", "local").lower()

# Render sets DATABASE_URL per service; local dev uses DATABASE_URL_UAT / DATABASE_URL_PRD.
database_url = os.getenv("DATABASE_URL") or (
    os.getenv("DATABASE_URL_UAT") if environment == "uat" else os.getenv("DATABASE_URL_PRD")
)

def _pool_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=_pool_int("DB_POOL_SIZE", 10),
    max_overflow=_pool_int("DB_POOL_MAX_OVERFLOW", 10),
    pool_timeout=_pool_int("DB_POOL_TIMEOUT", 10),
    pool_recycle=3600,
)


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
