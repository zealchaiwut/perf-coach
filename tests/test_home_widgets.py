"""Tests for home widget endpoints.

Issue #348: GET /api/home/recent-workouts
  AC (a)-(f): shape, limit validation, relative_date, sort, empty, has_more

Issue #349: GET /api/home/weight-summary
  AC (a) shape with current weight present
  AC (b) nulls when no weight entries
  AC (c) sparkline length=30, nulls for days with no data
  AC (d) target block when active target exists
  AC (e) target is null when no active target
  AC (f) graceful empty-defaults when weight_entries table absent

Issue #350: GET /api/home/personal-records
  AC (a) response shape matches spec
  AC (b) tracks filter returns only requested tracks
  AC (c) time formatting: 6871s → "1:54:31"
  AC (d) trend "improving" for faster time record
  AC (e) trend "stable" within 1% threshold
  AC (f) graceful empty response when personal_records table absent
  AC (g) graceful empty response when user has no records

Issue #351: GET /api/home/readiness
  AC (a) response has expected shape
  AC (b) score is null when no daily_metrics row for queried date
  AC (c) all-average values yield score ≈ 50
  AC (d) great sleep + great HRV yields score > 70
  AC (e) score_label correct at every boundary value (19, 20, 39, 40, 59, 60, 79, 80)
  AC (f) rolling_baseline excludes the queried date, covers only prior 7 days
  AC (g) contributors array contains exactly 5 factors
"""
import datetime
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import exc as _sa_exc

from backend.main import app
from backend.models import WeightEntry, WeightTarget

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


# ── Issue #349: GET /api/home/weight-summary ─────────────────────────────────

_W_UID = str(uuid.uuid4())
_TODAY = datetime.date.today()


def _make_entry(entry_date, weight_kg):
    e = MagicMock()
    e.entry_date = entry_date
    e.weight_kg = Decimal(str(weight_kg))
    return e


def _make_target(target_weight_kg, target_date, start_weight_kg, start_date):
    t = MagicMock()
    t.target_weight_kg = Decimal(str(target_weight_kg))
    t.target_date = target_date
    t.start_weight_kg = Decimal(str(start_weight_kg))
    t.start_date = start_date
    t.status = "active"
    return t


def _patch_weight_session(entries, target=None, user_exists=True):
    mock_user = MagicMock()
    mock_user.id = uuid.UUID(_W_UID)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_user if user_exists else None

    entry_q = MagicMock()
    entry_q.filter.return_value = entry_q
    entry_q.order_by.return_value = entry_q
    entry_q.all.return_value = entries

    target_q = MagicMock()
    target_q.filter.return_value = target_q
    target_q.first.return_value = target

    def _query(model):
        if model is WeightEntry:
            return entry_q
        return target_q

    mock_session.query.side_effect = _query

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False

    return patch("backend.main.Session", return_value=mock_cm)


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

    mock_cm2 = MagicMock()
    mock_cm2.__enter__.return_value = mock_session
    mock_cm2.__exit__.return_value = False

    return patch("backend.main.Session", return_value=mock_cm2)


# AC (a): returns expected shape with current weight present
def test_weight_summary_shape():
    entry = _make_entry(_TODAY, 75.0)
    with _patch_weight_session([entry]):
        res = client.get(f"/api/home/weight-summary?user_id={_W_UID}")
    assert res.status_code == 200
    body = res.json()
    for key in ("current_weight_kg", "current_date", "moving_avg_7d_kg",
                "delta_7d_kg", "delta_30d_kg", "target", "sparkline"):
        assert key in body, f"missing key: {key}"
    assert isinstance(body["current_weight_kg"], float)
    assert body["current_weight_kg"] == 75.0
    assert body["current_date"] == str(_TODAY)


# AC (b): returns nulls cleanly when no weight entries exist
def test_weight_summary_no_entries():
    with _patch_weight_session([]):
        res = client.get(f"/api/home/weight-summary?user_id={_W_UID}")
    assert res.status_code == 200
    body = res.json()
    assert body["current_weight_kg"] is None
    assert body["moving_avg_7d_kg"] is None
    assert body["delta_7d_kg"] is None
    assert body["delta_30d_kg"] is None
    assert body["current_date"] is None
    assert body["target"] is None
    assert len(body["sparkline"]) == 30
    assert all(v is None for v in body["sparkline"])


