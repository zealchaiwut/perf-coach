"""Tests for issue #122: Rename /training_log to GET /api/training-log and populate real fields"""
import os
import pytest
import httpx
from datetime import date as _date, timedelta

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

ALICE_USER_ID = "2898f7d7-e2f9-4125-871d-cc4fd5cb40ff"


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
        "name": kwargs.pop("name", "Issue 122 Test Workout"),
        "workout_date": kwargs.pop("workout_date", "2026-05-15"),
        "workout_type": kwargs.pop("workout_type", "run"),
        "exercises": kwargs.pop("exercises", []),
    }
    payload.update(kwargs)
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create workout: {res.text}"
    return res.json()


def _delete_workout(client, workout_id):
    client.delete(f"/api/workouts/{workout_id}")


# ── AC: Route at /api/training-log ───────────────────────────────────────────

def test_api_training_log_route_exists(client, alice_id):
    """AC: GET /api/training-log returns 200"""
    r = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"


def test_old_training_log_route_returns_404(client):
    """AC: Old /training_log route (no /api/ prefix) returns 404"""
    r = client.get("/training_log", params={"from": "2026-05-01", "to": "2026-05-31"})
    assert r.status_code == 404, f"Old /training_log should be gone, got {r.status_code}"


# ── AC: Response shape ────────────────────────────────────────────────────────

def test_response_has_weeks_array(client, alice_id):
    """AC: Response has a weeks array"""
    r = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()
    assert "weeks" in data
    assert isinstance(data["weeks"], list)


def test_week_shape_has_required_keys(client, alice_id):
    """AC: Each week item contains week_start, week_end, label, summary, entries"""
    r = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()
    for week in data["weeks"]:
        assert "week_start" in week
        assert "week_end" in week
        assert "label" in week
        assert "summary" in week
        assert "entries" in week


def test_week_label_this_week(client, alice_id):
    """AC: Label is 'This week' for the current ISO week"""
    today = _date.today()
    r = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": today.isoformat(),
        "to": today.isoformat(),
    })
    assert r.status_code == 200
    data = r.json()
    for week in data["weeks"]:
        assert week["label"] == "This week"


def test_week_label_past_week_format(client, alice_id):
    """AC: Past week label uses 'Mon DD–DD' format (e.g. 'May 19–25')"""
    r = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2026-05-01",
        "to": "2026-05-18",
    })
    assert r.status_code == 200
    data = r.json()
    for week in data["weeks"]:
        label = week["label"]
        assert label != "This week"
        assert "–" in label, f"Expected en-dash in label, got: {label!r}"


# ── AC: Real DB fields on workout entries ─────────────────────────────────────

def test_workout_entry_has_duration_seconds(client, alice_id):
    """AC: duration_seconds is present in each workout entry"""
    workout = _create_workout(
        client, alice_id,
        name="122 duration test",
        workout_type="run",
        workout_date="2026-05-15",
        duration_seconds=3600,
        distance_km=10.0,
    )
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for w in r.json()["weeks"] for e in w["entries"] if e.get("id") == workout["id"]]
        assert entries, "Created workout not found in training log"
        assert "duration_seconds" in entries[0]
        assert entries[0]["duration_seconds"] == 3600
    finally:
        _delete_workout(client, workout["id"])


def test_workout_entry_has_elevation_m(client, alice_id):
    """AC: elevation_m is present in each workout entry"""
    workout = _create_workout(
        client, alice_id,
        name="122 elevation test",
        workout_type="run",
        workout_date="2026-05-15",
        elevation_m=250,
    )
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for w in r.json()["weeks"] for e in w["entries"] if e.get("id") == workout["id"]]
        assert entries, "Created workout not found in training log"
        assert "elevation_m" in entries[0]
        assert entries[0]["elevation_m"] == 250
    finally:
        _delete_workout(client, workout["id"])


def test_workout_entry_has_avg_hr(client, alice_id):
    """AC: avg_hr is present in each workout entry"""
    workout = _create_workout(
        client, alice_id,
        name="122 avg_hr test",
        workout_type="run",
        workout_date="2026-05-15",
        avg_hr=155,
    )
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for w in r.json()["weeks"] for e in w["entries"] if e.get("id") == workout["id"]]
        assert entries, "Created workout not found in training log"
        assert "avg_hr" in entries[0]
        assert entries[0]["avg_hr"] == 155
    finally:
        _delete_workout(client, workout["id"])


# ── AC: average_pace_seconds_per_km ──────────────────────────────────────────

def test_pace_computed_for_run_with_both_fields(client, alice_id):
    """AC: average_pace_seconds_per_km = duration_seconds / distance_km for run"""
    workout = _create_workout(
        client, alice_id,
        name="122 pace run test",
        workout_type="run",
        workout_date="2026-05-15",
        duration_seconds=3000,
        distance_km=5.0,
    )
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for w in r.json()["weeks"] for e in w["entries"] if e.get("id") == workout["id"]]
        assert entries
        pace = entries[0].get("average_pace_seconds_per_km")
        assert pace is not None, "Pace should be computed for run with distance and duration"
        assert abs(pace - 600.0) < 1, f"Expected pace ~600, got {pace}"
    finally:
        _delete_workout(client, workout["id"])


