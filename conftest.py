"""Root conftest.py — sets minimal env vars so that backend.db can be imported
without a real Postgres URL.  Tests that need a live DB must set up their own
connection; tests that mock Session/engine work with this stub URL.
"""
import os
import pathlib

# If ENVIRONMENT=uat and DATABASE_URL_UAT is set, use that for the real database.
# Otherwise, default to a local SQLite for tests that mock the DB.
if os.getenv("ENVIRONMENT") != "uat":
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_perf_coach.db")
    os.environ.setdefault("ENVIRONMENT", "local")

os.environ.setdefault("SESSION_SECRET", "test-secret-key-for-testing-only-xxxxxxxxxxx")
os.environ.setdefault("STRYD_FERNET_KEY", "dGVzdC1mZXJuZXQta2V5LWZvci10ZXN0aW5nLW9ubHk=")
os.environ.setdefault("OAUTH_FERNET_KEY", "3ttWJuuQgVohOaEfabmb4WkB7VKPkh9z5zELJUyeFjY=")

# Auto-discover UAT server URL for integration tests.
# The pytest gate inherits the shell's UAT_BASE_URL which may point to the
# Commander dashboard (port 8001) instead of this project's UAT server.
# Read the actual port from the sibling uat/.env and override if needed.
def _setup_uat_base_url() -> None:
    existing = os.environ.get("UAT_BASE_URL", "")
    # Port 8001 is reserved for the Commander dashboard — not this project's UAT
    if existing and not existing.endswith(":8001"):
        return
    # Walk up from the repo root looking for a sibling uat/.env.
    # This handles both the standard tester worktree (../uat/.env) and
    # deeply nested coder worktrees (.commander/runtime/.../slot-N).
    search = pathlib.Path(__file__).parent
    for _ in range(6):
        candidate = search / "uat" / ".env"
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.startswith("PORT="):
                    port = line.split("=", 1)[1].strip().strip("'\"")
                    if port and port != "8001":
                        os.environ["UAT_BASE_URL"] = f"http://localhost:{port}"
                        os.environ["UAT_PORT"] = port
                        return
        search = search.parent


_setup_uat_base_url()
