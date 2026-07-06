"""Tests for issue #1297: route heavy paths (full syncs, performance backfill,
threshold-save rebuilds) to the compute worker.

AC coverage:
  AC1 - full=true Strava/Stryd syncs delegate to worker /internal/sync/run;
        incremental syncs keep in-process path
  AC2 - POST /api/performance/backfill and threshold-save backfill triggers
        delegate to /internal/performance/backfill
  AC3 - Worker-unreachable returns 503; no silent fall-through in-process;
        opt-in fallback via ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS env flag
  AC4 - GET /api/sync/status surfaces worker_job_runs rows for delegated jobs
  AC5 - Legacy POST /api/sync/strava is gated / returns 410 when disabled
  AC6 - Worker base URL and auth come from env vars (WORKER_BASE_URL,
        WORKER_SHARED_SECRET)
  AC7 - Full-sync delegate call is mocked; no in-process reconcile on full;
        worker-down returns documented error; incremental unchanged
"""
import json
import uuid
from unittest.mock import MagicMock, patch, call
import pytest

from backend.services import sync_jobs
import backend.main as main_mod
from backend.models import User
import backend.services.worker_client as worker_client


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_user(uid=None):
    user = MagicMock(spec=User)
    user.id = uid or uuid.uuid4()
    user.name = "test-user"
    return user


def _clear_registry():
    with sync_jobs._lock:
        sync_jobs._registry.clear()


# ── AC6: env-var config ───────────────────────────────────────────────────────

