"""Neon-backed job queue repo (worker pull-queue migration, Phase 1).

Pure DB helpers, no HTTP. The web tier enqueues rows; the compute worker (behind
home NAT) claims them with SELECT ... FOR UPDATE SKIP LOCKED, so both machines
only ever connect OUTBOUND to Neon and NAT is a non-issue. Kept separate from
worker_job_runs, which stays the execution audit trail.

Each function opens a short-lived `Session(engine)` (matching DbRecorder), lazily
imports the model, and commits per operation. All timestamps are DB-side
(`now()`), so web and worker agree on time regardless of clock skew.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.utils.log import get_logger

_log = get_logger(__name__)

ACTIVE_STATUSES = ("queued", "running")


def enqueue(
    job_type: str,
    payload: dict,
    *,
    priority: int = 0,
    enqueued_by: str = "web",
    dedupe_key: Optional[str] = None,
) -> Optional[str]:
    """Insert a `queued` row and return its id (str).

    If `dedupe_key` is given and an active (queued/running) row already shares
    it, skip the insert and return that row's id — mirrors the worker's existing
    single-flight intent so double-clicks don't double-enqueue.
    """
    from backend.models import JobQueue

    with Session(engine) as s:
        if dedupe_key is not None:
            existing = s.execute(
                text(
                    "SELECT id FROM job_queue "
                    "WHERE dedupe_key = :k AND status IN ('queued', 'running') "
                    "ORDER BY created_at LIMIT 1"
                ),
                {"k": dedupe_key},
            ).scalar_one_or_none()
            if existing is not None:
                _log.info("enqueue dedupe hit: %s (%s)", job_type, dedupe_key)
                return str(existing)

        row = JobQueue(
            job_type=job_type,
            payload=payload or {},
            status="queued",
            priority=priority,
            enqueued_by=enqueued_by,
            dedupe_key=dedupe_key,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        _log.info("enqueued %s id=%s by=%s", job_type, row.id, enqueued_by)
        return str(row.id)


def claim_next(
    worker_id: str,
    *,
    lease_seconds: int = 600,
    job_types: Optional[list[str]] = None,
) -> Optional[dict]:
    """Atomically claim the next queued job (lowest priority, oldest first).

    Uses FOR UPDATE SKIP LOCKED so concurrent workers/threads never grab the same
    row. Flips it to `running`, bumps attempts, sets the claim + lease. Returns
    the claimed row as a dict, or None when the queue is empty.
    """
    sql = text(
        """
        UPDATE job_queue
           SET status='running',
               claimed_by=:wid,
               attempts=attempts + 1,
               lease_expires_at = now() + make_interval(secs => :lease),
               heartbeat_at = now(),
               started_at = COALESCE(started_at, now())
         WHERE id = (
           SELECT id FROM job_queue
            WHERE status='queued'
              AND (:no_filter OR job_type = ANY(:job_types))
            ORDER BY priority, created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1)
        RETURNING id, job_type, payload, attempts, max_attempts, claimed_by,
                  lease_expires_at, priority, enqueued_by, dedupe_key
        """
    )
    with Session(engine) as s:
        row = s.execute(
            sql,
            {
                "wid": worker_id,
                "lease": lease_seconds,
                "no_filter": job_types is None,
                "job_types": job_types or [],
            },
        ).mappings().first()
        s.commit()
        return dict(row) if row is not None else None


def heartbeat(job_id: str, *, lease_seconds: int = 600) -> None:
    """Bump heartbeat + extend the lease for a long-running claimed job."""
    with Session(engine) as s:
        s.execute(
            text(
                "UPDATE job_queue "
                "SET heartbeat_at = now(), "
                "    lease_expires_at = now() + make_interval(secs => :lease) "
                "WHERE id = :id AND status = 'running'"
            ),
            {"id": job_id, "lease": lease_seconds},
        )
        s.commit()


def complete(job_id: str, result: Optional[dict] = None) -> None:
    """Mark a job done."""
    from backend.models import JobQueue

    with Session(engine) as s:
        row = s.get(JobQueue, job_id)
        if row is None:
            return
        row.status = "done"
        row.result = result
        row.error = None
        row.finished_at = _db_now(s)
        s.commit()


def fail(job_id: str, error: str, *, retryable: bool) -> None:
    """Fail a job. If retryable and attempts remain, return it to `queued`
    (clearing the claim); otherwise mark it terminally `failed`."""
    from backend.models import JobQueue

    with Session(engine) as s:
        row = s.get(JobQueue, job_id)
        if row is None:
            return
        row.error = (error or "")[:2000]
        if retryable and (row.attempts or 0) < (row.max_attempts or 0):
            row.status = "queued"
            row.claimed_by = None
            row.lease_expires_at = None
            row.heartbeat_at = None
            _log.warning("job %s failed (retryable, attempt %s/%s): %s",
                         job_id, row.attempts, row.max_attempts, error)
        else:
            row.status = "failed"
            row.finished_at = _db_now(s)
            _log.error("job %s failed terminally: %s", job_id, error)
        s.commit()


def requeue_stale(*, now: Any = None) -> int:
    """Reaper: any `running` row whose lease has expired goes back to `queued`
    (claim cleared) if attempts remain, else `failed`. This recovers jobs when
    the Mac sleeps or the worker dies mid-job. Returns the count requeued.

    `now` is accepted for test injection; when None the DB's now() is used.
    """
    with Session(engine) as s:
        # Terminally fail the ones out of attempts...
        s.execute(
            text(
                "UPDATE job_queue "
                "SET status='failed', finished_at=now(), "
                "    error=COALESCE(error, 'lease expired (max attempts reached)') "
                "WHERE status='running' AND lease_expires_at < now() "
                "  AND attempts >= max_attempts"
            )
        )
        # ...and requeue the rest.
        result = s.execute(
            text(
                "UPDATE job_queue "
                "SET status='queued', claimed_by=NULL, "
                "    lease_expires_at=NULL, heartbeat_at=NULL "
                "WHERE status='running' AND lease_expires_at < now() "
                "  AND attempts < max_attempts"
            )
        )
        s.commit()
        n = result.rowcount or 0
        if n:
            _log.warning("requeue_stale: returned %d stale job(s) to queued", n)
        return n


def list_for_user(
    user_id: str,
    *,
    limit: int = 50,
    statuses: Optional[list[str]] = None,
) -> list[dict]:
    """Return this user's queue rows (newest first), for the user-facing Queue tab.

    User isolation is by `payload->>'user_id'` — batch jobs (banister_refit,
    which carry no user_id) are naturally excluded, and one user never sees
    another's rows. Never returns the raw payload (may hold internal fields)."""
    clauses = ["payload->>'user_id' = :uid"]
    params: dict[str, Any] = {"uid": str(user_id), "lim": int(limit)}
    if statuses:
        clauses.append("status = ANY(:statuses)")
        params["statuses"] = list(statuses)
    sql = text(
        "SELECT id, job_type, status, attempts, max_attempts, priority, "
        "       enqueued_by, created_at, started_at, finished_at, error "
        "FROM job_queue "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at DESC LIMIT :lim"
    )
    with Session(engine) as s:
        rows = s.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def pending_for_user(user_id: str) -> Optional[dict]:
    """The user's most relevant in-flight row (running preferred, else oldest
    queued), or None. Used to surface a 'Pending' state in /api/sync/status."""
    sql = text(
        "SELECT id, job_type, status, created_at "
        "FROM job_queue "
        "WHERE payload->>'user_id' = :uid AND status IN ('queued', 'running') "
        "ORDER BY (status = 'running') DESC, created_at "
        "LIMIT 1"
    )
    with Session(engine) as s:
        row = s.execute(sql, {"uid": str(user_id)}).mappings().first()
    return dict(row) if row is not None else None


