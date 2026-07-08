"""Queue integration — drive a job through the REAL worker path.

Where test_job_queue__pull_queue.py unit-tests the repo functions, this file runs
the worker's actual dispatch loop in-process against the real queue: enqueue a
row, `claim_next` it, hand it to `worker_app._handle_job`, and assert the row
reaches the right terminal state. This is the "works with the queue" coverage —
claim → dispatch → complete / fail / retry / stale-reclaim, end to end.

Isolation: every job uses a `test_pq_*` job_type and handlers are added to
`_DISPATCH` only for the test (monkeypatch). The live worker on zeal-server polls
the real _DISPATCH job types, so it never claims these rows, and its dispatch map
is a different process — no cross-talk. Rows are wiped around each test.

Real-Postgres — run against UAT:
    set -a; source .env; set +a
    export ENVIRONMENT=UAT DATABASE_URL=$DATABASE_URL_UAT
    .venv/bin/python -m pytest tests/test_worker_queue_integration__phase1.py -q
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import backend.worker_app as w
from backend.db import engine
from backend.services import job_queue
from backend.services import precompute


def _wipe():
    with Session(engine) as s:
        s.execute(text("DELETE FROM job_queue WHERE job_type LIKE 'test_pq_%'"))
        s.commit()


@pytest.fixture(autouse=True)
def _clean():
    _wipe()
    yield
    _wipe()


def _status(job_id):
    with Session(engine) as s:
        return s.execute(
            text("SELECT status FROM job_queue WHERE id = :id"), {"id": job_id}
        ).scalar_one_or_none()


def _claim_and_handle(job_type):
    """One worker iteration for a single job type: claim the next row and run it
    through the real _handle_job (dispatch + complete/fail + heartbeat)."""
    row = job_queue.claim_next(w._WORKER_ID, job_types=[job_type])
    if row is None:
        return None
    w._handle_job(row)
    return row


# ── claim → dispatch → complete ──────────────────────────────────────────────

def test_worker_claims_and_completes_job(monkeypatch):
    seen = []
    monkeypatch.setitem(w._DISPATCH, "test_pq_echo", lambda p: seen.append(p))

    jid = job_queue.enqueue("test_pq_echo", {"x": 1})
    row = _claim_and_handle("test_pq_echo")

    assert row is not None and str(row["id"]) == jid
    assert seen == [{"x": 1}]          # handler ran with the payload
    assert _status(jid) == "done"      # _handle_job marked it done
    # queue now empty for this type
    assert job_queue.claim_next(w._WORKER_ID, job_types=["test_pq_echo"]) is None


# ── no handler → terminal fail (not retryable) ───────────────────────────────

def test_worker_fails_unhandled_job_terminally():
    jid = job_queue.enqueue("test_pq_nohandler", {})
    # claim manually (no _DISPATCH entry, so _claim_and_handle would still claim
    # then _handle_job fails it as unhandled)
    row = job_queue.claim_next(w._WORKER_ID, job_types=["test_pq_nohandler"])
    w._handle_job(row)
    assert _status(jid) == "failed"


# ── handler raises → retry to max_attempts then terminal ─────────────────────

def test_worker_retries_on_raise_then_terminal(monkeypatch):
    def _boom(_p):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(w._DISPATCH, "test_pq_boom", _boom)
    jid = job_queue.enqueue("test_pq_boom", {})

    # max_attempts defaults to 3: three claim+handle cycles → requeued, requeued,
    # then terminal failed.
    for _ in range(3):
        if _claim_and_handle("test_pq_boom") is None:
            break
    assert _status(jid) == "failed"


# ── real precompute handler, driven through the queue ────────────────────────

def test_precompute_handler_runs_via_queue(monkeypatch):
    """Map the real _h_precompute onto a test job type and drive it through the
    claim path — proves the precompute wiring works end-to-end via the queue
    without touching a real user's snapshot (precompute_user is spied)."""
    calls = []
    monkeypatch.setattr(precompute, "precompute_user",
                        lambda uid, dates=None: calls.append((uid, dates)) or {"ok": True})
    monkeypatch.setitem(w._DISPATCH, "test_pq_precompute", w._h_precompute)

    uid = str(uuid.uuid4())
    jid = job_queue.enqueue("test_pq_precompute", {"user_id": uid})
    _claim_and_handle("test_pq_precompute")

    assert calls == [(uid, None)]
    assert _status(jid) == "done"


# ── stale claim reclaimed and completed on the next pass ─────────────────────

def test_stale_running_job_is_reclaimed_and_completes(monkeypatch):
    """A job left `running` with an expired lease (worker crashed/slept) is
    requeued by requeue_stale and then successfully claimed + completed — the
    crash-recovery path the poll loop runs every tick."""
    seen = []
    monkeypatch.setitem(w._DISPATCH, "test_pq_stale", lambda p: seen.append(p))

    # Insert a running row whose lease already expired (attempts < max).
    with Session(engine) as s:
        jid = s.execute(
            text(
                "INSERT INTO job_queue "
                "(job_type, payload, status, attempts, max_attempts, claimed_by, "
                " lease_expires_at, heartbeat_at, started_at) "
                "VALUES ('test_pq_stale', '{\"n\": 7}'::jsonb, 'running', 1, 3, "
                "        'dead-worker', now() - interval '1 hour', now(), now()) "
                "RETURNING id"
            )
        ).scalar_one()
        s.commit()
    jid = str(jid)

    # Reaper returns it to queued...
    job_queue.requeue_stale()
    assert _status(jid) == "queued"

    # ...and the next claim runs it to completion.
    _claim_and_handle("test_pq_stale")
    assert seen == [{"n": 7}]
    assert _status(jid) == "done"
