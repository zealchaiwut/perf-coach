"""Tests for issue #303: reconcile_workouts merges source activities into workouts."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

from backend.services import sync_jobs
from backend.services.reconcile import reconcile_workouts, _find_in_memory, _TOLERANCE


def _clear_registry():
    with sync_jobs._lock:
        sync_jobs._registry.clear()


def _make_uid():
    return uuid.uuid4()


def _strava_act(uid, start_time, name="Morning Run", activity_type="Run", distance_km=10.0, duration_seconds=3600, avg_hr=145):
    act = MagicMock()
    act.id = uuid.uuid4()
    act.user_id = uid
    act.start_time = start_time
    act.name = name
    act.activity_type = activity_type
    act.distance_km = distance_km
    act.duration_seconds = duration_seconds
    act.avg_hr = avg_hr
    act.avg_power_w = None
    act.tss = None
    return act


def _stryd_act(uid, start_time, name="Stryd Run", distance_km=10.8, duration_seconds=3600, avg_hr=145):
    act = MagicMock()
    act.id = uuid.uuid4()
    act.user_id = uid
    act.start_time = start_time
    act.name = name
    act.activity_type = "Run"
    act.distance_km = distance_km
    act.duration_seconds = duration_seconds
    act.avg_hr = avg_hr
    act.avg_power_w = None
    act.tss = None
    act.splits = None
    act.form_metrics = None
    return act


def _workout(uid, start_time, name="Existing Workout"):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.user_id = uid
    w.start_time = start_time
    w.name = name
    w.manual_overrides = None
    w.distance_km = None
    w.duration_seconds = None
    w.avg_hr = None
    w.tss = None
    w.source = None
    w.strava_activity_pk = None
    w.stryd_activity_pk = None
    return w


def _make_session(strava_acts, stryd_acts, existing_workouts):
    """Build a mock session that returns pre-defined data."""
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)

    def query_side_effect(model):
        from backend.models import StravaActivity, StrydActivity, Workout
        q = MagicMock()
        q.filter.return_value = q
        if model is StravaActivity:
            q.all.return_value = strava_acts
        elif model is StrydActivity:
            q.all.return_value = stryd_acts
        elif model is Workout:
            q.all.return_value = list(existing_workouts)
        else:
            q.all.return_value = []
        return q

    session.query.side_effect = query_side_effect
    session.add = MagicMock()
    session.commit = MagicMock()
    return session


# ── _find_in_memory ───────────────────────────────────────────────────────────

def test_find_in_memory_match_within_tolerance():
    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    w = _workout(uuid.uuid4(), datetime(2026, 6, 1, 9, 3, 0, tzinfo=timezone.utc))
    assert _find_in_memory(t, [w], _TOLERANCE) is w


def test_find_in_memory_no_match_outside_tolerance():
    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    w = _workout(uuid.uuid4(), datetime(2026, 6, 1, 9, 10, 0, tzinfo=timezone.utc))
    assert _find_in_memory(t, [w], _TOLERANCE) is None


def test_find_in_memory_picks_closest():
    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    w1 = _workout(uuid.uuid4(), datetime(2026, 6, 1, 9, 4, 0, tzinfo=timezone.utc))
    w2 = _workout(uuid.uuid4(), datetime(2026, 6, 1, 8, 58, 0, tzinfo=timezone.utc))
    assert _find_in_memory(t, [w1, w2], _TOLERANCE) is w2


def test_find_in_memory_none_start_time_returns_none():
    assert _find_in_memory(None, [], _TOLERANCE) is None


# ── reconcile_workouts: happy path ────────────────────────────────────────────

def test_reconcile_creates_workout_for_unmatched_strava_activity():
    """Strava activity with no matching workout → new Workout row added."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    act = _strava_act(uid, t)
    session = _make_session([act], [], [])

    with patch("backend.services.reconcile._Session", return_value=session):
        reconcile_workouts(uid, uid)

    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_reconcile_updates_existing_matched_workout():
    """Strava activity matching an existing workout → no new row, existing updated."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    act = _strava_act(uid, t, name="Strava Run", distance_km=11.0)
    w = _workout(uid, datetime(2026, 6, 1, 9, 2, 0, tzinfo=timezone.utc))
    session = _make_session([act], [], [w])

    with patch("backend.services.reconcile._Session", return_value=session):
        reconcile_workouts(uid, uid)

    session.add.assert_not_called()
    assert w.strava_activity_pk == act.id
    session.commit.assert_called_once()


def test_reconcile_merged_run_keeps_strava_distance_when_both_sources():
    """When Strava and Stryd match the same workout, Strava distance wins."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    strava = _strava_act(uid, t, distance_km=11.0)
    stryd = _stryd_act(uid, t, distance_km=10.8)
    session = _make_session([strava], [stryd], [])

    with patch("backend.services.reconcile._Session", return_value=session), \
         patch("backend.services.reconcile.compute_run_metrics"), \
         patch("backend.services.reconcile._update_duration_curves"):
        reconcile_workouts(uid, uid)

    created = session.add.call_args[0][0]
    assert float(created.distance_km) == 11.0
    assert created.source == "strava,stryd"


