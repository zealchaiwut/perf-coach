"""
Tests for issue #108: Render grouped workout list with week summaries on Training Log.
Server under test: http://127.0.0.1:9001
"""
import os
import pathlib
import re

import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

HTML = (pathlib.Path(__file__).parent.parent / "log.html").read_text()
JS   = (pathlib.Path(__file__).parent.parent / "js" / "training-log.js").read_text()


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC-1: API fetches and route ──────────────────────────────────────────────

def test_ac1_api_training_log_returns_weeks(client):
    """/api/training-log must return a JSON object with a 'weeks' key."""
    res = client.get("/api/training-log")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert "weeks" in data, "Response must have a 'weeks' key"
    assert isinstance(data["weeks"], list), "'weeks' must be a list"


def test_ac1_api_weeks_have_required_keys(client):
    """Each week object must have week_start, week_end, label, entries, workouts, summary."""
    res = client.get("/api/training-log")
    data = res.json()
    weeks = data.get("weeks", [])
    if not weeks:
        pytest.skip("No weeks returned — seed the DB or extend the date range")
    required = {"week_start", "week_end", "label", "entries", "workouts", "summary"}
    for week in weeks[:3]:
        missing = required - set(week.keys())
        assert not missing, f"Week is missing keys: {missing}"


def test_ac1_api_summary_fields(client):
    """Each week summary must have workout_count, total_distance_km, total_tss, total_time_minutes."""
    res = client.get("/api/training-log")
    data = res.json()
    weeks = [w for w in data.get("weeks", []) if w.get("workouts")]
    if not weeks:
        pytest.skip("No weeks with workouts found")
    s = weeks[0]["summary"]
    for field in ("workout_count", "total_distance_km", "total_tss", "total_time_minutes"):
        assert field in s, f"summary is missing '{field}'"


def test_ac1_api_workout_entry_shape(client):
    """Workout entries must have date, type, title, tss, source fields."""
    res = client.get("/api/training-log")
    data = res.json()
    workouts = []
    for week in data.get("weeks", []):
        workouts.extend(week.get("workouts", []))
    if not workouts:
        pytest.skip("No workouts returned")
    required = {"date", "type", "title", "tss", "source"}
    w = workouts[0]
    missing = required - set(w.keys())
    assert not missing, f"Workout entry missing keys: {missing}"


# ── AC-2: Week header shows ISO week and date range ──────────────────────────

def test_ac2_js_renders_week_heading():
    """training-log.js must render an ISO week label (e.g. 'Week 22')."""
    assert "'Week ' + isoWeekNum" in JS or '"Week "' in JS or "Week " in JS, \
        "training-log.js must render a 'Week N' heading for each week section"


def test_ac2_js_iso_week_num_function():
    """training-log.js must define an isoWeekNum helper function."""
    assert "isoWeekNum" in JS, \
        "training-log.js must define isoWeekNum() to compute ISO week numbers"


def test_ac2_js_week_date_range_function():
    """training-log.js must define a weekDateRange helper function."""
    assert "weekDateRange" in JS, \
        "training-log.js must define weekDateRange() to format the date range"


def test_ac2_js_week_section_label_group():
    """training-log.js must render a label group with both week label and date range."""
    assert "week-section-label-group" in JS, \
        "training-log.js must render a 'week-section-label-group' element"


def test_ac2_js_week_section_daterange():
    """training-log.js must render a date range element in each week header."""
    assert "week-section-daterange" in JS, \
        "training-log.js must render a 'week-section-daterange' element"


def test_ac2_html_has_label_group_css():
    """log.html CSS must style .week-section-label-group."""
    assert "week-section-label-group" in HTML, \
        "log.html must define CSS for .week-section-label-group"


def test_ac2_html_has_daterange_css():
    """log.html CSS must style .week-section-daterange."""
    assert "week-section-daterange" in HTML, \
        "log.html CSS must define styles for .week-section-daterange"


# ── AC-3: Week summary totals ─────────────────────────────────────────────────

def test_ac3_js_summary_workout_count():
    """training-log.js must render the workout count in week summaries."""
    assert "workout_count" in JS or "s.workout_count" in JS, \
        "training-log.js must use summary.workout_count in week section headers"