def test_worker_client_reads_base_url_from_env(monkeypatch):
    """WORKER_BASE_URL env var is read by worker_client."""
    monkeypatch.setenv("WORKER_BASE_URL", "http://zeal-server:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "s3cr3t")
    import importlib
    importlib.reload(worker_client)
    assert worker_client.get_worker_base_url() == "http://zeal-server:9100"


def test_worker_client_reads_secret_from_env(monkeypatch):
    """WORKER_SHARED_SECRET env var is read by worker_client."""
    monkeypatch.setenv("WORKER_BASE_URL", "http://zeal-server:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "mysecret")
    import importlib
    importlib.reload(worker_client)
    assert worker_client.get_worker_shared_secret() == "mysecret"


def test_worker_unavailable_when_no_base_url(monkeypatch):
    """WorkerUnavailable raised when WORKER_BASE_URL is not set."""
    monkeypatch.delenv("WORKER_BASE_URL", raising=False)
    with pytest.raises(worker_client.WorkerUnavailable):
        worker_client.delegate_sync(str(uuid.uuid4()), ["strava"], full=True)


# ── AC1: full Strava sync → worker ───────────────────────────────────────────

def test_full_strava_sync_delegates_to_worker(monkeypatch):
    """full=true Strava sync calls worker /internal/sync/run, not in-process worker."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    with patch.object(worker_client, "delegate_sync", return_value={"started": True, "users": 1}) as mock_delegate, \
         patch.object(main_mod, "_strava_sync_worker") as mock_inprocess:

        body = MagicMock()
        body.full = True
        body.since_date = None
        resp = main_mod.strava_sync(body=body, user=user)

    assert resp.status_code == 202
    data = json.loads(resp.body)
    assert data.get("worker_delegated") is True
    mock_delegate.assert_called_once()
    mock_inprocess.assert_not_called()


def test_incremental_strava_sync_runs_inprocess(monkeypatch):
    """full=false (incremental) Strava sync still runs in the web process."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    # Even if worker is configured, incremental should NOT delegate
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    submitted = []

    def fake_submit(fn, *args, **kwargs):
        submitted.append(fn)

    with patch.object(worker_client, "delegate_sync") as mock_delegate, \
         patch.object(main_mod._sync_pool, "submit", side_effect=fake_submit):

        body = MagicMock()
        body.full = False
        body.since_date = None
        resp = main_mod.strava_sync(body=body, user=user)

    assert resp.status_code == 202
    mock_delegate.assert_not_called()
    assert submitted, "in-process worker should have been submitted to thread pool"


# ── AC1: full Stryd sync → worker ────────────────────────────────────────────

def test_full_stryd_sync_delegates_to_worker(monkeypatch):
    """full=true Stryd sync calls worker /internal/sync/run, not in-process."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    mock_cred = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_cred

    with patch.object(worker_client, "delegate_sync", return_value={"started": True, "users": 1}) as mock_delegate, \
         patch.object(main_mod, "_stryd_sync_worker") as mock_inprocess, \
         patch("backend.main.Session", return_value=mock_session):

        body = MagicMock()
        body.full = True
        body.since_date = None
        resp = main_mod.stryd_sync(body=body, user=user)

    assert resp.status_code == 202
    data = json.loads(resp.body)
    assert data.get("worker_delegated") is True
    mock_delegate.assert_called_once()
    mock_inprocess.assert_not_called()


def test_incremental_stryd_sync_runs_inprocess(monkeypatch):
    """full=false Stryd sync stays in-process even when worker is configured."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    mock_cred = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_cred

    submitted = []

    def fake_submit(fn, *args, **kwargs):
        submitted.append(fn)

    with patch.object(worker_client, "delegate_sync") as mock_delegate, \
         patch("backend.main.Session", return_value=mock_session), \
         patch.object(main_mod._sync_pool, "submit", side_effect=fake_submit):

        body = MagicMock()
        body.full = False
        body.since_date = None
        resp = main_mod.stryd_sync(body=body, user=user)

    assert resp.status_code == 202
    mock_delegate.assert_not_called()
    assert submitted, "in-process worker should have been submitted to thread pool"


# ── AC2: /api/performance/backfill → worker ───────────────────────────────────

def test_performance_backfill_delegates_to_worker(monkeypatch):
    """POST /api/performance/backfill proxies to worker's /internal/performance/backfill."""
    uid = uuid.uuid4()
    user = _make_user(uid)

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    with patch.object(worker_client, "delegate_backfill", return_value={"started": True}) as mock_delegate, \
         patch.object(main_mod, "_backfill_performance_for_athlete") as mock_inprocess:

        resp = main_mod.post_performance_backfill(user=user)

    assert resp.status_code == 202
    data = json.loads(resp.body)
    assert data.get("worker_delegated") is True
    mock_delegate.assert_called_once_with(str(uid))
    mock_inprocess.assert_not_called()


def test_threshold_save_trigger_delegates_to_worker(monkeypatch):
    """_trigger_performance_backfill_background calls worker, not daemon thread."""
    uid = uuid.uuid4()

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    with patch.object(worker_client, "delegate_backfill", return_value={"started": True}) as mock_delegate, \
         patch("backend.main._threading") as mock_threading:

        main_mod._trigger_performance_backfill_background(uid)

    mock_delegate.assert_called_once_with(str(uid))
    mock_threading.Thread.assert_not_called()


# ── AC3: worker unreachable → 503, no silent fallthrough ─────────────────────

def test_full_strava_sync_worker_down_returns_503(monkeypatch):
    """When worker is unreachable, full Strava sync returns 503 (not 202 running in-process)."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    # Ensure fallback is disabled (default)
    monkeypatch.delenv("ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS", raising=False)

    with patch.object(worker_client, "delegate_sync", side_effect=worker_client.WorkerUnavailable("conn refused")), \
         patch.object(main_mod, "_strava_sync_worker") as mock_inprocess:

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            body = MagicMock()
            body.full = True
            body.since_date = None
            main_mod.strava_sync(body=body, user=user)

    assert exc_info.value.status_code == 503
    mock_inprocess.assert_not_called()


def test_full_stryd_sync_worker_down_returns_503(monkeypatch):
    """When worker is unreachable, full Stryd sync returns 503."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.delenv("ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS", raising=False)

    mock_cred = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_cred

    with patch.object(worker_client, "delegate_sync", side_effect=worker_client.WorkerUnavailable("conn refused")), \
         patch.object(main_mod, "_stryd_sync_worker") as mock_inprocess, \
         patch("backend.main.Session", return_value=mock_session):

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            body = MagicMock()
            body.full = True
            body.since_date = None
            main_mod.stryd_sync(body=body, user=user)

    assert exc_info.value.status_code == 503
    mock_inprocess.assert_not_called()


def test_full_sync_fallback_opt_in_runs_inprocess(monkeypatch):
    """ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS=1 allows in-process fallback when worker is down."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.setenv("ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS", "1")

    submitted = []

    def fake_submit(fn, *args, **kwargs):
        submitted.append(fn)

    with patch.object(worker_client, "delegate_sync", side_effect=worker_client.WorkerUnavailable("down")), \
         patch.object(main_mod._sync_pool, "submit", side_effect=fake_submit):

        body = MagicMock()
        body.full = True
        body.since_date = None
        resp = main_mod.strava_sync(body=body, user=user)

    assert resp.status_code == 202
    assert submitted, "fallback: in-process worker should be submitted"


def test_performance_backfill_worker_down_returns_503(monkeypatch):
    """POST /api/performance/backfill returns 503 when worker unreachable."""
    uid = uuid.uuid4()
    user = _make_user(uid)

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")
    monkeypatch.delenv("ROUTE_BACKFILL_FALLBACK_TO_INPROCESS", raising=False)

    with patch.object(worker_client, "delegate_backfill", side_effect=worker_client.WorkerUnavailable("down")):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            main_mod.post_performance_backfill(user=user)

    assert exc_info.value.status_code == 503


# ── AC4: GET /api/sync/status surfaces worker_job_runs ───────────────────────

def test_sync_status_includes_worker_job_when_no_inprocess(monkeypatch):
    """GET /api/sync/status returns worker_job_runs row when no in-process job exists."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    from datetime import datetime, timezone
    mock_worker_job = MagicMock()
    mock_worker_job.status = "running"
    mock_worker_job.phase = "pulling_strava"
    mock_worker_job.job_type = "strava_sync"
    mock_worker_job.items_synced = 0
    mock_worker_job.error = None
    mock_worker_job.started_at = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)
    mock_worker_job.finished_at = None

    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_worker_job

    with patch("backend.main.Session", return_value=mock_session):
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(main_mod.get_sync_status(user=user))

    data = json.loads(resp.body)
    assert data["status"] == "running"
    assert data.get("source") == "worker"


def test_sync_status_prefers_inprocess_over_worker(monkeypatch):
    """In-process job takes precedence over worker_job_runs in GET /api/sync/status."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    sync_jobs.start(uid, "strava")

    with patch("backend.main.Session") as mock_session_cls:
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(main_mod.get_sync_status(user=user))

    data = json.loads(resp.body)
    assert data["status"] == "running"
    assert data.get("source") != "worker"


# ── AC5: legacy POST /api/sync/strava gated ──────────────────────────────────

def test_legacy_sync_strava_disabled_by_default(monkeypatch):
    """POST /api/sync/strava returns 410 when LEGACY_SYNC_STRAVA_ENABLED is unset/0."""
    monkeypatch.delenv("LEGACY_SYNC_STRAVA_ENABLED", raising=False)
    uid = uuid.uuid4()
    user = _make_user(uid)

    from fastapi import HTTPException
    import asyncio
    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(
            main_mod.post_sync_strava(
                background_tasks=MagicMock(),
                body=None,
                user=user,
            )
        )
    assert exc_info.value.status_code == 410


def test_legacy_sync_strava_enabled_by_flag(monkeypatch):
    """POST /api/sync/strava works when LEGACY_SYNC_STRAVA_ENABLED=1."""
    monkeypatch.setenv("LEGACY_SYNC_STRAVA_ENABLED", "1")
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    from sqlalchemy import select
    mock_token = MagicMock()
    mock_job = MagicMock()
    mock_job.id = uuid.uuid4()

    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    call_count = [0]

    def mock_execute(query):
        call_count[0] += 1
        r = MagicMock()
        if call_count[0] == 1:
            r.scalar_one_or_none.return_value = mock_token
        else:
            r.scalar_one_or_none.return_value = None
        return r

    mock_session.execute = mock_execute
    mock_session.add = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.refresh = MagicMock()

    background_tasks = MagicMock()

    with patch("backend.main.Session", return_value=mock_session):
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(
            main_mod.post_sync_strava(
                background_tasks=background_tasks,
                body=None,
                user=user,
            )
        )

    assert resp.status_code == 202


# ── AC7: delegate call produces no in-process reconcile ─────────────────────

def test_full_strava_sync_no_inprocess_reconcile(monkeypatch):
    """Full Strava sync via worker: reconcile is NOT called in-process."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    with patch.object(worker_client, "delegate_sync", return_value={"started": True}), \
         patch("backend.main._workout_reconcile") as mock_reconcile:

        body = MagicMock()
        body.full = True
        body.since_date = None
        main_mod.strava_sync(body=body, user=user)

    mock_reconcile.reconcile_strava_to_workouts.assert_not_called()
    mock_reconcile.reconcile_stryd_to_workouts.assert_not_called()


def test_worker_client_delegate_sync_sends_correct_payload(monkeypatch):
    """delegate_sync sends correct JSON body and X-Worker-Secret header to worker."""
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "mysecret")

    import importlib
    importlib.reload(worker_client)

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["data"] = json.loads(req.data)
        ctx = MagicMock()
        ctx.__enter__ = lambda s: s
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.read = MagicMock(return_value=b'{"started": true, "users": 1}')
        ctx.getcode = MagicMock(return_value=200)
        return ctx

    user_id = str(uuid.uuid4())
    with patch("backend.services.worker_client._urllib_request.urlopen", side_effect=fake_urlopen):
        worker_client.delegate_sync(user_id, sources=["strava"], full=True)

    assert captured["url"] == "http://worker:9100/internal/sync/run"
    assert captured["headers"].get("X-worker-secret") == "mysecret"
    assert captured["data"]["user_id"] == user_id
    assert captured["data"]["full"] is True
    assert captured["data"]["sources"] == ["strava"]


def test_worker_client_connection_error_raises_worker_unavailable(monkeypatch):
    """Connection error to worker raises WorkerUnavailable."""
    monkeypatch.setenv("WORKER_BASE_URL", "http://worker:9100")
    monkeypatch.setenv("WORKER_SHARED_SECRET", "sec")

    import importlib
    importlib.reload(worker_client)

    import urllib.error
    with patch("backend.services.worker_client._urllib_request.urlopen",
               side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(worker_client.WorkerUnavailable):
            worker_client.delegate_sync(str(uuid.uuid4()), ["strava"], full=True)
