"""Phase 2 — worker-driven precompute of the training-load snapshot.

Unit/mocked (no DB): the DB-level correctness of daily_update / current_load is
already covered by test_training_load.py. Here we verify the Phase 2 wiring:
- precompute_user warms today + yesterday + any extra dates,
- worker_client.delegate_precompute enqueues in queue mode / no-ops in http mode
  and never raises,
- current_load honours LOAD_READ_FROM_SNAPSHOT=0 (force inline recompute),
- the worker dispatches `precompute` and enqueues a precompute after a sync.
"""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from backend.services import precompute
from backend.services import worker_client
from backend.services import training_load


def _stub_du(*_a, **_k):
    return {"date": date.today(), "tss": 0, "ctl": 1.0, "atl": 2.0, "tsb": -1.0, "acwr": None}


# ── precompute_user orchestration ────────────────────────────────────────────

def test_precompute_user_warms_today_yesterday_and_extra_dates():
    today = date.today()
    with patch.object(training_load, "daily_update", side_effect=_stub_du) as mock_du:
        out = precompute.precompute_user("u1", dates=["2026-01-01", None, "bad-date"])

    warmed_dates = {c.kwargs.get("target_date") or c.args[1] for c in mock_du.call_args_list}
    assert today in warmed_dates
    assert today - timedelta(days=1) in warmed_dates
    assert date(2026, 1, 1) in warmed_dates  # extra date coerced from ISO string
    # "bad-date" and None are dropped, not warmed
    assert all(isinstance(d, date) for d in warmed_dates)
    assert out["user_id"] == "u1"
    assert today.isoformat() in out["warmed"]


def test_precompute_user_dedupes_extra_date_equal_to_today():
    today = date.today()
    with patch.object(training_load, "daily_update", side_effect=_stub_du) as mock_du:
        precompute.precompute_user("u1", dates=[today.isoformat()])
    # today passed as an "extra" collapses into the today target (a set) — 2 calls
    assert mock_du.call_count == 2  # today + yesterday, no duplicate


# ── delegate_precompute (web → queue) ────────────────────────────────────────

def test_delegate_precompute_enqueues_in_queue_mode(monkeypatch):
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "queue")
    with patch("backend.services.job_queue.enqueue", return_value="jid") as mock_enq:
        out = worker_client.delegate_precompute("u1", dates=[date(2026, 1, 1)])
    assert out == {"queued": True, "job_ids": ["jid"]}
    args, kwargs = mock_enq.call_args
    assert args[0] == "precompute"
    assert args[1]["user_id"] == "u1"
    assert args[1]["dates"] == ["2026-01-01"]
    assert kwargs["dedupe_key"] == "precompute:u1"


def test_delegate_precompute_noop_in_http_mode(monkeypatch):
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "http")
    with patch("backend.services.job_queue.enqueue") as mock_enq:
        out = worker_client.delegate_precompute("u1")
    assert out == {"queued": False}
    mock_enq.assert_not_called()


def test_delegate_precompute_never_raises(monkeypatch):
    monkeypatch.setenv("WORKER_TRIGGER_MODE", "queue")
    with patch("backend.services.job_queue.enqueue", side_effect=RuntimeError("db down")):
        out = worker_client.delegate_precompute("u1")
    assert out == {"queued": False}  # swallowed — never fails the workout write


def test_precompute_flags_default_on(monkeypatch):
    monkeypatch.delenv("PRECOMPUTE_ON_WRITE_ENABLED", raising=False)
    monkeypatch.delenv("PRECOMPUTE_AFTER_SYNC_ENABLED", raising=False)
    assert worker_client.precompute_on_write_enabled() is True
    assert worker_client.precompute_after_sync_enabled() is True
    monkeypatch.setenv("PRECOMPUTE_ON_WRITE_ENABLED", "0")
    assert worker_client.precompute_on_write_enabled() is False


# ── current_load read flag ───────────────────────────────────────────────────

def test_current_load_flag_off_forces_inline_recompute(monkeypatch):
    """LOAD_READ_FROM_SNAPSHOT=0 must skip the snapshot read and recompute inline
    (via daily_update) even when a fresh snapshot exists."""
    monkeypatch.setenv("LOAD_READ_FROM_SNAPSHOT", "0")
    with (
        patch.object(training_load, "resolve_user_ewma_days", return_value=(42, 7)),
        patch.object(training_load, "daily_update", side_effect=_stub_du) as mock_du,
        # If the snapshot path were taken it would open a Session; make that blow up
        # so the test fails loudly if the flag is ignored.
        patch.object(training_load, "Session", side_effect=AssertionError("snapshot read not skipped")),
    ):
        out = training_load.current_load("u1")
    mock_du.assert_called_once()
    assert out["ctl"] == 1.0 and out["tsb"] == -1.0


def test_current_load_flag_on_reads_snapshot(monkeypatch):
    """Default (flag on): a present snapshot is returned without a recompute."""
    monkeypatch.setenv("LOAD_READ_FROM_SNAPSHOT", "1")
    uid = "08af003e-bf5f-4e96-b90f-711af7485fb6"
    today = date.today()
    snap = MagicMock(
        snapshot_date=today, ctl=10.0, atl=5.0, tsb=5.0, acwr=1.2,
        formula_version=training_load._FORMULA_VERSION,
        ctl_days=None, atl_days=None,
    )
    sess = MagicMock()
    sess.__enter__ = lambda s: sess
    sess.__exit__ = MagicMock(return_value=False)
    sess.query.return_value.filter.return_value.first.return_value = snap
    with (
        patch.object(training_load, "resolve_user_ewma_days", return_value=(42, 7)),
        patch.object(training_load, "Session", return_value=sess),
        patch.object(training_load, "daily_update", side_effect=AssertionError("should not recompute")) as mock_du,
    ):
        out = training_load.current_load(uid, as_of=today)
    assert out["ctl"] == 10.0
    mock_du.assert_not_called()


# ── worker dispatch + post-sync enqueue ──────────────────────────────────────

def test_worker_dispatch_has_precompute_handler():
    import backend.worker_app as w
    assert "precompute" in w._DISPATCH


def test_h_precompute_calls_precompute_user():
    import backend.worker_app as w
    with patch.object(precompute, "precompute_user") as mock_pc:
        w._h_precompute({"user_id": "u1", "dates": ["2026-01-01"]})
    mock_pc.assert_called_once_with("u1", dates=["2026-01-01"])


def test_enqueue_precompute_after_sync_enqueues_for_user(monkeypatch):
    import backend.worker_app as w
    monkeypatch.setattr(worker_client, "precompute_after_sync_enabled", lambda: True)
    with patch("backend.services.job_queue.enqueue", return_value="jid") as mock_enq:
        w._enqueue_precompute_after_sync("u1")
    args, kwargs = mock_enq.call_args
    assert args[0] == "precompute"
    assert kwargs["dedupe_key"] == "precompute:u1"
    assert kwargs["enqueued_by"] == "worker"


def test_enqueue_precompute_after_sync_skips_none_user_and_when_disabled(monkeypatch):
    import backend.worker_app as w
    with patch("backend.services.job_queue.enqueue") as mock_enq:
        monkeypatch.setattr(worker_client, "precompute_after_sync_enabled", lambda: True)
        w._enqueue_precompute_after_sync(None)  # batch job, no concrete user
        monkeypatch.setattr(worker_client, "precompute_after_sync_enabled", lambda: False)
        w._enqueue_precompute_after_sync("u1")  # flag off
    mock_enq.assert_not_called()
