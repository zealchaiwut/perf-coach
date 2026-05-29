"""
Tests for issue #130: Add Training Log workout detail side panel.

Verifies:
- GET /api/workouts/{id} returns all fields the panel needs
- training-log.js defines required helper functions
- training-log.html has correct panel structure (380px desktop, 100% mobile,
  date element, source pill, stat grid, exercises section, notes section)
- Focus management: activeTriggerEl tracked and restored on close
- Stat grid always renders 6 fixed cells (null → em-dash handled in JS)
- Exercises section rendered only when exercises array is non-empty
- Notes section rendered only when remarks is non-empty
"""
import os
from datetime import date

import httpx
import pytest


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


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def run_workout_full(client):
    """Run with all optional fields to verify full stat grid population."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Morning 10K Run #130",
        "workout_date": "2026-05-27",
        "workout_type": "run",
        "distance_km": 10.0,
        "duration_seconds": 3600,
        "avg_hr": 148,
        "elevation_m": 120,
        "tss": 65.0,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create failed: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def bike_workout(client):
    """Bike workout to test km/h speed display instead of min/km pace."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Afternoon Ride #130",
        "workout_date": "2026-05-26",
        "workout_type": "bike",
        "distance_km": 40.0,
        "duration_seconds": 5400,
        "avg_hr": 135,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create failed: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def lift_with_exercises(client):
    """Strength workout with exercises and remarks to test both optional sections."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Push Day #130",
        "workout_date": "2026-05-25",
        "workout_type": "lift",
        "remarks": "Felt strong today",
        "exercises": [
            {"name": "Bench Press", "sets": 4, "reps": 8, "weight_kg": 80.0, "rpe": 8, "display_order": 1},
            {"name": "Overhead Press", "sets": 3, "reps": 10, "weight_kg": 50.0, "rpe": 7, "display_order": 2},
            {"name": "Tricep Dips", "sets": 3, "reps": 12, "display_order": 3},
        ],
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create failed: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def run_no_optional_fields(client):
    """Run with only required fields — all stat cells should show em-dash except workout type."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Bare Run #130",
        "workout_date": "2026-05-24",
        "workout_type": "run",
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create failed: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def lift_no_exercises_no_remarks(client):
    """Strength workout with empty exercises and no remarks — both sections must be hidden."""
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Empty Lift #130",
        "workout_date": "2026-05-23",
        "workout_type": "lift",
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create failed: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


# ── AC: GET /api/workouts/{id} returns all required fields ────────────────────

def test_workout_detail_returns_name(client, run_workout_full):
    res = client.get(f"/api/workouts/{run_workout_full}")
    assert res.status_code == 200
    assert res.json()["name"] == "Morning 10K Run #130"


def test_workout_detail_returns_workout_date(client, run_workout_full):
    res = client.get(f"/api/workouts/{run_workout_full}")
    assert res.status_code == 200
    assert res.json()["workout_date"] == "2026-05-27"


def test_workout_detail_returns_source_field(client, run_workout_full):
    """source field must be present in the API response (key exists even if null for manual creates)."""
    res = client.get(f"/api/workouts/{run_workout_full}")
    assert res.status_code == 200
    data = res.json()
    assert "source" in data, \
        "GET /api/workouts/{id} must include 'source' key for the source pill to render"


def test_workout_detail_null_source_for_api_created_workout(client, bike_workout):
    """Workouts created via API (not Strava import) must return null source."""
    res = client.get(f"/api/workouts/{bike_workout}")
    assert res.status_code == 200
    data = res.json()
    assert "source" in data, "source key must be present in workout detail response"
    assert data["source"] is None, \
        "Workouts created via POST /api/workouts (no Strava integration) must have null source"


def test_workout_detail_returns_distance_km(client, run_workout_full):
    res = client.get(f"/api/workouts/{run_workout_full}")
    assert res.status_code == 200
    assert res.json()["distance_km"] == 10.0


def test_workout_detail_returns_duration_seconds(client, run_workout_full):
    res = client.get(f"/api/workouts/{run_workout_full}")
    assert res.status_code == 200
    assert res.json()["duration_seconds"] == 3600


def test_workout_detail_returns_avg_hr(client, run_workout_full):
    res = client.get(f"/api/workouts/{run_workout_full}")
    assert res.status_code == 200
    assert res.json()["avg_hr"] == 148


def test_workout_detail_returns_elevation_m(client, run_workout_full):
    res = client.get(f"/api/workouts/{run_workout_full}")
    assert res.status_code == 200
    assert res.json()["elevation_m"] == 120


def test_workout_detail_returns_tss(client, run_workout_full):
    res = client.get(f"/api/workouts/{run_workout_full}")
    assert res.status_code == 200
    assert res.json()["tss"] == 65.0


