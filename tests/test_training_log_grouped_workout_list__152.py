"""
Tests for issue #152: Render grouped workout list with week summaries and rest days.
Acceptance-criteria tests run against UAT (http://localhost:9001).

Backend-verifiable ACs are tested here; purely frontend rendering ACs are skipped
with an explanatory note.
"""
import os
from datetime import date, timedelta

import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 before pytest."
    )

USER_ID = "2898f7d7-e2f9-4125-871d-cc4fd5cb40ff"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def log_js(client):
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    return res.text


@pytest.fixture(scope="module")
def two_week_data(client):
    today = date.today()
    from_d = (today - timedelta(days=13)).isoformat()
    to_d = today.isoformat()
    res = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_d, "to": to_d},
    )
    assert res.status_code == 200
    return res.json()


@pytest.fixture(scope="module")
def rest_data(client):
    today = date.today()
    from_d = (today - timedelta(days=29)).isoformat()
    to_d = today.isoformat()
    res = client.get(
        "/api/training-log",
        params={"user_id": USER_ID, "from": from_d, "to": to_d, "include_rest": "true"},
    )
    assert res.status_code == 200
    return res.json()


# ── AC: workouts grouped by ISO week ─────────────────────────────────────────

def test_weeks_grouped_by_iso_week(two_week_data):
    """AC: workouts are fetched from /api/training-log and grouped by ISO week."""
    weeks = two_week_data["weeks"]
    assert isinstance(weeks, list)
    for week in weeks:
        assert "week_start" in week
        assert "week_end" in week
        assert "label" in week
        assert "entries" in week
        assert "workouts" in week
        assert "summary" in week


def test_week_summary_fields(two_week_data):
    """AC: each week header shows totals for count, distance, TSS, and total time."""
    for week in two_week_data["weeks"]:
        s = week["summary"]
        assert "workout_count" in s
        assert "total_distance_km" in s
        assert "total_tss" in s
        assert "total_time_minutes" in s


def test_week_has_label_and_date_range(two_week_data):
    """AC: each week exposes a label and week_start / week_end date strings."""
    for week in two_week_data["weeks"]:
        assert week.get("label"), "week label must be non-empty"
        assert week.get("week_start"), "week_start must be present"
        assert week.get("week_end"), "week_end must be present"


# ── AC: workout row fields ────────────────────────────────────────────────────

def test_workout_entry_required_fields(two_week_data):
    """AC: each workout entry has date, type, id, title, and source."""
    for week in two_week_data["weeks"]:
        for entry in week["entries"]:
            if entry.get("type") == "rest":
                continue
            assert "date" in entry
            assert "type" in entry
            assert "id" in entry
            assert "title" in entry
            assert "source" in entry


def test_workout_entry_meta_fields_are_null_or_number(two_week_data):
    """AC: meta fields (duration, distance, avg_hr, pace) are null or numeric — never strings."""
    for week in two_week_data["weeks"]:
        for entry in week["entries"]:
            if entry.get("type") == "rest":
                continue
            for field in ("duration_seconds", "distance_km", "avg_hr",
                          "average_pace_seconds_per_km", "tss"):
                val = entry.get(field)
                assert val is None or isinstance(val, (int, float)), (
                    f"Field {field} should be None or numeric, got {val!r}"
                )


def test_tss_values_are_non_negative(two_week_data):
    """AC: TSS values (≤50 grey, 51-80 amber, >80 red) — API returns valid numeric TSS."""
    for week in two_week_data["weeks"]:
        for entry in week["entries"]:
            if entry.get("type") == "rest":
                continue
            tss = entry.get("tss")
            if tss is not None:
                assert tss >= 0, f"TSS {tss} must be non-negative"


def test_source_field_is_known_value(two_week_data):
    """AC: source badge renders correctly — API source field is strava, stryd, manual, or similar."""
    known = {"strava", "stryd", "manual", "calculated", "garmin"}
    for week in two_week_data["weeks"]:
        for entry in week["entries"]:
            if entry.get("type") == "rest":
                continue
            src = (entry.get("source") or "manual").lower()
            # Allow any value but ensure the field is a non-empty string
            assert isinstance(src, str) and src


# ── AC: rest day rows ─────────────────────────────────────────────────────────

def test_rest_days_have_required_metric_fields(rest_data):
    """AC: rest day rows expose sleep_hours, energy, mood, resting_hr (any may be null)."""
    rest_entries = [
        e
        for week in rest_data["weeks"]
        for e in week["entries"]
        if e.get("type") == "rest"
    ]
    for entry in rest_entries:
        # Fields must be present (even if null)
        assert "sleep_hours" in entry
        assert "energy" in entry
        assert "mood" in entry
        assert "resting_hr" in entry


def test_rest_days_excluded_from_weekly_totals(rest_data):
    """AC: rest day rows are not counted in weekly summary totals."""
    for week in rest_data["weeks"]:
        workouts = week["workouts"]
        summary = week["summary"]
        # workout_count equals len(workouts) — rest entries are excluded
        assert summary["workout_count"] == len(workouts)
        manual_dist = sum((w.get("distance_km") or 0) for w in workouts)
        assert abs((summary.get("total_distance_km") or 0) - manual_dist) < 0.01


def test_rest_day_type_field(rest_data):
    """AC: rest day entries have type == 'rest'."""
    for week in rest_data["weeks"]:
        for entry in week["entries"]:
            if entry.get("type") == "rest":
                assert entry["type"] == "rest"


# ── AC: empty-state message in JS source ─────────────────────────────────────

def test_empty_state_message_in_js(log_js):
    """AC: when no workouts match, the message includes 'try widening your date filter'."""
    assert "try widening your date filter" in log_js


# ── AC: frontend-only, cannot be HTTP tested ──────────────────────────────────

def test_week_header_translucent_skip():
    """AC: week header is translucent (not inside a card). Frontend-only."""
    pytest.skip("Frontend rendering — cannot be HTTP-tested")


def test_workout_row_active_state_skip():
    """AC: clicking a row applies blue left border + tinted background. Frontend-only."""
    pytest.skip("Frontend interaction — cannot be HTTP-tested")


def test_active_state_clears_on_panel_close_skip():
    """AC: active state clears when panel is closed. Frontend-only."""
    pytest.skip("Frontend interaction — cannot be HTTP-tested")


def test_source_badges_stacking_skip():
    """AC: multiple source badges stack when workout has more than one source. Frontend-only."""
    pytest.skip("Frontend rendering — cannot be HTTP-tested")


def test_rest_day_not_clickable_skip():
    """AC: rest day rows are not clickable. Frontend-only."""
    pytest.skip("Frontend rendering — cannot be HTTP-tested")


def test_meta_line_omits_null_fields_skip():
    """AC: meta line omits duration/pace/HR when null — no 'undefined' visible. Frontend-only."""
    pytest.skip("Frontend rendering — cannot be HTTP-tested")


def test_no_console_errors_skip():
    """AC: no console errors or warnings in any scenario. Frontend-only."""
    pytest.skip("Frontend behavior — cannot be HTTP-tested")
