"""Tests for issue #381: Strava E2E Smoke Test & Final Integration Polish.

AC (C): GET /api/training-log includes source and is_stryd_synced per workout
AC (D): GET /api/sync/strava/data-quality returns correct shape and counts
"""
import time
import uuid
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import create_session_cookie, COOKIE_NAME
from backend.main import app, resolve_user

_USER_ID = "00000000-0000-0000-0000-000000000381"
_NOW_DATE = date(2025, 6, 10)


def _mock_user(user_id=_USER_ID):
    u = MagicMock()
    u.id = user_id
    return u


def _make_client(user_id=_USER_ID):
    """TestClient with resolve_user overridden to return a mock user."""
    mock_user = _mock_user(user_id)

    async def _fake_resolve_user():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve_user
    token = create_session_cookie(user_id, time.time())
    client = TestClient(app, cookies={COOKIE_NAME: token})
    return client, mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_workout(
    workout_date=_NOW_DATE,
    source="manual",
    stryd_activity_pk=None,
    strava_activity_pk=None,
    **kwargs,
):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.workout_date = workout_date
    w.workout_type = kwargs.get("workout_type", "run")
    w.name = kwargs.get("name", "Morning Run")
    w.distance_km = kwargs.get("distance_km", 10.0)
    w.duration_seconds = kwargs.get("duration_seconds", 3600)
    w.avg_hr = kwargs.get("avg_hr", 145)
    w.elevation_m = kwargs.get("elevation_m", None)
    w.tss = kwargs.get("tss", None)
    w.source = source
    w.tss_source = kwargs.get("tss_source", None)
    w.remarks = kwargs.get("remarks", None)
    w.strava_activity_pk = strava_activity_pk
    w.stryd_activity_pk = stryd_activity_pk
    w.created_at = MagicMock()
    return w


@contextmanager
def _patch_training_log_session(workouts):
    """Patch backend.main.Session for the training-log endpoint."""
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.distinct.return_value = query_mock
    query_mock.all.return_value = workouts
    query_mock.count.return_value = 0  # total_workout_days → skip snapshot query

    mock_session = MagicMock()
    mock_session.query.return_value = query_mock

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False

    with patch("backend.main.Session", return_value=mock_cm):
        yield


# ── AC (C): GET /api/training-log includes is_stryd_synced ───────────────────

class TestTrainingLogSourceFields:
    """AC (C): training-log response includes source and is_stryd_synced per workout."""

    def test_c1_source_field_present(self):
        """AC (C): source field is present in each workout entry."""
        client, _ = _make_client()
        try:
            wo = _make_workout(source="strava")
            with _patch_training_log_session([wo]):
                res = client.get("/api/training-log")
            assert res.status_code == 200
            entries = [e for wk in res.json()["weeks"] for e in wk["entries"] if e.get("type") != "rest"]
            assert len(entries) == 1
            assert "source" in entries[0]
        finally:
            _teardown()

    def test_c2_is_stryd_synced_false_when_no_stryd_pk(self):
        """AC (C): is_stryd_synced=False when stryd_activity_pk is None."""
        client, _ = _make_client()
        try:
            wo = _make_workout(source="strava", stryd_activity_pk=None)
            with _patch_training_log_session([wo]):
                res = client.get("/api/training-log")
            assert res.status_code == 200
            entries = [e for wk in res.json()["weeks"] for e in wk["entries"] if e.get("type") != "rest"]
            assert len(entries) == 1
            assert entries[0]["is_stryd_synced"] is False
        finally:
            _teardown()

    def test_c3_is_stryd_synced_true_when_stryd_pk_present(self):
        """AC (C): is_stryd_synced=True when stryd_activity_pk is set."""
        client, _ = _make_client()
        try:
            wo = _make_workout(source="strava", stryd_activity_pk=uuid.uuid4())
            with _patch_training_log_session([wo]):
                res = client.get("/api/training-log")
            assert res.status_code == 200
            entries = [e for wk in res.json()["weeks"] for e in wk["entries"] if e.get("type") != "rest"]
            assert len(entries) == 1
            assert entries[0]["is_stryd_synced"] is True
        finally:
            _teardown()

    def test_c4_strava_source_field_value(self):
        """AC (C): source field reflects strava for strava-sourced workouts."""
        client, _ = _make_client()
        try:
            wo = _make_workout(source="strava")
            with _patch_training_log_session([wo]):
                res = client.get("/api/training-log")
            assert res.status_code == 200
            entries = [e for wk in res.json()["weeks"] for e in wk["entries"] if e.get("type") != "rest"]
            assert entries[0]["source"] == "strava"
        finally:
            _teardown()

    def test_c5_manual_source_default(self):
        """AC (C): source defaults to manual when workout.source is None."""
        client, _ = _make_client()
        try:
            wo = _make_workout(source=None, tss_source=None)
            with _patch_training_log_session([wo]):
                res = client.get("/api/training-log")
            assert res.status_code == 200
            entries = [e for wk in res.json()["weeks"] for e in wk["entries"] if e.get("type") != "rest"]
            assert entries[0]["source"] == "manual"
        finally:
            _teardown()