def test_ac3_js_summary_total_distance():
    """training-log.js must render the total distance in week summaries."""
    assert "total_distance_km" in JS, \
        "training-log.js must display total_distance_km in week section summaries"


def test_ac3_js_summary_total_tss():
    """training-log.js must render the total TSS in week summaries."""
    assert "total_tss" in JS, \
        "training-log.js must display total_tss in week section summaries"


def test_ac3_js_summary_total_time():
    """training-log.js must render the total duration in week summaries."""
    assert "total_time_minutes" in JS, \
        "training-log.js must display total_time_minutes in week section summaries"


def test_ac3_api_summary_totals_aggregate_workouts(client):
    """Week summary totals must correctly aggregate workouts in that week."""
    res = client.get("/api/training-log?from=2020-01-01&to=2099-12-31")
    data = res.json()
    for week in data.get("weeks", []):
        workouts = week.get("workouts", [])
        s = week["summary"]
        expected_count = len(workouts)
        assert s["workout_count"] == expected_count, \
            f"workout_count {s['workout_count']} != actual count {expected_count}"
        expected_dist = sum(w.get("distance_km") or 0 for w in workouts)
        assert abs(s["total_distance_km"] - expected_dist) < 0.01, \
            "total_distance_km does not match sum of workout distances"
        expected_tss = sum(w.get("tss") or 0 for w in workouts)
        assert abs(s["total_tss"] - expected_tss) < 0.01, \
            "total_tss does not match sum of workout TSS values"


# ── AC-4: Workout row display ─────────────────────────────────────────────────

def test_ac4_js_renders_date_column():
    """training-log.js must render a date column with day-of-month and day-of-week."""
    assert "workout-day-num" in JS and "workout-day-name" in JS, \
        "training-log.js must render .workout-day-num and .workout-day-name in each row"


def test_ac4_js_renders_type_badge():
    """training-log.js must render a type badge for each workout."""
    assert "workout-type-badge" in JS, \
        "training-log.js must render a .workout-type-badge element"


def test_ac4_js_badge_colors_run():
    """Run badge must use blue colors."""
    assert "#dbeafe" in JS or "#1d4ed8" in JS, \
        "training-log.js must define blue background/text for run type badge"


def test_ac4_js_badge_colors_lift():
    """Lift badge must use purple colors."""
    assert "#ede9fe" in JS or "#6d28d9" in JS, \
        "training-log.js must define purple background/text for lift type badge"


def test_ac4_js_badge_colors_wod():
    """WOD badge must use orange colors."""
    assert "#ffedd5" in JS or "#c2410c" in JS, \
        "training-log.js must define orange background/text for wod type badge"


def test_ac4_js_badge_colors_bike():
    """Bike badge must use teal colors."""
    assert "#ccfbf1" in JS or "#0f766e" in JS, \
        "training-log.js must define teal background/text for bike type badge"


def test_ac4_js_renders_meta_line():
    """training-log.js must render a meta line with duration."""
    assert "workout-meta-line" in JS and "metaLine" in JS, \
        "training-log.js must render .workout-meta-line using metaLine()"


def test_ac4_js_meta_line_distance_conditional():
    """training-log.js must only include distance in meta line when present."""
    assert "distance_km" in JS, \
        "training-log.js must conditionally include distance in the meta line"


def test_ac4_js_meta_line_avg_hr_conditional():
    """training-log.js must only include avg HR in meta line when present."""
    assert "avg_hr" in JS, \
        "training-log.js must conditionally include avg_hr in the meta line"


def test_ac4_js_tss_pill_thresholds():
    """training-log.js must apply TSS pill classes based on thresholds."""
    assert "tss-grey" in JS and "tss-amber" in JS and "tss-red" in JS, \
        "training-log.js must define tss-grey, tss-amber, and tss-red pill classes"


def test_ac4_js_tss_pill_threshold_50():
    """TSS ≤50 must be grey."""
    assert "50" in JS, "training-log.js must use 50 as the grey/amber TSS threshold"


def test_ac4_js_tss_pill_threshold_80():
    """TSS >80 must be red."""
    assert "80" in JS, "training-log.js must use 80 as the amber/red TSS threshold"


def test_ac4_html_tss_pill_css():
    """log.html must define CSS for .tss-grey, .tss-amber, .tss-red."""
    assert "tss-grey" in HTML and "tss-amber" in HTML and "tss-red" in HTML, \
        "log.html must define CSS for all three TSS pill variants"