# AC (c): sparkline length is exactly 30, nulls for days with no data
def test_weight_summary_sparkline_length():
    entry = _make_entry(_TODAY, 75.0)
    with _patch_weight_session([entry]):
        res = client.get(f"/api/home/weight-summary?user_id={_W_UID}")
    sparkline = res.json()["sparkline"]
    assert len(sparkline) == 30
    assert sparkline[-1] is not None  # today's MA is non-null
    assert all(v is None for v in sparkline[:-1])  # older days have no data


# AC (d): target block populated correctly when active target exists
def test_weight_summary_target_block():
    entry = _make_entry(_TODAY, 75.0)
    target_date = _TODAY + datetime.timedelta(days=60)
    start_date = _TODAY - datetime.timedelta(days=30)
    target = _make_target(
        target_weight_kg=70.0,
        target_date=target_date,
        start_weight_kg=80.0,
        start_date=start_date,
    )
    with _patch_weight_session([entry], target=target):
        res = client.get(f"/api/home/weight-summary?user_id={_W_UID}")
    assert res.status_code == 200
    t = res.json()["target"]
    assert t is not None
    assert "target_weight_kg" in t
    assert "target_date" in t
    assert "progress_pct" in t
    assert "kg_to_go" in t
    assert "status_label" in t
    assert t["target_weight_kg"] == 70.0
    assert t["target_date"] == str(target_date)
    assert 0 <= t["progress_pct"] <= 100
    assert t["status_label"] in ("on_track", "behind", "ahead", "no_data")


# AC (e): target is null when no active target exists
def test_weight_summary_no_target():
    entry = _make_entry(_TODAY, 75.0)
    with _patch_weight_session([entry], target=None):
        res = client.get(f"/api/home/weight-summary?user_id={_W_UID}")
    assert res.status_code == 200
    assert res.json()["target"] is None


# AC (f): graceful empty-defaults when weight_entries table absent
def test_weight_summary_table_absent():
    mock_user = MagicMock()
    mock_user.id = uuid.UUID(_W_UID)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_user
    mock_session.query.side_effect = _sa_exc.OperationalError(
        "no such table: weight_entries", "SELECT 1", None, None
    )

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False

    with patch("backend.main.Session", return_value=mock_cm):
        res = client.get(f"/api/home/weight-summary?user_id={_W_UID}")

    assert res.status_code == 200
    body = res.json()
    assert body["current_weight_kg"] is None
    assert body["moving_avg_7d_kg"] is None
    assert body["delta_7d_kg"] is None
    assert body["delta_30d_kg"] is None
    assert body["current_date"] is None
    assert body["target"] is None
    assert body["sparkline"] == []


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


# ── Home readiness widget tests (issue #351) ──────────────────────────────────

_RDY_UID = str(uuid.uuid4())
_RDY_TODAY = datetime.date.today()


def _make_daily_metric(metric_date=None, sleep_hours=7.0, hrv=60, resting_hr=60, mood=3, energy=3):
    m = MagicMock()
    m.metric_date = metric_date or _RDY_TODAY
    m.sleep_hours = Decimal(str(sleep_hours)) if sleep_hours is not None else None
    m.hrv = hrv
    m.resting_hr = resting_hr
    m.mood = mood
    m.energy = energy
    return m


def _patch_readiness_session(user_found=True, metrics_row=None, baseline_rows=None):
    mock_user = MagicMock()
    mock_user.id = uuid.UUID(_RDY_UID)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_user if user_found else None

    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.first.return_value = metrics_row
    query_chain.all.return_value = baseline_rows or []
    mock_session.query.return_value = query_chain

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False

    return patch("backend.main.Session", return_value=mock_cm)


