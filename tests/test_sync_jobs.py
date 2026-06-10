"""
Tests for issue #373: sync_jobs table and SyncJob model.

4 AC anchors:
  (a) model importable from backend.models
  (b) status defaults to "pending"
  (c) cascade delete removes child rows when parent user deleted
  (d) timestamps and counters persist correctly after flush/commit
"""
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine


def _make_user() -> str:
    """Insert a bare user row and return its id as str."""
    name = f"sj373_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:n) RETURNING id"),
            {"n": name},
        ).fetchone()
    return str(row.id)


def _drop_user(uid: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


# ── (a) model importable ──────────────────────────────────────────────────────

def test_a_model_importable():
    """AC (a): SyncJob importable from backend.models and instantiates without error."""
    from backend.models import SyncJob
    obj = SyncJob()
    assert obj is not None


# ── (b) status defaults to "pending" ─────────────────────────────────────────

def test_b_status_defaults_to_pending():
    """AC (b): SyncJob.status Python-level default is 'pending'."""
    from backend.models import SyncJob
    uid = _make_user()
    try:
        with Session(engine) as session:
            job = SyncJob(
                user_id=uid,
                source="strava",
                job_type="incremental",
            )
            session.add(job)
            session.flush()
            assert job.status == "pending", f"Expected 'pending', got {job.status!r}"
            session.rollback()
    finally:
        _drop_user(uid)


# ── (c) cascade delete removes child rows ────────────────────────────────────

def test_c_cascade_delete_removes_sync_jobs():
    """AC (c): Deleting parent user removes all associated sync_jobs rows."""
    from backend.models import SyncJob
    uid = _make_user()

    with Session(engine) as session:
        for source in ("strava", "stryd"):
            job = SyncJob(user_id=uid, source=source, job_type="full")
            session.add(job)
        session.commit()

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM sync_jobs WHERE user_id = :uid"),
            {"uid": uid},
        ).scalar()
    assert count == 2, f"Expected 2 sync_jobs before delete, got {count}"

    _drop_user(uid)

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM sync_jobs WHERE user_id = :uid"),
            {"uid": uid},
        ).scalar()
    assert count == 0, f"Expected 0 sync_jobs after cascade delete, got {count}"


# ── (d) timestamps and counters persist correctly ────────────────────────────

def test_d_timestamps_and_counters_persist():
    """AC (d): Timestamps and counter columns persist correctly after flush/commit."""
    from backend.models import SyncJob
    uid = _make_user()
    try:
        with Session(engine) as session:
            job = SyncJob(
                user_id=uid,
                source="strava",
                job_type="incremental",
                activities_fetched=10,
                activities_created=3,
                activities_updated=5,
                activities_skipped=2,
                parameters={"force_resync": True, "date_range": "2025-01-01/2025-06-01"},
            )
            session.add(job)
            session.commit()
            job_id = job.id

        with Session(engine) as session:
            fetched = session.get(SyncJob, job_id)
            assert fetched is not None
            assert fetched.activities_fetched == 10
            assert fetched.activities_created == 3
            assert fetched.activities_updated == 5
            assert fetched.activities_skipped == 2
            assert fetched.parameters == {"force_resync": True, "date_range": "2025-01-01/2025-06-01"}
            assert fetched.created_at is not None
    finally:
        _drop_user(uid)
