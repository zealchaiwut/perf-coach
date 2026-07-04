"""Tests for issue #541: Dedicated endpoint for volume chart weekly aggregations (runs against UAT)"""
import os
import pytest
import httpx
from datetime import date, timedelta


# Resolved from UAT .env at runtime; see tester skill Step 0.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- Acceptance Criteria ---

def test_training_load_weekly__endpoint_exists_with_date_params(client):
    # AC1: A GET /api/training-load/weekly endpoint exists and accepts from/to query parameters
    r = client.get("/api/training-load/weekly?from=2025-01-01&to=2025-03-31")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert isinstance(data, dict), "Response should be a JSON object"
    assert "weeks" in data, "Response should contain a 'weeks' key"


def test_training_load_weekly__returns_weekly_summary_without_full_workouts(client):
    # AC2: Returns weekly summary aggregates (week_start, total_distance_km, total_tss) without full workout serialization
    r = client.get("/api/training-load/weekly?from=2025-01-01&to=2025-03-31")
    assert r.status_code == 200
    data = r.json()
    weeks = data.get("weeks", [])

    # Verify each week has the expected fields
    for week in weeks:
        assert "week_start" in week, f"Week missing 'week_start': {week}"
        assert "total_distance_km" in week, f"Week missing 'total_distance_km': {week}"
        assert "total_tss" in week, f"Week missing 'total_tss': {week}"
        # Ensure no full workout detail objects (workouts field should not exist or be empty)
        assert "workouts" not in week or len(week.get("workouts", [])) == 0, \
            f"Week should not contain full workout objects: {week}"


def test_training_load_weekly__accepts_iso_date_format(client):
    # AC1 verification: endpoint accepts ISO date query params
    today = date.today()
    from_date = (today - timedelta(days=30)).isoformat()
    to_date = today.isoformat()

    r = client.get(f"/api/training-load/weekly?from={from_date}&to={to_date}")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert isinstance(data, dict)


def test_training_load_weekly__validates_date_format(client):
    # Invalid date format should return 422
    r = client.get("/api/training-load/weekly?from=invalid&to=2025-03-31")
    assert r.status_code == 422, f"Expected 422 for invalid date, got {r.status_code}"


def test_training_load_weekly__validates_date_range(client):
    # from date should not be after to date
    r = client.get("/api/training-load/weekly?from=2025-03-31&to=2025-01-01")
    assert r.status_code == 422, f"Expected 422 for invalid range, got {r.status_code}"


def test_training_load_weekly__response_structure(client):
    # AC2 verification: response structure contains only lightweight summary data
    r = client.get("/api/training-load/weekly?from=2025-01-01&to=2025-01-31")
    assert r.status_code == 200
    data = r.json()

    assert "weeks" in data
    weeks = data["weeks"]
    assert isinstance(weeks, list)

    for week in weeks:
        # Verify it's a summary, not full workout data
        assert isinstance(week["week_start"], str), "week_start should be ISO date string"
        assert isinstance(week["total_distance_km"], (int, float)), "total_distance_km should be numeric"
        assert isinstance(week["total_tss"], (int, float)), "total_tss should be numeric"
        # No full "entries" or "workouts" arrays with full serialization
        assert "entries" not in week, "Week should not contain 'entries' (full detail)"
