"""Tests for issue #1137: plan router _resolve_user deduplication.

Acceptance criteria verified:
- AC1: _resolve_user is removed from backend/routers/projection.py (no cookie-checking logic)
- AC2: resolve_user is importable from backend.auth as a shared FastAPI dependency
- AC3: All Depends(_resolve_user) replaced with Depends(resolve_user) in projection.py
- AC4: No file in the codebase references _resolve_user
- AC5: Plan router endpoints reject unauthenticated requests (no session → 401/403)
- AC6: Plan router endpoints return valid responses with a valid session cookie
"""
import ast
import os
import pathlib
import uuid

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PROJECTION_PY = _ROOT / "backend" / "routers" / "projection.py"

# ── AC1: _resolve_user not defined in projection.py ──────────────────────────

def test_ac1_no_resolve_user_function_in_projection():
    """AC1: _resolve_user function must not exist in backend/routers/projection.py."""
    assert _PROJECTION_PY.exists(), "backend/routers/projection.py must exist"
    source = _PROJECTION_PY.read_text()
    assert "_resolve_user" not in source, (
        "backend/routers/projection.py must not define or reference _resolve_user"
    )


def test_ac1_no_cookie_direct_access_in_projection():
    """AC1: request.cookies.get(COOKIE_NAME) must not appear in projection.py."""
    source = _PROJECTION_PY.read_text()
    assert 'request.cookies.get(COOKIE_NAME)' not in source, (
        "projection.py must not duplicate cookie-checking — use the shared resolve_user dependency"
    )


# ── AC2: resolve_user importable from backend.auth ───────────────────────────

def test_ac2_resolve_user_importable_from_auth():
    """AC2: resolve_user must be importable as a named symbol from backend.auth."""
    from backend import auth
    assert hasattr(auth, "resolve_user"), (
        "backend.auth must expose resolve_user as a FastAPI dependency"
    )


def test_ac2_resolve_user_is_coroutine_function():
    """AC2: resolve_user must be an async function (FastAPI dependency)."""
    import asyncio
    from backend.auth import resolve_user
    assert asyncio.iscoroutinefunction(resolve_user), (
        "resolve_user must be an async function compatible with Depends()"
    )


# ── AC3: projection.py imports and uses resolve_user from backend.auth ────────

def test_ac3_projection_imports_resolve_user_from_auth():
    """AC3: backend/routers/projection.py must import resolve_user from backend.auth."""
    source = _PROJECTION_PY.read_text()
    assert "from backend.auth import" in source, (
        "projection.py must import from backend.auth"
    )
    assert "resolve_user" in source, (
        "projection.py must reference the shared resolve_user dependency"
    )


def test_ac3_projection_uses_depends_resolve_user():
    """AC3: All auth dependencies in projection.py use Depends(resolve_user), not _resolve_user."""
    source = _PROJECTION_PY.read_text()
    assert "Depends(_resolve_user)" not in source, (
        "projection.py must not use Depends(_resolve_user) — use Depends(resolve_user)"
    )
    assert "Depends(resolve_user)" in source, (
        "projection.py must use Depends(resolve_user) for authentication"
    )


# ── AC4: No file references _resolve_user ────────────────────────────────────

def _iter_backend_files(root: pathlib.Path):
    """Yield backend/ source files (not tests) to check for _resolve_user."""
    for p in root.rglob("*.py"):
        if ".git" in p.parts or "__pycache__" in p.parts or "venv" in p.parts:
            continue
        if "tests" in p.parts:
            continue
        yield p


def test_ac4_no_codebase_references_to_private_resolve_user():
    """AC4: No backend Python file defines or calls the auth _resolve_user function.

    Uses a word-boundary check so _resolve_user_id (CLI util) is not matched.
    """
    import re
    # Match _resolve_user NOT followed by an underscore or alphanumeric (so _resolve_user_id is excluded)
    pattern = re.compile(r'\b_resolve_user\b(?!_id\b)')
    matches = []
    for py_file in _iter_backend_files(_ROOT):
        text = py_file.read_text(errors="replace")
        if pattern.search(text):
            matches.append(str(py_file.relative_to(_ROOT)))
    assert not matches, (
        f"_resolve_user still referenced in backend source: {matches}"
    )


# ── AC5 & AC6: Integration — auth behaviour of projection endpoints ───────────

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "plan1137test!"

try:
    from dotenv import dotenv_values
    _env = dotenv_values(_ROOT / ".env")
    _uat_url = _env.get("DATABASE_URL_UAT")
except ImportError:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

if _uat_url:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _OrmSess
    from backend.auth import hash_password as _hash_pw
    from backend.models import User as _UserModel, TrainingPlan as _PlanModel
    _db_engine = create_engine(_uat_url, pool_pre_ping=True)
else:
    _db_engine = None


def _skip_if_no_db():
    if _db_engine is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping integration test")


@pytest.fixture(scope="module")
def authed_client_and_plan():
    """Create a test user + training plan, authenticate, yield (client, plan_id)."""
    import httpx
    from tests._admin_helpers import admin_cookies as _admin_cookies

    _skip_if_no_db()

    uname = f"plantest1137_{uuid.uuid4().hex[:8]}"

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/users", json={"name": uname}, cookies=_admin_cookies())
        assert r.status_code == 201, f"create user failed: {r.text}"
        user_id = r.json()["id"]

    with _OrmSess(_db_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/auth/login", json={"username": uname, "password": _TEST_PW})
        assert r.status_code == 200, f"login failed: {r.text}"
        session_cookie = r.cookies.get("session")
        csrf_token = r.cookies.get("csrf-token")

    client = httpx.Client(
        base_url=BASE_URL,
        timeout=10.0,
        cookies={"session": session_cookie, "csrf-token": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )

    # Create a training plan for the user
    with _OrmSess(_db_engine) as db:
        plan = _PlanModel(user_id=uuid.UUID(user_id), name="Test Plan 1137")
        db.add(plan)
        db.commit()
        plan_id = str(plan.id)

    yield client, plan_id

    client.close()
    with _OrmSess(_db_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


def test_ac5_unauthenticated_request_rejected(authed_client_and_plan):
    """AC5: GET /api/plans/{plan_id}/races without a session cookie returns 401 or 403."""
    import httpx
    _, plan_id = authed_client_and_plan
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as anon:
        r = anon.get(f"/api/plans/{plan_id}/races")
    assert r.status_code in (401, 403), (
        f"Expected 401 or 403 for unauthenticated request, got {r.status_code}: {r.text}"
    )


def test_ac6_authenticated_request_succeeds(authed_client_and_plan):
    """AC6: GET /api/plans/{plan_id}/races with a valid session cookie returns 200."""
    client, plan_id = authed_client_and_plan
    r = client.get(f"/api/plans/{plan_id}/races")
    assert r.status_code == 200, (
        f"Expected 200 for authenticated request, got {r.status_code}: {r.text}"
    )
    assert isinstance(r.json(), list), "Response must be a list of races"
