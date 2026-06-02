"""Tests for issue #306: background Stryd sync with 409 guard."""
import time
import uuid
from unittest.mock import MagicMock, patch
import urllib.error

import pytest
from fastapi import HTTPException

from backend.services import sync_jobs
import backend.main as main_mod
from backend.models import User
from backend.services.stryd import fetch_stryd_activities


def _make_user(uid=None):
    user = MagicMock(spec=User)
    user.id = uid or uuid.uuid4()
    user.name = "test-user"
    return user


def _clear_registry():
    with sync_jobs._lock:
        sync_jobs._registry.clear()


def _make_mock_session():
    s = MagicMock()
    s.__enter__ = lambda self: self
    s.__exit__ = MagicMock(return_value=False)
    s.execute = MagicMock()
    s.commit = MagicMock()
    return s


# ── fetch_stryd_activities unit tests ─────────────────────────────────────────

def test_fetch_stryd_activities_returns_list_response():
    """API returns a bare list → returned as-is."""
    activities = [{"id": "abc", "timestamp": 1700000000}]
    ctx = MagicMock()
    ctx.__enter__ = lambda s: s
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.read = MagicMock(return_value=b'[{"id": "abc", "timestamp": 1700000000}]')

    with patch("backend.services.stryd.refresh_stryd_session_if_needed", return_value="tok"), \
         patch("backend.services.stryd._urllib_request.urlopen", return_value=ctx):
        result = fetch_stryd_activities("user-1")

    assert result == activities


def test_fetch_stryd_activities_returns_runs_key_response():
    """API returns {runs: [...]} dict → unwraps the 'runs' list."""
    ctx = MagicMock()
    ctx.__enter__ = lambda s: s
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.read = MagicMock(return_value=b'{"runs": [{"id": "xyz"}]}')

    with patch("backend.services.stryd.refresh_stryd_session_if_needed", return_value="tok"), \
         patch("backend.services.stryd._urllib_request.urlopen", return_value=ctx):
        result = fetch_stryd_activities("user-1")

    assert result == [{"id": "xyz"}]


def test_fetch_stryd_activities_401_raises_http_exception():
    """Stryd 401 → HTTPException with status 401."""
    err = urllib.error.HTTPError(url="", code=401, msg="Unauthorized", hdrs={}, fp=None)

    with patch("backend.services.stryd.refresh_stryd_session_if_needed", return_value="tok"), \
         patch("backend.services.stryd._urllib_request.urlopen", side_effect=err):
        with pytest.raises(HTTPException) as exc_info:
            fetch_stryd_activities("user-1")

    assert exc_info.value.status_code == 401
    assert "re-connect" in exc_info.value.detail.lower()


def test_fetch_stryd_activities_502_on_server_error():
    """Stryd 5xx → HTTPException with status 502."""
    err = urllib.error.HTTPError(url="", code=503, msg="Service Unavailable", hdrs={}, fp=None)

    with patch("backend.services.stryd.refresh_stryd_session_if_needed", return_value="tok"), \
         patch("backend.services.stryd._urllib_request.urlopen", side_effect=err):
        with pytest.raises(HTTPException) as exc_info:
            fetch_stryd_activities("user-1")

    assert exc_info.value.status_code == 502


# ── POST /api/stryd/sync unit tests ───────────────────────────────────────────

def test_stryd_sync_returns_202():
    """First POST → HTTP 202 {"started": true} immediately."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    import threading
    barrier = threading.Event()

    def blocking_worker(user_id):
        barrier.wait(timeout=5)

    with patch.object(main_mod, "_stryd_sync_worker", side_effect=blocking_worker):
        resp = main_mod.stryd_sync_start(user=user)

    barrier.set()

    import json
    assert resp.status_code == 202
    assert json.loads(resp.body) == {"started": True}


def test_stryd_sync_409_when_already_running():
    """Second POST while first is running → 409."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    sync_jobs.start(uid, "stryd")

    with pytest.raises(HTTPException) as exc_info:
        main_mod.stryd_sync_start(user=user)

    assert exc_info.value.status_code == 409