def test_pace_computed_for_bike_with_both_fields(client, alice_id):
    """AC: average_pace_seconds_per_km = duration_seconds / distance_km for bike"""
    workout = _create_workout(
        client, alice_id,
        name="122 pace bike test",
        workout_type="bike",
        workout_date="2026-05-15",
        duration_seconds=3600,
        distance_km=30.0,
    )
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for w in r.json()["weeks"] for e in w["entries"] if e.get("id") == workout["id"]]
        assert entries
        pace = entries[0].get("average_pace_seconds_per_km")
        assert pace is not None, "Pace should be computed for bike with distance and duration"
        assert abs(pace - 120.0) < 1, f"Expected pace ~120, got {pace}"
    finally:
        _delete_workout(client, workout["id"])


def test_pace_null_when_distance_missing(client, alice_id):
    """AC: average_pace_seconds_per_km is null/absent when distance_km is missing"""
    workout = _create_workout(
        client, alice_id,
        name="122 pace null test",
        workout_type="run",
        workout_date="2026-05-15",
        duration_seconds=3600,
    )
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for w in r.json()["weeks"] for e in w["entries"] if e.get("id") == workout["id"]]
        assert entries
        pace = entries[0].get("average_pace_seconds_per_km")
        assert pace is None, f"Pace should be null when distance_km is absent, got {pace}"
    finally:
        _delete_workout(client, workout["id"])


def test_pace_null_for_non_run_bike_type(client, alice_id):
    """AC: average_pace_seconds_per_km is null for non-run/bike workout types"""
    workout = _create_workout(
        client, alice_id,
        name="122 pace strength test",
        workout_type="strength",
        workout_date="2026-05-15",
        duration_seconds=3600,
        distance_km=5.0,
    )
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
        })
        assert r.status_code == 200
        entries = [e for w in r.json()["weeks"] for e in w["entries"] if e.get("id") == workout["id"]]
        assert entries
        pace = entries[0].get("average_pace_seconds_per_km")
        assert pace is None, f"Pace should be null for strength type, got {pace}"
    finally:
        _delete_workout(client, workout["id"])


# ── AC: Summary aggregation from real columns ─────────────────────────────────

def test_summary_total_distance_km_aggregates_real_values(client, alice_id):
    """AC: summary.total_distance_km sums non-null distance_km values"""
    w1 = _create_workout(client, alice_id, name="122 dist1", workout_date="2026-05-14", distance_km=5.0)
    w2 = _create_workout(client, alice_id, name="122 dist2", workout_date="2026-05-15", distance_km=10.0)
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-12",
            "to": "2026-05-18",
        })
        assert r.status_code == 200
        weeks = r.json()["weeks"]
        week = next((w for w in weeks if w["week_start"] == "2026-05-11"), None)
        assert week is not None, "Expected week starting 2026-05-11"
        total = week["summary"]["total_distance_km"]
        assert total >= 15.0, f"Expected total_distance_km >= 15.0, got {total}"
    finally:
        _delete_workout(client, w1["id"])
        _delete_workout(client, w2["id"])


def test_summary_total_time_minutes_aggregates_real_values(client, alice_id):
    """AC: summary.total_time_minutes sums non-null duration_seconds values"""
    w1 = _create_workout(client, alice_id, name="122 dur1", workout_date="2026-05-14", duration_seconds=3600)
    w2 = _create_workout(client, alice_id, name="122 dur2", workout_date="2026-05-15", duration_seconds=1800)
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-12",
            "to": "2026-05-18",
        })
        assert r.status_code == 200
        weeks = r.json()["weeks"]
        week = next((w for w in weeks if w["week_start"] == "2026-05-11"), None)
        assert week is not None, "Expected week starting 2026-05-11"
        total_min = week["summary"]["total_time_minutes"]
        assert total_min >= 90.0, f"Expected total_time_minutes >= 90.0, got {total_min}"
    finally:
        _delete_workout(client, w1["id"])
        _delete_workout(client, w2["id"])


# ── AC: Query param filtering ─────────────────────────────────────────────────

def test_types_filter_returns_only_matching_type(client, alice_id):
    """AC: types=run filters entries to runs only"""
    r = client.get("/api/training-log", params={
        "user_id": alice_id,
        "from": "2026-05-01",
        "to": "2026-05-31",
        "types": "run",
    })
    assert r.status_code == 200
    for week in r.json()["weeks"]:
        for entry in week["entries"]:
            assert entry["type"].lower() == "run", (
                f"Expected only run entries, got type={entry['type']!r}"
            )


def test_search_param_filters_by_name(client, alice_id):
    """AC: search=tempo filters entries by workout name (case-insensitive)"""
    workout = _create_workout(
        client, alice_id,
        name="Tempo Intervals",
        workout_type="run",
        workout_date="2026-05-15",
    )
    try:
        r = client.get("/api/training-log", params={
            "user_id": alice_id,
            "from": "2026-05-15",
            "to": "2026-05-15",
            "search": "tempo",
        })
        assert r.status_code == 200
        entries = [e for w in r.json()["weeks"] for e in w["entries"]]
        titles = [e.get("title", "").lower() for e in entries]
        assert any("tempo" in t for t in titles), (
            f"Expected a 'tempo' entry in results, got: {titles}"
        )
    finally:
        _delete_workout(client, workout["id"])


# ── AC: UAT step 7 – old path must 404 ───────────────────────────────────────

def test_uat_step_7_old_path_404(client):
    """UAT Step 7: GET /training_log (old path, no /api/) returns 404"""
    r = client.get("/training_log")
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"