def link_audit_row(job_id: str, worker_job_run_id: Any) -> None:
    """Link a claimed queue row to the worker_job_runs audit row created for it."""
    with Session(engine) as s:
        s.execute(
            text("UPDATE job_queue SET worker_job_run_id = :wjr WHERE id = :id"),
            {"wjr": worker_job_run_id, "id": job_id},
        )
        s.commit()


def has_done(dedupe_key: str) -> bool:
    """Return True if a `done` row with this dedupe_key exists.

    Used by the scheduler to skip re-enqueueing weekly_coach when the first
    wake-time run already completed successfully for this ISO week.
    """
    with Session(engine) as s:
        result = s.execute(
            text("SELECT 1 FROM job_queue WHERE dedupe_key = :k AND status = 'done' LIMIT 1"),
            {"k": dedupe_key},
        ).scalar_one_or_none()
        return result is not None


def get_owned_job(job_id: str, user_id: str, *, job_type: str | None = None) -> Optional[dict]:
    """Fetch one queue row scoped to the session user (never cross-user)."""
    clauses = ["id = :jid", "payload->>'user_id' = :uid"]
    params: dict[str, Any] = {"jid": job_id, "uid": str(user_id)}
    if job_type:
        clauses.append("job_type = :jt")
        params["jt"] = job_type
    sql = text(
        "SELECT id, job_type, status, result, error, created_at, started_at, finished_at "
        f"FROM job_queue WHERE {' AND '.join(clauses)}"
    )
    with Session(engine) as s:
        row = s.execute(sql, params).mappings().first()
    return dict(row) if row is not None else None


def _db_now(s: Session):
    return s.execute(text("SELECT now()")).scalar_one()