# (a) response has expected shape
def test_readiness_response_shape():
    m = _make_daily_metric()
    with _patch_readiness_session(metrics_row=m, baseline_rows=[]):
        res = client.get(f"/api/home/readiness?user_id={_RDY_UID}")
    assert res.status_code == 200
    body = res.json()
    for key in ("date", "score", "score_label", "contributors", "rolling_baseline"):
        assert key in body
    assert len(body["contributors"]) == 5
    for c in body["contributors"]:
        for key in ("factor", "value", "weight", "impact"):
            assert key in c
    for key in ("hrv_7d_avg", "rhr_7d_avg", "sleep_7d_avg_hours"):
        assert key in body["rolling_baseline"]


# (b) score null when no daily_metrics row
def test_readiness_score_null_when_no_metrics():
    with _patch_readiness_session(metrics_row=None, baseline_rows=[]):
        res = client.get(f"/api/home/readiness?user_id={_RDY_UID}")
    assert res.status_code == 200
    body = res.json()
    assert body["score"] is None
    assert body["score_label"] == "No data"
    for c in body["contributors"]:
        assert c["value"] is None


# (c) all-average values yield score ≈ 50
def test_readiness_all_average_score_approx_50():
    baseline = [
        _make_daily_metric(sleep_hours=7.0, hrv=60, resting_hr=60, mood=3, energy=3)
        for _ in range(7)
    ]
    today_m = _make_daily_metric(sleep_hours=7.0, hrv=60, resting_hr=60, mood=3, energy=3)
    with _patch_readiness_session(metrics_row=today_m, baseline_rows=baseline):
        res = client.get(f"/api/home/readiness?user_id={_RDY_UID}&date={_RDY_TODAY.isoformat()}")
    body = res.json()
    assert body["score"] is not None
    assert 40 <= body["score"] <= 65


# (d) great sleep + great HRV yields score > 70
def test_readiness_great_sleep_hrv_yields_high_score():
    baseline = [
        _make_daily_metric(sleep_hours=6.0, hrv=60, resting_hr=60, mood=3, energy=3)
        for _ in range(7)
    ]
    today_m = _make_daily_metric(sleep_hours=9.0, hrv=90, resting_hr=60, mood=3, energy=3)
    with _patch_readiness_session(metrics_row=today_m, baseline_rows=baseline):
        res = client.get(f"/api/home/readiness?user_id={_RDY_UID}&date={_RDY_TODAY.isoformat()}")
    body = res.json()
    assert body["score"] is not None
    assert body["score"] > 70


# (e) score_label correct at every boundary
@pytest.mark.parametrize("score,expected_label", [
    (19, "Recovery"),
    (20, "Caution"),
    (39, "Caution"),
    (40, "OK"),
    (59, "OK"),
    (60, "Good"),
    (79, "Good"),
    (80, "Excellent"),
    (None, "No data"),
])
def test_readiness_score_label_boundaries(score, expected_label):
    from backend.main import _readiness_score_label
    assert _readiness_score_label(score) == expected_label


# (f) rolling_baseline excludes queried date, covers only prior 7 days
def test_readiness_rolling_baseline_excludes_queried_date():
    baseline = [
        _make_daily_metric(sleep_hours=6.0, hrv=50, resting_hr=65, mood=2, energy=2)
        for _ in range(7)
    ]
    today_m = _make_daily_metric(sleep_hours=9.0, hrv=90, resting_hr=45, mood=5, energy=5)
    with _patch_readiness_session(metrics_row=today_m, baseline_rows=baseline):
        res = client.get(f"/api/home/readiness?user_id={_RDY_UID}&date={_RDY_TODAY.isoformat()}")
    body = res.json()
    rb = body["rolling_baseline"]
    assert rb["sleep_7d_avg_hours"] == pytest.approx(6.0, abs=0.1)
    assert rb["hrv_7d_avg"] == pytest.approx(50.0, abs=0.1)
    assert rb["rhr_7d_avg"] == pytest.approx(65.0, abs=0.1)


# (g) contributors array contains exactly 5 factors
def test_readiness_contributors_5_factors():
    m = _make_daily_metric()
    with _patch_readiness_session(metrics_row=m, baseline_rows=[]):
        res = client.get(f"/api/home/readiness?user_id={_RDY_UID}")
    factors = [c["factor"] for c in res.json()["contributors"]]
    assert len(factors) == 5
    assert set(factors) == {"sleep_hours", "hrv", "rhr", "mood", "energy"}


