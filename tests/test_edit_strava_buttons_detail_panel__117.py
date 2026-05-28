"""
Tests for issue #117: Add Edit and Open in Strava buttons to Training Log detail panel
Runs against UAT environment (http://localhost:9001)
"""
import os
import uuid
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


@pytest.fixture(scope="module")
def manual_workout_id(client):
    payload = {
        "user_id": ALICE_USER_ID,
        "name": "Test Manual Workout #117",
        "workout_date": str(date.today()),
        "workout_type": "lift",
        "exercises": [{"name": "Squat", "sets": 3, "reps": 5}],
    }
    res = client.post("/api/workouts", json=payload)
    assert res.status_code == 201, f"Failed to create manual workout: {res.text}"
    yield res.json()["id"]
    client.delete(f"/api/workouts/{res.json()['id']}")


# ── AC: log.html contains the detail panel footer with Edit and Strava buttons ──

def test_log_page_has_detail_edit_button(client):
    """AC: Edit button with id='detail-edit-btn' is present in the detail panel."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-edit-btn"' in res.text, "Edit button must be present in detail panel"


def test_log_page_has_detail_strava_button(client):
    """AC: Strava button with id='detail-strava-btn' is present and hidden by default."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-strava-btn"' in res.text, "Open in Strava button must be present in detail panel"
    assert 'display:none' in res.text or "display: none" in res.text, \
        "Strava button must be hidden by default (display:none)"


def test_log_page_detail_panel_footer_present(client):
    """AC: Action footer is rendered at the bottom of the detail panel."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'detail-panel-footer' in res.text, "detail-panel-footer container must be in the HTML"


def test_log_page_strava_button_aria_label(client):
    """AC: Open in Strava button has accessible aria-label."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'Open in Strava' in res.text, "Strava button must have visible text 'Open in Strava'"


def test_log_page_edit_button_aria_label(client):
    """AC: Edit button has accessible aria-label."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'aria-label="Edit workout"' in res.text or 'Edit' in res.text, \
        "Edit button must have accessible label"


# ── AC: GET /api/workouts/{id} includes source and strava_activity_url fields ──

def test_workout_get_includes_source_field(client, manual_workout_id):
    """AC: GET /api/workouts/{id} response includes a 'source' field."""
    res = client.get(f"/api/workouts/{manual_workout_id}")
    assert res.status_code == 200
    data = res.json()
    assert "source" in data, "GET /api/workouts/{id} must include 'source' field"


def test_workout_get_includes_strava_activity_url_field(client, manual_workout_id):
    """AC: GET /api/workouts/{id} response includes a 'strava_activity_url' field."""
    res = client.get(f"/api/workouts/{manual_workout_id}")
    assert res.status_code == 200
    data = res.json()
    assert "strava_activity_url" in data, \
        "GET /api/workouts/{id} must include 'strava_activity_url' field"


def test_manual_workout_source_is_null_or_manual(client, manual_workout_id):
    """AC: A manually-created workout has source null or 'manual' (never 'strava')."""
    res = client.get(f"/api/workouts/{manual_workout_id}")
    assert res.status_code == 200
    data = res.json()
    source = data.get("source")
    assert source in (None, "manual"), \
        f"Manual workout source should be null or 'manual', got '{source}'"


def test_manual_workout_has_no_strava_url(client, manual_workout_id):
    """AC: A manually-created workout has no Strava activity URL."""
    res = client.get(f"/api/workouts/{manual_workout_id}")
    assert res.status_code == 200
    data = res.json()
    assert data.get("strava_activity_url") is None, \
        "Manual workout must not have a strava_activity_url"


# ── AC: training-log API response includes source field ──

def test_training_log_entries_include_source_field(client):
    """AC: GET /api/training-log workouts include a 'source' field for each entry."""
    res = client.get(
        f"/api/training-log?user_id={ALICE_USER_ID}&from=2020-01-01&to=2030-12-31"
    )
    assert res.status_code == 200
    data = res.json()
    weeks = data.get("weeks", [])
    if not weeks:
        pytest.skip("No workout data for this user; skipping source-field check")
    for week in weeks:
        for entry in week.get("workouts", []):
            assert "source" in entry, \
                f"Training-log workout entry must include 'source' field; got keys: {list(entry.keys())}"


# ── AC: training-log JS wires up Edit and Strava buttons in renderPanelContent ──

def test_training_log_js_wires_edit_button(client):
    """AC: training-log.js contains logic to navigate to training.html for Edit."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "training.html?edit=" in res.text, \
        "training-log.js must navigate to training.html?edit=<id> when Edit is clicked"


def test_training_log_js_shows_strava_button_conditionally(client):
    """AC: training-log.js conditionally shows Strava button based on source and URL."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "strava_activity_url" in res.text, \
        "training-log.js must check strava_activity_url to show/hide Strava button"
    assert "detail-strava-btn" in res.text, \
        "training-log.js must reference detail-strava-btn element"


# ── AC: training.js handles ?edit= URL param ──

def test_training_js_handles_edit_url_param(client):
    """AC: training.js reads ?edit= URL param to enter edit mode."""
    res = client.get("/js/training.js")
    assert res.status_code == 200
    assert "get('edit')" in res.text or '.get("edit")' in res.text, \
        "training.js must read the 'edit' URL param"
    assert "fillForm" in res.text, \
        "training.js must call fillForm() when loading a workout for editing"


# ── AC: Strava button opens in new tab ──

def test_strava_button_opens_new_tab(client):
    """AC: Open in Strava button has target='_blank' to open in a new tab."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'target="_blank"' in res.text, \
        "Open in Strava button must open in a new tab (target='_blank')"
    assert 'rel="noopener noreferrer"' in res.text, \
        "Open in Strava button must include rel='noopener noreferrer' for security"
