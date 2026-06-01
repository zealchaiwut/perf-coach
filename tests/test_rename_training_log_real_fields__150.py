"""Tests for issue #150: Rename /training_log to GET /api/training-log with real fields"""
import os
import pytest
import httpx
from datetime import date as _date, timedelta

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


def _create_workout(client, user_id, **kwargs):
    payload = {
        "user_id": user_id,
        "name": kwargs.pop("name", "150 Test Workout"),
        "workout_date": kwargs.pop("workout_date", "2026-05-15"),
        "workout_type": kwargs.pop("workout_type", "run"),
        "exercises": kwargs.pop("exercises", []),
    }
    payload.update(kwargs)
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    return res.json()


def _create_daily_metric(client, user_id, metric_date, **kwargs):
    payload = {"user_id": user_id, "metric_date": metric_date, **kwargs}
    res = client.post("/api/daily-metrics", json=payload)
    assert res.status_code in (200, 201), f"Failed to create daily metric: {res.text}"
    return res.json()


def _delete_workout(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


def _delete_daily_metric(client, metric_id):
    client.delete(f"/api/daily-metrics/{metric_id}")


# ── AC 1: GET /api/training-log returns 200 with weeks array ─────────────────

def test_new_route_returns_200_with_weeks(client, alice_id):
    """AC: GET /api/training-log responds with HTTP 200 and a weeks array"""
    r = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "weeks" in data
    assert isinstance(data["weeks"], list)


# ── AC 2: Old route /training_log returns 404 ─────────────────────────────────

def test_old_training_log_route_returns_404(client):
    """AC: GET /training_log (old route) returns 404"""
    r = client.get("/training_log", params={"from": "2026-05-01", "to": "2026-05-31"})
    assert r.status_code == 404, f"Old /training_log should be 404, got {r.status_code}"


# ── AC 3 & 4: user_id, from, to query params ─────────────────────────────────

def test_user_id_scopes_results(client, alice_id):
    """AC: user_id param scopes results to that user"""
    r = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    for week in r.json()["weeks"]:
        for entry in week["entries"]:
            if entry.get("type") != "rest":
                assert "id" in entry


def test_from_to_filter_range(client, alice_id):
    """AC: from/to params filter entries to that date range"""
    w = _create_workout(client, alice_id, name="150 range test", workout_date="2026-04-15")
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-01",
            "to": "2026-05-31",
        })
        assert r.status_code == 200
        all_entries = [e for wk in r.json()["weeks"] for e in wk["entries"]]
        ids = [e.get("id") for e in all_entries]
        assert w["id"] not in ids, "Workout outside date range should not appear"
    finally:
        _delete_workout(client, w["id"])


# ── AC 5: types filter (comma-separated) ─────────────────────────────────────

def test_types_filter_single_type(client, alice_id):
    """AC: types=run filters to run entries only"""
    run_w = _create_workout(client, alice_id, name="150 run entry", workout_type="run",
                            workout_date="2026-05-15")
    str_w = _create_workout(client, alice_id, name="150 strength entry", workout_type="strength",
                            workout_date="2026-05-16")
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-16",
            "types": "run",
        })
        assert r.status_code == 200
        entries = [e for wk in r.json()["weeks"] for e in wk["entries"]]
        ids = [e.get("id") for e in entries]
        assert run_w["id"] in ids, "Run workout should appear"
        assert str_w["id"] not in ids, "Strength workout should be filtered out"
    finally:
        _delete_workout(client, run_w["id"])
        _delete_workout(client, str_w["id"])


def test_types_filter_comma_separated(client, alice_id):
    """AC: types=run,bike returns both run and bike entries, excludes others"""
    run_w = _create_workout(client, alice_id, name="150 run multi", workout_type="run",
                            workout_date="2026-05-15")
    bike_w = _create_workout(client, alice_id, name="150 bike multi", workout_type="bike",
                             workout_date="2026-05-16")
    str_w = _create_workout(client, alice_id, name="150 strength multi", workout_type="strength",
                            workout_date="2026-05-17")
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-17",
            "types": "run,bike",
        })
        assert r.status_code == 200
        entries = [e for wk in r.json()["weeks"] for e in wk["entries"]]
        ids = [e.get("id") for e in entries]
        assert run_w["id"] in ids, "Run workout should appear in run,bike filter"
        assert bike_w["id"] in ids, "Bike workout should appear in run,bike filter"
        assert str_w["id"] not in ids, "Strength workout should be excluded by run,bike filter"
    finally:
        _delete_workout(client, run_w["id"])
        _delete_workout(client, bike_w["id"])
        _delete_workout(client, str_w["id"])


# ── AC 6: search filter ───────────────────────────────────────────────────────