# ── AC (D): GET /api/sync/strava/data-quality ─────────────────────────────────

_ANON_CLIENT = TestClient(app)


def _patch_dq_session(counts=(0, 0, 0, 0, 0)):
    """Patch Session for data-quality endpoint; counts = (strava_acts, w_strava, w_no_src, stryd_synced, dupes)."""
    call_state = [0]
    def _execute(stmt, *args, **kwargs):
        i = call_state[0]
        call_state[0] += 1
        r = MagicMock()
        r.scalar.return_value = counts[i] if i < len(counts) else 0
        return r

    mock_session = MagicMock()
    mock_session.execute.side_effect = _execute

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False

    return patch("backend.main.Session", return_value=mock_cm)


class TestStravaDataQuality:
    """AC (D): data-quality endpoint returns correct shape and counts."""

    def test_d1_returns_200_with_expected_shape(self):
        """AC (D): endpoint returns 200 with all 5 required fields."""
        uid = str(uuid.uuid4())
        with _patch_dq_session((3, 2, 1, 1, 0)):
            res = _ANON_CLIENT.get(f"/api/sync/strava/data-quality?user_id={uid}")
        assert res.status_code == 200
        body = res.json()
        assert "strava_activities_count" in body
        assert "workouts_with_strava_source_count" in body
        assert "workouts_without_source_count" in body
        assert "is_stryd_synced_count" in body
        assert "potential_dupes_count" in body

    def test_d2_all_fields_are_non_negative_integers(self):
        """AC (D): all 5 fields are non-negative integers."""
        uid = str(uuid.uuid4())
        with _patch_dq_session((5, 4, 1, 2, 0)):
            res = _ANON_CLIENT.get(f"/api/sync/strava/data-quality?user_id={uid}")
        assert res.status_code == 200
        body = res.json()
        for key in ["strava_activities_count", "workouts_with_strava_source_count",
                    "workouts_without_source_count", "is_stryd_synced_count",
                    "potential_dupes_count"]:
            assert isinstance(body[key], int), f"{key} should be int"
            assert body[key] >= 0, f"{key} should be non-negative"

    def test_d3_missing_user_id_returns_400(self):
        """AC (D): omitting user_id returns 400."""
        res = _ANON_CLIENT.get("/api/sync/strava/data-quality")
        assert res.status_code == 400

    def test_d4_invalid_user_id_returns_4xx(self):
        """AC (D): non-UUID user_id returns 422 (FastAPI type validation)."""
        res = _ANON_CLIENT.get("/api/sync/strava/data-quality?user_id=not-a-uuid")
        assert res.status_code == 422

    def test_d5_correct_counts_returned(self):
        """AC (D): response values match the DB counts (simulated)."""
        uid = str(uuid.uuid4())
        with _patch_dq_session((10, 8, 2, 3, 1)):
            res = _ANON_CLIENT.get(f"/api/sync/strava/data-quality?user_id={uid}")
        assert res.status_code == 200
        body = res.json()
        assert body["strava_activities_count"] == 10
        assert body["workouts_with_strava_source_count"] == 8
        assert body["workouts_without_source_count"] == 2
        assert body["is_stryd_synced_count"] == 3
        assert body["potential_dupes_count"] == 1
