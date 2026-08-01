"""Tests for issue #384: Add zone2_minutes column to workouts API.

Each test is anchored to one Acceptance Criterion item.
"""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000384")


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    client = TestClient(app)
    return client, mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _minimal_payload(**kwargs):
    base = {
        "name": "Z2 Test 384",
        "workout_date": "2026-06-10",
        "workout_type": "run",
    }
    base.update(kwargs)
    return base


def _make_workout_obj(zone2_minutes=None, wid=None):
    """Mock Workout ORM object with zone2_minutes."""
    w = MagicMock()
    w.id = wid or uuid.uuid4()
    w.user_id = _USER_ID
    w.name = "Z2 Test 384"
    w.workout_date = date(2026, 6, 10)
    w.workout_type = "run"
    w.remarks = None
    w.tss = None
    w.tss_source = None
    w.source = None
    w.strava_activity_pk = None
    w.stryd_activity_pk = None
    w.strava_activity_url = None
    w.strava_activity = None  # relationship — must be None to avoid MagicMock serialization
    w.stryd_activity = None   # relationship — must be None to avoid MagicMock serialization
    w.distance_km = None
    w.duration_seconds = None
    w.avg_hr = None
    w.max_hr = None
    w.elevation_m = None
    w.zone2_minutes = zone2_minutes
    w.manual_overrides = None
    # _workout_dict() (backend/main.py) serializes several fields added by
    # later tickets that this mock predates; an unconfigured MagicMock
    # attribute isn't JSON-serializable, so PATCH's response-building step
    # (not this test's own zone2_minutes assertion) was what actually failed
    # (#1606).
    w.run_subtype = None
    w.tss_method = None
    w.avg_power = None
    w.max_power = None
    w.np = None
    w.avg_cadence_spm = None
    w.avg_stride_m = None
    w.temperature_c = None
    w.humidity_pct = None
    w.flat_equivalent_pace = None
    w.feeling = None
    w.fuelled = None
    w.drills_minutes = None
    created = MagicMock()
    created.isoformat.return_value = "2026-06-10T00:00:00+00:00"
    w.created_at = created
    return w


def _make_session_ctx(workout_obj, exercises=None):
    """Return a mock Session context that surfaces workout_obj on get()."""
    if exercises is None:
        exercises = []
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)
    sess.get.return_value = workout_obj

    query_m = MagicMock()
    query_m.filter.return_value = query_m
    query_m.order_by.return_value = query_m
    query_m.all.return_value = exercises
    query_m.count.return_value = 0
    sess.query.return_value = query_m
    return sess


# ── AC: _workout_dict includes zone2_minutes ──────────────────────────────────

class TestSerializerIncludesZone2Minutes:
    """AC: zone2_minutes appears in all workout serializer outputs."""

    def test_workout_dict_has_zone2_minutes_key(self):
        """_workout_dict includes zone2_minutes key."""
        from backend.main import _workout_dict
        w = _make_workout_obj(zone2_minutes=30)
        result = _workout_dict(w, [])
        assert "zone2_minutes" in result

    def test_workout_dict_zone2_minutes_value(self):
        """_workout_dict returns correct zone2_minutes value."""
        from backend.main import _workout_dict
        w = _make_workout_obj(zone2_minutes=30)
        assert _workout_dict(w, [])["zone2_minutes"] == 30

    def test_workout_dict_zone2_minutes_null(self):
        """_workout_dict returns null when zone2_minutes not set."""
        from backend.main import _workout_dict
        w = _make_workout_obj(zone2_minutes=None)
        assert _workout_dict(w, [])["zone2_minutes"] is None

    def test_workout_list_dict_has_zone2_minutes_key(self):
        """_workout_list_dict includes zone2_minutes key."""
        from backend.main import _workout_list_dict
        w = _make_workout_obj(zone2_minutes=15)
        result = _workout_list_dict(w, 0)
        assert "zone2_minutes" in result

    def test_workout_list_dict_zone2_minutes_value(self):
        """_workout_list_dict returns correct zone2_minutes value."""
        from backend.main import _workout_list_dict
        w = _make_workout_obj(zone2_minutes=15)
        assert _workout_list_dict(w, 0)["zone2_minutes"] == 15

    def test_workout_list_dict_zone2_minutes_null(self):
        """_workout_list_dict returns null when zone2_minutes not set."""
        from backend.main import _workout_list_dict
        w = _make_workout_obj(zone2_minutes=None)
        assert _workout_list_dict(w, 0)["zone2_minutes"] is None


# ── AC: GET /api/workouts/{id} returns zone2_minutes ─────────────────────────

