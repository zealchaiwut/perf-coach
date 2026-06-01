"""Tests for issue #126: Render grouped workout list with weekly summaries on Training Log"""
import os
import pytest
import httpx
from datetime import date, timedelta

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:9001"
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

USER_ID = "2898f7d7-e2f9-4125-871d-cc4fd5cb40ff"


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def _get_weeks(client, days_back=29):
    today = date.today()
    r = client.get(
        "/api/training-log",
        params={
            "user_id": USER_ID,
            "from": (today - timedelta(days=days_back)).isoformat(),
            "to": today.isoformat(),
        },
    )
    assert r.status_code == 200
    return r.json()["weeks"]


# ── API structure ──────────────────────────────────────────────────────────────

def test_weeks_have_required_fields(client):
    """AC: Each week has label, week_start, week_end, entries, workouts, summary"""
    weeks = _get_weeks(client)
    for wk in weeks:
        for field in ("label", "week_start", "week_end", "entries", "workouts", "summary"):
            assert field in wk, f"Missing '{field}' in week: {wk}"


def test_week_label_format(client):
    """AC: Week label is non-empty (e.g. 'Week 22')"""
    weeks = _get_weeks(client)
    for wk in weeks:
        label = wk.get("label", "")
        assert label, "Week label must not be empty"


def test_week_date_range_fields(client):
    """AC: week_start and week_end are valid ISO dates"""
    weeks = _get_weeks(client)
    for wk in weeks:
        try:
            s = date.fromisoformat(wk["week_start"])
            e = date.fromisoformat(wk["week_end"])
        except (ValueError, KeyError) as exc:
            pytest.fail(f"Invalid date fields: {exc}")
        assert s <= e, "week_start must be <= week_end"


def test_summary_has_all_totals(client):
    """AC: Summary contains workout_count, total_distance_km, total_tss, total_time_minutes"""
    weeks = _get_weeks(client)
    for wk in weeks:
        s = wk["summary"]
        for key in ("workout_count", "total_distance_km", "total_tss", "total_time_minutes"):
            assert key in s, f"Summary missing '{key}'"


def test_summary_totals_match_workout_rows(client):
    """AC: Summary totals equal the sum across individual workout rows in that week"""
    weeks = _get_weeks(client)
    for wk in weeks:
        workouts = wk["workouts"]
        s = wk["summary"]

        assert s["workout_count"] == len(workouts)

        calc_dist = sum((w.get("distance_km") or 0) for w in workouts)
        assert abs((s["total_distance_km"] or 0) - calc_dist) < 0.01

        calc_tss = sum((w.get("tss") or 0) for w in workouts)
        assert abs((s["total_tss"] or 0) - calc_tss) < 0.01

        calc_time = sum((w.get("duration_minutes") or 0) for w in workouts)
        assert abs((s["total_time_minutes"] or 0) - calc_time) < 0.01


# ── Entry fields ───────────────────────────────────────────────────────────────

def test_workout_entries_have_id_and_date(client):
    """AC: Each workout entry has an id and a date in YYYY-MM-DD format"""
    weeks = _get_weeks(client)
    for wk in weeks:
        for e in wk["entries"]:
            if e.get("type") == "rest":
                continue
            assert "id" in e, "Workout entry missing 'id'"
            assert "date" in e, "Workout entry missing 'date'"
            parts = e["date"].split("-")
            assert len(parts) == 3


def test_workout_entries_have_type(client):
    """AC: Each workout entry has a non-empty type field"""
    weeks = _get_weeks(client)
    for wk in weeks:
        for e in wk["entries"]:
            if e.get("type") == "rest":
                continue
            assert e.get("type"), "Workout entry 'type' must not be empty"


def test_tss_values_are_numeric_when_present(client):
    """AC: TSS is a number >= 0 when present (used for colour-coding pill)"""
    weeks = _get_weeks(client)
    for wk in weeks:
        for e in wk["entries"]:
            tss = e.get("tss")
            if tss is not None:
                assert isinstance(tss, (int, float)) and tss >= 0


def test_source_field_is_valid(client):
    """AC: source is 'strava', 'manual', or 'calculated' (drives Strava/Manual pill)"""
    weeks = _get_weeks(client)
    valid_sources = {"strava", "manual", "calculated"}
    for wk in weeks:
        for e in wk["entries"]:
            if e.get("type") == "rest":
                continue
            src = (e.get("source") or "manual").lower()
            assert src in valid_sources, f"Unexpected source value: {src!r}"


def test_numeric_fields_are_not_strings(client):
    """AC: distance_km, duration_seconds, avg_hr are numbers or None — never string 'null'"""
    weeks = _get_weeks(client)
    for wk in weeks:
        for e in wk["entries"]:
            if e.get("type") == "rest":
                continue
            for field in ("distance_km", "duration_seconds", "avg_hr", "tss"):
                val = e.get(field)
                assert not isinstance(val, str), (
                    f"Field '{field}' should be numeric or None, got string {val!r}"
                )


# ── Empty range ────────────────────────────────────────────────────────────────

def test_empty_range_returns_empty_weeks(client):
    """AC: A date range with no data returns an empty weeks list"""
    future = date.today() + timedelta(days=365)
    r = client.get(
        "/api/training-log",
        params={
            "user_id": USER_ID,
            "from": future.isoformat(),
            "to": (future + timedelta(days=30)).isoformat(),
        },
    )
    assert r.status_code == 200
    assert r.json()["weeks"] == []


# ── Pace logic ─────────────────────────────────────────────────────────────────

def test_pace_field_only_for_runs_with_distance_and_duration(client):
    """AC: average_pace_seconds_per_km is set only for run/bike with both distance and duration"""
    weeks = _get_weeks(client)
    for wk in weeks:
        for e in wk["entries"]:
            if e.get("type") == "rest":
                continue
            pace = e.get("average_pace_seconds_per_km")
            if pace is not None:
                assert e.get("type", "").lower() in ("run", "bike"), (
                    "Pace should only be set for run/bike"
                )
                assert e.get("distance_km") and e.get("duration_seconds"), (
                    "Pace requires both distance and duration"
                )


# ── Frontend-only behaviours (skipped) ────────────────────────────────────────

def test_loading_state_in_log_list():
    """AC: #log-list shows 'Loading workouts...' while fetch is in flight"""
    pytest.skip("Frontend behaviour — cannot be HTTP-tested")


def test_empty_state_message_in_log_list():
    """AC: #log-list shows 'No workouts in this range.' when empty"""
    pytest.skip("Frontend behaviour — cannot be HTTP-tested")


def test_row_click_logs_id_to_console():
    """AC: Clicking a workout row logs its id to the browser console"""
    pytest.skip("Frontend behaviour — cannot be HTTP-tested")


def test_row_stacks_at_380px():
    """AC: At 380 px viewport each workout row stacks to a single column with no overflow"""
    pytest.skip("Frontend behaviour — cannot be HTTP-tested")
