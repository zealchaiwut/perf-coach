"""Phase 3 — sync routing, queue visibility, Garmin scaffold.

Real-PG for the job_queue user-isolation helpers (payload->>'user_id' filter),
unit/mocked for the routing + Garmin wiring. Run against UAT:

    set -a; source .env; set +a
    export ENVIRONMENT=UAT DATABASE_URL=$DATABASE_URL_UAT
    .venv/bin/python -m pytest tests/test_queue_endpoints__phase3.py -q

Rows use the `test_pq_*` job_type namespace and are wiped around each test.
"""
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import engine
from backend.services import job_queue


def _wipe():
    with Session(engine) as s:
        s.execute(text("DELETE FROM job_queue WHERE job_type LIKE 'test_pq_%'"))
        s.commit()


@pytest.fixture(autouse=True)
def _clean():
    _wipe()
    yield
    _wipe()


# ── job_queue.list_for_user / pending_for_user (user isolation) ───────────────

def test_list_for_user_isolates_by_payload_user():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    job_queue.enqueue("test_pq_q1", {"user_id": a})
    job_queue.enqueue("test_pq_q2", {"user_id": a})
    job_queue.enqueue("test_pq_q3", {"user_id": b})

    rows_a = job_queue.list_for_user(a)
    assert len(rows_a) == 2
    assert all(r["job_type"].startswith("test_pq_") for r in rows_a)
    # newest first
    assert rows_a[0]["job_type"] == "test_pq_q2"
    # b's row is not visible to a
    assert not any(r["job_type"] == "test_pq_q3" for r in rows_a)


def test_list_for_user_excludes_batch_without_user():
    a = str(uuid.uuid4())
    job_queue.enqueue("test_pq_batch", {})  # no user_id (like banister_refit)
    job_queue.enqueue("test_pq_mine", {"user_id": a})
    rows = job_queue.list_for_user(a)
    assert [r["job_type"] for r in rows] == ["test_pq_mine"]


def test_list_for_user_respects_limit():
    a = str(uuid.uuid4())
    for i in range(5):
        job_queue.enqueue(f"test_pq_lim{i}", {"user_id": a})
    assert len(job_queue.list_for_user(a, limit=3)) == 3


def test_pending_for_user_prefers_running_over_queued():
    a = str(uuid.uuid4())
    job_queue.enqueue("test_pq_pend_q", {"user_id": a})  # stays queued
    running_id = job_queue.enqueue("test_pq_pend_r", {"user_id": a})
    job_queue.claim_next("w", job_types=["test_pq_pend_r"])  # → running

    pending = job_queue.pending_for_user(a)
    assert pending is not None
    assert str(pending["id"]) == running_id
    assert pending["status"] == "running"


def test_pending_for_user_none_when_all_terminal():
    a = str(uuid.uuid4())
    jid = job_queue.enqueue("test_pq_done", {"user_id": a})
    job_queue.claim_next("w", job_types=["test_pq_done"])
    job_queue.complete(jid, {})
    assert job_queue.pending_for_user(a) is None


# ── sync routing flag + _maybe_delegate_incremental (unit) ───────────────────

def test_web_incremental_sync_enabled_default_on(monkeypatch):
    import backend.main as m
    monkeypatch.delenv("WEB_INCREMENTAL_SYNC_ENABLED", raising=False)
    assert m._web_incremental_sync_enabled() is True
    monkeypatch.setenv("WEB_INCREMENTAL_SYNC_ENABLED", "0")
    assert m._web_incremental_sync_enabled() is False


def test_maybe_delegate_incremental_none_when_web_enabled(monkeypatch):
    import backend.main as m
    monkeypatch.setenv("WEB_INCREMENTAL_SYNC_ENABLED", "1")
    assert m._maybe_delegate_incremental(uuid.uuid4(), "strava") is None


def test_maybe_delegate_incremental_delegates_when_disabled(monkeypatch):
    import backend.main as m
    from unittest.mock import patch
    monkeypatch.setenv("WEB_INCREMENTAL_SYNC_ENABLED", "0")
    with patch.object(m._worker_client, "delegate_sync",
                      return_value={"queued": True, "job_ids": ["x"]}) as mock_del:
        resp = m._maybe_delegate_incremental("u1", "stryd")
    assert resp is not None
    assert resp.status_code == 202
    body = json.loads(resp.body)
    assert body["worker_delegated"] is True
    args, kwargs = mock_del.call_args
    assert kwargs["full"] is False and kwargs["sources"] == ["stryd"]


def test_maybe_delegate_incremental_fails_closed_when_worker_unavailable(monkeypatch):
    import backend.main as m
    from unittest.mock import patch
    monkeypatch.setenv("WEB_INCREMENTAL_SYNC_ENABLED", "0")
    with patch.object(m._worker_client, "delegate_sync",
                      side_effect=m._worker_client.WorkerUnavailable("no worker")):
        resp = m._maybe_delegate_incremental("u1", "strava")
    assert resp is not None
    assert resp.status_code == 503
    body = __import__("json").loads(resp.body)
    assert "unavailable" in (body.get("detail") or "").lower()

# ── Garmin scaffold ──────────────────────────────────────────────────────────

def test_garmin_disabled_by_default(monkeypatch):
    from backend.services import garmin
    monkeypatch.delenv("GARMIN_SYNC_ENABLED", raising=False)
    assert garmin.is_enabled() is False
    monkeypatch.setenv("GARMIN_SYNC_ENABLED", "1")
    assert garmin.is_enabled() is True


def test_garmin_sync_raises_scaffold():
    from backend.services import garmin
    with pytest.raises(garmin.GarminNotConfigured):
        garmin.sync_garmin("u1")


def test_worker_h_garmin_sync_skips_when_disabled(monkeypatch):
    import backend.worker_app as w
    from backend.services import garmin
    from unittest.mock import patch
    monkeypatch.setattr(garmin, "is_enabled", lambda: False)
    with patch.object(garmin, "sync_garmin") as mock_sync:
        w._h_garmin_sync({"user_id": "u1"})  # must NOT call sync_garmin
    mock_sync.assert_not_called()


def test_worker_dispatch_has_garmin_sync():
    import backend.worker_app as w
    assert "garmin_sync" in w._DISPATCH
