"""Pull-queue (worker trigger migration, Phase 1) — job_queue repo + web enqueue.

Real-Postgres tests: they exercise FOR UPDATE SKIP LOCKED, partial indexes, JSONB
and gen_random_uuid(), none of which SQLite has. Run against UAT:

    set -a; source .env; set +a
    export ENVIRONMENT=UAT DATABASE_URL=$DATABASE_URL_UAT
    .venv/bin/python -m pytest tests/test_job_queue__pull_queue.py -q

Isolation: every row this file creates uses a `test_pq_*` job_type and the repo's
`job_types=` claim filter, so it never claims or reaps a real app/worker job on the
shared DB. An autouse fixture deletes the namespace before and after each test.

Acceptance criteria (issue: worker pull-queue Phase 1):
- enqueue inserts a `queued` row; claim_next flips exactly one row to `running`.
- Two concurrent claims never grab the same row (SKIP LOCKED).
- requeue_stale returns an expired-lease `running` row to `queued`, and terminally
  fails one that is out of attempts.
- fail(retryable=True) requeues until attempts hit max_attempts, then terminal.
- dedupe_key prevents a second active row for the same key.
- The web tier's delegate_* enqueue in queue mode and open NO socket to the worker.
- The job_queue table + its three partial indexes exist (migration applied).
"""
import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.services import job_queue


# ── Isolation: wipe the test namespace around every test ─────────────────────

def _wipe_namespace():
    with Session(engine) as s:
        s.execute(text("DELETE FROM job_queue WHERE job_type LIKE 'test_pq_%'"))
        s.commit()


@pytest.fixture(autouse=True)
def _clean_namespace():
    _wipe_namespace()
    yield
    _wipe_namespace()


def _row(job_id):
    with Session(engine) as s:
        return s.execute(
            text("SELECT id, status, attempts, max_attempts, claimed_by, "
                 "lease_expires_at, payload, enqueued_by, dedupe_key "
                 "FROM job_queue WHERE id = :id"),
            {"id": job_id},
        ).mappings().first()


def _insert_running_stale(*, attempts, max_attempts, expired=True):
    """Directly insert a `running` row whose lease is in the past (or future),
    so requeue_stale has a deterministic target with precise attempt counts."""
    offset = "-1 hour" if expired else "+1 hour"
    with Session(engine) as s:
        jid = s.execute(
            text(
                "INSERT INTO job_queue "
                "(job_type, payload, status, attempts, max_attempts, claimed_by, "
                " lease_expires_at, heartbeat_at, started_at) "
                "VALUES ('test_pq_stale', '{}'::jsonb, 'running', :a, :m, 'w-dead', "
                f"       now() + interval '{offset}', now(), now()) "
                "RETURNING id"
            ),
            {"a": attempts, "m": max_attempts},
        ).scalar_one()
        s.commit()
        return str(jid)


# ── enqueue / claim ──────────────────────────────────────────────────────────

def test_enqueue_inserts_queued_row():
    jid = job_queue.enqueue("test_pq_basic", {"user_id": "u1", "full": True})
    assert jid is not None
    row = _row(jid)
    assert row["status"] == "queued"
    assert row["attempts"] == 0
    assert row["payload"] == {"user_id": "u1", "full": True}
    assert row["enqueued_by"] == "web"
    assert row["claimed_by"] is None


def test_claim_next_flips_one_row_to_running():
    jid = job_queue.enqueue("test_pq_claim1", {"user_id": "u1"})
    claimed = job_queue.claim_next("worker-A", job_types=["test_pq_claim1"])
    assert claimed is not None
    assert str(claimed["id"]) == jid
    assert claimed["attempts"] == 1
    assert claimed["claimed_by"] == "worker-A"

    row = _row(jid)
    assert row["status"] == "running"
    assert row["lease_expires_at"] is not None

    # Queue now empty for this type → second claim returns None.
    assert job_queue.claim_next("worker-A", job_types=["test_pq_claim1"]) is None


def test_concurrent_claims_never_grab_same_row():
    """SKIP LOCKED: N threads claiming N rows get N distinct rows, no dup, no None."""
    n = 6
    for i in range(n):
        job_queue.enqueue("test_pq_race", {"i": i})

    results = []
    lock = threading.Lock()

    def worker(k):
        got = job_queue.claim_next(f"w{k}", job_types=["test_pq_race"])
        with lock:
            results.append(got)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = [str(r["id"]) for r in results if r is not None]
    assert len(ids) == n, f"expected {n} claims, got {len(ids)}"
    assert len(set(ids)) == n, f"duplicate claim detected: {ids}"


# ── requeue_stale (crash / sleep recovery) ───────────────────────────────────

def test_requeue_stale_returns_expired_lease_to_queued():
    jid = _insert_running_stale(attempts=1, max_attempts=3, expired=True)
    job_queue.requeue_stale()
    row = _row(jid)
    assert row["status"] == "queued"
    assert row["claimed_by"] is None
    assert row["lease_expires_at"] is None


def test_requeue_stale_terminally_fails_when_out_of_attempts():
    jid = _insert_running_stale(attempts=3, max_attempts=3, expired=True)
    job_queue.requeue_stale()
    row = _row(jid)
    assert row["status"] == "failed"


