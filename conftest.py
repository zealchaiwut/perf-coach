"""Root conftest.py — sets minimal env vars so that backend.db can be imported
without a real Postgres URL.  Tests that need a live DB must set up their own
connection; tests that mock Session/engine work with this stub URL.
"""
import os
import pathlib

# Load SESSION_SECRET from .env when present so integration tests that hit the
# live UAT server use the same HMAC key as the server (admin cookie validation).
_env_file = pathlib.Path(__file__).resolve().parent / ".env"
_real_session_secret: str | None = None
if _env_file.exists():
    try:
        from dotenv import dotenv_values as _dotenv_values
        _real_session_secret = _dotenv_values(_env_file).get("SESSION_SECRET")
    except Exception:
        pass

# If ENVIRONMENT=uat and DATABASE_URL_UAT is set, use that for the real database.
# Otherwise, default to a local SQLite for tests that mock the DB.
if os.getenv("ENVIRONMENT") != "uat":
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
    os.environ.setdefault("ENVIRONMENT", "local")

os.environ.setdefault(
    "SESSION_SECRET",
    _real_session_secret or "test-secret-key-for-testing-only-xxxxxxxxxxx",
)
os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