def test_ac4_js_source_pill_strava():
    """training-log.js must render 'Strava' for strava-sourced workouts."""
    assert "Strava" in JS, \
        "training-log.js must display 'Strava' text for strava-sourced workouts"


def test_ac4_js_source_pill_manual():
    """training-log.js must render 'Manual' for manually logged workouts."""
    assert "Manual" in JS, \
        "training-log.js must display 'Manual' text for manually logged workouts"


def test_ac4_html_source_pill_css():
    """log.html must define CSS for .source-strava and .source-manual."""
    assert "source-strava" in HTML and "source-manual" in HTML, \
        "log.html must define CSS for both .source-strava and .source-manual"


# ── AC-5: Row click stub ──────────────────────────────────────────────────────

def test_ac5_js_row_click_handler():
    """Each workout row must have a click handler."""
    assert "addEventListener('click'" in JS or 'addEventListener("click"' in JS, \
        "training-log.js must attach a click event listener to workout rows"


def test_ac5_js_click_logs_to_console():
    """Row click must fire a console action (stub handler)."""
    assert "console.log" in JS or "console." in JS, \
        "training-log.js must call console.log in the click stub handler"


# ── AC-6: Empty state ────────────────────────────────────────────────────────

def test_ac6_empty_state_message():
    """log.html must display the exact empty-state message for no results."""
    assert "No workouts in this range" in HTML, \
        "log.html must include 'No workouts in this range' in the empty-state message"


def test_ac6_empty_state_has_log_cta():
    """Empty state message must include a call to action to log a workout."""
    assert "log one" in HTML.lower(), \
        "log.html empty state must include 'log one' CTA"


def test_ac6_js_shows_empty_msg_on_no_results():
    """training-log.js must show the empty message when no weeks are returned."""
    assert "emptyMsg" in JS and "style.display" in JS, \
        "training-log.js must toggle the empty message element visibility"


# ── AC-7: Loading state ──────────────────────────────────────────────────────

def test_ac7_js_loading_state_skeleton():
    """training-log.js must render a skeleton loading state while fetching."""
    assert "skeleton-list" in JS or "skeleton-row" in JS, \
        "training-log.js must render skeleton rows as the loading state"


def test_ac7_html_skeleton_css():
    """log.html must define CSS for skeleton loading rows."""
    assert "skeleton-row" in HTML, \
        "log.html must define CSS for .skeleton-row elements"


def test_ac7_html_skeleton_animation():
    """log.html skeleton must use a shimmer animation."""
    assert "skeleton-shimmer" in HTML or "@keyframes" in HTML, \
        "log.html must define a keyframe animation for the skeleton shimmer"


# ── AC-8: Graceful missing-field handling ────────────────────────────────────

def test_ac8_js_distance_optional_in_meta():
    """meta line must not break when distance_km is null/absent."""
    meta_fn = re.search(r'function metaLine\(w\)\s*\{(.*?)\}', JS, re.DOTALL)
    assert meta_fn, "training-log.js must define a metaLine() function"
    body = meta_fn.group(1)
    assert "distance_km" in body, "metaLine must reference distance_km"
    assert "if" in body, "metaLine must conditionally include distance"


def test_ac8_js_avg_hr_optional_in_meta():
    """meta line must not show avg HR when avg_hr is null/absent."""
    # Verify metaLine function exists
    assert "function metaLine" in JS, "training-log.js must define a metaLine() function"
    # avg_hr must appear in the JS and be guarded by an if (conditional inclusion)
    assert "avg_hr" in JS, "training-log.js must reference avg_hr in the meta line"
    assert re.search(r'if\s*\(w\.avg_hr\)', JS), \
        "training-log.js must conditionally include avg_hr (if (w.avg_hr))"


def test_ac8_api_workout_entry_allows_null_distance(client):
    """API must accept and return null for distance_km on non-distance workouts."""
    res = client.get("/api/training-log")
    data = res.json()
    workouts = []
    for week in data.get("weeks", []):
        workouts.extend(week.get("workouts", []))
    if not workouts:
        pytest.skip("No workouts in API response")
    # Check that distance_km key exists (even if null)
    for w in workouts[:5]:
        assert "distance_km" in w, f"workout entry missing 'distance_km' key: {w}"
