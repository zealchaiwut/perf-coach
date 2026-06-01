"""Tests for issue #106: Fix and standardize GET /training_log to /api/training-log"""
import os
import pytest
import httpx
from datetime import date as _date, timedelta


# UAT environment — resolved from .env at runtime by the tester skill Step 0.
UAT_BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")

# Alice's user_id for testing (from task description)
ALICE_USER_ID = "2898f7d7-e2f9-4125-871d-cc4fd5cb40ff"


@pytest.fixture
def client():
    """HTTP client pointed at UAT server."""
    with httpx.Client(base_url=UAT_BASE_URL, timeout=10.0) as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# Acceptance Criteria Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_api_training_log_responds_200(client):
    """AC1: GET /api/training-log responds with 200 OK"""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"


def test_old_training_log_route_returns_404(client):
    """AC1b: Old route GET /training_log returns 404 (removed)"""
    r = client.get("/training_log")
    assert r.status_code == 404, \
        f"Expected old route to return 404, got {r.status_code}"


def test_response_shape_has_required_fields(client):
    """AC2: Response shape preserved with weeks array and entry fields"""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()

    assert "weeks" in data
    assert isinstance(data["weeks"], list)

    if data["weeks"]:
        for week in data["weeks"]:
            assert "week_start" in week
            assert "week_end" in week
            assert "label" in week
            assert "summary" in week
            assert "entries" in week


def test_summary_total_distance_computed_from_real_db(client):
    """AC3: summary.total_distance_km computed from real DB distance values"""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()

    if data["weeks"]:
        for week in data["weeks"]:
            summary = week["summary"]
            assert "total_distance_km" in summary
            assert isinstance(summary["total_distance_km"], (int, float))


def test_summary_total_time_minutes_computed_from_real_db(client):
    """AC3: summary.total_time_minutes computed from real DB duration values"""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()

    if data["weeks"]:
        for week in data["weeks"]:
            summary = week["summary"]
            assert "total_time_minutes" in summary
            assert isinstance(summary["total_time_minutes"], (int, float))


def test_entry_distance_duration_avg_hr_reflect_db_values(client):
    """AC4: Entry fields (distance_km, duration_minutes, avg_hr) reflect DB values"""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()

    for week in data["weeks"]:
        for entry in week["entries"]:
            if entry.get("type") != "rest":
                assert "distance_km" in entry
                assert "duration_minutes" in entry
                assert "avg_hr" in entry


def test_user_id_query_param_filters_by_user(client):
    """AC5: Query param user_id filters results to the specified user"""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()
    assert "weeks" in data


def test_from_to_date_range_bounds_returned_weeks(client):
    """AC6: Query params from/to correctly bound the returned weeks"""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": "2026-05-13",
        "to": "2026-05-19",
    })
    assert r.status_code == 200
    data = r.json()

    for week in data["weeks"]:
        for entry in week["entries"]:
            entry_date = _date.fromisoformat(entry["date"])
            assert entry_date >= _date(2026, 5, 13)
            assert entry_date <= _date(2026, 5, 19)


def test_types_query_param_filters_entries(client):
    """AC7: Query param types filters entries by workout type"""
    r = client.get("/api/training-log", params={
        "types": "run",
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()
    assert "weeks" in data


def test_search_query_param_filters_entries(client):
    """AC8: Query param search performs text search across entry fields"""
    r = client.get("/api/training-log", params={
        "search": "tempo",
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()
    assert "weeks" in data


def test_include_rest_false_excludes_rest_entries(client):
    """AC9: Query param include_rest=false removes rest-day entries"""
    r = client.get("/api/training-log", params={
        "include_rest": "false",
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()

    for week in data["weeks"]:
        for entry in week["entries"]:
            assert entry.get("type") != "rest"


def test_from_to_date_range_returns_weeks_array(client):
    """AC10: GET /api/training-log?from=2026-05-01&to=2026-05-31 returns weeks array"""
    r = client.get("/api/training-log", params={
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()

    assert "weeks" in data
    assert isinstance(data["weeks"], list)


def test_workout_real_metrics_appear_in_entry_and_summary(client):
    """AC11: Workout entry and week summary contain real metric values"""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()

    for week in data["weeks"]:
        assert "total_distance_km" in week["summary"]
        assert "total_time_minutes" in week["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# UAT Test Steps
# ─────────────────────────────────────────────────────────────────────────────

def test_uat_step_1_api_training_log_200_ok(client):
    """UAT Step 1: GET /api/training-log returns 200 OK with weeks array"""
    r = client.get("/api/training-log", params={
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()
    assert "weeks" in data


def test_uat_step_2_old_route_404(client):
    """UAT Step 2: GET /training_log (old path) returns 404"""
    r = client.get("/training_log")
    assert r.status_code == 404


def test_uat_step_4_types_param(client):
    """UAT Step 4: types param filters by workout type"""
    r = client.get("/api/training-log", params={
        "types": "run",
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200


def test_uat_step_5_search_param(client):
    """UAT Step 5: search param performs text search"""
    r = client.get("/api/training-log", params={
        "search": "tempo",
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200


def test_uat_step_6_include_rest_false(client):
    """UAT Step 6: include_rest=false excludes rest entries"""
    r = client.get("/api/training-log", params={
        "include_rest": "false",
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200
    data = r.json()

    for week in data["weeks"]:
        for entry in week["entries"]:
            assert entry.get("type") != "rest"


def test_uat_step_7_user_id_param(client):
    """UAT Step 7: user_id param filters by user"""
    r = client.get("/api/training-log", params={
        "user_id": ALICE_USER_ID,
        "from": "2026-05-01",
        "to": "2026-05-31",
    })
    assert r.status_code == 200


def test_error_invalid_user_id_format(client):
    """Error handling: invalid user_id returns 400"""
    r = client.get("/api/training-log", params={
        "user_id": "not-a-uuid",
    })
    assert r.status_code == 400


def test_error_invalid_date_format(client):
    """Error handling: invalid date format returns 400"""
    r = client.get("/api/training-log", params={
        "from": "05-01-2026",
    })
    assert r.status_code == 400