def test_workout_detail_null_fields_for_bare_run(client, run_no_optional_fields):
    """When optional fields not set, API must return null (not absent keys)."""
    res = client.get(f"/api/workouts/{run_no_optional_fields}")
    assert res.status_code == 200
    data = res.json()
    assert data.get("distance_km") is None
    assert data.get("duration_seconds") is None
    assert data.get("avg_hr") is None
    assert data.get("elevation_m") is None
    assert data.get("tss") is None
    assert data.get("source") is None


# ── AC: exercises array returned in display_order ─────────────────────────────

def test_exercises_returned_in_display_order(client, lift_with_exercises):
    res = client.get(f"/api/workouts/{lift_with_exercises}")
    assert res.status_code == 200
    exercises = res.json()["exercises"]
    assert len(exercises) == 3
    orders = [e["display_order"] for e in exercises]
    assert orders == sorted(orders), "exercises must be sorted by display_order"


def test_exercise_fields_present(client, lift_with_exercises):
    """Each exercise must include name, sets, reps, weight_kg, rpe, display_order."""
    res = client.get(f"/api/workouts/{lift_with_exercises}")
    assert res.status_code == 200
    ex = res.json()["exercises"][0]
    assert ex["name"] == "Bench Press"
    assert ex["sets"] == 4
    assert ex["reps"] == 8
    assert ex["weight_kg"] == 80.0
    assert ex["rpe"] == 8


def test_exercise_without_weight_rpe_returns_null(client, lift_with_exercises):
    """Exercise without weight_kg and rpe must return null for those fields."""
    res = client.get(f"/api/workouts/{lift_with_exercises}")
    assert res.status_code == 200
    tricep = next(e for e in res.json()["exercises"] if e["name"] == "Tricep Dips")
    assert tricep["weight_kg"] is None
    assert tricep["rpe"] is None


def test_workout_without_exercises_returns_empty_array(client, lift_no_exercises_no_remarks):
    """Workout with no exercises must return an empty exercises array, not null."""
    res = client.get(f"/api/workouts/{lift_no_exercises_no_remarks}")
    assert res.status_code == 200
    assert res.json()["exercises"] == []


# ── AC: remarks field ─────────────────────────────────────────────────────────

def test_workout_detail_returns_remarks(client, lift_with_exercises):
    res = client.get(f"/api/workouts/{lift_with_exercises}")
    assert res.status_code == 200
    assert res.json()["remarks"] == "Felt strong today"


def test_workout_without_remarks_returns_null(client, lift_no_exercises_no_remarks):
    res = client.get(f"/api/workouts/{lift_no_exercises_no_remarks}")
    assert res.status_code == 200
    assert res.json()["remarks"] is None


# ── AC: HTML structure ────────────────────────────────────────────────────────

def test_log_page_detail_panel_width_380px(client):
    """Desktop detail panel must be 380px wide (AC: approximately 380px)."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "width: 380px" in res.text, \
        "detail-panel CSS must set width: 380px for desktop"


def test_log_page_mobile_breakpoint_767px(client):
    """Mobile full-screen breakpoint must be at ≤767px (AC: <768px)."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "max-width: 767px" in res.text, \
        "detail-panel must switch to full-width at 767px media query"


def test_log_page_has_detail_panel_date_element(client):
    """HTML must include the detail-panel-date element for date display."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-panel-date"' in res.text, \
        "training-log.html must have #detail-panel-date element for formatted date"


def test_log_page_has_source_pill_element(client):
    """HTML must include the detail-panel-source-pill element for Strava/Manual pill."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-panel-source-pill"' in res.text, \
        "training-log.html must have #detail-panel-source-pill element"


def test_log_page_source_pill_strava_style(client):
    """HTML must define CSS for Strava source pill (orange badge)."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "detail-source-pill--strava" in res.text, \
        "training-log.html must define .detail-source-pill--strava CSS class"


def test_log_page_source_pill_manual_style(client):
    """HTML must define CSS for Manual source pill."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "detail-source-pill--manual" in res.text or "detail-source-pill" in res.text, \
        "training-log.html must define styles for both Strava and Manual source pills"


def test_log_page_detail_header_meta_element(client):
    """HTML must include the detail-header-meta wrapper for date and source pill."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "detail-header-meta" in res.text, \
        "training-log.html must have .detail-header-meta wrapper element"


def test_log_page_exercises_section_css(client):
    """HTML must define CSS for exercises-section and exercise-item."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "exercises-section" in res.text, \
        "training-log.html must include CSS for .exercises-section"
    assert "exercise-item" in res.text, \
        "training-log.html must include CSS for .exercise-item"


def test_log_page_exercise_name_and_meta_classes(client):
    """HTML must define .exercise-name and .exercise-meta CSS classes."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "exercise-name" in res.text, \
        "training-log.html must define .exercise-name CSS class"
    assert "exercise-meta" in res.text, \
        "training-log.html must define .exercise-meta CSS class"


# ── AC: JS helper functions ───────────────────────────────────────────────────

def test_js_has_fmtDate_function(client):
    """training-log.js must define fmtDate to format 'Tue, May 28'."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "fmtDate" in res.text, \
        "training-log.js must define fmtDate for panel header date formatting"


