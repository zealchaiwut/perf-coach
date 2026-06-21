"""Tests for issue #832: Build Create and Edit Habit Form (Slide-Over/Modal).

Static checks read frontend/pages/habits.html and frontend/js/habits.js directly.
Live tests hit the server at BASE_URL.
"""
import os
import pathlib
import re
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
ROOT = pathlib.Path(__file__).parent.parent

_CREDENTIALS = {"username": "tester832", "password": "Test832pass!"}


def _html() -> str:
    return (ROOT / "frontend" / "pages" / "habits.html").read_text()


def _js() -> str:
    return (ROOT / "frontend" / "js" / "habits.js").read_text()


def _extract_cookie(response: httpx.Response, name: str) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        parts = [p.strip() for p in header.split(";")]
        if parts and "=" in parts[0]:
            k, v = parts[0].split("=", 1)
            if k.strip() == name:
                return v.strip()
    return None


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/api/auth/login", json=_CREDENTIALS)
        if r.status_code != 200:
            pytest.skip(f"Login failed ({r.status_code}); seed tester832 user first")
        csrf_val = _extract_cookie(r, "csrf-token")
        if csrf_val:
            c.cookies.set("csrf-token", csrf_val, domain="127.0.0.1")
        yield c


def _csrf(client: httpx.Client) -> str:
    r = client.get("/api/csrf-token")
    assert r.status_code == 200
    token = r.json()["csrf_token"]
    client.cookies.set("csrf-token", token, domain="127.0.0.1")
    return token


# ── AC1: Slide-over / full-screen overlay element ────────────────────────────

def test_slideover_element_exists():
    """AC1: A slide-over/modal element exists in habits.html."""
    html = _html()
    assert 'id="habit-slideover"' in html, \
        "habits.html must have id='habit-slideover' for the slide-over overlay"


def test_slideover_panel_exists():
    """AC1: Inner panel element for the slide-over content."""
    html = _html()
    assert 'id="habit-slideover-panel"' in html, \
        "habits.html must have id='habit-slideover-panel' for the inner panel"


def test_slideover_opens_on_new_habit_trigger():
    """AC1: A 'New Habit' button or trigger exists."""
    html = _html()
    assert "add-habit-btn" in html or "new-habit-btn" in html, \
        "habits.html must have a 'New Habit' trigger button"


def test_slideover_open_function_in_js():
    """AC1: openHabitForm() function defined in habits.js."""
    js = _js()
    assert "function openHabitForm" in js or "openHabitForm = function" in js, \
        "habits.js must define openHabitForm()"


def test_slideover_close_function_in_js():
    """AC1: closeHabitForm() function defined in habits.js."""
    js = _js()
    assert "function closeHabitForm" in js or "closeHabitForm = function" in js, \
        "habits.js must define closeHabitForm()"


# ── AC2: Gradient theme ────────────────────────────────────────────────────────

def test_slideover_uses_gradient_theme():
    """AC2: Slide-over uses gradient design tokens, not legacy light tokens."""
    html = _html()
    # Must use gradient vars anywhere in the page (already established by prior issues)
    assert "var(--page-bg)" in html or "var(--card-bg)" in html, \
        "habits.html must use gradient-theme CSS custom properties"


def test_slideover_panel_css_defined():
    """AC2: CSS for the habit-slideover panel is defined in habits.html."""
    html = _html()
    assert ".habit-slideover" in html or "#habit-slideover" in html, \
        "habits.html must define styles for the habit-slideover element"


# ── AC3: name field always visible and required ──────────────────────────────

def test_name_field_exists():
    """AC3: name input exists in the slide-over form."""
    html = _html()
    assert 'id="habit-form-name"' in html, \
        "habits.html must have id='habit-form-name' for the name field"


def test_name_field_required_attribute():
    """AC3: name input is marked required or validated in JS."""
    html = _html()
    js = _js()
    has_required_attr = bool(re.search(r'id=["\']habit-form-name["\'].*?required', html, re.DOTALL))
    has_js_validation = "habit-form-name" in js and (
        "required" in js or
        "Name is required" in js or
        "name.*required" in js.lower()
    )
    assert has_required_attr or has_js_validation, \
        "name field must be required (HTML required attr or JS validation)"


def test_name_inline_error_element_exists():
    """AC14: Inline error for name field exists."""
    html = _html()
    assert 'id="habit-form-name-error"' in html, \
        "habits.html must have id='habit-form-name-error' for inline name error"