def test_search_filter_case_insensitive(client, alice_id):
    """AC: search filters entries by workout name (case-insensitive substring)"""
    tempo_w = _create_workout(client, alice_id, name="Tempo intervals", workout_date="2026-05-15")
    easy_w = _create_workout(client, alice_id, name="Easy jog", workout_date="2026-05-16")
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-16",
            "search": "tempo",
        })
        assert r.status_code == 200
        entries = [e for wk in r.json()["weeks"] for e in wk["entries"]]
        ids = [e.get("id") for e in entries]
        assert tempo_w["id"] in ids, "Tempo workout should appear"
        assert easy_w["id"] not in ids, "Easy jog should be filtered out"
    finally:
        _delete_workout(client, tempo_w["id"])
        _delete_workout(client, easy_w["id"])


# ── AC 7 & 8: include_rest param ─────────────────────────────────────────────

def test_rest_days_hidden_by_default(client, alice_id):
    """AC: include_rest defaults to false — rest-day entries not returned by default"""
    r = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    for week in r.json()["weeks"]:
        for entry in week["entries"]:
            assert entry.get("type") != "rest", "Rest-day entries should not appear without include_rest=true"


def test_include_rest_true_shows_rest_days(client, alice_id):
    """AC: include_rest=true includes rest-day entries from daily_metrics"""
    metric_date = "2026-05-20"
    metric = _create_daily_metric(client, alice_id, metric_date,
                                  sleep_hours=7.5, energy=3, mood=4, resting_hr=52)
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": metric_date,
            "to": metric_date,
            "include_rest": "true",
        })
        assert r.status_code == 200
        entries = [e for wk in r.json()["weeks"] for e in wk["entries"]]
        rest_entries = [e for e in entries if e.get("type") == "rest"]
        assert rest_entries, "Expected at least one rest-day entry with include_rest=true"
        rest = rest_entries[0]
        assert rest.get("sleep_hours") == 7.5
        assert rest.get("energy") == 3
        assert rest.get("mood") == 4
        assert rest.get("resting_hr") == 52
    finally:
        if isinstance(metric, dict) and "id" in metric:
            _delete_daily_metric(client, metric["id"])


# ── AC 9 & 10: Real workout fields ───────────────────────────────────────────

def test_workout_entry_real_fields(client, alice_id):
    """AC: Workout entries return real values from distance_km, duration_seconds, avg_hr, elevation_m"""
    w = _create_workout(client, alice_id,
                        name="150 real fields",
                        workout_type="run",
                        workout_date="2026-05-15",
                        distance_km=10.0,
                        duration_seconds=3600,
                        avg_hr=145,
                        elevation_m=200)
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for wk in r.json()["weeks"] for e in wk["entries"] if e.get("id") == w["id"]]
        assert entries, "Created workout not found in training log"
        entry = entries[0]
        assert entry["distance_km"] == 10.0
        assert entry["duration_seconds"] == 3600
        assert entry["avg_hr"] == 145
        assert entry["elevation_m"] == 200
    finally:
        _delete_workout(client, w["id"])


def test_nullable_fields_are_null_when_not_set(client, alice_id):
    """AC: Fields are null only when the column value is genuinely NULL"""
    w = _create_workout(client, alice_id,
                        name="150 null fields",
                        workout_type="strength",
                        workout_date="2026-05-15")
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for wk in r.json()["weeks"] for e in wk["entries"] if e.get("id") == w["id"]]
        assert entries
        entry = entries[0]
        assert entry.get("distance_km") is None
        assert entry.get("duration_seconds") is None
        assert entry.get("avg_hr") is None
        assert entry.get("elevation_m") is None
    finally:
        _delete_workout(client, w["id"])


# ── AC 11: Pace computation ───────────────────────────────────────────────────

def test_pace_computed_for_run(client, alice_id):
    """AC: Run entries include average_pace_seconds_per_km when both fields present"""
    w = _create_workout(client, alice_id,
                        name="150 pace run",
                        workout_type="run",
                        workout_date="2026-05-15",
                        distance_km=10.0,
                        duration_seconds=3600)
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for wk in r.json()["weeks"] for e in wk["entries"] if e.get("id") == w["id"]]
        assert entries
        pace = entries[0].get("average_pace_seconds_per_km")
        assert pace is not None, "Pace should be present for run with distance+duration"
        assert abs(pace - 360.0) < 1, f"Expected pace 360, got {pace}"
    finally:
        _delete_workout(client, w["id"])