def test_stryd_sync_409_when_strava_is_running():
    """POST /api/stryd/sync while a Strava sync is running → 409."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    sync_jobs.start(uid, "strava")

    with pytest.raises(HTTPException) as exc_info:
        main_mod.stryd_sync_start(user=user)

    assert exc_info.value.status_code == 409


def test_stryd_sync_worker_success():
    """Worker fetches activities, upserts, increments counters, marks success."""
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "stryd")

    activities = [
        {
            "id": "run-1",
            "timestamp": 1700000000,
            "name": "Morning Run",
            "distance": 5000,
            "duration": 1800,
            "average_power": 250,
            "average_heart_rate": 155,
            "training_stress_score": 65,
        }
    ]

    mock_session = _make_mock_session()

    with patch("backend.main._fetch_stryd_activities", return_value=activities), \
         patch("backend.main.Session", return_value=mock_session), \
         patch("backend.main._pg_insert") as mock_insert, \
         patch("backend.main._reconcile.reconcile_workouts"):
        mock_insert.return_value.on_conflict_do_update.return_value = MagicMock()
        main_mod._stryd_sync_worker(str(uid))

    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "success"
    assert snap["items_synced"] == 1


def test_stryd_sync_worker_sets_phase_pulling_stryd():
    """Worker sets phase='pulling_stryd' before fetching activities."""
    _clear_registry()
    uid = uuid.uuid4()
    phases_seen = []

    def capturing_fetch(user_id):
        phases_seen.append(sync_jobs.snapshot(uid)["phase"])
        return []

    sync_jobs.start(uid, "stryd")
    mock_session = _make_mock_session()

    with patch("backend.main._fetch_stryd_activities", side_effect=capturing_fetch), \
         patch("backend.main.Session", return_value=mock_session), \
         patch("backend.main._reconcile.reconcile_workouts"):
        main_mod._stryd_sync_worker(str(uid))

    assert phases_seen and phases_seen[0] == "pulling_stryd"


def test_stryd_sync_disconnected_user_job_ends_with_error():
    """No Stryd credentials → 202, but job ends with status='error'."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    from sqlalchemy.orm.exc import NoResultFound

    with patch("backend.main._fetch_stryd_activities", side_effect=NoResultFound()):
        resp = main_mod.stryd_sync_start(user=user)

    assert resp.status_code == 202

    deadline = time.time() + 5
    while time.time() < deadline:
        snap = sync_jobs.snapshot(uid)
        if snap and snap["status"] != "running":
            break
        time.sleep(0.05)

    snap = sync_jobs.snapshot(uid)
    assert snap is not None
    assert snap["status"] == "error"
    assert "not connected" in snap["error"].lower()


def test_stryd_sync_auth_failure_does_not_reconcile():
    """Auth failure → job ends with error; reconcile is NOT called."""
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "stryd")

    auth_error = HTTPException(status_code=401, detail="Stryd session rejected — re-connect your Stryd account.")

    with patch("backend.main._fetch_stryd_activities", side_effect=auth_error), \
         patch("backend.main._reconcile.reconcile_workouts") as mock_reconcile:
        main_mod._stryd_sync_worker(str(uid))

    mock_reconcile.assert_not_called()
    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "error"
    assert "re-connect" in snap["error"].lower()


def test_stryd_sync_worker_empty_activities_still_reconciles():
    """Zero activities fetched → reconcile still runs, job succeeds."""
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "stryd")

    with patch("backend.main._fetch_stryd_activities", return_value=[]), \
         patch("backend.main._reconcile.reconcile_workouts") as mock_reconcile:
        main_mod._stryd_sync_worker(str(uid))

    mock_reconcile.assert_called_once_with(uid, uid)
    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "success"


def test_stryd_sync_worker_skips_activities_without_timestamp():
    """Activities without parseable timestamp are skipped gracefully."""
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "stryd")

    activities = [
        {"id": "bad-1"},                                        # no timestamp
        {"id": "good-1", "timestamp": 1700000000, "name": "X"}, # valid
    ]

    mock_session = _make_mock_session()

    with patch("backend.main._fetch_stryd_activities", return_value=activities), \
         patch("backend.main.Session", return_value=mock_session), \
         patch("backend.main._pg_insert") as mock_insert, \
         patch("backend.main._reconcile.reconcile_workouts"):
        mock_insert.return_value.on_conflict_do_update.return_value = MagicMock()
        main_mod._stryd_sync_worker(str(uid))

    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "success"
    assert snap["items_synced"] == 1  # only the valid activity counted
