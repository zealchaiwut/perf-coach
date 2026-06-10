"""Tests for issue #388: Habit log endpoints and weekly progress computation.

Each test class is anchored to one Acceptance Criterion item (a–g).
Uses FastAPI TestClient with mocked resolve_user and Session.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Habit, HabitLog, Workout

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000388")


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _make_habit(
    *,
    hid=None,
    tracking_type="daily_checkmark",
    weekly_target=None,
    auto_fill_source=None,
):
    h = MagicMock(spec=Habit)
    h.id = hid or uuid.uuid4()
    h.user_id = _USER_ID
    h.name = "Test Habit"
    h.description = None
    h.tracking_type = tracking_type
    h.weekly_target = weekly_target
    h.unit = None
    h.auto_fill_source = auto_fill_source
    h.icon = None
    h.color = None
    h.sort_order = 0
    h.is_archived = False
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-10T00:00:00+00:00"
    h.created_at = ts
    h.updated_at = None
    return h


def _make_habit_log(
    *,
    lid=None,
    habit_id=None,
    log_date=date(2026, 6, 10),  # Wednesday
    log_week_start=date(2026, 6, 8),  # Monday
    value=1.0,
    notes=None,
    source="manual",
):
    log = MagicMock(spec=HabitLog)
    log.id = lid or uuid.uuid4()
    log.habit_id = habit_id or uuid.uuid4()
    log.user_id = _USER_ID
    log.log_date = log_date
    log.log_week_start = log_week_start
    log.value = value
    log.notes = notes
    log.source = source
    ts = MagicMock()
    ts.isoformat.return_value = "2026-06-10T00:00:00+00:00"
    log.created_at = ts
    log.updated_at = None
    return log


def _make_workout(
    *,
    wid=None,
    workout_date=date(2026, 6, 10),
    workout_type="run",
    zone2_minutes=None,
    duration_seconds=None,
    distance_km=None,
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


def _make_post_session(habit, existing_log=None, saved_log=None):
    """Session mock for POST /log endpoint."""
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = habit

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.first.return_value = existing_log

    if saved_log is not None:
        sess.refresh.side_effect = lambda obj: None

    sess.query.return_value = log_q
    return sess


def _make_delete_session(habit, existing_log=None):
    """Session mock for DELETE /log endpoint."""
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = habit

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.first.return_value = existing_log
    sess.query.return_value = log_q
    return sess


def _make_progress_session(habit, logs=None, workouts=None):
    """Session mock for GET /progress endpoint; routes by model class."""
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = habit

    log_q = MagicMock()
    log_q.filter.return_value = log_q
    log_q.all.return_value = logs or []

    workout_q = MagicMock()
    workout_q.filter.return_value = workout_q
    workout_q.filter_by.return_value = workout_q
    workout_q.all.return_value = workouts or []

    def _side(model):
        if model is HabitLog:
            return log_q
        if model is Workout:
            return workout_q
        return log_q

    sess.query.side_effect = _side
    return sess


# ── AC (a): Logging a daily_checkmark increments weekly progress ──────────────

class TestACa_DailyCheckmarkIncrements:
    """AC (a): POST log for daily_checkmark creates entry with value=1."""

    def test_post_log_returns_201(self):
        """POST /api/habits/{id}/log returns 201."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="daily_checkmark")
        new_log = _make_habit_log(habit_id=habit_id, value=1.0)
        sess = _make_post_session(habit, existing_log=None, saved_log=new_log)

        def _refresh(obj):
            obj.id = new_log.id
            obj.habit_id = new_log.habit_id
            obj.user_id = new_log.user_id
            obj.log_date = new_log.log_date
            obj.log_week_start = new_log.log_week_start
            obj.value = new_log.value
            obj.notes = new_log.notes
            obj.source = new_log.source
            obj.created_at = new_log.created_at
            obj.updated_at = new_log.updated_at

        sess.refresh.side_effect = _refresh

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post(
                    f"/api/habits/{habit_id}/log",
                    json={"log_date": "2026-06-10"},
                )
            assert res.status_code == 201, res.text
        finally:
            _teardown()

    def test_post_log_default_value_is_1_for_daily_checkmark(self):
        """daily_checkmark log default value is 1 when not provided."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="daily_checkmark")

        captured = {}

        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit

        log_q = MagicMock()
        log_q.filter.return_value = log_q
        log_q.first.return_value = None
        sess.query.return_value = log_q

        def _add(obj):
            captured["log"] = obj

        sess.add.side_effect = _add

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.habit_id = habit_id
            obj.user_id = _USER_ID
            obj.log_date = date(2026, 6, 10)
            obj.log_week_start = date(2026, 6, 8)
            obj.value = captured["log"].value if "log" in captured else 1.0
            obj.notes = None
            obj.source = "manual"
            obj.created_at = MagicMock()
            obj.created_at.isoformat.return_value = "2026-06-10T00:00:00+00:00"
            obj.updated_at = None

        sess.refresh.side_effect = _refresh

        try:
            with patch("backend.main.Session", return_value=sess):
                client.post(f"/api/habits/{habit_id}/log", json={"log_date": "2026-06-10"})
            assert "log" in captured
            assert float(captured["log"].value) == 1.0
        finally:
            _teardown()

    def test_post_log_upsert_updates_existing(self):
        """Re-logging same date updates existing row, not duplicate."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="daily_checkmark")
        existing = _make_habit_log(habit_id=habit_id, value=1.0, log_date=date(2026, 6, 10))
        sess = _make_post_session(habit, existing_log=existing)

        def _refresh(obj):
            obj.id = existing.id
            obj.habit_id = habit_id
            obj.user_id = _USER_ID
            obj.log_date = date(2026, 6, 10)
            obj.log_week_start = date(2026, 6, 8)
            obj.value = 2.0  # updated value
            obj.notes = None
            obj.source = "manual"
            obj.created_at = existing.created_at
            upd = MagicMock()
            upd.isoformat.return_value = "2026-06-10T01:00:00+00:00"
            obj.updated_at = upd

        sess.refresh.side_effect = _refresh

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post(
                    f"/api/habits/{habit_id}/log",
                    json={"log_date": "2026-06-10", "value": 2.0},
                )
            assert res.status_code == 201
            # Existing row was mutated, not a new add
            sess.add.assert_not_called()
        finally:
            _teardown()

    def test_post_log_progress_increments(self):
        """GET /progress shows current_value = 1 after logging one entry."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="daily_checkmark", weekly_target=5.0)
        log = _make_habit_log(habit_id=habit_id, value=1.0, log_week_start=date(2026, 6, 8))
        sess = _make_progress_session(habit, logs=[log])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            assert res.status_code == 200
            body = res.json()
            assert body["current_value"] == 1.0
        finally:
            _teardown()


# ── AC (b): log_week_start auto-computed correctly in Bangkok TZ ──────────────

class TestACb_LogWeekStartBangkok:
    """AC (b): log_week_start = Monday of log_date in Bangkok TZ."""

    def test_wednesday_log_date_gets_monday_week_start(self):
        """log_date=Wednesday 2026-06-10 → log_week_start=Monday 2026-06-08."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id)

        captured = {}
        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit
        log_q = MagicMock()
        log_q.filter.return_value = log_q
        log_q.first.return_value = None
        sess.query.return_value = log_q

        def _add(obj):
            captured["log"] = obj

        sess.add.side_effect = _add

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.habit_id = habit_id
            obj.user_id = _USER_ID
            obj.log_date = captured["log"].log_date if "log" in captured else date(2026, 6, 10)
            obj.log_week_start = captured["log"].log_week_start if "log" in captured else date(2026, 6, 8)
            obj.value = 1.0
            obj.notes = None
            obj.source = "manual"
            obj.created_at = MagicMock()
            obj.created_at.isoformat.return_value = "2026-06-10T00:00:00+00:00"
            obj.updated_at = None

        sess.refresh.side_effect = _refresh

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.post(
                    f"/api/habits/{habit_id}/log",
                    json={"log_date": "2026-06-10"},  # Wednesday
                )
            assert res.status_code == 201
            assert "log" in captured
            assert captured["log"].log_week_start == date(2026, 6, 8), (
                f"Expected Monday 2026-06-08 got {captured['log'].log_week_start}"
            )
        finally:
            _teardown()

    def test_sunday_log_date_gets_same_week_monday(self):
        """log_date=Sunday 2026-06-14 → log_week_start=Monday 2026-06-08 (same week)."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id)

        captured = {}
        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit
        log_q = MagicMock()
        log_q.filter.return_value = log_q
        log_q.first.return_value = None
        sess.query.return_value = log_q
        sess.add.side_effect = lambda obj: captured.__setitem__("log", obj)

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.habit_id = habit_id
            obj.user_id = _USER_ID
            obj.log_date = captured["log"].log_date if "log" in captured else date(2026, 6, 14)
            obj.log_week_start = captured["log"].log_week_start if "log" in captured else date(2026, 6, 8)
            obj.value = 1.0
            obj.notes = None
            obj.source = "manual"
            obj.created_at = MagicMock()
            obj.created_at.isoformat.return_value = "2026-06-14T00:00:00+00:00"
            obj.updated_at = None

        sess.refresh.side_effect = _refresh

        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main._bangkok_today", return_value=date(2026, 6, 14)):
                res = client.post(
                    f"/api/habits/{habit_id}/log",
                    json={"log_date": "2026-06-14"},  # Sunday — mock today=Sun so date is valid
                )
            assert res.status_code == 201
            assert "log" in captured
            assert captured["log"].log_week_start == date(2026, 6, 8), (
                f"Sunday should map to same-week Monday 2026-06-08, got {captured['log'].log_week_start}"
            )
        finally:
            _teardown()

    def test_monday_log_date_gets_same_day_as_week_start(self):
        """log_date=Monday 2026-06-15 → log_week_start=2026-06-15 (same day)."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id)

        captured = {}
        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = habit
        log_q = MagicMock()
        log_q.filter.return_value = log_q
        log_q.first.return_value = None
        sess.query.return_value = log_q
        sess.add.side_effect = lambda obj: captured.__setitem__("log", obj)

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.habit_id = habit_id
            obj.user_id = _USER_ID
            obj.log_date = captured["log"].log_date if "log" in captured else date(2026, 6, 15)
            obj.log_week_start = captured["log"].log_week_start if "log" in captured else date(2026, 6, 15)
            obj.value = 1.0
            obj.notes = None
            obj.source = "manual"
            obj.created_at = MagicMock()
            obj.created_at.isoformat.return_value = "2026-06-15T00:00:00+00:00"
            obj.updated_at = None

        sess.refresh.side_effect = _refresh

        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main._bangkok_today", return_value=date(2026, 6, 15)):
                res = client.post(
                    f"/api/habits/{habit_id}/log",
                    json={"log_date": "2026-06-15"},  # Monday — mock today=Mon so date is valid
                )
            assert res.status_code == 201
            assert "log" in captured
            assert captured["log"].log_week_start == date(2026, 6, 15), (
                f"Monday should map to itself as week_start, got {captured['log'].log_week_start}"
            )
        finally:
            _teardown()


