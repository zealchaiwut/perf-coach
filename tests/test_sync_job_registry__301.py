"""Tests for issue #301: thread-safe sync job registry and GET /api/sync/status."""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import sync_jobs
from backend.services.sync_jobs import SyncInProgress
import backend.main as main_mod
from backend.auth import COOKIE_NAME
from backend.models import User


def _make_user(uid=None):
    user = MagicMock(spec=User)
    user.id = uid or uuid.uuid4()
    user.name = "test-user"
    return user


def _clear_registry():
    with sync_jobs._lock:
        sync_jobs._registry.clear()


# ── Registry unit tests ───────────────────────────────────────────────────────

def test_snapshot_fresh_user_returns_none():
    _clear_registry()
    assert sync_jobs.snapshot(uuid.uuid4()) is None


def test_start_returns_running_snapshot():
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")
    snap = sync_jobs.snapshot(uid)
    assert snap is not None
    assert snap["status"] == "running"
    assert snap["provider"] == "strava"
    assert snap["current"] == 0
    assert snap["items_synced"] == 0
    assert snap["cancel_requested"] is False
    assert snap["started_at"] is not None


def test_start_raises_sync_in_progress_for_running_job():
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")
    with pytest.raises(SyncInProgress):
        sync_jobs.start(uid, "strava")
    with sync_jobs._lock:
        assert len([k for k, v in sync_jobs._registry.items() if k == uid]) == 1


def test_start_allows_new_job_after_completion():
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")
    sync_jobs.mark_success(uid)
    sync_jobs.start(uid, "stryd")
    snap = sync_jobs.snapshot(uid)
    assert snap["provider"] == "stryd"
    assert snap["status"] == "running"


def test_mark_success_sets_status_and_finished_at():
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")
    sync_jobs.mark_success(uid)
    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "success"
    assert snap["finished_at"] is not None


def test_mark_error_sets_status_error_and_message():
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "stryd")
    sync_jobs.mark_error(uid, "connection timeout")
    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "error"
    assert snap["error"] == "connection timeout"
    assert snap["finished_at"] is not None


def test_set_phase_updates_phase():
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")
    sync_jobs.set_phase(uid, "pulling_strava")
    assert sync_jobs.snapshot(uid)["phase"] == "pulling_strava"


def test_increment_updates_counters():
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")
    sync_jobs.increment(uid, current=3, items_synced=2)
    snap = sync_jobs.snapshot(uid)
    assert snap["current"] == 3
    assert snap["items_synced"] == 2


def test_snapshot_returns_copy_not_reference():
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")
    snap = sync_jobs.snapshot(uid)
    snap["status"] = "mutated"
    assert sync_jobs.snapshot(uid)["status"] == "running"


# ── Endpoint tests ────────────────────────────────────────────────────────────

def _request_with_cookie(value):
    request = MagicMock()
    request.cookies.get.return_value = value
    return request


def test_get_sync_status_401_for_anonymous():
    from fastapi import HTTPException
    request = _request_with_cookie(None)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(
            main_mod.resolve_user(request, user_id=None)
        )
    assert exc_info.value.status_code == 401


def test_get_sync_status_idle_when_no_job():
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    with patch.object(main_mod, "_sync_jobs", sync_jobs):
        result = asyncio.get_event_loop().run_until_complete(
            main_mod.get_sync_status(user=user)
        )

    assert result.status_code == 200
    import json
    body = json.loads(result.body)
    assert body == {"status": "idle"}


def test_get_sync_status_returns_running_snapshot():
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)
    sync_jobs.start(uid, "strava")

    with patch.object(main_mod, "_sync_jobs", sync_jobs):
        result = asyncio.get_event_loop().run_until_complete(
            main_mod.get_sync_status(user=user)
        )

    import json
    body = json.loads(result.body)
    assert body["status"] == "running"
    assert body["provider"] == "strava"
    assert body["current"] == 0
    assert body["items_synced"] == 0
    assert body["cancel_requested"] is False
    assert body["started_at"] is not None