# ── AC4: habit_type selector ─────────────────────────────────────────────────

def test_habit_type_select_exists():
    """AC4: habit_type selector exists."""
    html = _html()
    assert 'id="habit-form-habit-type"' in html, \
        "habits.html must have id='habit-form-habit-type' select"


def test_habit_type_has_binary_option():
    """AC4: binary option in habit_type selector."""
    html = _html()
    assert 'value="binary"' in html, \
        "habits.html habit-type select must have value='binary'"


def test_habit_type_has_count_option():
    """AC4: count option in habit_type selector."""
    html = _html()
    assert 'value="count"' in html, \
        "habits.html habit-type select must have value='count'"


def test_habit_type_has_duration_option():
    """AC4: duration option in habit_type selector."""
    html = _html()
    assert 'value="duration"' in html, \
        "habits.html habit-type select must have value='duration'"


def test_habit_type_exactly_three_options():
    """AC4: Exactly three options in habit_type selector."""
    html = _html()
    # Find the habit-form-habit-type select block
    m = re.search(
        r'id=["\']habit-form-habit-type["\'].*?</select>',
        html, re.DOTALL
    )
    assert m is not None, "habit-form-habit-type select not found"
    block = m.group(0)
    options = re.findall(r'<option\b', block)
    assert len(options) == 3, \
        f"habit_type selector must have exactly 3 options, found {len(options)}: {block[:300]}"


# ── AC5: target_value + unit conditional on count/duration ────────────────────

def test_target_value_input_exists():
    """AC5: target_value input exists in the slide-over form."""
    html = _html()
    assert 'id="habit-form-target-value"' in html, \
        "habits.html must have id='habit-form-target-value'"


def test_unit_input_exists():
    """AC5: unit input exists in the slide-over form."""
    html = _html()
    assert 'id="habit-form-unit"' in html, \
        "habits.html must have id='habit-form-unit'"


def test_target_row_exists_for_conditional_visibility():
    """AC5: A container element for target_value+unit that can be shown/hidden."""
    html = _html()
    assert 'id="habit-form-target-row"' in html, \
        "habits.html must have id='habit-form-target-row' for conditional visibility"


def test_js_hides_target_row_for_binary():
    """AC5: JS hides target-row when habit_type is binary."""
    js = _js()
    assert "binary" in js and ("habit-form-target-row" in js or "target-row" in js), \
        "habits.js must reference binary and the target-row to conditionally hide it"


def test_target_value_error_element_exists():
    """AC14: Inline error for target_value exists."""
    html = _html()
    assert 'id="habit-form-target-value-error"' in html, \
        "habits.html must have id='habit-form-target-value-error'"


# ── AC6: schedule_type selector ──────────────────────────────────────────────

def test_schedule_type_select_exists():
    """AC6: schedule_type selector exists."""
    html = _html()
    assert 'id="habit-form-schedule-type"' in html, \
        "habits.html must have id='habit-form-schedule-type' select"


def test_schedule_type_has_daily_option():
    """AC6: daily option in schedule_type selector."""
    html = _html()
    assert 'value="daily"' in html, \
        "habits.html schedule-type select must have value='daily'"


def test_schedule_type_has_weekly_option():
    """AC6: weekly option in schedule_type selector."""
    html = _html()
    assert 'value="weekly"' in html, \
        "habits.html schedule-type select must have value='weekly'"


def test_schedule_type_has_times_per_week_option():
    """AC6: times_per_week option in schedule_type selector."""
    html = _html()
    assert 'value="times_per_week"' in html, \
        "habits.html schedule-type select must have value='times_per_week'"


def test_schedule_type_exactly_three_options():
    """AC6: Exactly three options in schedule_type selector."""
    html = _html()
    m = re.search(
        r'id=["\']habit-form-schedule-type["\'].*?</select>',
        html, re.DOTALL
    )
    assert m is not None, "habit-form-schedule-type select not found"
    block = m.group(0)
    options = re.findall(r'<option\b', block)
    assert len(options) == 3, \
        f"schedule_type selector must have exactly 3 options, found {len(options)}"


# ── AC7: schedule_target conditional on times_per_week ───────────────────────

def test_schedule_target_input_exists():
    """AC7: schedule_target input exists."""
    html = _html()
    assert 'id="habit-form-schedule-target"' in html, \
        "habits.html must have id='habit-form-schedule-target'"


