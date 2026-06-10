"""Tests for issue #389: Auto-fill linked habits on workout save.

Each test class is anchored to one Acceptance Criterion item (a–g).
Tests (a), (b), (c), (g): unit-test recompute_autofill_for_week directly.
Tests (d), (e), (f): verify workout endpoints trigger recompute correctly.
"""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog, Workout
from backend.services.habit_autofill import recompute_autofill_for_week

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000389")
_WEEK_START = date(2020, 6, 8)  # Monday 2020-06-08


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app), mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_habit_mock(*, auto_fill_source, hid=None):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.auto_fill_source = auto_fill_source
    h.is_archived = False
    return h


def _make_workout_mock(
    *,
    workout_date,
    workout_type="run",
    zone2_minutes=None,
    duration_seconds=None,
    distance_km=None,
    wid=None,
):
    w = MagicMock(spec=Workout)
    w.id = wid or uuid.uuid4()
    w.user_id = _USER_ID
    w.workout_date = workout_date
    w.workout_type = workout_type
    w.zone2_minutes = zone2_minutes
    w.duration_seconds = duration_seconds
    w.distance_km = distance_km
    return w


def _build_autofill_session(habits, workouts, *, delete_count=0, existing_logs=None):
    """Return (ctx, added_list, delete_call_count) for recompute unit tests."""
    existing_logs = existing_logs or []
    added = []
    delete_calls = [0]

    sess = MagicMock()

    habit_q = MagicMock()
    habit_q.filter.return_value = habit_q
    habit_q.all.return_value = habits

    workout_q = MagicMock()
    workout_q.filter.return_value = workout_q
    workout_q.all.return_value = workouts

    log_q = MagicMock()
    log_q.filter.return_value = log_q

    def _delete(synchronize_session=False):
        delete_calls[0] += 1
        return delete_count

    log_q.delete.side_effect = _delete
    log_q.all.return_value = existing_logs

    def _query(model):
        if model is Habit:
            return habit_q
        if model is Workout:
            return workout_q
        return log_q  # HabitLog

    sess.query.side_effect = _query
    sess.add.side_effect = added.append

    ctx = MagicMock()
    ctx.__enter__.return_value = sess
    ctx.__exit__.return_value = False

    return ctx, added, delete_calls


def _make_endpoint_workout_mock(*, workout_date, wid=None):
    """Full MagicMock Workout for endpoint tests (avoids serialization issues)."""
    w = MagicMock(spec=Workout)
    w.id = wid or uuid.uuid4()
    w.user_id = _USER_ID
    w.workout_date = workout_date
    w.name = "Test Workout"
    w.workout_type = "run"
    w.remarks = None
    w.tss = None
    w.tss_source = None
    w.source = None
    w.strava_activity_pk = None
    w.stryd_activity_pk = None
    w.strava_activity_url = None
    w.strava_activity = None
    w.stryd_activity = None
    w.distance_km = None
    w.duration_seconds = None
    w.avg_hr = None
    w.max_hr = None
    w.elevation_m = None
    w.zone2_minutes = None
    w.manual_overrides = None
    ts = MagicMock()
    ts.isoformat.return_value = f"{workout_date}T00:00:00+00:00"
    w.created_at = ts
    return w


# ── AC (a): run workout → run_count habit gets workout_autofill log ────────────

class TestACa_RunWorkoutAddsRunCountLog:
    """AC (a): recompute inserts a workout_autofill HabitLog for a run_count habit."""

    def test_run_workout_creates_autofill_log_value_1(self):
        habit = _make_habit_mock(auto_fill_source="workout.run_count")
        workout = _make_workout_mock(workout_date=date(2020, 6, 10), workout_type="run")

        ctx, added, _ = _build_autofill_session([habit], [workout])

        with patch("backend.services.habit_autofill.Session", return_value=ctx):
            result = recompute_autofill_for_week(_USER_ID, _WEEK_START)

        assert result["habits_recomputed"] == 1
        assert result["logs_created"] == 1
        assert len(added) == 1
        log = added[0]
        assert isinstance(log, HabitLog), "add() should receive a real HabitLog instance"
        assert log.source == "workout_autofill"
        assert float(log.value) == 1.0
        assert log.log_date == date(2020, 6, 10)
        assert log.habit_id == habit.id
        assert log.log_week_start == _WEEK_START


# ── AC (b): zone2_minutes workout → zone2 habit log with correct value ─────────

class TestACb_Zone2MinutesUpdatesLog:
    """AC (b): recompute inserts log with zone2_minutes value."""

    def test_zone2_workout_creates_log_with_correct_value(self):
        habit = _make_habit_mock(auto_fill_source="workout.zone2_minutes")
        workout = _make_workout_mock(workout_date=date(2020, 6, 10), zone2_minutes=45)

        ctx, added, _ = _build_autofill_session([habit], [workout])

        with patch("backend.services.habit_autofill.Session", return_value=ctx):
            result = recompute_autofill_for_week(_USER_ID, _WEEK_START)

        assert result["logs_created"] == 1
        assert len(added) == 1
        log = added[0]
        assert log.source == "workout_autofill"
        assert float(log.value) == 45.0
        assert log.log_date == date(2020, 6, 10)


# ── AC (c): recompute is idempotent ───────────────────────────────────────────