# ── Home weekly-summary widget tests (issue #352) ─────────────────────────────

_WK_UID = str(uuid.uuid4())
_WK_START = datetime.date(2026, 6, 2)   # Monday
_WK_END = datetime.date(2026, 6, 8)     # Sunday
_WK_PREV_START = datetime.date(2026, 5, 26)  # Previous Monday


def _make_wk_workout(workout_date, workout_type="run", distance_km=None,
                      duration_seconds=None, tss=None, elevation_m=None):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.workout_date = workout_date
    w.workout_type = workout_type
    w.distance_km = Decimal(str(distance_km)) if distance_km is not None else None
    w.duration_seconds = duration_seconds
    w.tss = tss
    w.elevation_m = elevation_m
    return w


def _patch_wk_session(workouts, user_found=True):
    mock_user = MagicMock()
    mock_user.id = uuid.UUID(_WK_UID)
    mock_session = MagicMock()
    mock_session.get.return_value = mock_user if user_found else None
    q = MagicMock()
    q.filter.return_value = q
    q.all.return_value = workouts
    mock_session.query.return_value = q
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_session
    mock_cm.__exit__.return_value = False
    return patch("backend.main.Session", return_value=mock_cm)


# (a) returns 7-day window with correct schema
def test_weekly_summary_returns_7day_window():
    w = _make_wk_workout(_WK_START, distance_km=5.0, tss=50.0)
    qs = f"?user_id={_WK_UID}&week_start={_WK_START.isoformat()}"
    with _patch_wk_session([w]):
        res = client.get(f"/api/home/weekly-summary{qs}")
    assert res.status_code == 200
    body = res.json()
    assert body["week_start"] == "2026-06-02"
    assert body["week_end"] == "2026-06-08"
    assert "workouts" in body
    assert "total" in body["workouts"]
    assert "by_type" in body["workouts"]
    assert "distance_km" in body
    assert "duration_minutes" in body
    assert "total_tss" in body
    assert "elevation_m" in body
    assert "rest_days" in body
    assert "vs_prev_week" in body
    assert "daily_load" in body
    assert len(body["daily_load"]) == 7


# (b) by_type counts correct
def test_weekly_summary_by_type_counts():
    workouts = [
        _make_wk_workout(_WK_START, workout_type="run"),
        _make_wk_workout(_WK_START + datetime.timedelta(days=1), workout_type="run"),
        _make_wk_workout(_WK_START + datetime.timedelta(days=2), workout_type="lift"),
        _make_wk_workout(_WK_START + datetime.timedelta(days=3), workout_type="bike"),
        _make_wk_workout(_WK_START + datetime.timedelta(days=4), workout_type="wod"),
    ]
    qs = f"?user_id={_WK_UID}&week_start={_WK_START.isoformat()}"
    with _patch_wk_session(workouts):
        res = client.get(f"/api/home/weekly-summary{qs}")
    by_type = res.json()["workouts"]["by_type"]
    assert by_type["run"] == 2
    assert by_type["lift"] == 1
    assert by_type["bike"] == 1
    assert by_type["wod"] == 1


# (c) distance_km and tss sums correct
def test_weekly_summary_aggregates():
    workouts = [
        _make_wk_workout(_WK_START, distance_km=5.0, tss=50.0, duration_seconds=1800, elevation_m=100),
        _make_wk_workout(_WK_START + datetime.timedelta(days=1), distance_km=10.0, tss=80.0, duration_seconds=3600, elevation_m=200),
    ]
    qs = f"?user_id={_WK_UID}&week_start={_WK_START.isoformat()}"
    with _patch_wk_session(workouts):
        res = client.get(f"/api/home/weekly-summary{qs}")
    body = res.json()
    assert body["distance_km"] == pytest.approx(15.0, abs=0.01)
    assert body["total_tss"] == pytest.approx(130.0, abs=0.01)
    assert body["duration_minutes"] == pytest.approx(90.0, abs=0.1)
    assert body["elevation_m"] == 300


