"""
Tests for issue #106: Fix and standardize GET /training_log to /api/training-log
Runs against UAT environment (http://127.0.0.1:9001)
"""
import os

import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_WORKOUT_DATE = "2026-04-15"
_RANGE_FROM   = "2026-04-01"
_RANGE_TO     = "2026-04-30"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    res = client.post("/api/users", json={"name": "TrainingLogTester106"})
    assert res.status_code in (200, 201), f"Failed to create test user: {res.text}"
    uid = res.json()["id"]
    yield uid
    client.delete(f"/api/users/{uid}")


@pytest.fixture(scope="module")
def workout_with_metrics(client, test_user):
    payload = {
        "user_id": test_user,
        "name": "Test Run 106",
        "workout_date": _WORKOUT_DATE,
        "workout_type": "run",
        "exercises": [{"name": "Run", "duration": "60 min"}],
        "distance_km": 10.5,
        "duration_seconds": 3600,
        "avg_hr": 145,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


def _get_log(client, user_id, from_date=_RANGE_FROM, to_date=_RANGE_TO, **params):
    query = f"/api/training-log?user_id={user_id}&from={from_date}&to={to_date}"
    for k, v in params.items():
        query += f"&{k}={v}"
    res = client.get(query)
    assert res.status_code == 200, f"GET /api/training-log failed: {res.status_code} {res.text}"
    return res.json()


def _all_entries(data):
    return [e for week in data["weeks"] for e in week["entries"]]


# ── AC: old route is gone ─────────────────────────────────────────────────────

def test_old_route_returns_404(client):
    res = client.get("/training_log?from=2026-04-01&to=2026-04-30")
    assert res.status_code == 404, f"Old /training_log must return 404, got {res.status_code}"


# ── AC: new route exists and returns correct shape ────────────────────────────

def test_new_route_returns_200(client, test_user):
    res = client.get(f"/api/training-log?user_id={test_user}&from={_RANGE_FROM}&to={_RANGE_TO}")
    assert res.status_code == 200


def test_response_has_weeks_key(client, test_user):
    data = _get_log(client, test_user)
    assert "weeks" in data


def test_each_week_has_required_keys(client, test_user):
    data = _get_log(client, test_user)
    for week in data["weeks"]:
        for key in ("week_start", "week_end", "label", "summary", "entries"):
            assert key in week, f"Week missing key {key!r}: {week}"


# ── AC: real distance/duration/avg_hr values ──────────────────────────────────

def test_entry_shows_real_distance(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e.get("id") == workout_with_metrics), None)
    assert entry is not None, "Workout with metrics not found in training log"
    assert entry["distance_km"] == 10.5


def test_entry_shows_real_duration_minutes(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e.get("id") == workout_with_metrics), None)
    assert entry is not None
    assert entry["duration_minutes"] == 60.0


def test_entry_shows_real_avg_hr(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user)
    entry = next((e for e in _all_entries(data) if e.get("id") == workout_with_metrics), None)
    assert entry is not None
    assert entry["avg_hr"] == 145


# ── AC: week summary uses real values ─────────────────────────────────────────

def test_week_summary_total_distance_includes_real_value(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user)
    week = next(
        (w for w in data["weeks"] if any(e.get("id") == workout_with_metrics for e in w["entries"])),
        None,
    )
    assert week is not None
    assert week["summary"]["total_distance_km"] >= 10.5


def test_week_summary_total_time_includes_real_value(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user)
    week = next(
        (w for w in data["weeks"] if any(e.get("id") == workout_with_metrics for e in w["entries"])),
        None,
    )
    assert week is not None
    assert week["summary"]["total_time_minutes"] >= 60.0


# ── AC: query param filtering ─────────────────────────────────────────────────

def test_types_filter_returns_only_matching_type(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user, types="run")
    for entry in _all_entries(data):
        if entry["type"] != "rest":
            assert entry["type"] == "run", f"Expected only 'run', got {entry['type']!r}"


def test_types_filter_excludes_non_matching(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user, types="lift")
    ids = [e.get("id") for e in _all_entries(data)]
    assert workout_with_metrics not in ids, "run workout must not appear when filtering for lift"


def test_search_filter_returns_matching_entries(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user, search="Test Run 106")
    ids = [e.get("id") for e in _all_entries(data)]
    assert workout_with_metrics in ids, "Workout matching search term not found"


def test_search_filter_excludes_non_matching(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user, search="xyzzy_no_match_ever")
    assert _all_entries(data) == [], "Non-matching search should return no entries"


def test_include_rest_false_excludes_rest_entries(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user, include_rest="false")
    rest_entries = [e for e in _all_entries(data) if e["type"] == "rest"]
    assert rest_entries == [], "include_rest=false must omit rest entries"


def test_user_id_filters_to_specific_user(client, test_user, workout_with_metrics):
    # Create a second user — their workouts must not leak into test_user's results
    res = client.post("/api/users", json={"name": "OtherUser106"})
    assert res.status_code in (200, 201)
    other_id = res.json()["id"]
    try:
        data = _get_log(client, test_user)
        for entry in _all_entries(data):
            if entry.get("type") != "rest":
                assert entry.get("id") != other_id, "Another user's workout leaked into results"
    finally:
        client.delete(f"/api/users/{other_id}")


# ── AC: date range correctness ────────────────────────────────────────────────

def test_date_range_covers_requested_period(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user)
    ids = [e.get("id") for e in _all_entries(data)]
    assert workout_with_metrics in ids, "Workout inside range must appear"


def test_date_range_excludes_entries_outside_range(client, test_user, workout_with_metrics):
    data = _get_log(client, test_user, from_date="2026-03-01", to_date="2026-03-31")
    ids = [e.get("id") for e in _all_entries(data)]
    assert workout_with_metrics not in ids, "Workout outside range must not appear"


# ── AC: invalid input returns correct error codes ─────────────────────────────

def test_invalid_user_id_returns_400(client):
    res = client.get("/api/training-log?user_id=not-a-uuid&from=2026-04-01&to=2026-04-30")
    assert res.status_code == 400


def test_invalid_from_date_returns_400(client, test_user):
    res = client.get(f"/api/training-log?user_id={test_user}&from=bad-date&to=2026-04-30")
    assert res.status_code == 400


def test_invalid_to_date_returns_400(client, test_user):
    res = client.get(f"/api/training-log?user_id={test_user}&from=2026-04-01&to=bad-date")
    assert res.status_code == 400