# ── AC (c): GET /progress for weekly_minutes aggregates values correctly ──────

class TestACc_WeeklyMinutesAggregation:
    """AC (c): /progress for weekly_minutes aggregates value sum."""

    def test_progress_sums_multiple_logs(self):
        """current_value = sum of manual log values."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="weekly_minutes", weekly_target=150.0)
        logs = [
            _make_habit_log(habit_id=habit_id, log_date=date(2026, 6, 8), value=30.0),
            _make_habit_log(habit_id=habit_id, log_date=date(2026, 6, 10), value=45.0),
            _make_habit_log(habit_id=habit_id, log_date=date(2026, 6, 12), value=60.0),
        ]
        sess = _make_progress_session(habit, logs=logs)

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            assert res.status_code == 200
            body = res.json()
            assert body["current_value"] == 135.0
        finally:
            _teardown()

    def test_progress_percentage_computed(self):
        """percentage = (current_value / target) * 100, clamped 0-100."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="weekly_minutes", weekly_target=100.0)
        logs = [
            _make_habit_log(habit_id=habit_id, value=40.0),
            _make_habit_log(habit_id=habit_id, log_date=date(2026, 6, 11), value=25.0),
        ]
        sess = _make_progress_session(habit, logs=logs)

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            assert res.status_code == 200
            body = res.json()
            assert body["percentage"] == 65.0
            assert body["is_complete"] is False
        finally:
            _teardown()

    def test_progress_is_complete_when_target_reached(self):
        """is_complete = True when current_value >= target."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="weekly_minutes", weekly_target=60.0)
        logs = [
            _make_habit_log(habit_id=habit_id, value=60.0),
        ]
        sess = _make_progress_session(habit, logs=logs)

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            assert body["is_complete"] is True
        finally:
            _teardown()

    def test_progress_no_target_returns_null_percentage(self):
        """percentage and target are null when no weekly_target set."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="weekly_minutes", weekly_target=None)
        sess = _make_progress_session(habit, logs=[])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            assert body["target"] is None
            assert body["percentage"] is None
            assert body["is_complete"] is False
        finally:
            _teardown()

    def test_progress_response_shape(self):
        """Response contains all required fields."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="weekly_minutes", weekly_target=100.0)
        sess = _make_progress_session(habit, logs=[])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            assert res.status_code == 200
            body = res.json()
            for field in ("habit", "week_start", "week_end", "target", "current_value",
                          "percentage", "manual_logs", "computed_logs", "is_complete"):
                assert field in body, f"missing field '{field}'"
        finally:
            _teardown()


# ── AC (d): /progress with auto_fill_source pulls from workouts table ─────────

class TestACd_AutoFillFromWorkouts:
    """AC (d): /progress computed_logs populated from workouts when auto_fill_source set."""

    def test_zone2_minutes_source_populates_computed_logs(self):
        """auto_fill_source=workout.zone2_minutes fills computed_logs from workouts."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(
            hid=habit_id,
            tracking_type="weekly_minutes",
            weekly_target=120.0,
            auto_fill_source="workout.zone2_minutes",
        )
        workout = _make_workout(
            workout_date=date(2026, 6, 10),
            workout_type="run",
            zone2_minutes=45,
        )
        sess = _make_progress_session(habit, logs=[], workouts=[workout])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            assert res.status_code == 200
            body = res.json()
            assert len(body["computed_logs"]) == 1
            assert body["computed_logs"][0]["value"] == 45.0
            assert body["computed_logs"][0]["date"] == "2026-06-10"
            assert body["computed_logs"][0]["source"] == "workout.zone2_minutes"
        finally:
            _teardown()

    def test_auto_fill_contributes_to_current_value(self):
        """computed_logs add to current_value (no manual logs)."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(
            hid=habit_id,
            tracking_type="weekly_minutes",
            weekly_target=120.0,
            auto_fill_source="workout.zone2_minutes",
        )
        workout = _make_workout(workout_date=date(2026, 6, 10), zone2_minutes=45)
        sess = _make_progress_session(habit, logs=[], workouts=[workout])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            assert body["current_value"] == 45.0
        finally:
            _teardown()

    def test_no_auto_fill_source_computed_logs_empty(self):
        """computed_logs is empty when auto_fill_source is not set."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, auto_fill_source=None)
        sess = _make_progress_session(habit, logs=[], workouts=[])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            assert body["computed_logs"] == []
        finally:
            _teardown()