def test_js_fmtDate_uses_day_abbr(client):
    """fmtDate must use DAY_ABBR array to produce abbreviated day names."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "DAY_ABBR" in res.text, \
        "training-log.js must use DAY_ABBR array in fmtDate for day-of-week abbreviation"


def test_js_has_fmtDurationDetail(client):
    """training-log.js must define fmtDurationDetail for h:mm:ss / m:ss format."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "fmtDurationDetail" in res.text, \
        "training-log.js must define fmtDurationDetail for detail panel duration display"


def test_js_fmtDurationDetail_returns_em_dash_for_null(client):
    """fmtDurationDetail must return em-dash for null input."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    # The function must guard null and return '—'
    assert "fmtDurationDetail" in src
    # Confirm em-dash is used as the null sentinel in the stats array
    assert "—" in src or "'\\u2014'" in src or "'—'" in src or '"—"' in src, \
        "training-log.js must use em-dash (—) as the null-stat sentinel"


def test_js_stat_grid_is_fixed_six_cells(client):
    """Stat grid must always render exactly 6 cells (2×3 layout)."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    # The fixed stats array must contain exactly 6 label entries
    stat_labels = ["Distance", "Duration", "Avg Pace", "Avg HR", "Elevation", "TSS"]
    for label in stat_labels:
        assert f"'{label}'" in src or f'"{label}"' in src, \
            f"training-log.js stat grid must include '{label}' cell"


def test_js_exercises_section_only_when_non_empty(client):
    """JS must guard exercises section behind a length check."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    assert "exercises.length" in src, \
        "training-log.js must check exercises.length before rendering exercises section"


def test_js_notes_section_only_when_remarks_non_empty(client):
    """JS must guard notes section behind a truthy check on workout.remarks."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    assert "workout.remarks" in src, \
        "training-log.js must guard notes section with workout.remarks check"


def test_js_exercises_rendered_with_display_order(client):
    """JS must iterate exercises in the display_order they arrive from the API."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    assert "exercises-section" in src and "exercise-item" in src, \
        "training-log.js must render .exercises-section and .exercise-item elements"


def test_js_exercise_shows_sets_reps_weight_rpe(client):
    """JS must format exercise row with sets × reps, weight, and RPE."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    assert "ex.sets" in src and "ex.reps" in src, \
        "training-log.js must use ex.sets and ex.reps for exercise display"
    assert "ex.weight_kg" in src, \
        "training-log.js must include ex.weight_kg in exercise display"
    assert "ex.rpe" in src, \
        "training-log.js must include ex.rpe in exercise display"


# ── AC: Focus management ──────────────────────────────────────────────────────

def test_js_tracks_active_trigger_element(client):
    """JS must track activeTriggerEl to restore focus on panel close."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "activeTriggerEl" in res.text, \
        "training-log.js must track activeTriggerEl for focus-return on panel close"


def test_js_restores_focus_on_close(client):
    """closeDetailPanel must call trigger.focus() to return keyboard focus."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "trigger.focus()" in res.text, \
        "training-log.js closeDetailPanel must call trigger.focus() to restore keyboard focus"


def test_js_rows_have_tabindex(client):
    """Workout rows must have tabindex='0' so they can receive keyboard focus."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "tabindex" in res.text, \
        "training-log.js must set tabindex on workout rows for keyboard focus management"


def test_js_rows_keyboard_open_panel(client):
    """Pressing Enter or Space on a workout row must open the detail panel."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    assert "keydown" in src, \
        "training-log.js must listen for keydown on workout rows"
    assert "'Enter'" in src or '"Enter"' in src, \
        "training-log.js must open panel when Enter is pressed on a row"


# ── AC: Source pill rendering logic ──────────────────────────────────────────

def test_js_source_pill_maps_strava(client):
    """JS must map source === 'strava' to 'Strava' label."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "'strava'" in res.text or '"strava"' in res.text, \
        "training-log.js must check workout.source === 'strava'"
    assert "'Strava'" in res.text or '"Strava"' in res.text, \
        "training-log.js must display 'Strava' label for strava source"


def test_js_source_pill_maps_manual(client):
    """JS must map non-strava source to 'Manual' label."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "'Manual'" in res.text or '"Manual"' in res.text, \
        "training-log.js must display 'Manual' label for non-strava source"


def test_js_source_pill_hidden_initially(client):
    """detail-panel-source-pill must be hidden on reset before each panel fetch."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    assert "sourcePillEl" in src and "hidden" in src, \
        "training-log.js must reset sourcePillEl.hidden = true before each fetch"
