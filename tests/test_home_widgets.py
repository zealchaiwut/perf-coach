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


# ── Personal Records widget tests (issue #350) ────────────────────────────────

_PR_UID = str(uuid.uuid4())
_PR_TODAY = datetime.date.today()


def _make_pr(track_key="half_marathon", track_name="Half Marathon", track_type="time",
             value_numeric=6871.0, achieved_on=None):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.track_key = track_key
    r.track_name = track_name
    r.track_type = track_type
    r.value_numeric = value_numeric
    r.achieved_on = achieved_on or _PR_TODAY
    return r


def _patch_pr_session(records, user_found=True, raise_on_all=None):
    mock_user = MagicMock()
    mock_user.id = uuid.UUID(_PR_UID)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_user if user_found else None

    pr_query = MagicMock()
    pr_query.filter.return_value = pr_query
    pr_query.order_by.return_value = pr_query
    if raise_on_all is not None:
        pr_query.all.side_effect = raise_on_all
    else:
        pr_query.all.return_value = records
    mock_session.query.return_value = pr_query

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False

    return patch("backend.main.Session", return_value=mock_cm)


# (a) response shape matches spec
def test_pr_response_shape():
    r = _make_pr(value_numeric=6871.0)
    with _patch_pr_session([r]):
        res = client.get(f"/api/home/personal-records?user_id={_PR_UID}&tracks=half_marathon")
    assert res.status_code == 200
    body = res.json()
    assert "tracks" in body
    track = body["tracks"][0]
    for key in ("track_key", "track_name", "track_type", "current_value",
                "current_value_formatted", "achieved_on",
                "predicted_value", "predicted_value_formatted", "predicted_method", "trend"):
        assert key in track, f"missing key: {key}"
    assert track["predicted_value"] is None
    assert track["predicted_value_formatted"] is None
    assert track["predicted_method"] is None
    assert track["track_key"] == "half_marathon"
    assert track["track_type"] == "time"


# (b) tracks filter returns only requested tracks
def test_pr_tracks_filter():
    r_10k = _make_pr(track_key="10k", track_name="10K", track_type="time", value_numeric=2400.0)
    with _patch_pr_session([r_10k]):
        res = client.get(f"/api/home/personal-records?user_id={_PR_UID}&tracks=10k")
    assert res.status_code == 200
    tracks = res.json()["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["track_key"] == "10k"


# (c) time formatting: 6871 → "1:54:31"
def test_pr_time_formatting():
    r = _make_pr(track_key="half_marathon", track_type="time", value_numeric=6871.0)
    with _patch_pr_session([r]):
        res = client.get(f"/api/home/personal-records?user_id={_PR_UID}&tracks=half_marathon")
    assert res.json()["tracks"][0]["current_value_formatted"] == "1:54:31"


# (d) trend "improving" for a faster time record
def test_pr_trend_improving_time():
    r_latest = _make_pr(track_key="half_marathon", track_type="time", value_numeric=6000.0,
                        achieved_on=_PR_TODAY)
    r_prev = _make_pr(track_key="half_marathon", track_type="time", value_numeric=6871.0,
                      achieved_on=_PR_TODAY - datetime.timedelta(days=30))
    with _patch_pr_session([r_latest, r_prev]):
        res = client.get(f"/api/home/personal-records?user_id={_PR_UID}&tracks=half_marathon")
    assert res.json()["tracks"][0]["trend"] == "improving"


# (e) trend "stable" when values are within 1% threshold
def test_pr_trend_stable():
    r_latest = _make_pr(track_key="half_marathon", track_type="time", value_numeric=6871.0)
    r_prev = _make_pr(track_key="half_marathon", track_type="time", value_numeric=6870.0)
    with _patch_pr_session([r_latest, r_prev]):
        res = client.get(f"/api/home/personal-records?user_id={_PR_UID}&tracks=half_marathon")
    assert res.json()["tracks"][0]["trend"] == "stable"


# (f) graceful empty response when personal_records table is absent
def test_pr_table_absent():
    with _patch_pr_session([], raise_on_all=Exception("relation 'personal_records' does not exist")):
        res = client.get(f"/api/home/personal-records?user_id={_PR_UID}")
    assert res.status_code == 200
    assert res.json() == {"tracks": []}


# (g) graceful empty response when user has no records
def test_pr_no_records_for_user():
    with _patch_pr_session([]):
        res = client.get(f"/api/home/personal-records?user_id={_PR_UID}&tracks=half_marathon")
    assert res.status_code == 200
    track = res.json()["tracks"][0]
    assert track["current_value"] is None
    assert track["current_value_formatted"] is None
    assert track["trend"] == "no_data"