class TestGetWorkoutDetailIncludesZone2Minutes:
    """AC: zone2_minutes present in workout-detail response."""

    def test_get_detail_includes_zone2_minutes_key(self):
        """GET /api/workouts/{id} response includes zone2_minutes key."""
        client, _ = _make_client()
        wid = uuid.uuid4()
        w = _make_workout_obj(zone2_minutes=45, wid=wid)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/workouts/{wid}")
            assert res.status_code == 200
            assert "zone2_minutes" in res.json()
        finally:
            _teardown()

    def test_get_detail_zone2_minutes_value(self):
        """GET /api/workouts/{id} returns correct zone2_minutes value."""
        client, _ = _make_client()
        wid = uuid.uuid4()
        w = _make_workout_obj(zone2_minutes=45, wid=wid)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/workouts/{wid}")
            assert res.status_code == 200
            assert res.json()["zone2_minutes"] == 45
        finally:
            _teardown()

    def test_get_detail_zone2_minutes_null_for_existing_rows(self):
        """Existing workout rows return zone2_minutes: null."""
        client, _ = _make_client()
        wid = uuid.uuid4()
        w = _make_workout_obj(zone2_minutes=None, wid=wid)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.get(f"/api/workouts/{wid}")
            assert res.status_code == 200
            assert res.json()["zone2_minutes"] is None
        finally:
            _teardown()


# ── AC: POST validation 0–600 range ──────────────────────────────────────────

class TestPostZone2MinutesValidation:
    """AC: POST /api/workouts validates zone2_minutes 0-600."""

    def test_post_zone2_minutes_601_returns_422(self):
        """POST with zone2_minutes=601 returns HTTP 422."""
        client, _ = _make_client()
        try:
            res = client.post("/api/workouts", json=_minimal_payload(zone2_minutes=601))
            assert res.status_code == 422
        finally:
            _teardown()

    def test_post_zone2_minutes_negative_returns_422(self):
        """POST with zone2_minutes=-1 returns HTTP 422."""
        client, _ = _make_client()
        try:
            res = client.post("/api/workouts", json=_minimal_payload(zone2_minutes=-1))
            assert res.status_code == 422
        finally:
            _teardown()

    def test_post_zone2_minutes_0_boundary_valid(self):
        """POST with zone2_minutes=0 is valid (lower boundary)."""
        client, _ = _make_client()
        w = _make_workout_obj(zone2_minutes=0)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main.daily_update"):
                res = client.post("/api/workouts", json=_minimal_payload(zone2_minutes=0))
            assert res.status_code == 201
        finally:
            _teardown()

    def test_post_zone2_minutes_600_boundary_valid(self):
        """POST with zone2_minutes=600 is valid (upper boundary)."""
        client, _ = _make_client()
        w = _make_workout_obj(zone2_minutes=600)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main.daily_update"):
                res = client.post("/api/workouts", json=_minimal_payload(zone2_minutes=600))
            assert res.status_code == 201
        finally:
            _teardown()

    def test_post_without_zone2_minutes_omitted_returns_null(self):
        """POST without zone2_minutes field returns zone2_minutes: null."""
        client, _ = _make_client()
        w = _make_workout_obj(zone2_minutes=None)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main.daily_update"):
                res = client.post("/api/workouts", json=_minimal_payload())
            assert res.status_code == 201
            assert res.json()["zone2_minutes"] is None
        finally:
            _teardown()

    def test_post_zone2_minutes_null_explicit_returns_null(self):
        """POST with zone2_minutes=null explicitly returns zone2_minutes: null."""
        client, _ = _make_client()
        w = _make_workout_obj(zone2_minutes=None)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main.daily_update"):
                res = client.post("/api/workouts", json=_minimal_payload(zone2_minutes=None))
            assert res.status_code == 201
            assert res.json()["zone2_minutes"] is None
        finally:
            _teardown()


# ── AC: PATCH validation 0–600 range ─────────────────────────────────────────

class TestPatchZone2MinutesValidation:
    """AC: PATCH /api/workouts/{id} validates zone2_minutes 0-600."""

    def _wid(self):
        return uuid.uuid4()

    def test_patch_zone2_minutes_700_returns_422(self):
        """PATCH with zone2_minutes=700 returns HTTP 422."""
        client, _ = _make_client()
        wid = self._wid()
        w = _make_workout_obj(zone2_minutes=0, wid=wid)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/workouts/{wid}", json={"zone2_minutes": 700})
            assert res.status_code == 422
        finally:
            _teardown()

    def test_patch_zone2_minutes_negative_returns_422(self):
        """PATCH with zone2_minutes=-1 returns HTTP 422."""
        client, _ = _make_client()
        wid = self._wid()
        w = _make_workout_obj(zone2_minutes=0, wid=wid)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess):
                res = client.patch(f"/api/workouts/{wid}", json={"zone2_minutes": -1})
            assert res.status_code == 422
        finally:
            _teardown()

    def test_patch_zone2_minutes_45_returns_200(self):
        """PATCH with zone2_minutes=45 returns 200 with zone2_minutes: 45."""
        client, _ = _make_client()
        wid = self._wid()
        w = _make_workout_obj(zone2_minutes=0, wid=wid)
        sess = _make_session_ctx(w)
        try:
            with patch("backend.main.Session", return_value=sess), \
                 patch("backend.main.daily_update"):
                res = client.patch(f"/api/workouts/{wid}", json={"zone2_minutes": 45})
            assert res.status_code == 200
            assert res.json()["zone2_minutes"] == 45
        finally:
            _teardown()