def test_pace_absent_when_distance_missing(client, alice_id):
    """AC: average_pace_seconds_per_km is absent/null when distance_km is null"""
    w = _create_workout(client, alice_id,
                        name="150 pace no dist",
                        workout_type="run",
                        workout_date="2026-05-15",
                        duration_seconds=3600)
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for wk in r.json()["weeks"] for e in wk["entries"] if e.get("id") == w["id"]]
        assert entries
        pace = entries[0].get("average_pace_seconds_per_km")
        assert pace is None, f"Pace should be null when distance_km missing, got {pace}"
    finally:
        _delete_workout(client, w["id"])


# ── AC 12: Week object shape ──────────────────────────────────────────────────

def test_week_object_has_required_fields(client, alice_id):
    """AC: Each week object contains week_start, week_end, label, summary, entries"""
    w = _create_workout(client, alice_id, name="150 week shape", workout_date="2026-05-15")
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        for week in r.json()["weeks"]:
            assert "week_start" in week
            assert "week_end" in week
            assert "label" in week
            assert "summary" in week
            assert "entries" in week
    finally:
        _delete_workout(client, w["id"])


def test_week_label_this_week(client, alice_id):
    """AC: Label is 'This week' for the current ISO week"""
    today = _date.today()
    w = _create_workout(client, alice_id, name="150 this week label", workout_date=today.isoformat())
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": today.isoformat(),
            "to": today.isoformat(),
        })
        assert r.status_code == 200
        weeks = r.json()["weeks"]
        labels = [wk["label"] for wk in weeks]
        assert "This week" in labels, f"Expected 'This week' label, got: {labels}"
    finally:
        _delete_workout(client, w["id"])


# ── AC 13-16: Summary fields ──────────────────────────────────────────────────

def test_summary_total_distance_km(client, alice_id):
    """AC: summary.total_distance_km sums distance_km for the week, skipping nulls"""
    w1 = _create_workout(client, alice_id, name="150 dist1", workout_date="2026-05-14", distance_km=5.0)
    w2 = _create_workout(client, alice_id, name="150 dist2", workout_date="2026-05-15", distance_km=10.0)
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-11",
            "to": "2026-05-17",
        })
        assert r.status_code == 200
        week = next((wk for wk in r.json()["weeks"] if wk["week_start"] == "2026-05-11"), None)
        assert week is not None, "Expected week starting 2026-05-11"
        total = week["summary"]["total_distance_km"]
        assert total >= 15.0, f"Expected total_distance_km >= 15.0, got {total}"
    finally:
        _delete_workout(client, w1["id"])
        _delete_workout(client, w2["id"])


def test_summary_total_time_minutes(client, alice_id):
    """AC: summary.total_time_minutes sums duration_seconds/60 for the week, skipping nulls"""
    w1 = _create_workout(client, alice_id, name="150 dur1", workout_date="2026-05-14", duration_seconds=1500)
    w2 = _create_workout(client, alice_id, name="150 dur2", workout_date="2026-05-15", duration_seconds=3000)
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-11",
            "to": "2026-05-17",
        })
        assert r.status_code == 200
        week = next((wk for wk in r.json()["weeks"] if wk["week_start"] == "2026-05-11"), None)
        assert week is not None, "Expected week starting 2026-05-11"
        total_min = week["summary"]["total_time_minutes"]
        assert total_min >= 75.0, f"Expected total_time_minutes >= 75.0, got {total_min}"
    finally:
        _delete_workout(client, w1["id"])
        _delete_workout(client, w2["id"])


def test_summary_workout_count(client, alice_id):
    """AC: summary.workout_count counts only workout entries (not rest days)"""
    w1 = _create_workout(client, alice_id, name="150 count1", workout_date="2026-05-14")
    w2 = _create_workout(client, alice_id, name="150 count2", workout_date="2026-05-15")
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-11",
            "to": "2026-05-17",
        })
        assert r.status_code == 200
        week = next((wk for wk in r.json()["weeks"] if wk["week_start"] == "2026-05-11"), None)
        assert week is not None
        assert week["summary"]["workout_count"] >= 2
    finally:
        _delete_workout(client, w1["id"])
        _delete_workout(client, w2["id"])


def test_summary_total_tss(client, alice_id):
    """AC: summary.total_tss aggregates TSS for the week"""
    w1 = _create_workout(client, alice_id, name="150 tss1", workout_date="2026-05-14", tss=80.0)
    w2 = _create_workout(client, alice_id, name="150 tss2", workout_date="2026-05-15", tss=60.0)
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-11",
            "to": "2026-05-17",
        })
        assert r.status_code == 200
        week = next((wk for wk in r.json()["weeks"] if wk["week_start"] == "2026-05-11"), None)
        assert week is not None
        assert week["summary"]["total_tss"] >= 140.0, f"Expected TSS >= 140, got {week['summary']['total_tss']}"
    finally:
        _delete_workout(client, w1["id"])
        _delete_workout(client, w2["id"])
