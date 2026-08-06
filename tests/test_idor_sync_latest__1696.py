"""TDD tests for issue #1696: IDOR on /api/sync/strava/latest and /api/sync/stryd/latest.

Both endpoints accepted an optional user_id query param and queried SyncJob
directly with no ownership or admin check — any authenticated user could read
another user's sync history.  The fix must add the same gate that
GET /api/sync/history already uses: non-admin callers who pass another user's
uuid must receive 403, not 200.

AC:
  1. /api/sync/strava/latest?user_id=<other> returns 403 for non-admin users.
  2. /api/sync/stryd/latest?user_id=<other> returns 403 for non-admin users.
  3. Owner may still query their own data via ?user_id=<own_uuid> (200).
  4. Admin user may query any user's data (200).
  5. Omitting user_id still works (session-user legacy path, 200 or 404).
"""
import datetime
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Register JSONB → JSON for SQLite (idempotent — other test modules do the same)
try:
    @compiles(JSONB, "sqlite")
    def _jsonb_as_json(type_, compiler, **kw):
        return "JSON"
except Exception:
    pass

import backend.main as _main_mod
from backend.main import app, resolve_user
from backend.models import Base, SyncJob, User

_UTC = datetime.timezone.utc


@pytest.fixture(scope="module")
def db_engine():
    """In-memory SQLite with StaticPool + Postgres shims for server defaults."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _pg_shims(dbapi_conn, _rec):
        dbapi_conn.create_function("now", 0, lambda: datetime.datetime.now(_UTC).isoformat(" "))
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    Base.metadata.create_all(eng, tables=[User.__table__, SyncJob.__table__])
    return eng


@pytest.fixture(scope="module")
def users_and_jobs(db_engine):
    """Two regular users + one admin; owner has one strava and one stryd SyncJob."""
    original_engine = _main_mod.engine
    _main_mod.engine = db_engine

    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    strava_job_id = uuid.uuid4()
    stryd_job_id = uuid.uuid4()
    now = datetime.datetime.now(_UTC)

    with Session(db_engine) as db:
        db.add_all([
            User(id=owner_id, name="idor1696-owner", is_admin=False, is_active=True, created_at=now),
            User(id=other_id, name="idor1696-other", is_admin=False, is_active=True, created_at=now),
            User(id=admin_id, name="idor1696-admin", is_admin=True,  is_active=True, created_at=now),
        ])
        db.add_all([
            SyncJob(id=strava_job_id, user_id=owner_id, source="strava", job_type="manual", status="completed"),
            SyncJob(id=stryd_job_id,  user_id=owner_id, source="stryd",  job_type="manual", status="completed"),
        ])
        db.commit()

    yield SimpleNamespace(
        owner_id=owner_id,
        other_id=other_id,
        admin_id=admin_id,
        strava_job_id=strava_job_id,
        stryd_job_id=stryd_job_id,
    )

    _main_mod.engine = original_engine


_client = TestClient(app)


def _act_as(user_id: uuid.UUID, is_admin: bool = False):
    """Override resolve_user to return a minimal stub with the given identity."""
    stub = SimpleNamespace(id=user_id, is_admin=is_admin)
    async def _fake():
        return stub
    app.dependency_overrides[resolve_user] = _fake


def _clear_override():
    app.dependency_overrides.pop(resolve_user, None)


# ── AC1: strava/latest cross-user → 403 ───────────────────────────────────────

class TestStravaLatestIDOR:
    """AC1: GET /api/sync/strava/latest?user_id=<other> must return 403 for non-admin."""

    def test_non_admin_cross_user_strava_returns_403(self, users_and_jobs):
        _act_as(users_and_jobs.other_id)
        try:
            res = _client.get(
                "/api/sync/strava/latest",
                params={"user_id": str(users_and_jobs.owner_id)},
            )
            assert res.status_code == 403, (
                f"Expected 403 for cross-user strava/latest, got {res.status_code}: {res.text}"
            )
        finally:
            _clear_override()

    def test_non_admin_cross_user_strava_error_message(self, users_and_jobs):
        _act_as(users_and_jobs.other_id)
        try:
            res = _client.get(
                "/api/sync/strava/latest",
                params={"user_id": str(users_and_jobs.owner_id)},
            )
            assert res.status_code == 403
            # Should not expose any sync data in 403 response
            body = res.text
            assert "activities" not in body.lower() or "Forbidden" in body, (
                "403 response must not leak sync job data"
            )
        finally:
            _clear_override()


# ── AC2: stryd/latest cross-user → 403 ────────────────────────────────────────

class TestStrydLatestIDOR:
    """AC2: GET /api/sync/stryd/latest?user_id=<other> must return 403 for non-admin."""

    def test_non_admin_cross_user_stryd_returns_403(self, users_and_jobs):
        _act_as(users_and_jobs.other_id)
        try:
            res = _client.get(
                "/api/sync/stryd/latest",
                params={"user_id": str(users_and_jobs.owner_id)},
            )
            assert res.status_code == 403, (
                f"Expected 403 for cross-user stryd/latest, got {res.status_code}: {res.text}"
            )
        finally:
            _clear_override()

    def test_non_admin_cross_user_stryd_error_message(self, users_and_jobs):
        _act_as(users_and_jobs.other_id)
        try:
            res = _client.get(
                "/api/sync/stryd/latest",
                params={"user_id": str(users_and_jobs.owner_id)},
            )
            assert res.status_code == 403
            body = res.text
            assert "activities" not in body.lower() or "Forbidden" in body, (
                "403 response must not leak sync job data"
            )
        finally:
            _clear_override()


# ── AC3: Owner queries own data → 200 ─────────────────────────────────────────

class TestOwnerCanQueryOwnData:
    """AC3: Owner may still query their own data via ?user_id=<own_uuid>."""

    def test_owner_strava_with_user_id_returns_200(self, users_and_jobs):
        _act_as(users_and_jobs.owner_id)
        try:
            res = _client.get(
                "/api/sync/strava/latest",
                params={"user_id": str(users_and_jobs.owner_id)},
            )
            assert res.status_code == 200, (
                f"Owner querying own strava/latest should get 200, got {res.status_code}: {res.text}"
            )
        finally:
            _clear_override()

    def test_owner_stryd_with_user_id_returns_200(self, users_and_jobs):
        _act_as(users_and_jobs.owner_id)
        try:
            res = _client.get(
                "/api/sync/stryd/latest",
                params={"user_id": str(users_and_jobs.owner_id)},
            )
            assert res.status_code == 200, (
                f"Owner querying own stryd/latest should get 200, got {res.status_code}: {res.text}"
            )
        finally:
            _clear_override()


# ── AC4: Admin queries any user → 200 ─────────────────────────────────────────

class TestAdminCanQueryAnyUser:
    """AC4: Admin user may query any user's data (200)."""

    def test_admin_cross_user_strava_returns_200(self, users_and_jobs):
        _act_as(users_and_jobs.admin_id, is_admin=True)
        try:
            res = _client.get(
                "/api/sync/strava/latest",
                params={"user_id": str(users_and_jobs.owner_id)},
            )
            assert res.status_code == 200, (
                f"Admin querying another user's strava/latest should get 200, "
                f"got {res.status_code}: {res.text}"
            )
        finally:
            _clear_override()

    def test_admin_cross_user_stryd_returns_200(self, users_and_jobs):
        _act_as(users_and_jobs.admin_id, is_admin=True)
        try:
            res = _client.get(
                "/api/sync/stryd/latest",
                params={"user_id": str(users_and_jobs.owner_id)},
            )
            assert res.status_code == 200, (
                f"Admin querying another user's stryd/latest should get 200, "
                f"got {res.status_code}: {res.text}"
            )
        finally:
            _clear_override()


# ── AC5: No user_id (legacy path) still works ─────────────────────────────────

class TestLegacyPathUnaffected:
    """AC5: Omitting user_id uses the session user (legacy path) — must still work."""

    def test_strava_legacy_no_user_id_returns_200(self, users_and_jobs):
        _act_as(users_and_jobs.owner_id)
        try:
            res = _client.get("/api/sync/strava/latest")
            assert res.status_code in (200, 404), (
                f"Legacy strava/latest (no user_id) should return 200 or 404, "
                f"got {res.status_code}: {res.text}"
            )
        finally:
            _clear_override()

    def test_stryd_legacy_no_user_id_returns_200(self, users_and_jobs):
        _act_as(users_and_jobs.owner_id)
        try:
            res = _client.get("/api/sync/stryd/latest")
            assert res.status_code in (200, 404), (
                f"Legacy stryd/latest (no user_id) should return 200 or 404, "
                f"got {res.status_code}: {res.text}"
            )
        finally:
            _clear_override()