def test_requeue_stale_leaves_live_lease_alone():
    jid = _insert_running_stale(attempts=1, max_attempts=3, expired=False)
    job_queue.requeue_stale()
    row = _row(jid)
    assert row["status"] == "running", "a job with a live lease must not be reaped"


# ── fail retry semantics ─────────────────────────────────────────────────────

def test_fail_retryable_requeues_until_max_then_terminal():
    jid = job_queue.enqueue("test_pq_retry", {})
    # attempt 1
    job_queue.claim_next("w", job_types=["test_pq_retry"])
    job_queue.fail(jid, "boom 1", retryable=True)
    assert _row(jid)["status"] == "queued"
    # attempt 2
    job_queue.claim_next("w", job_types=["test_pq_retry"])
    job_queue.fail(jid, "boom 2", retryable=True)
    assert _row(jid)["status"] == "queued"
    # attempt 3 == max_attempts → terminal even though retryable
    job_queue.claim_next("w", job_types=["test_pq_retry"])
    job_queue.fail(jid, "boom 3", retryable=True)
    assert _row(jid)["status"] == "failed"


def test_fail_not_retryable_is_immediately_terminal():
    jid = job_queue.enqueue("test_pq_noretry", {})
    job_queue.claim_next("w", job_types=["test_pq_noretry"])
    job_queue.fail(jid, "no handler", retryable=False)
    assert _row(jid)["status"] == "failed"


def test_complete_marks_done():
    jid = job_queue.enqueue("test_pq_done", {})
    job_queue.claim_next("w", job_types=["test_pq_done"])
    job_queue.complete(jid, {"ok": True})
    row = _row(jid)
    assert row["status"] == "done"


# ── dedupe ───────────────────────────────────────────────────────────────────

def test_dedupe_key_prevents_second_active_row():
    key = f"test_pq_dedupe:{uuid.uuid4()}"
    first = job_queue.enqueue("test_pq_dedupe", {}, dedupe_key=key)
    second = job_queue.enqueue("test_pq_dedupe", {}, dedupe_key=key)
    assert first == second, "dedupe should return the existing row's id, not a new one"

    with Session(engine) as s:
        cnt = s.execute(
            text("SELECT COUNT(*) FROM job_queue WHERE dedupe_key = :k"),
            {"k": key},
        ).scalar_one()
    assert cnt == 1, f"dedupe_key must not create a second active row (got {cnt})"


def test_dedupe_allows_new_row_after_previous_is_terminal():
    key = f"test_pq_dedupe2:{uuid.uuid4()}"
    first = job_queue.enqueue("test_pq_dedupe2", {}, dedupe_key=key)
    job_queue.claim_next("w", job_types=["test_pq_dedupe2"])
    job_queue.complete(first, {})
    # previous row done → a fresh enqueue is allowed
    second = job_queue.enqueue("test_pq_dedupe2", {}, dedupe_key=key)
    assert second != first


# ── web tier enqueues in queue mode and opens NO socket ──────────────────────

def test_delegate_sync_enqueues_and_opens_no_socket(monkeypatch):
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "queue")
    from backend.services import worker_client

    calls = []
    monkeypatch.setattr(
        job_queue, "enqueue",
        lambda *a, **k: (calls.append((a, k)) or "fake-id"),
    )

    def _boom(*a, **k):  # any HTTP attempt is a bug in queue mode
        raise AssertionError("queue mode must not open a socket to the worker")

    monkeypatch.setattr(worker_client._urllib_request, "urlopen", _boom)

    uid = str(uuid.uuid4())
    out = worker_client.delegate_sync(uid, ["strava", "stryd"], full=True)

    assert out["queued"] is True
    assert out["job_ids"] == ["fake-id", "fake-id"]
    assert [c[0][0] for c in calls] == ["strava_sync", "stryd_sync"]
    # dedupe_key mirrors the worker's single-flight intent: <source>_sync:<uid>
    assert calls[0][1]["dedupe_key"] == f"strava_sync:{uid}"


def test_delegate_backfill_enqueues_and_opens_no_socket(monkeypatch):
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "queue")
    from backend.services import worker_client

    calls = []
    monkeypatch.setattr(
        job_queue, "enqueue",
        lambda *a, **k: (calls.append((a, k)) or "bf-id"),
    )
    monkeypatch.setattr(
        worker_client._urllib_request, "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no socket in queue mode")),
    )

    uid = str(uuid.uuid4())
    out = worker_client.delegate_backfill(uid)
    assert out["queued"] is True
    assert out["job_ids"] == ["bf-id"]
    assert calls[0][0][0] == "backfill"
    assert calls[0][1]["dedupe_key"] == f"backfill:{uid}"


# ── migration applied (table + three partial indexes present) ────────────────

def test_job_queue_table_and_partial_indexes_exist():
    """The migration created the table and its three partial indexes. Combined
    with the migration's table_exists / CREATE INDEX IF NOT EXISTS guards, this
    is how idempotency is verified in this codebase (see issue #706 pattern)."""
    with engine.connect() as conn:
        tbl = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='job_queue'"
        )).scalar()
        assert tbl == 1, "job_queue table not found — migration not applied"

        idx = {r[0] for r in conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname='public' AND tablename='job_queue'"
        )).fetchall()}
    for name in ("ix_job_queue_claim", "ix_job_queue_lease", "ix_job_queue_dedupe"):
        assert name in idx, f"missing partial index {name}: {sorted(idx)}"
