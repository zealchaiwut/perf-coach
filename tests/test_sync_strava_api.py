"""TDD tests for issue #382: POST /api/sync/strava trigger endpoint.

Each test class is anchored to one Acceptance Criterion.
Server: http://127.0.0.1:9001
"""
import uuid
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from backend.auth import generate_csrf_token, hash_password
from backend.models import SyncJob, StravaActivity, StravaToken, User

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "sync382-int-pw"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_REPO_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_authed_client(username: str, user_id: str) -> httpx.Client:
    temp = httpx.Client(base_url=BASE, timeout=15, follow_redirects=True)
    login = temp.post("/api/auth/login", json={"username": username, "password": _TEST_PASSWORD})
    assert login.status_code == 200, f"Login failed: {login.text}"
    session_val = temp.cookies.get("session", "")
    temp.close()
    assert session_val, "Login must set session cookie"
    csrf = generate_csrf_token()
    c = httpx.Client(
        base_url=BASE,
        timeout=15,
        follow_redirects=True,
        cookies={"session": session_val, "csrf-token": csrf},
        headers={"X-CSRF-Token": csrf},
    )
    c._user_id = user_id
    return c


def _create_user_with_password(username: str) -> str:
    temp = httpx.Client(base_url=BASE, timeout=15, follow_redirects=True)
    res = temp.post("/api/users", json={"name": username})
    assert res.status_code == 201, f"User create failed: {res.text}"
    user_id = res.json()["id"]
    temp.close()
    with Session(engine) as db:
        u = db.get(User, uuid.UUID(user_id))
        assert u is not None
        u.password_hash = hash_password(_TEST_PASSWORD)
        db.commit()
    return user_id


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def authed_client():
    """Authenticated user with a fake strava_tokens row."""
    username = f"s382_{uuid.uuid4().hex[:8]}"
    user_id = _create_user_with_password(username)
    uid = uuid.UUID(user_id)
    with Session(engine) as db:
        token = StravaToken(
            user_id=uid,
            athlete_id=99382,
            access_token="fake_access_382",
            refresh_token="fake_refresh_382",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        )
        db.add(token)
        db.commit()
    c = _make_authed_client(username, user_id)
    yield c
    with Session(engine) as db:
        db.execute(delete(SyncJob).where(SyncJob.user_id == uid))
        db.execute(delete(StravaToken).where(StravaToken.user_id == uid))
        db.commit()
    with httpx.Client(base_url=BASE, timeout=10) as tmp:
        tmp.delete(f"/api/users/{user_id}")
    c.close()


@pytest.fixture(scope="module")
def no_strava_client():
    """Authenticated user without strava_tokens row."""
    username = f"s382ns_{uuid.uuid4().hex[:8]}"
    user_id = _create_user_with_password(username)
    c = _make_authed_client(username, user_id)
    yield c
    with httpx.Client(base_url=BASE, timeout=10) as tmp:
        tmp.delete(f"/api/users/{user_id}")
    c.close()


def _clean_active_jobs(uid: uuid.UUID) -> None:
    with Session(engine) as db:
        db.execute(
            delete(SyncJob)
            .where(SyncJob.user_id == uid)
            .where(SyncJob.status.in_(["pending", "running"]))
        )
        db.commit()


# ── (a) POST creates a SyncJob row in the database ───────────────────────────

class TestPostCreatesSyncJob:
    """AC (a): POST /api/sync/strava creates a SyncJob row in the database."""

    def test_a_post_creates_sync_job_row(self, authed_client):
        uid = uuid.UUID(authed_client._user_id)
        _clean_active_jobs(uid)

        res = authed_client.post("/api/sync/strava")
        assert res.status_code == 202, res.text
        body = res.json()

        job_id = body.get("job_id")
        assert job_id is not None, "Response must include job_id"
        assert body.get("status") == "running"
        assert body.get("polling_url") == f"/api/sync/strava/status?job_id={job_id}"

        with Session(engine) as db:
            job = db.get(SyncJob, uuid.UUID(job_id))
            assert job is not None, f"SyncJob {job_id} not found in DB"
            assert job.source == "strava"
            assert job.user_id == uid
            # job_type is initial_backfill (no strava_activities) or manual_trigger
            assert job.job_type in ("initial_backfill", "manual_trigger")

        _clean_active_jobs(uid)
        with Session(engine) as db:
            db.execute(delete(SyncJob).where(SyncJob.id == uuid.UUID(job_id)))
            db.commit()


# ── (b) POST when Strava not connected → 422 ─────────────────────────────────

class TestPostNoStravaToken:
    """AC (b): POST /api/sync/strava when Strava not connected returns 422."""

    def test_b_no_strava_token_returns_422(self, no_strava_client):
        res = no_strava_client.post("/api/sync/strava")
        assert res.status_code == 422, res.text
        assert "Connect Strava first" in res.text


# ── (c) POST when sync already running → 409 ─────────────────────────────────

