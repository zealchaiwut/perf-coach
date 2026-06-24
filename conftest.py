"""Root conftest.py — sets minimal env vars so that backend.db can be imported
without a real Postgres URL.  Tests that need a live DB must set up their own
connection; tests that mock Session/engine work with this stub URL.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