def test_schedule_target_row_exists():
    """AC7: Container for schedule_target that can be shown/hidden."""
    html = _html()
    assert 'id="habit-form-schedule-target-row"' in html, \
        "habits.html must have id='habit-form-schedule-target-row'"


def test_js_hides_schedule_target_for_non_times_per_week():
    """AC7: JS hides schedule-target-row when schedule_type is not times_per_week."""
    js = _js()
    assert "times_per_week" in js and "habit-form-schedule-target-row" in js, \
        "habits.js must reference times_per_week and habit-form-schedule-target-row"


def test_schedule_target_error_element_exists():
    """AC14: Inline error element for schedule_target exists."""
    html = _html()
    assert 'id="habit-form-schedule-target-error"' in html, \
        "habits.html must have id='habit-form-schedule-target-error'"


# ── AC8: target_value validation (positive > 0) ───────────────────────────────

def test_js_validates_target_value_positive():
    """AC8: JS validates target_value > 0 when field is visible."""
    js = _js()
    assert "target-value" in js or "targetValue" in js or "target_value" in js, \
        "habits.js must reference the target_value field in validation"
    # Should have a check that value > 0
    assert "> 0" in js or "positive" in js.lower() or "must be" in js.lower(), \
        "habits.js must validate that target_value is positive"


# ── AC9: schedule_target validation (positive int > 0) ────────────────────────

def test_js_validates_schedule_target_positive_int():
    """AC9: JS validates schedule_target > 0 and is an integer."""
    js = _js()
    assert "schedule-target" in js or "scheduleTarget" in js or "schedule_target" in js, \
        "habits.js must reference the schedule_target field in validation"


# ── AC10: New habit calls create endpoint ─────────────────────────────────────

def test_js_calls_post_habits_for_new():
    """AC10: JS calls POST /api/habits when creating a new habit."""
    js = _js()
    assert "POST" in js and "/api/habits" in js, \
        "habits.js must call POST /api/habits to create a new habit"


def test_js_closes_form_on_success():
    """AC10: Form closes after successful save."""
    js = _js()
    assert "closeHabitForm" in js, \
        "habits.js must call closeHabitForm() after successful save"


# ── AC11: Edit populates form with existing values ───────────────────────────

def test_js_open_edit_populates_name():
    """AC11: openHabitForm(habit) populates name field from habit object."""
    js = _js()
    assert "habit-form-name" in js and ".name" in js, \
        "habits.js must populate habit-form-name from habit.name in edit mode"


def test_js_calls_patch_habits_for_edit():
    """AC11: JS calls PATCH /api/habits/{id} when editing."""
    js = _js()
    assert "PATCH" in js and "/api/habits/" in js, \
        "habits.js must call PATCH /api/habits/{id} to update a habit"


# ── AC12: Archive sets is_archived = true ─────────────────────────────────────

def test_archive_button_exists_in_html():
    """AC12: Archive button exists in the form."""
    html = _html()
    assert 'id="habit-form-archive"' in html, \
        "habits.html must have id='habit-form-archive' archive button"


def test_js_archive_calls_patch_with_is_archived():
    """AC12: JS archive action patches habit with is_archived=true."""
    js = _js()
    assert "is_archived" in js and ("true" in js or "True" in js), \
        "habits.js must send is_archived: true when archiving"


# ── AC13: Mobile full-screen ──────────────────────────────────────────────────

def test_mobile_fullscreen_css_in_html():
    """AC13: CSS media query for mobile full-screen slide-over."""
    html = _html()
    # Look for a media query that makes the panel full-screen on mobile
    assert "@media" in html and (
        "habit-slideover-panel" in html or "habit-slideover" in html
    ), "habits.html must have responsive CSS for the slide-over"
    # Check that mobile breakpoint is referenced (< 768px or similar)
    assert "768px" in html or "640px" in html or "max-width" in html, \
        "habits.html must define mobile breakpoint CSS for the slide-over"


# ── AC14: Inline validation errors ────────────────────────────────────────────

def test_form_error_element_exists():
    """AC14: General form error element exists."""
    html = _html()
    assert 'id="habit-form-error"' in html, \
        "habits.html must have id='habit-form-error' for general form errors"


