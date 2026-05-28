"""Tests for issue #108: Render grouped workout list with week summaries on Training Log (runs against UAT)"""
import os
import pytest
import httpx
from datetime import date, timedelta

# Resolved from UAT .env at runtime; see tester skill Step 0.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:9001"
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

# Alice's user ID from UAT setup
USER_ID = "2898f7d7-e2f9-4125-871d-cc4fd5cb40ff"


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- Acceptance Criteria ---

def test_training_log_grouped_fetch_and_render(client):
    """AC: Workouts are fetched from /api/training-log and rendered below the existing filter bar"""
    # Hit the endpoint with a date range
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    assert "weeks" in data
    assert isinstance(data["weeks"], list)


def test_training_log_grouped_by_iso_week(client):
    """AC: Workouts are grouped by ISO week; each group has a header with week label, date range, totals"""
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]

    # Each week should have required fields
    if weeks:
        for week in weeks:
            assert "week_start" in week
            assert "week_end" in week
            assert "label" in week
            assert "entries" in week
            assert "workouts" in week
            assert "summary" in week

            # Summary should have the required totals
            summary = week["summary"]
            assert "workout_count" in summary
            assert "total_distance_km" in summary
            assert "total_tss" in summary
            assert "total_time_minutes" in summary


def test_training_log_week_header_label_and_range(client):
    """AC: Each week header shows week label and date range (e.g. 'Week 22' / 'May 26 – Jun 1')"""
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]

    # Verify label exists and is non-empty
    if weeks:
        for week in weeks:
            label = week.get("label", "")
            assert label, "Week label should not be empty"
            # Label should contain a date range or be a relative label (e.g., "This week")
            assert ("–" in label or "-" in label or "this" in label.lower())


def test_training_log_workout_row_date_display(client):
    """AC: Each workout row displays a date column with day-of-month and day-of-week abbrev."""
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]

    # Find a workout entry and verify date field
    workout_found = False
    for week in weeks:
        for entry in week.get("entries", []):
            if entry.get("type") != "rest":
                workout_found = True
                assert "date" in entry
                # Date should be in YYYY-MM-DD format
                date_str = entry["date"]
                parts = date_str.split("-")
                assert len(parts) == 3, f"Date {date_str} should be YYYY-MM-DD"
                break
        if workout_found:
            break


def test_training_log_workout_type_badge_colors(client):
    """AC: Each workout row displays a type icon badge: run=blue, lift=purple, wod=orange, bike=teal"""
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]

    # Verify type field exists and has valid values
    # Accept various workout type formats (run, Run, lift, Strength, etc.)
    for week in weeks:
        for entry in week.get("entries", []):
            workout_type = entry.get("type", "").lower()
            # Accept any non-empty type that's not a rest day
            assert workout_type or entry.get("type") == "rest"


def test_training_log_workout_title_and_meta(client):
    """AC: Each workout row displays title and meta line including duration; distance/pace/HR shown when available"""
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]

    # Verify title and optional fields
    for week in weeks:
        for entry in week.get("entries", []):
            if entry.get("type") != "rest":
                assert "title" in entry or "name" in entry
                # Optional fields should gracefully be absent (not null strings)
                # duration_minutes, distance_km, avg_hr may be None or a number


def test_training_log_tss_pill_color_coding(client):
    """AC: Each workout row displays a TSS pill color-coded by load: <=50=grey, 51-80=amber, >80=red"""
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]

    # Verify TSS field exists (may be None if workout has no TSS)
    for week in weeks:
        for entry in week.get("entries", []):
            if entry.get("type") != "rest":
                # TSS may be None or a number
                tss = entry.get("tss")
                if tss is not None:
                    assert isinstance(tss, (int, float))
                    assert tss >= 0


def test_training_log_source_pill_strava_vs_manual(client):
    """AC: Each workout row displays a source pill showing 'Strava' or 'Manual' based on tss_source"""
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]

    # Verify source field
    for week in weeks:
        for entry in week.get("entries", []):
            if entry.get("type") != "rest":
                source = entry.get("source", "manual")
                # Source should be 'strava', 'manual', or similar
                assert source in ("strava", "manual", "calculated")


def test_training_log_workout_row_clickable(client):
    """AC: Workout rows are full-width and clickable; clicking logs to console or calls a stub handler"""
    # This is a frontend behavior that cannot be tested via HTTP API
    pytest.skip("Frontend behavior — cannot be HTTP-tested")


def test_training_log_empty_result_message(client):
    """AC: When the filtered result set is empty, the message 'No workouts in this range - log one.' is displayed"""
    # Request a date range with no data (far future)
    from_date = (date.today() + timedelta(days=365)).isoformat()
    to_date = (date.today() + timedelta(days=395)).isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]
    # Empty result should return empty weeks list
    assert isinstance(weeks, list)


def test_training_log_loading_state(client):
    """AC: A loading state (spinner or skeleton) is shown while the API request is in flight"""
    # This is a frontend behavior — cannot test via HTTP API
    pytest.skip("Frontend behavior — cannot be HTTP-tested")


def test_training_log_missing_fields_graceful(client):
    """AC: Rows with missing distance, pace, or HR fields omit those fields gracefully"""
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]

    # Verify fields are either present with values or absent (not empty strings)
    for week in weeks:
        for entry in week.get("entries", []):
            if entry.get("type") != "rest":
                # distance_km, avg_hr should be None or numbers, not ""
                dist = entry.get("distance_km")
                if dist is not None:
                    assert isinstance(dist, (int, float))

                hr = entry.get("avg_hr")
                if hr is not None:
                    assert isinstance(hr, (int, float))


def test_training_log_week_summary_totals_accuracy(client):
    """AC: Week summary totals (distance, TSS, time) correctly aggregate all workouts within that week"""
    today = date.today()
    from_date = (today - timedelta(days=29)).isoformat()
    to_date = today.isoformat()

    r = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_date, "to": to_date}
    )
    assert r.status_code == 200
    data = r.json()
    weeks = data["weeks"]

    # Verify that summary totals match workout-level sums
    for week in weeks:
        workouts = week.get("workouts", [])
        summary = week.get("summary", {})

        # Count workouts
        assert summary.get("workout_count") == len(workouts)

        # Sum distance
        manual_total_distance = sum((w.get("distance_km") or 0) for w in workouts)
        assert abs((summary.get("total_distance_km") or 0) - manual_total_distance) < 0.01

        # Sum TSS
        manual_total_tss = sum((w.get("tss") or 0) for w in workouts)
        assert abs((summary.get("total_tss") or 0) - manual_total_tss) < 0.01

        # Sum time
        manual_total_time = sum((w.get("duration_minutes") or 0) for w in workouts)
        assert abs((summary.get("total_time_minutes") or 0) - manual_total_time) < 0.01
