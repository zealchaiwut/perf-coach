"""Tests for issue #302: background Strava sync with 409 guard."""
import time
import uuid
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from backend.services import sync_jobs
import backend.main as main_mod
from backend.models import User


def _make_user(uid=None):
    user = MagicMock(spec=User)
    user.id = uid or uuid.uuid4()
    user.name = "test-user"
    return user


def _clear_registry():
    with sync_jobs._lock:
        sync_jobs._registry.clear()


# ── POST /api/strava/sync unit tests ─────────────────────────────────────────

def test_strava_sync_returns_202():
    """First POST → HTTP 202 {"started": true} immediately."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    # Block the worker so it stays in running state during assertion
    import threading
    barrier = threading.Event()

    def blocking_worker(user_id):
        barrier.wait(timeout=5)

    with patch.object(main_mod, "_strava_sync_worker", side_effect=blocking_worker):
        resp = main_mod.strava_sync(user=user)

    barrier.set()  # unblock

    import json
    assert resp.status_code == 202
    assert json.loads(resp.body) == {"started": True}


def test_strava_sync_worker_success():
    """Worker pulls activities, upserts, increments counters, marks success."""
    _clear_registry()
    uid = uuid.uuid4()
    sync_jobs.start(uid, "strava")

    page_counter = {"n": 0}

    def counting_urlopen(req):
        page_counter["n"] += 1
        ctx = MagicMock()
        ctx.__enter__ = lambda s: s
        ctx.__exit__ = MagicMock(return_value=False)
        if page_counter["n"] == 1:
            ctx.read = MagicMock(return_value=b'[{"id":111,"start_date":"2023-01-01T08:00:00Z","type":"Run","name":"Morning Run","distance":5000,"moving_time":1500,"average_heartrate":null,"max_heartrate":null,"total_elevation_gain":null,"average_watts":null,"max_watts":null,"device_name":null,"external_id":null}]')
        else:
            ctx.read = MagicMock(return_value=b'[]')
        return ctx

    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.execute = MagicMock()
    mock_session.commit = MagicMock()

    with patch("backend.main.refresh_token_if_needed", return_value="fake-token"), \
         patch("backend.main._urllib_request.urlopen", side_effect=counting_urlopen), \
         patch("backend.main.Session", return_value=mock_session), \
         patch("backend.main._pg_insert") as mock_insert:
        mock_insert.return_value.on_conflict_do_update.return_value = MagicMock()
        main_mod._strava_sync_worker(str(uid))

    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "success"
    assert snap["items_synced"] == 1


def test_strava_sync_409_when_already_running():
    """Second POST while first is running → 409."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    sync_jobs.start(uid, "strava")  # simulate in-progress job

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        main_mod.strava_sync(user=user)

    assert exc_info.value.status_code == 409


def test_strava_sync_disconnected_user_job_ends_with_error():
    """Disconnected user → 202, but job ends with status='error'."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    with patch("backend.main.refresh_token_if_needed", return_value=None):
        resp = main_mod.strava_sync(user=user)

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


def test_strava_sync_http_error_marks_job_error():
    """Strava HTTP error mid-pull → job transitions to error."""
    _clear_registry()
    uid = uuid.uuid4()
    user = _make_user(uid)

    http_err = urllib.error.HTTPError(
        url="https://www.strava.com/api/v3/athlete/activities",
        code=429,
        msg="Too Many Requests",
        hdrs={},
        fp=None,
    )

    with patch("backend.main.refresh_token_if_needed", return_value="fake-token"), \
         patch("backend.main._urllib_request.urlopen", side_effect=http_err):
        resp = main_mod.strava_sync(user=user)

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
    assert "429" in snap["error"]


def test_strava_sync_worker_sets_phase_pulling_strava():
    """Worker sets phase='pulling_strava' before any Strava call."""
    _clear_registry()
    uid = uuid.uuid4()
    phases_seen = []

    original_urlopen = __builtins__  # unused; just capturing phase

    def capturing_urlopen(req):
        phases_seen.append(sync_jobs.snapshot(uid)["phase"])
        ctx = MagicMock()
        ctx.__enter__ = lambda s: s
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.read = MagicMock(return_value=b'[]')
        return ctx

    sync_jobs.start(uid, "strava")

    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("backend.main.refresh_token_if_needed", return_value="fake-token"), \
         patch("backend.main._urllib_request.urlopen", side_effect=capturing_urlopen), \
         patch("backend.main.Session", return_value=mock_session):
        main_mod._strava_sync_worker(str(uid))

    assert phases_seen and phases_seen[0] == "pulling_strava"
