"""Shared admin-cookie helper for live-server (httpx.Client) tests.

POST/DELETE /api/users are admin-gated (fix-loopholes Task 1). Many
unrelated test files use those two endpoints purely as fixture plumbing to
create/tear down a throwaway test user over a real HTTP connection (not
FastAPI's TestClient, so tests/conftest.py's dependency_overrides bypass
doesn't apply). This gives them a one-line way to authenticate those calls
without duplicating the admin-cookie construction everywhere.
"""
import time

from backend.auth import ADMIN_COOKIE_NAME, create_admin_cookie


def admin_cookies() -> dict:
    return {ADMIN_COOKIE_NAME: create_admin_cookie(time.time())}