# (d) vs_prev_week deltas correct
def test_weekly_summary_vs_prev_week():
    prev_w = _make_wk_workout(_WK_PREV_START, distance_km=8.0, tss=60.0)
    curr_w1 = _make_wk_workout(_WK_START, distance_km=5.0, tss=50.0)
    curr_w2 = _make_wk_workout(_WK_START + datetime.timedelta(days=1), distance_km=10.0, tss=80.0)
    qs = f"?user_id={_WK_UID}&week_start={_WK_START.isoformat()}"
    with _patch_wk_session([prev_w, curr_w1, curr_w2]):
        res = client.get(f"/api/home/weekly-summary{qs}")
    vp = res.json()["vs_prev_week"]
    assert vp["total_delta"] == 1
    assert vp["distance_km_delta"] == pytest.approx(7.0, abs=0.01)
    assert vp["tss_delta"] == pytest.approx(70.0, abs=0.01)


# (e) daily_load has exactly 7 entries with date/tss/is_rest
def test_weekly_summary_daily_load_7_entries():
    w = _make_wk_workout(_WK_START, tss=40.0)
    qs = f"?user_id={_WK_UID}&week_start={_WK_START.isoformat()}"
    with _patch_wk_session([w]):
        res = client.get(f"/api/home/weekly-summary{qs}")
    dl = res.json()["daily_load"]
    assert len(dl) == 7
    dates = [entry["date"] for entry in dl]
    assert dates[0] == _WK_START.isoformat()
    assert dates[-1] == _WK_END.isoformat()
    for entry in dl:
        assert "date" in entry
        assert "tss" in entry
        assert "is_rest" in entry
    assert dl[0]["tss"] == pytest.approx(40.0, abs=0.01)
    assert dl[0]["is_rest"] is False
    assert all(entry["is_rest"] for entry in dl[1:])


# (f) rest_days counts correctly
def test_weekly_summary_rest_days():
    workouts = [
        _make_wk_workout(_WK_START),
        _make_wk_workout(_WK_START + datetime.timedelta(days=2)),
        _make_wk_workout(_WK_START + datetime.timedelta(days=4)),
    ]
    qs = f"?user_id={_WK_UID}&week_start={_WK_START.isoformat()}"
    with _patch_wk_session(workouts):
        res = client.get(f"/api/home/weekly-summary{qs}")
    assert res.json()["rest_days"] == 4


# (g) graceful degradation when distance/duration/tss columns absent
def test_weekly_summary_graceful_no_columns():
    class _SlimWorkout:
        def __init__(self, d):
            self.id = uuid.uuid4()
            self.workout_date = d
            self.workout_type = "run"

    slim = _SlimWorkout(_WK_START)
    qs = f"?user_id={_WK_UID}&week_start={_WK_START.isoformat()}"
    with _patch_wk_session([slim]):
        res = client.get(f"/api/home/weekly-summary{qs}")
    assert res.status_code == 200
    body = res.json()
    assert body["distance_km"] is None
    assert body["duration_minutes"] is None
    assert body["total_tss"] is None
    assert body["workouts"]["total"] == 1


# (h) week boundaries computed in Bangkok time — default week_start is Monday
def test_weekly_summary_default_week_start_is_monday():
    qs = f"?user_id={_WK_UID}"
    with _patch_wk_session([]):
        res = client.get(f"/api/home/weekly-summary{qs}")
    assert res.status_code == 200
    body = res.json()
    ws = datetime.date.fromisoformat(body["week_start"])
    we = datetime.date.fromisoformat(body["week_end"])
    assert ws.weekday() == 0  # Monday
    assert (we - ws).days == 6


# 404 cases (AC: user_id missing or unknown returns 404)
def test_weekly_summary_missing_user_id_returns_404():
    with _patch_wk_session([]):
        res = client.get("/api/home/weekly-summary")
    assert res.status_code == 404


def test_weekly_summary_unknown_user_returns_404():
    with _patch_wk_session([], user_found=False):
        res = client.get(f"/api/home/weekly-summary?user_id={_WK_UID}")
    assert res.status_code == 404