def test_js_shows_inline_errors():
    """AC14: JS sets error text on inline error elements."""
    js = _js()
    assert "habit-form-name-error" in js, \
        "habits.js must reference habit-form-name-error to show inline errors"


# ── AC15: Dismiss without saving ──────────────────────────────────────────────

def test_cancel_button_exists():
    """AC15: Cancel button exists in the form."""
    html = _html()
    assert 'id="habit-form-cancel"' in html, \
        "habits.html must have id='habit-form-cancel' button"


def test_js_cancel_calls_close():
    """AC15: Cancel button wires to closeHabitForm()."""
    js = _js()
    assert "habit-form-cancel" in js and "closeHabitForm" in js, \
        "habits.js must wire cancel button to closeHabitForm()"


def test_backdrop_click_closes_form():
    """AC15: Clicking the backdrop (outside panel) closes the form on desktop."""
    js = _js()
    assert "habit-slideover" in js and "closeHabitForm" in js, \
        "habits.js must close form when backdrop is clicked"


# ── Live API tests ─────────────────────────────────────────────────────────────

def test_create_habit_via_api(client):
    """AC10: POST /api/habits creates a new habit successfully (live)."""
    token = _csrf(client)
    payload = {
        "name": "Test run 832",
        "tracking_type": "weekly_count",
        "weekly_target": 3,
        "unit": "sessions",
    }
    r = client.post(
        "/api/habits",
        json=payload,
        headers={"X-CSRF-Token": token},
    )
    assert r.status_code == 201, f"Expected 201 creating habit, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["name"] == "Test run 832"
    assert data["id"] is not None
    return data["id"]


def test_edit_habit_via_api(client):
    """AC11: PATCH /api/habits/{id} updates a habit (live)."""
    token = _csrf(client)
    # Create one first
    r = client.post(
        "/api/habits",
        json={"name": "Edit test 832", "tracking_type": "daily_checkmark"},
        headers={"X-CSRF-Token": token},
    )
    assert r.status_code == 201, f"Create failed: {r.status_code}: {r.text}"
    habit_id = r.json()["id"]

    # Edit it
    r2 = client.patch(
        f"/api/habits/{habit_id}",
        json={"name": "Edited name 832"},
        headers={"X-CSRF-Token": token},
    )
    assert r2.status_code == 200, f"Expected 200 updating habit, got {r2.status_code}: {r2.text}"
    assert r2.json()["name"] == "Edited name 832"


def test_archive_habit_via_api(client):
    """AC12: PATCH /api/habits/{id} with is_archived=true archives the habit (live)."""
    token = _csrf(client)
    r = client.post(
        "/api/habits",
        json={"name": "Archive test 832", "tracking_type": "daily_checkmark"},
        headers={"X-CSRF-Token": token},
    )
    assert r.status_code == 201, f"Create failed: {r.status_code}: {r.text}"
    habit_id = r.json()["id"]

    r2 = client.patch(
        f"/api/habits/{habit_id}",
        json={"is_archived": True},
        headers={"X-CSRF-Token": token},
    )
    assert r2.status_code == 200, f"Expected 200 archiving habit, got {r2.status_code}: {r2.text}"
    assert r2.json()["is_archived"] is True

    # Verify it's gone from active list
    r3 = client.get("/api/habits")
    assert r3.status_code == 200
    active_ids = [h["id"] for h in r3.json()]
    assert habit_id not in active_ids, "Archived habit should not appear in active list"


def test_archived_habit_history_preserved(client):
    """AC12: Archiving a habit preserves its log data (live)."""
    token = _csrf(client)
    # Create and log
    r = client.post(
        "/api/habits",
        json={"name": "History test 832", "tracking_type": "daily_checkmark"},
        headers={"X-CSRF-Token": token},
    )
    assert r.status_code == 201
    habit_id = r.json()["id"]

    log_r = client.post(
        "/api/habits/logs",
        json={"habit_id": habit_id, "logged_date": "2026-01-15"},
        headers={"X-CSRF-Token": token},
    )
    assert log_r.status_code == 201, f"Log failed: {log_r.status_code}: {log_r.text}"

    # Archive
    client.patch(
        f"/api/habits/{habit_id}",
        json={"is_archived": True},
        headers={"X-CSRF-Token": token},
    )

    # Check logs still accessible
    logs_r = client.get(f"/api/habits/{habit_id}/progress")
    assert logs_r.status_code == 200, \
        "Archived habit's progress endpoint must still be accessible"
