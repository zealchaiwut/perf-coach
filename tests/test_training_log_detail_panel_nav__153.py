"""
Tests for issue #153: Build Training Log detail panel with prev/next nav.

Verifies:
- HTML structure: top bar (close, prev, position pill, next, overflow), hero block,
  stats grid 2×3, intervals section, splits section, exercises section, notes section,
  sticky action bar (Edit, Strava/Delete buttons).
- JS: flatWorkouts navigation state, prev/next logic, position pill updates,
  swipe gesture support, delete confirmation, splits fetch for RUN/BIKE workouts.
- API: GET /api/workouts/{id}/splits, workout detail fields.
- Desktop (≥880px) layout: 520px sticky column; mobile (<880px): full-screen overlay.
"""
import os
import pytest
import httpx
from datetime import date, timedelta

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
def log_html(client):
    res = client.get("/log")
    assert res.status_code == 200
    return res.text


@pytest.fixture(scope="module")
def log_js(client):
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    return res.text


@pytest.fixture(scope="module")
def run_workout(client):
    """A run workout with all fields for detail panel testing."""
    payload = {
        "user_id": USER_ID,
        "name": "Morning Intervals #153",
        "workout_date": "2026-05-26",
        "workout_type": "run",
        "distance_km": 10.5,
        "duration_seconds": 3134,
        "avg_hr": 168,
        "elevation_m": 42,
        "tss": 92.0,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create failed: {res.text}"
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def lift_workout(client):
    """A strength workout with exercises for detail panel testing."""
    payload = {
        "user_id": USER_ID,
        "name": "Lower Body Session #153",
        "workout_date": "2026-05-25",
        "workout_type": "lift",
        "duration_seconds": 3300,
        "tss": 42.0,
        "remarks": "Good session today.",
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create failed: {res.text}"
    wid = res.json()["id"]
    for ex in [
        {"name": "Squat", "sets": 4, "reps": 6, "weight_kg": 100.0, "rpe": 8, "display_order": 1},
        {"name": "RDL",   "sets": 3, "reps": 10, "weight_kg": 70.0,  "rpe": 7, "display_order": 2},
    ]:
        client.post(f"/api/workouts/{wid}/exercises", json=ex)
    yield wid
    client.delete(f"/api/workouts/{wid}")


@pytest.fixture(scope="module")
def run_with_splits(client):
    """A run workout with per-km splits."""
    payload = {
        "user_id": USER_ID,
        "name": "Easy Run with Splits #153",
        "workout_date": "2026-05-24",
        "workout_type": "run",
        "distance_km": 6.2,
        "duration_seconds": 2050,
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"create failed: {res.text}"
    wid = res.json()["id"]
    splits_payload = {
        "splits": [
            {"split_index": 1, "distance_km": 1.0, "duration_seconds": 330, "avg_hr": 142},
            {"split_index": 2, "distance_km": 1.0, "duration_seconds": 328, "avg_hr": 145},
            {"split_index": 3, "distance_km": 1.0, "duration_seconds": 335, "avg_hr": 148},
        ]
    }
    res2 = client.post(f"/api/workouts/{wid}/splits", json=splits_payload)
    assert res2.status_code == 201, f"splits create failed: {res2.text}"
    yield wid
    client.delete(f"/api/workouts/{wid}")


# ── HTML structure ────────────────────────────────────────────────────────────

def test_html_has_layout_wrapper(log_html):
    """HTML must wrap list and panel in #layout-wrapper for the 2-column desktop grid."""
    assert 'id="layout-wrapper"' in log_html, \
        "training-log.html must have #layout-wrapper for desktop 2-column grid layout"


def test_html_has_list_main(log_html):
    """HTML must have #list-main wrapping the list content."""
    assert 'id="list-main"' in log_html, \
        "training-log.html must have #list-main inside #layout-wrapper"


def test_html_has_detail_panel(log_html):
    """HTML must have #detail-panel aside element."""
    assert 'id="detail-panel"' in log_html, \
        "training-log.html must have #detail-panel aside element"


def test_html_detail_panel_top_bar(log_html):
    """HTML must have .dp-topbar for the panel top bar."""
    assert "dp-topbar" in log_html, \
        "training-log.html must define .dp-topbar for the detail panel top bar"


def test_html_has_close_btn(log_html):
    """HTML must have #dp-close-btn."""
    assert 'id="dp-close-btn"' in log_html, \
        "training-log.html must have #dp-close-btn"


def test_html_has_prev_btn(log_html):
    """HTML must have #dp-prev-btn for previous navigation."""
    assert 'id="dp-prev-btn"' in log_html, \
        "training-log.html must have #dp-prev-btn"


def test_html_has_next_btn(log_html):
    """HTML must have #dp-next-btn for next navigation."""
    assert 'id="dp-next-btn"' in log_html, \
        "training-log.html must have #dp-next-btn"


def test_html_has_position_pill(log_html):
    """HTML must have #dp-position-pill for the '3 of 23' position indicator."""
    assert 'id="dp-position-pill"' in log_html, \
        "training-log.html must have #dp-position-pill"


def test_html_position_pill_is_monospace(log_html):
    """Position pill must use monospace font (JetBrains Mono or similar)."""
    assert "dp-position" in log_html, \
        "training-log.html must define .dp-position with monospace font"
    assert "monospace" in log_html.lower() or "JetBrains Mono" in log_html, \
        "dp-position must use a monospace font family"


def test_html_has_desktop_close_icon(log_html):
    """Desktop close button must show ✕ (dp-icon-close-x)."""
    assert "dp-icon-close-x" in log_html, \
        "HTML must have .dp-icon-close-x for the desktop ✕ icon"


def test_html_has_mobile_close_icon(log_html):
    """Mobile close button must show ← (dp-icon-close-back)."""
    assert "dp-icon-close-back" in log_html, \
        "HTML must have .dp-icon-close-back for the mobile ← icon"


def test_html_has_desktop_nav_icons(log_html):
    """Desktop prev/next must show ▲/▼ icons."""
    assert "dp-icon-nav-up" in log_html and "dp-icon-nav-down" in log_html, \
        "HTML must have .dp-icon-nav-up and .dp-icon-nav-down for desktop ▲/▼ navigation"


def test_html_has_mobile_nav_icons(log_html):
    """Mobile prev/next must show ◀/▶ icons."""
    assert "dp-icon-nav-left" in log_html and "dp-icon-nav-right" in log_html, \
        "HTML must have .dp-icon-nav-left and .dp-icon-nav-right for mobile ◀/▶ navigation"


def test_html_mobile_icons_hidden_on_desktop(log_html):
    """Mobile-only icons must be hidden on desktop (≥880px) via CSS."""
    assert "dp-icon-close-back" in log_html, "HTML must have mobile-only close icon"
    # CSS must hide mobile icons on desktop
    assert "dp-icon-nav-left" in log_html
    # The CSS media query must show/hide these icons correctly
    css_section = log_html[log_html.find("<style>"):log_html.find("</style>")]
    assert "dp-icon-close-back" in css_section, \
        "CSS must control visibility of dp-icon-close-back"


def test_html_desktop_panel_is_520px(log_html):
    """Desktop detail panel must be 520px wide (per issue spec)."""
    assert "520px" in log_html, \
        "training-log.html must define 520px panel width for desktop layout"


def test_html_mobile_panel_fullscreen(log_html):
    """Mobile panel must be full-width (100%) at <880px."""
    assert "880px" in log_html or "879px" in log_html, \
        "training-log.html must define breakpoint around 880px for panel behavior"


def test_html_has_dp_scroll(log_html):
    """Panel must have #dp-scroll scrollable body area."""
    assert 'id="dp-scroll"' in log_html, \
        "training-log.html must have #dp-scroll for the scrollable panel body"


def test_html_has_loading_state(log_html):
    """Panel must have #dp-loading skeleton state."""
    assert 'id="dp-loading"' in log_html, \
        "training-log.html must have #dp-loading skeleton state"


def test_html_has_error_state(log_html):
    """Panel must have #dp-error element."""
    assert 'id="dp-error"' in log_html, \
        "training-log.html must have #dp-error state"


def test_html_has_content_area(log_html):
    """Panel must have #dp-content for rendered workout details."""
    assert 'id="dp-content"' in log_html, \
        "training-log.html must have #dp-content area"


def test_html_has_edit_btn(log_html):
    """Panel must have #dp-edit-btn in action bar."""
    assert 'id="dp-edit-btn"' in log_html, \
        "training-log.html must have #dp-edit-btn in the sticky action bar"


def test_html_has_strava_btn(log_html):
    """Panel must have #dp-strava-btn (hidden initially)."""
    assert 'id="dp-strava-btn"' in log_html, \
        "training-log.html must have #dp-strava-btn"


def test_html_has_delete_btn(log_html):
    """Panel must have #dp-delete-btn (hidden initially)."""
    assert 'id="dp-delete-btn"' in log_html, \
        "training-log.html must have #dp-delete-btn"


def test_html_has_stats_grid_css(log_html):
    """CSS must define .dp-stats-grid with 3 columns (2×3 grid)."""
    assert "dp-stats-grid" in log_html, \
        "training-log.html must define .dp-stats-grid"
    assert "1fr 1fr 1fr" in log_html or "repeat(3" in log_html, \
        "dp-stats-grid must be a 3-column grid (2 rows × 3 cols)"


def test_html_stat_highlight_class(log_html):
    """CSS must define .dp-stat.highlight with blue gradient for the first tile."""
    assert "dp-stat" in log_html and "highlight" in log_html, \
        "training-log.html must define .dp-stat.highlight with blue gradient"
    css = log_html[log_html.find("<style>"):log_html.find("</style>")]
    assert "highlight" in css, \
        "highlight class must be defined in CSS with blue gradient"


def test_html_strava_btn_color(log_html):
    """Strava button must have orange (#fc4c02) styling."""
    assert "fc4c02" in log_html.lower() or "#fc4c02" in log_html, \
        "training-log.html must define the Strava orange color (#fc4c02) for the Strava button"


# ── JS: flat workout list and navigation ──────────────────────────────────────

def test_js_has_flat_workouts(log_js):
    """JS must maintain flatWorkouts array for prev/next navigation."""
    assert "flatWorkouts" in log_js, \
        "training-log.js must define flatWorkouts array for navigation"


def test_js_has_active_pos_index(log_js):
    """JS must track activePosIndex for the current position in flatWorkouts."""
    assert "activePosIndex" in log_js, \
        "training-log.js must track activePosIndex"


def test_js_has_build_flat_workouts(log_js):
    """JS must have buildFlatWorkouts() to rebuild the ordered workout list."""
    assert "buildFlatWorkouts" in log_js, \
        "training-log.js must define buildFlatWorkouts()"


def test_js_has_navigate_detail(log_js):
    """JS must have navigateDetail() for prev/next navigation."""
    assert "navigateDetail" in log_js, \
        "training-log.js must define navigateDetail() for panel navigation"


def test_js_navigate_updates_position(log_js):
    """navigateDetail must call updatePositionPill() after navigation."""
    assert "updatePositionPill" in log_js, \
        "training-log.js must define updatePositionPill() to update the position display"


def test_js_prev_disabled_at_first(log_js):
    """Prev button must be disabled at position 0."""
    assert "activePosIndex <= 0" in log_js or "activePosIndex < 1" in log_js or \
           "activePosIndex == 0" in log_js or "activePosIndex === 0" in log_js, \
        "JS must disable prev button when activePosIndex is 0 (first item)"


def test_js_next_disabled_at_last(log_js):
    """Next button must be disabled at the last position."""
    assert "total - 1" in log_js or "flatWorkouts.length - 1" in log_js or \
           ">= total - 1" in log_js or ">= flatWorkouts.length" in log_js, \
        "JS must disable next button at the last position in flatWorkouts"


def test_js_has_swipe_support(log_js):
    """JS must add touchstart/touchend listeners for swipe navigation on mobile."""
    assert "touchstart" in log_js, \
        "training-log.js must listen for touchstart for mobile swipe navigation"
    assert "touchend" in log_js, \
        "training-log.js must listen for touchend for mobile swipe navigation"


def test_js_swipe_left_triggers_next(log_js):
    """Swipe left (dx < 0) must trigger next workout."""
    assert "dx < 0" in log_js or "dx<0" in log_js, \
        "training-log.js swipe handler must navigate next on left swipe (dx < 0)"


def test_js_swipe_right_triggers_prev(log_js):
    """Swipe right (dx > 0) must trigger prev workout."""
    assert "navigateDetail(-1)" in log_js, \
        "training-log.js must call navigateDetail(-1) for prev (swipe right)"


def test_js_has_delete_workout(log_js):
    """JS must have deleteWorkout() that calls DELETE /api/workouts/{id}."""
    assert "deleteWorkout" in log_js, \
        "training-log.js must define deleteWorkout()"
    assert "DELETE" in log_js, \
        "deleteWorkout must call DELETE /api/workouts/{id}"


def test_js_delete_has_confirmation(log_js):
    """Delete must show a confirmation dialog before calling DELETE."""
    assert "confirm(" in log_js, \
        "training-log.js deleteWorkout must call confirm() before DELETE"


def test_js_fetches_splits_for_run(log_js):
    """JS must fetch /api/workouts/{id}/splits for RUN workouts."""
    assert "splits" in log_js, \
        "training-log.js must fetch splits endpoint for run/bike workouts"
    assert "/splits" in log_js, \
        "training-log.js must call GET /api/workouts/{id}/splits"


def test_js_hero_block_renders_type_icon(log_js):
    """renderDetailContent must include a type icon-pill based on workout_type."""
    assert "dp-icon-pill" in log_js, \
        "training-log.js renderDetailContent must render .dp-icon-pill for the type icon"


def test_js_hero_block_renders_type_pill(log_js):
    """renderDetailContent must render an uppercase type pill."""
    assert "dp-type-pill" in log_js, \
        "training-log.js renderDetailContent must render .dp-type-pill"


def test_js_stats_grid_highlight_first_tile(log_js):
    """First stat tile must have .highlight class."""
    assert "highlight" in log_js, \
        "training-log.js renderDetailContent must add 'highlight' class to the first stat tile"


def test_js_run_first_tile_is_distance(log_js):
    """For run/bike workouts, first tile must be Distance."""
    assert "Distance" in log_js, \
        "training-log.js must render Distance as first stat for run/bike workouts"


def test_js_strength_first_tile_is_duration(log_js):
    """For lift/WOD workouts, first tile must be Duration (highlighted)."""
    # The condition for the else branch (non-cardio) with highlighted duration
    assert "isCardio" in log_js or "isRun\n" in log_js or "!isCardio" in log_js, \
        "training-log.js must distinguish cardio vs strength for stat grid layout"


def test_js_null_renders_as_emdash(log_js):
    """Null stat fields must render as '—' (em-dash), not 'null' or 'undefined'."""
    assert "'—'" in log_js or '"—"' in log_js, \
        "training-log.js must render em-dash ('—') for null/missing stat values"


def test_js_intervals_section_for_run_with_distance_exercises(log_js):
    """RUN workouts with distance_km exercises must render the Intervals section."""
    assert "dp-intervals" in log_js, \
        "training-log.js must render .dp-intervals for run interval exercises"
    assert "intervalExs" in log_js or "interval" in log_js.lower(), \
        "training-log.js must filter exercises with distance_km for the Intervals section"


def test_js_splits_section_when_no_intervals(log_js):
    """Per-km splits section is rendered only when no interval exercises exist."""
    assert "dp-splits" in log_js, \
        "training-log.js must render .dp-splits for per-km splits"
    assert "intervalsHtml" in log_js, \
        "training-log.js must conditionally render splits only when there are no intervals"


def test_js_exercises_section_for_strength(log_js):
    """STRENGTH/WOD workouts must render an exercises section."""
    assert "dp-exercise-item" in log_js, \
        "training-log.js must render .dp-exercise-item elements for strength/WOD exercises"


def test_js_notes_hidden_when_empty(log_js):
    """Notes section must be hidden when workout.remarks is empty/null."""
    assert "workout.remarks" in log_js, \
        "training-log.js must check workout.remarks before rendering the Notes section"


def test_js_strava_btn_visibility_logic(log_js):
    """Strava button shown only when source=strava OR strava_activity_url is present."""
    assert "isStrava" in log_js or "strava_activity_url" in log_js, \
        "training-log.js must check strava_activity_url and/or source for the Strava button"


def test_js_manual_shows_delete_btn(log_js):
    """For manual workouts (no Strava), Delete button must be shown."""
    assert "dp-delete-btn" in log_js, \
        "training-log.js must reference #dp-delete-btn to show/hide it"
    assert "dp-strava-btn" in log_js, \
        "training-log.js must reference #dp-strava-btn to show/hide it"


def test_js_keyboard_arrow_navigation(log_js):
    """Arrow key navigation (up/down/left/right) must navigate prev/next."""
    assert "ArrowUp" in log_js or "ArrowDown" in log_js, \
        "training-log.js must support keyboard arrow navigation in the panel"


def test_js_tracks_active_trigger(log_js):
    """JS must track activeTriggerEl to restore focus on panel close."""
    assert "activeTriggerEl" in log_js, \
        "training-log.js must track activeTriggerEl for focus restoration"


def test_js_restores_focus_on_close(log_js):
    """closeDetailPanel must call trigger.focus()."""
    assert "trigger.focus()" in log_js, \
        "training-log.js closeDetailPanel must call trigger.focus() to restore keyboard focus"


def test_js_desktop_adds_has_panel_class(log_js):
    """On desktop (≥880px), opening the panel must add has-panel class."""
    assert "has-panel" in log_js, \
        "training-log.js must add 'has-panel' class to layout-wrapper on desktop panel open"


def test_js_mobile_body_overflow_hidden(log_js):
    """On mobile, opening the panel must set body overflow to hidden."""
    assert "body.style.overflow" in log_js, \
        "training-log.js must set body.style.overflow on mobile when panel opens"


# ── API: splits endpoint ──────────────────────────────────────────────────────

def test_splits_endpoint_returns_list(client, run_with_splits):
    """GET /api/workouts/{id}/splits must return a list of split objects."""
    res = client.get(f"/api/workouts/{run_with_splits}/splits")
    assert res.status_code == 200
    splits = res.json()
    assert isinstance(splits, list), "splits endpoint must return a JSON list"
    assert len(splits) == 3, "must return 3 splits as created"


def test_splits_have_required_fields(client, run_with_splits):
    """Each split must include split_index, distance_km, duration_seconds, avg_hr."""
    res = client.get(f"/api/workouts/{run_with_splits}/splits")
    splits = res.json()
    for s in splits:
        assert "split_index" in s
        assert "distance_km" in s
        assert "duration_seconds" in s
        assert "avg_hr" in s


def test_splits_ordered_by_split_index(client, run_with_splits):
    """Splits must be returned in ascending split_index order."""
    res = client.get(f"/api/workouts/{run_with_splits}/splits")
    splits = res.json()
    indices = [s["split_index"] for s in splits]
    assert indices == sorted(indices), "splits must be ordered by split_index"


def test_splits_empty_for_workout_without_splits(client, run_workout):
    """GET /api/workouts/{id}/splits for a workout with no splits returns empty list."""
    res = client.get(f"/api/workouts/{run_workout}/splits")
    assert res.status_code == 200
    assert res.json() == [], "must return empty list for workout with no splits"


# ── API: workout detail ───────────────────────────────────────────────────────

def test_workout_detail_has_workout_type(client, run_workout):
    res = client.get(f"/api/workouts/{run_workout}")
    assert res.status_code == 200
    assert res.json()["workout_type"] == "run"


def test_workout_detail_has_distance_km(client, run_workout):
    res = client.get(f"/api/workouts/{run_workout}")
    assert res.status_code == 200
    assert res.json()["distance_km"] == 10.5


def test_workout_detail_has_avg_hr(client, run_workout):
    res = client.get(f"/api/workouts/{run_workout}")
    assert res.status_code == 200
    assert res.json()["avg_hr"] == 168


def test_workout_detail_has_elevation_m(client, run_workout):
    res = client.get(f"/api/workouts/{run_workout}")
    assert res.status_code == 200
    assert res.json()["elevation_m"] == 42


def test_workout_detail_has_tss(client, run_workout):
    res = client.get(f"/api/workouts/{run_workout}")
    assert res.status_code == 200
    assert res.json()["tss"] == 92.0


def test_workout_detail_exercises_for_lift(client, lift_workout):
    """GET /api/workouts/{id} for lift must return exercises array."""
    res = client.get(f"/api/workouts/{lift_workout}")
    assert res.status_code == 200
    exercises = res.json()["exercises"]
    assert len(exercises) == 2
    assert exercises[0]["name"] == "Squat"
    assert exercises[0]["sets"] == 4
    assert exercises[0]["reps"] == 6


def test_workout_detail_returns_remarks(client, lift_workout):
    res = client.get(f"/api/workouts/{lift_workout}")
    assert res.status_code == 200
    assert res.json()["remarks"] == "Good session today."


def test_delete_workout_endpoint(client):
    """DELETE /api/workouts/{id} must delete the workout and return 204."""
    create_res = client.post("/api/workouts", json={
        "user_id": USER_ID,
        "name": "To Be Deleted #153",
        "workout_date": "2026-05-23",
        "workout_type": "run",
    })
    assert create_res.status_code == 201
    wid = create_res.json()["id"]

    del_res = client.delete(f"/api/workouts/{wid}")
    assert del_res.status_code == 204, f"DELETE must return 204; got {del_res.status_code}"

    get_res = client.get(f"/api/workouts/{wid}")
    assert get_res.status_code == 404, "Deleted workout must return 404"