class TestPostAlreadyRunning:
    """AC (c): POST /api/sync/strava when a sync is already running returns 409."""

    def test_c_already_running_returns_409(self, authed_client):
        uid = uuid.UUID(authed_client._user_id)
        _clean_active_jobs(uid)

        with Session(engine) as db:
            job = SyncJob(
                user_id=uid,
                source="strava",
                job_type="manual_trigger",
                status="running",
                started_at=datetime.now(tz=timezone.utc),
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            blocking_job_id = str(job.id)

        try:
            res = authed_client.post("/api/sync/strava")
            assert res.status_code == 409, res.text
            body = res.json()
            detail = body.get("detail", "")
            assert "A sync is already in progress" in detail
            assert body.get("job_id") == blocking_job_id
        finally:
            with Session(engine) as db:
                db.execute(delete(SyncJob).where(SyncJob.id == uuid.UUID(blocking_job_id)))
                db.commit()


# ── (d) GET /api/sync/strava/status returns current job state ─────────────────

class TestGetStatus:
    """AC (d): GET /api/sync/strava/status?job_id={uuid} returns full SyncJob dict."""

    def test_d_status_returns_job_fields(self, authed_client):
        uid = uuid.UUID(authed_client._user_id)
        with Session(engine) as db:
            job = SyncJob(
                user_id=uid,
                source="strava",
                job_type="manual_trigger",
                status="completed",
                started_at=datetime.now(tz=timezone.utc) - timedelta(minutes=2),
                completed_at=datetime.now(tz=timezone.utc) - timedelta(minutes=1),
                activities_created=5,
                activities_updated=3,
                error_message=None,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            job_id = str(job.id)

        try:
            res = authed_client.get(f"/api/sync/strava/status?job_id={job_id}")
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["status"] == "completed"
            assert body["activities_created"] == 5
            assert body["activities_updated"] == 3
            assert body.get("started_at") is not None
            assert body.get("completed_at") is not None
            assert body.get("error_message") is None
        finally:
            with Session(engine) as db:
                db.execute(delete(SyncJob).where(SyncJob.id == uuid.UUID(job_id)))
                db.commit()

    def test_d_status_404_for_unknown_job(self, authed_client):
        unknown = str(uuid.uuid4())
        res = authed_client.get(f"/api/sync/strava/status?job_id={unknown}")
        assert res.status_code == 404, res.text


# ── (e) GET /api/sync/strava/latest returns most recent job ──────────────────

class TestGetLatest:
    """AC (e): GET /api/sync/strava/latest?user_id={uid} returns most recent SyncJob."""

    def test_e_latest_returns_most_recent(self, authed_client):
        uid = uuid.UUID(authed_client._user_id)
        inserted_ids = []
        with Session(engine) as db:
            for i, status in enumerate(["completed", "failed", "running"]):
                job = SyncJob(
                    user_id=uid,
                    source="strava",
                    job_type="manual_trigger",
                    status=status,
                    started_at=datetime.now(tz=timezone.utc) - timedelta(minutes=10 - i),
                )
                db.add(job)
            db.commit()
            rows = db.execute(
                select(SyncJob)
                .where(SyncJob.user_id == uid)
                .where(SyncJob.source == "strava")
            ).scalars().all()
            inserted_ids = [str(r.id) for r in rows]
            latest_id = str(
                sorted(rows, key=lambda r: r.started_at, reverse=True)[0].id
            )

        try:
            res = authed_client.get(f"/api/sync/strava/latest?user_id={uid}")
            assert res.status_code == 200, res.text
            body = res.json()
            assert body.get("id") == latest_id
            assert body.get("status") is not None
            assert body.get("source") == "strava"
        finally:
            with Session(engine) as db:
                for jid in inserted_ids:
                    db.execute(delete(SyncJob).where(SyncJob.id == uuid.UUID(jid)))
                db.commit()

    def test_e_latest_404_when_no_jobs(self, no_strava_client):
        uid = no_strava_client._user_id
        res = no_strava_client.get(f"/api/sync/strava/latest?user_id={uid}")
        assert res.status_code == 404, res.text


# ── (f) since_date filter applied correctly ───────────────────────────────────

class TestSinceDateFilter:
    """AC (f): since_date filter is stored on the SyncJob and validated correctly."""

    def test_f_valid_since_date_stored_on_job(self, authed_client):
        uid = uuid.UUID(authed_client._user_id)
        _clean_active_jobs(uid)

        since = (date.today() - timedelta(days=30)).isoformat()
        res = authed_client.post("/api/sync/strava", json={"since_date": since})
        assert res.status_code == 202, res.text
        job_id = res.json()["job_id"]

        try:
            with Session(engine) as db:
                job = db.get(SyncJob, uuid.UUID(job_id))
                assert job is not None
                assert job.since_date is not None
                assert job.since_date.isoformat() == since
        finally:
            _clean_active_jobs(uid)
            with Session(engine) as db:
                db.execute(delete(SyncJob).where(SyncJob.id == uuid.UUID(job_id)))
                db.commit()

    def test_f_since_date_too_old_returns_422(self, authed_client):
        old_date = (date.today() - timedelta(days=400)).isoformat()
        res = authed_client.post("/api/sync/strava", json={"since_date": old_date})
        assert res.status_code == 422, res.text

    def test_f_since_date_invalid_format_returns_422(self, authed_client):
        res = authed_client.post("/api/sync/strava", json={"since_date": "not-a-date"})
        assert res.status_code == 422, res.text