# ── AC (e): Manual + computed logs on same date coexist (sum) ─────────────────

class TestACe_ManualPlusComputedSum:
    """AC (e): manual + computed on same date sum unless source == manual_override."""

    def test_same_date_manual_and_computed_are_summed(self):
        """Same date: manual(30) + computed(45) = current_value 75."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(
            hid=habit_id,
            tracking_type="weekly_minutes",
            weekly_target=120.0,
            auto_fill_source="workout.zone2_minutes",
        )
        manual_log = _make_habit_log(
            habit_id=habit_id,
            log_date=date(2026, 6, 10),
            value=30.0,
            source="manual",
        )
        workout = _make_workout(workout_date=date(2026, 6, 10), zone2_minutes=45)
        sess = _make_progress_session(habit, logs=[manual_log], workouts=[workout])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            assert body["current_value"] == 75.0
            assert len(body["manual_logs"]) == 1
            assert len(body["computed_logs"]) == 1
        finally:
            _teardown()

    def test_manual_override_replaces_computed_on_same_date(self):
        """source=manual_override on same date replaces (not adds) computed value."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(
            hid=habit_id,
            tracking_type="weekly_minutes",
            weekly_target=120.0,
            auto_fill_source="workout.zone2_minutes",
        )
        # manual_override: value=20, computed=45 → result should be 20, not 65
        override_log = _make_habit_log(
            habit_id=habit_id,
            log_date=date(2026, 6, 10),
            value=20.0,
            source="manual_override",
        )
        workout = _make_workout(workout_date=date(2026, 6, 10), zone2_minutes=45)
        sess = _make_progress_session(habit, logs=[override_log], workouts=[workout])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            # manual_override replaces computed: 20, not 20+45=65
            assert body["current_value"] == 20.0, (
                "manual_override should replace computed value, not add to it"
            )
        finally:
            _teardown()

    def test_both_lists_always_present_in_response(self):
        """manual_logs and computed_logs always present even if empty."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id)
        sess = _make_progress_session(habit, logs=[], workouts=[])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            assert "manual_logs" in body
            assert "computed_logs" in body
            assert isinstance(body["manual_logs"], list)
            assert isinstance(body["computed_logs"], list)
        finally:
            _teardown()


# ── AC (f): DELETE removes entry; subsequent GET returns 404 ──────────────────

class TestACf_DeleteLog:
    """AC (f): DELETE /api/habits/{id}/log removes entry; then 404 if not found."""

    def test_delete_existing_log_returns_204(self):
        """DELETE existing log entry returns 204."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id)
        existing = _make_habit_log(habit_id=habit_id, log_date=date(2026, 6, 10))
        sess = _make_delete_session(habit, existing_log=existing)

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.delete(f"/api/habits/{habit_id}/log?date=2026-06-10")
            assert res.status_code == 204
            sess.delete.assert_called_once_with(existing)
        finally:
            _teardown()

    def test_delete_nonexistent_log_returns_404(self):
        """DELETE non-existent log returns 404."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id)
        sess = _make_delete_session(habit, existing_log=None)

        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main._bangkok_today", return_value=date(2026, 6, 11)):
                res = client.delete(f"/api/habits/{habit_id}/log?date=2026-06-10")
            assert res.status_code == 404
        finally:
            _teardown()

    def test_delete_missing_date_param_returns_422(self):
        """DELETE without date param returns 422."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        try:
            res = client.delete(f"/api/habits/{habit_id}/log")
            assert res.status_code == 422
        finally:
            _teardown()

    def test_progress_after_delete_excludes_removed_log(self):
        """After delete, /progress no longer includes that date in manual_logs."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id, tracking_type="daily_checkmark", weekly_target=5.0)
        # After delete, logs are empty
        sess = _make_progress_session(habit, logs=[])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            assert body["current_value"] == 0.0
            assert body["manual_logs"] == []
        finally:
            _teardown()


# ── AC (g): Bangkok TZ — workout at 23:00 Sunday Bangkok = current week ───────

class TestACg_BangkokTimezone:
    """AC (g): Workout at 23:00 Sunday Bangkok counts in current week, not next."""

    def test_sunday_workout_in_current_week(self):
        """workout_date=Sunday 2026-06-14 appears in week starting 2026-06-08."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(
            hid=habit_id,
            tracking_type="weekly_minutes",
            weekly_target=120.0,
            auto_fill_source="workout.zone2_minutes",
        )
        # Sunday workout (last day of Mon-Sun week)
        sunday_workout = _make_workout(
            workout_date=date(2026, 6, 14),  # Sunday
            zone2_minutes=30,
        )
        sess = _make_progress_session(habit, logs=[], workouts=[sunday_workout])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            assert len(body["computed_logs"]) == 1, (
                "Sunday workout should be in current week (2026-06-08 to 2026-06-14)"
            )
            assert body["computed_logs"][0]["date"] == "2026-06-14"
            assert body["current_value"] == 30.0
        finally:
            _teardown()

    def test_week_end_is_sunday(self):
        """week_end in response is Sunday (week_start + 6 days)."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id)
        sess = _make_progress_session(habit, logs=[])

        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/habits/{habit_id}/progress?week_start=2026-06-08")
            body = res.json()
            assert body["week_start"] == "2026-06-08"
            assert body["week_end"] == "2026-06-14"  # Sunday
        finally:
            _teardown()

    def test_default_week_start_uses_bangkok_tz(self):
        """When week_start omitted, /progress computes current Monday in Bangkok TZ."""
        client, _ = _make_client()
        habit_id = uuid.uuid4()
        habit = _make_habit(hid=habit_id)
        sess = _make_progress_session(habit, logs=[])

        # 2026-06-10 is Wednesday; Bangkok Monday = 2026-06-08
        fake_now_bkk = datetime(2026, 6, 10, 10, 0, 0)
        from zoneinfo import ZoneInfo
        _BANGKOK = ZoneInfo("Asia/Bangkok")
        fake_now_bkk_aware = fake_now_bkk.replace(tzinfo=_BANGKOK)

        try:
            with patch("backend.main.Session", return_value=sess):
                with patch("backend.main._datetime") as mock_dt:
                    mock_dt.now.return_value = fake_now_bkk_aware
                    mock_dt.fromisoformat = datetime.fromisoformat
                    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                    res = client.get(f"/api/habits/{habit_id}/progress")
            body = res.json()
            assert body["week_start"] == "2026-06-08", (
                f"Expected Monday 2026-06-08, got {body['week_start']}"
            )
        finally:
            _teardown()
