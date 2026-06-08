"""Tests for issue #348: GET /api/home/recent-workouts endpoint.

Acceptance Criteria:
(a) Returns expected response shape: {workouts: [...], count: int, has_more: bool}
(b) limit=11 returns 422
(c) relative_date correct for today, yesterday, 3 days ago
(d) Sort order is most-recent-first
(e) Empty result returns {workouts: [], count: 0, has_more: false}
(f) has_more accurate when total exceeds limit
"""
import datetime
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

TODAY = datetime.date.today()
_UID = str(uuid.uuid4())


def _make_workout(workout_date=None, **kwargs):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.workout_date = workout_date or TODAY
    w.workout_type = kwargs.get("workout_type", "Run")
    w.name = kwargs.get("name", "Morning Run")
    w.distance_km = kwargs.get("distance_km", None)
    w.duration_seconds = kwargs.get("duration_seconds", None)
    w.avg_hr = kwargs.get("avg_hr", None)
    w.tss = kwargs.get("tss", None)
    w.source = kwargs.get("source", None)
    w.stryd_activity_pk = kwargs.get("stryd_activity_pk", None)
    w.created_at = datetime.datetime.now(datetime.timezone.utc)
    return w


def _patch_session(workouts, user=None):
    """Patch backend.main.Session to return mock user + workouts."""
    mock_user = user or MagicMock()
    mock_user.id = uuid.UUID(_UID)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_user

    workout_query = MagicMock()
    workout_query.filter.return_value = workout_query
    workout_query.order_by.return_value = workout_query
    workout_query.limit.return_value = workout_query
    workout_query.all.return_value = workouts
    mock_session.query.return_value = workout_query

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False

    return patch("backend.main.Session", return_value=mock_cm)


# ── AC (a): response shape ────────────────────────────────────────────────────

def test_response_shape():
    w = _make_workout(distance_km=5.0, duration_seconds=1800, avg_hr=145, tss=50.0, source="strava")
    with _patch_session([w]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.status_code == 200
    body = res.json()
    assert "workouts" in body
    assert "count" in body
    assert "has_more" in body
    assert body["count"] == 1
    assert body["has_more"] is False
    wo = body["workouts"][0]
    assert "id" in wo
    assert "workout_date" in wo
    assert "workout_type" in wo
    assert "name" in wo
    assert "relative_date" in wo
    assert "is_stryd_synced" in wo
    # Nullable fields present when non-null
    assert wo["distance_km"] == 5.0
    assert wo["duration_seconds"] == 1800
    assert wo["avg_hr"] == 145
    assert wo["tss"] == 50.0
    assert wo["source"] == "strava"


def test_null_fields_omitted():
    w = _make_workout()
    with _patch_session([w]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.status_code == 200
    wo = res.json()["workouts"][0]
    assert "distance_km" not in wo
    assert "duration_seconds" not in wo
    assert "avg_hr" not in wo
    assert "tss" not in wo
    assert "source" not in wo


def test_is_stryd_synced_false_when_no_stryd_pk():
    w = _make_workout(stryd_activity_pk=None)
    with _patch_session([w]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.json()["workouts"][0]["is_stryd_synced"] is False


def test_is_stryd_synced_true_when_stryd_pk_set():
    w = _make_workout(stryd_activity_pk=uuid.uuid4())
    with _patch_session([w]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.json()["workouts"][0]["is_stryd_synced"] is True


# ── AC (b): limit=11 returns 422 ─────────────────────────────────────────────

def test_limit_11_returns_422():
    res = client.get(f"/api/home/recent-workouts?user_id={_UID}&limit=11")
    assert res.status_code == 422


def test_limit_10_accepted():
    with _patch_session([]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}&limit=10")
    assert res.status_code == 200


def test_missing_user_id_returns_422():
    res = client.get("/api/home/recent-workouts")
    assert res.status_code == 422


# ── AC (c): relative_date computation ────────────────────────────────────────

def test_relative_date_today():
    w = _make_workout(workout_date=TODAY)
    with _patch_session([w]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.json()["workouts"][0]["relative_date"] == "Today"


def test_relative_date_yesterday():
    yesterday = TODAY - datetime.timedelta(days=1)
    w = _make_workout(workout_date=yesterday)
    with _patch_session([w]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.json()["workouts"][0]["relative_date"] == "Yesterday"


def test_relative_date_3_days_ago():
    three_ago = TODAY - datetime.timedelta(days=3)
    w = _make_workout(workout_date=three_ago)
    with _patch_session([w]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.json()["workouts"][0]["relative_date"] == "3 days ago"


def test_relative_date_6_days_ago():
    six_ago = TODAY - datetime.timedelta(days=6)
    w = _make_workout(workout_date=six_ago)
    with _patch_session([w]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.json()["workouts"][0]["relative_date"] == "6 days ago"


def test_relative_date_old_is_iso():
    old_date = TODAY - datetime.timedelta(days=10)
    w = _make_workout(workout_date=old_date)
    with _patch_session([w]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.json()["workouts"][0]["relative_date"] == old_date.isoformat()


# ── AC (d): sort order most-recent-first ─────────────────────────────────────

def test_sort_order_most_recent_first():
    oldest = _make_workout(workout_date=TODAY - datetime.timedelta(days=5), name="Oldest")
    newest = _make_workout(workout_date=TODAY, name="Newest")
    middle = _make_workout(workout_date=TODAY - datetime.timedelta(days=2), name="Middle")
    # DB mock returns them in sorted order (endpoint delegates sort to DB)
    with _patch_session([newest, middle, oldest]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    workouts = res.json()["workouts"]
    assert workouts[0]["name"] == "Newest"
    assert workouts[1]["name"] == "Middle"
    assert workouts[2]["name"] == "Oldest"


# ── AC (e): empty result ──────────────────────────────────────────────────────

def test_empty_result():
    with _patch_session([]):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.status_code == 200
    body = res.json()
    assert body == {"workouts": [], "count": 0, "has_more": False}


# ── AC (f): has_more ──────────────────────────────────────────────────────────

def test_has_more_false_when_within_limit():
    workouts = [_make_workout() for _ in range(3)]
    # limit=5 default, DB returns 3 (≤ limit) so has_more=False
    with _patch_session(workouts):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.json()["has_more"] is False


def test_has_more_true_when_exceeds_limit():
    # limit=3, but DB returns 4 (limit+1) meaning there are more
    workouts = [_make_workout() for _ in range(4)]
    with _patch_session(workouts):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}&limit=3")
    body = res.json()
    assert body["has_more"] is True
    assert body["count"] == 3  # Only limit rows returned


def test_has_more_false_at_exact_limit():
    workouts = [_make_workout() for _ in range(5)]
    # limit=5 default; DB returns exactly 5 (limit+1 = 6 was asked but only 5 available)
    with _patch_session(workouts):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    body = res.json()
    assert body["has_more"] is False
    assert body["count"] == 5


# ── Unknown user returns 404 ──────────────────────────────────────────────────

def test_unknown_user_returns_404():
    mock_session = MagicMock()
    mock_session.get.return_value = None

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False

    with patch("backend.main.Session", return_value=mock_cm):
        res = client.get(f"/api/home/recent-workouts?user_id={_UID}")
    assert res.status_code == 404


def test_invalid_user_id_returns_404():
    res = client.get("/api/home/recent-workouts?user_id=not-a-uuid")
    assert res.status_code == 404
