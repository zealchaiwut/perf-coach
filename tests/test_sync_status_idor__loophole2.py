"""Tests for fix-loopholes Task 2: IDOR on GET /api/sync/strava/status.

The endpoint fetched SyncJob by job_id with no ownership check — any
authenticated user could read another user's sync job (source, counts,
error_message) by guessing/enumerating job_id. Now returns 404 (not 403,
to avoid confirming the job_id exists) when job.user_id != session user.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.db import engine
from backend.main import app, resolve_user
from backend.models import SyncJob, User
from sqlalchemy.orm import Session

_client = TestClient(app)


@pytest.fixture
def two_users_and_job():
    owner = User(name="idor2-owner-" + uuid.uuid4().hex[:8])
    other = User(name="idor2-other-" + uuid.uuid4().hex[:8])
    with Session(engine) as db:
        db.add_all([owner, other])
        db.commit()
        owner_id, other_id = owner.id, other.id
        job = SyncJob(user_id=owner_id, source="strava", job_type="sync", status="completed")
        db.add(job)
        db.commit()
        job_id = job.id

    yield SimpleNamespace(id=owner_id), SimpleNamespace(id=other_id), job_id

    with Session(engine) as db:
        db.query(SyncJob).filter(SyncJob.id == job_id).delete()
        db.query(User).filter(User.id.in_([owner_id, other_id])).delete(synchronize_session=False)
        db.commit()


def _as(user):
    async def _fake():
        return user
    app.dependency_overrides[resolve_user] = _fake


def test_owner_can_read_own_job_status(two_users_and_job):
    owner, other, job_id = two_users_and_job
    _as(owner)
    try:
        res = _client.get("/api/sync/strava/status", params={"job_id": str(job_id)})
        assert res.status_code == 200
        assert res.json()["id"] == str(job_id)
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_other_user_reading_job_returns_404(two_users_and_job):
    owner, other, job_id = two_users_and_job
    _as(other)
    try:
        res = _client.get("/api/sync/strava/status", params={"job_id": str(job_id)})
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_nonexistent_job_returns_404(two_users_and_job):
    owner, other, job_id = two_users_and_job
    _as(owner)
    try:
        res = _client.get("/api/sync/strava/status", params={"job_id": str(uuid.uuid4())})
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(resolve_user, None)
