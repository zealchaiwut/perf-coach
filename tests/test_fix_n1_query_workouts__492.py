"""Tests for issue #492: Fix N+1 query in GET /api/workouts endpoint.

AC items:
  (a) exercise_count uses single GROUP BY aggregate — not per-row COUNT.
  (b) _workout_list_dict / compute_best_values does not issue per-row child
      queries — strava/stryd relationships are eager-loaded before serialization.
  (c) Total SQL query count for GET /api/workouts is O(1) with respect to
      workout count (constant regardless of N workouts returned).
  (d) Existing workout list response shape is unchanged.
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import Workout, WorkoutExercise

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000492")


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


async def _fake_resolve():
    return _make_user()


def _make_workout(idx: int, workout_id=None):
    w = MagicMock(spec=Workout)
    w.id = workout_id or uuid.uuid4()
    w.workout_date = date(2026, 1, (idx % 28) + 1)
    w.name = f"Workout {idx}"
    w.workout_type = "Running"
    w.remarks = None
    w.tss = None
    w.tss_source = None
    w.strava_activity_url = None
    w.distance_km = None
    w.duration_seconds = None
    w.avg_hr = None
    w.max_hr = None
    w.elevation_m = None
    w.zone2_minutes = None
    ts = MagicMock()
    ts.isoformat.return_value = "2026-01-01T00:00:00+00:00"
    w.created_at = ts
    w.manual_overrides = {}
    w.strava_activity = None
    w.stryd_activity = None
    w.strava_activity_pk = None
    w.stryd_activity_pk = None
    return w


def _make_agg_row(workout_id, count):
    """Simulate a row returned by GROUP BY aggregate query."""
    row = MagicMock()
    row.workout_id = workout_id
    row.cnt = count
    return row


def _make_session_for_n_workouts(n: int):
    """Build a mock session that returns n workouts and handles aggregate count query."""
    workouts = [_make_workout(i) for i in range(n)]
    workout_ids = [w.id for w in workouts]
    agg_rows = [_make_agg_row(wid, 3) for wid in workout_ids]

    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)

    def _query_side_effect(*args, **kwargs):
        q = MagicMock()
        q.filter.return_value = q
        q.filter_by.return_value = q
        q.order_by.return_value = q
        q.options.return_value = q
        q.group_by.return_value = q
        q.all.return_value = workouts if (len(args) == 1 and args[0] is Workout) else agg_rows
        q.count.return_value = 0
        q.first.return_value = None
        return q

    sess.query.side_effect = _query_side_effect
    return sess, workouts


# ── AC (a): exercise_count must not use per-row COUNT ───────────────────────


def test_ac_a_exercise_count_not_per_row_with_5_workouts():
    """With 5 workouts, session.query must NOT be called 6 times (1 + N).

    Before fix: 1 (workouts) + 5 (per-workout COUNT) = 6 calls.
    After fix:  2 calls (workouts + aggregate).
    """
    n = 5
    mock_sess, _ = _make_session_for_n_workouts(n)

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        with patch("backend.main.Session", return_value=mock_sess):
            res = TestClient(app).get(
                "/api/workouts",
                params={"from": "2026-01-01", "to": "2026-01-31"},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert res.status_code == 200
    call_count = mock_sess.query.call_count
    assert call_count <= 3, (
        f"session.query called {call_count} times for {n} workouts. "
        f"Expected ≤ 3 (O(1)), got N+1 pattern indicating N+1 queries."
    )


def test_ac_a_exercise_count_not_per_row_with_20_workouts():
    """With 20 workouts, session.query must NOT be called 21 times (1 + N).

    This is the key regression test: call count must stay constant.
    """
    n = 20
    mock_sess, _ = _make_session_for_n_workouts(n)

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        with patch("backend.main.Session", return_value=mock_sess):
            res = TestClient(app).get(
                "/api/workouts",
                params={"from": "2026-01-01", "to": "2026-01-31"},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert res.status_code == 200
    call_count = mock_sess.query.call_count
    assert call_count <= 3, (
        f"session.query called {call_count} times for {n} workouts. "
        f"Expected ≤ 3 (O(1)), got N+1 pattern."
    )


# ── AC (c): query count is O(1) — same count for 1 vs 20 workouts ───────────


def test_ac_c_query_count_constant_regardless_of_workout_count():
    """AC3: Query count must be identical for 1 workout vs 20 workouts."""
    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        sess_1, _ = _make_session_for_n_workouts(1)
        sess_20, _ = _make_session_for_n_workouts(20)

        with patch("backend.main.Session", return_value=sess_1):
            TestClient(app).get(
                "/api/workouts",
                params={"from": "2026-01-01", "to": "2026-01-31"},
            )
        count_for_1 = sess_1.query.call_count

        with patch("backend.main.Session", return_value=sess_20):
            TestClient(app).get(
                "/api/workouts",
                params={"from": "2026-01-01", "to": "2026-01-31"},
            )
        count_for_20 = sess_20.query.call_count

    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert count_for_1 == count_for_20, (
        f"Query count for 1 workout ({count_for_1}) differs from "
        f"20 workouts ({count_for_20}). Must be O(1)."
    )


# ── AC (b): strava/stryd loaded before serialization (no lazy per-row) ───────


def test_ac_b_workout_list_dict_uses_preloaded_strava_attributes():
    """_workout_list_dict must read strava_activity as attribute, not trigger
    lazy queries mid-serialization.  We verify by checking the response
    succeeds even when strava_activity is explicitly None on each workout mock.
    """
    n = 3
    mock_sess, workouts = _make_session_for_n_workouts(n)
    for w in workouts:
        w.strava_activity = None
        w.stryd_activity = None

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        with patch("backend.main.Session", return_value=mock_sess):
            res = TestClient(app).get(
                "/api/workouts",
                params={"from": "2026-01-01", "to": "2026-01-31"},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert res.status_code == 200
    data = res.json()
    assert len(data) == n
    for item in data:
        assert item["best_avg_power_w"] is None


# ── AC (d): response shape unchanged ─────────────────────────────────────────


_EXPECTED_FIELDS = {
    "id",
    "workout_date",
    "name",
    "workout_type",
    "remarks",
    "tss",
    "tss_source",
    "strava_activity_url",
    "distance_km",
    "duration_seconds",
    "avg_hr",
    "max_hr",
    "elevation_m",
    "zone2_minutes",
    "exercise_count",
    "created_at",
    "best_distance_km",
    "best_duration_seconds",
    "best_avg_hr",
    "best_avg_power_w",
    "best_tss",
    "best_name",
}


def test_ac_d_response_shape_unchanged():
    """All existing fields must still be present in each workout item."""
    n = 2
    mock_sess, _ = _make_session_for_n_workouts(n)

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        with patch("backend.main.Session", return_value=mock_sess):
            res = TestClient(app).get(
                "/api/workouts",
                params={"from": "2026-01-01", "to": "2026-01-31"},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert res.status_code == 200
    data = res.json()
    assert len(data) == n
    for item in data:
        missing = _EXPECTED_FIELDS - set(item.keys())
        assert not missing, f"Response missing fields: {missing}"


def test_ac_d_exercise_count_value_matches_aggregate():
    """exercise_count in response must reflect the aggregate value, not 0."""
    wid = uuid.uuid4()
    workouts = [_make_workout(0, workout_id=wid)]
    agg_rows = [_make_agg_row(wid, 7)]

    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)

    def _query_side_effect(*args, **kwargs):
        q = MagicMock()
        q.filter.return_value = q
        q.filter_by.return_value = q
        q.order_by.return_value = q
        q.options.return_value = q
        q.group_by.return_value = q
        q.all.return_value = workouts if (len(args) == 1 and args[0] is Workout) else agg_rows
        q.count.return_value = 0
        q.first.return_value = None
        return q

    sess.query.side_effect = _query_side_effect

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        with patch("backend.main.Session", return_value=sess):
            res = TestClient(app).get(
                "/api/workouts",
                params={"from": "2026-01-01", "to": "2026-01-31"},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["exercise_count"] == 7, (
        f"exercise_count should be 7 from aggregate, got {data[0]['exercise_count']}"
    )


def test_ac_d_exercise_count_zero_for_workout_with_no_exercises():
    """A workout with no exercises must have exercise_count=0, not KeyError."""
    wid = uuid.uuid4()
    workouts = [_make_workout(0, workout_id=wid)]
    agg_rows = []  # no rows → workout has 0 exercises

    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)

    def _query_side_effect(*args, **kwargs):
        q = MagicMock()
        q.filter.return_value = q
        q.filter_by.return_value = q
        q.order_by.return_value = q
        q.options.return_value = q
        q.group_by.return_value = q
        q.all.return_value = workouts if (len(args) == 1 and args[0] is Workout) else agg_rows
        q.count.return_value = 0
        q.first.return_value = None
        return q

    sess.query.side_effect = _query_side_effect

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        with patch("backend.main.Session", return_value=sess):
            res = TestClient(app).get(
                "/api/workouts",
                params={"from": "2026-01-01", "to": "2026-01-31"},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert res.status_code == 200
    data = res.json()
    assert data[0]["exercise_count"] == 0


def test_empty_date_range_returns_empty_list():
    """GET /api/workouts with no workouts in range returns []."""
    sess = MagicMock()
    sess.__enter__ = MagicMock(return_value=sess)
    sess.__exit__ = MagicMock(return_value=False)

    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.options.return_value = q
    q.group_by.return_value = q
    q.all.return_value = []
    q.count.return_value = 0
    sess.query.return_value = q

    app.dependency_overrides[resolve_user] = _fake_resolve
    try:
        with patch("backend.main.Session", return_value=sess):
            res = TestClient(app).get(
                "/api/workouts",
                params={"from": "2026-01-01", "to": "2026-01-31"},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert res.status_code == 200
    assert res.json() == []