def test_reconcile_idempotent_second_run_no_duplicates():
    """Second reconcile on same data: matched workout found again, no new add."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    t = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    act = _strava_act(uid, t)

    # First run: no existing workout
    session1 = _make_session([act], [], [])
    with patch("backend.services.reconcile._Session", return_value=session1):
        reconcile_workouts(uid, uid)

    # Verify a workout was added
    assert session1.add.call_count == 1
    created_workout = session1.add.call_args[0][0]
    created_workout.start_time = t  # set start_time so second run can match it

    # Second run: the created workout is now "existing"
    _clear_registry()
    sync_jobs.start(uid, "strava")
    session2 = _make_session([act], [], [created_workout])
    with patch("backend.services.reconcile._Session", return_value=session2):
        reconcile_workouts(uid, uid)

    # No new workout created
    session2.add.assert_not_called()


# ── reconcile_workouts: progress counters ─────────────────────────────────────

def test_reconcile_sets_phase_reconciling():
    """reconcile_workouts sets phase='reconciling' at start."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    session = _make_session([], [], [])
    with patch("backend.services.reconcile._Session", return_value=session):
        reconcile_workouts(uid, uid)

    snap = sync_jobs.snapshot(uid)
    assert snap["phase"] == "reconciling"


def test_reconcile_increments_current_per_activity():
    """current counter increments once per source activity processed."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    t1 = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    acts = [_strava_act(uid, t1), _strava_act(uid, t2)]
    session = _make_session(acts, [], [])

    with patch("backend.services.reconcile._Session", return_value=session):
        reconcile_workouts(uid, uid)

    snap = sync_jobs.snapshot(uid)
    assert snap["current"] == 2
    assert snap["total"] == 2


def test_reconcile_sets_total_from_activity_count():
    """total is set to the number of source activities before processing starts."""
    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    acts = [_strava_act(uid, datetime(2026, 6, 1, i, 0, 0, tzinfo=timezone.utc)) for i in range(5)]
    session = _make_session(acts, [], [])

    with patch("backend.services.reconcile._Session", return_value=session):
        reconcile_workouts(uid, uid)

    snap = sync_jobs.snapshot(uid)
    assert snap["total"] == 5


# ── reconcile_workouts + strava_sync worker ───────────────────────────────────

def test_strava_sync_worker_phases_pulling_then_reconciling_then_success():
    """Full worker: phase goes pulling_strava → reconciling, job ends success."""
    import backend.main as main_mod

    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    def fake_urlopen(req):
        ctx = MagicMock()
        ctx.__enter__ = lambda s: s
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.read = MagicMock(return_value=b'[]')
        return ctx

    mock_db_session = MagicMock()
    mock_db_session.__enter__ = lambda s: s
    mock_db_session.__exit__ = MagicMock(return_value=False)
    mock_db_session.execute = MagicMock()
    mock_db_session.commit = MagicMock()

    reconcile_session = _make_session([], [], [])

    with patch("backend.main.refresh_token_if_needed", return_value="fake-token"), \
         patch("backend.main._urllib_request.urlopen", side_effect=fake_urlopen), \
         patch("backend.main.Session", return_value=mock_db_session), \
         patch("backend.services.reconcile._Session", return_value=reconcile_session):
        main_mod._strava_sync_worker(str(uid))

    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "success"
    assert snap["phase"] == "reconciling"


def test_strava_sync_worker_reconcile_error_marks_job_error():
    """If reconcile raises, worker marks job error."""
    import backend.main as main_mod

    _clear_registry()
    uid = _make_uid()
    sync_jobs.start(uid, "strava")

    def fake_urlopen(req):
        ctx = MagicMock()
        ctx.__enter__ = lambda s: s
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.read = MagicMock(return_value=b'[]')
        return ctx

    mock_db_session = MagicMock()
    mock_db_session.__enter__ = lambda s: s
    mock_db_session.__exit__ = MagicMock(return_value=False)
    mock_db_session.execute = MagicMock()
    mock_db_session.commit = MagicMock()

    with patch("backend.main.refresh_token_if_needed", return_value="fake-token"), \
         patch("backend.main._urllib_request.urlopen", side_effect=fake_urlopen), \
         patch("backend.main.Session", return_value=mock_db_session), \
         patch("backend.main._reconcile.reconcile_workouts", side_effect=RuntimeError("db gone")):
        main_mod._strava_sync_worker(str(uid))

    snap = sync_jobs.snapshot(uid)
    assert snap["status"] == "error"
    assert "db gone" in snap["error"]