class TestACc_RecomputeIsIdempotent:
    """AC (c): Running recompute twice produces same N logs, not 2N."""

    def test_second_run_deletes_then_recreates_same_logs(self):
        habit = _make_habit_mock(auto_fill_source="workout.run_count")
        workout = _make_workout_mock(workout_date=date(2020, 6, 10), workout_type="run")

        # First run: nothing to delete, creates 1 log
        ctx1, added1, del_calls1 = _build_autofill_session([habit], [workout], delete_count=0)
        with patch("backend.services.habit_autofill.Session", return_value=ctx1):
            r1 = recompute_autofill_for_week(_USER_ID, _WEEK_START)

        # Second run: deletes the 1 log from first run, then recreates 1 log
        ctx2, added2, del_calls2 = _build_autofill_session([habit], [workout], delete_count=1)
        with patch("backend.services.habit_autofill.Session", return_value=ctx2):
            r2 = recompute_autofill_for_week(_USER_ID, _WEEK_START)

        assert r1["logs_created"] == 1
        assert r2["logs_created"] == 1, "Second run must not duplicate: should still be 1 log"
        assert r2["logs_deleted"] == 1, "Second run must delete previous autofill log"
        assert del_calls2[0] >= 1, "delete() must be called before inserting"


# ── AC (d): PATCH workout_date recomputes both old and new weeks ───────────────

class TestACd_WorkoutDateChangeRecomputesBothWeeks:
    """AC (d): PATCH changing workout_date triggers recompute for old and new week."""

    def test_patch_date_change_calls_recompute_for_both_weeks(self):
        client, _ = _make_client()
        wid = uuid.uuid4()

        # Old date: 2020-06-10 (week: 2020-06-08); new date: 2020-06-03 (week: 2020-06-01)
        workout_obj = _make_endpoint_workout_mock(workout_date=date(2020, 6, 10), wid=wid)

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = workout_obj

        ex_q = MagicMock()
        ex_q.filter.return_value = ex_q
        ex_q.order_by.return_value = ex_q
        ex_q.all.return_value = []
        sess.query.return_value = ex_q

        recompute_calls = []

        try:
            with patch("backend.main.Session", return_value=sess):
                with patch(
                    "backend.main._recompute_autofill",
                    side_effect=lambda uid, ws: recompute_calls.append(ws),
                ):
                    res = client.patch(
                        f"/api/workouts/{wid}",
                        json={"workout_date": "2020-06-03"},
                    )
            assert res.status_code == 200, res.text
            assert date(2020, 6, 8) in recompute_calls, "Old week must be recomputed"
            assert date(2020, 6, 1) in recompute_calls, "New week must be recomputed"
        finally:
            _teardown()


# ── AC (e): DELETE workout triggers recompute removing autofill logs ───────────

class TestACe_DeleteWorkoutRemovesAutofillLogs:
    """AC (e): DELETE /api/workouts/{id} triggers recompute for the affected week."""

    def test_delete_triggers_recompute_for_workout_week(self):
        client, _ = _make_client()
        wid = uuid.uuid4()

        workout_obj = MagicMock(spec=Workout)
        workout_obj.id = wid
        workout_obj.user_id = _USER_ID
        workout_obj.workout_date = date(2020, 6, 10)  # week: 2020-06-08

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = workout_obj

        recompute_calls = []

        try:
            with patch("backend.main.Session", return_value=sess):
                with patch(
                    "backend.main._recompute_autofill",
                    side_effect=lambda uid, ws: recompute_calls.append(ws),
                ):
                    res = client.delete(f"/api/workouts/{wid}")
            assert res.status_code == 204, res.text
            assert date(2020, 6, 8) in recompute_calls, "Affected week must be recomputed after delete"
        finally:
            _teardown()


# ── AC (f): recompute failure does not fail workout POST ──────────────────────

class TestACf_RecomputeFailureDoesNotFailWorkoutWrite:
    """AC (f): Recompute exception is caught; POST /api/workouts still returns 201."""

    def test_failing_recompute_does_not_prevent_workout_creation(self):
        client, _ = _make_client()
        wid = uuid.uuid4()

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)

        captured = {}

        def _add(obj):
            if isinstance(obj, Workout):
                captured["w"] = obj
                obj.id = wid

        def _refresh(obj):
            if captured.get("w") is obj:
                ts = MagicMock()
                ts.isoformat.return_value = "2020-06-01T00:00:00+00:00"
                obj.created_at = ts

        sess.add.side_effect = _add
        sess.refresh.side_effect = _refresh

        ex_q = MagicMock()
        ex_q.filter.return_value = ex_q
        ex_q.all.return_value = []
        sess.query.return_value = ex_q

        try:
            with patch("backend.main.Session", return_value=sess):
                with patch(
                    "backend.main._recompute_autofill",
                    side_effect=RuntimeError("simulated DB failure"),
                ):
                    res = client.post(
                        "/api/workouts",
                        json={
                            "name": "Morning Run",
                            "workout_date": "2020-06-01",
                            "workout_type": "run",
                        },
                    )
            assert res.status_code == 201, (
                f"Expected 201 even with failing recompute, got {res.status_code}: {res.text}"
            )
        finally:
            _teardown()


# ── AC (g): zone2_minutes = null → no zone2 autofill log ──────────────────────

class TestACg_NullZone2MinutesNoLog:
    """AC (g): Workout with zone2_minutes=None must not generate a zone2 habit log."""

    def test_null_zone2_minutes_skipped(self):
        habit = _make_habit_mock(auto_fill_source="workout.zone2_minutes")
        workout = _make_workout_mock(workout_date=date(2020, 6, 10), zone2_minutes=None)

        ctx, added, _ = _build_autofill_session([habit], [workout])

        with patch("backend.services.habit_autofill.Session", return_value=ctx):
            result = recompute_autofill_for_week(_USER_ID, _WEEK_START)

        assert result["logs_created"] == 0, "zone2_minutes=None must not create any log"
        assert len(added) == 0, "No HabitLog should be added for null zone2_minutes"
