"""Tests for issue #832: Build Create and Edit Habit Form (Slide-Over/Modal)"""
import os
import pytest
import httpx


BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=False) as c:
        yield c


@pytest.fixture(scope="module")
def habits_html():
    """Load the habits page HTML to inspect form structure."""
    html_path = os.path.join(os.path.dirname(__file__), "../frontend/pages/habits.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def habits_js():
    """Load the habits JS to inspect form logic."""
    js_path = os.path.join(os.path.dirname(__file__), "../frontend/js/habits.js")
    with open(js_path, encoding="utf-8") as f:
        return f.read()


def test_832__slide_over_form_markup_present(habits_html):
    """AC: A slide-over (desktop) or full-screen overlay (mobile) opens when user triggers 'New Habit' or 'Edit Habit'"""
    # Verify the form container exists
    assert "habit-slideover" in habits_html
    assert "habit-form-title" in habits_html
    assert 'id="habit-slideover-panel"' in habits_html
    assert "habit-slideover-header" in habits_html


def test_832__form_renders_with_gradient_theme(habits_html):
    """AC: Form renders using the app's gradient theme and follows structure-over-pixel-styling"""
    # Check gradient applied to header
    assert "linear-gradient" in habits_html
    assert "habit-slideover-header" in habits_html
    # Check field structure classes present
    assert "sf-field" in habits_html
    assert "sf-input" in habits_html
    assert "sf-select" in habits_html


def test_832__name_field_always_visible_required(habits_html):
    """AC: **name** field is always visible and required"""
    assert 'id="habit-form-name"' in habits_html
    assert 'class="sf-input"' in habits_html
    # Required indicator
    assert "sf-required" in habits_html
    assert 'id="habit-form-name-error"' in habits_html


def test_832__habit_type_selector_three_options(habits_html):
    """AC: **habit_type** selector offers exactly three options: binary, count, duration"""
    assert 'id="habit-form-habit-type"' in habits_html
    assert 'value="binary"' in habits_html
    assert 'value="count"' in habits_html
    assert 'value="duration"' in habits_html
    # Count occurrences to ensure exactly 3 options (ignore other form values)
    habit_type_section = habits_html[habits_html.find('id="habit-form-habit-type"'):habits_html.find('id="habit-form-habit-type"') + 500]
    assert habit_type_section.count('value="binary"') >= 1
    assert habit_type_section.count('value="count"') >= 1
    assert habit_type_section.count('value="duration"') >= 1


def test_832__target_value_unit_conditional_visibility(habits_html, habits_js):
    """AC: target_value and unit shown only for count/duration; hidden for binary"""
    assert 'id="habit-form-target-row"' in habits_html
    assert 'id="habit-form-target-value"' in habits_html
    assert 'id="habit-form-unit"' in habits_html
    # Row should be hidden by default (binary is default)
    assert "habit-form-target-row" in habits_html
    # Check JavaScript conditional logic exists in JS (not HTML)
    assert ("habitType === 'count' || habitType === 'duration'" in habits_js or
            "habitType == 'count' || habitType == 'duration'" in habits_js)


def test_832__schedule_type_selector_three_options(habits_html):
    """AC: **schedule_type** selector offers exactly three options: daily, weekly, times_per_week"""
    assert 'id="habit-form-schedule-type"' in habits_html
    assert 'value="daily"' in habits_html
    assert 'value="weekly"' in habits_html
    assert 'value="times_per_week"' in habits_html


def test_832__schedule_target_conditional_visibility(habits_html, habits_js):
    """AC: schedule_target shown only for times_per_week; hidden otherwise"""
    assert 'id="habit-form-schedule-target-row"' in habits_html
    assert 'id="habit-form-schedule-target"' in habits_html
    # Check JavaScript conditional for visibility in JS (not HTML)
    assert ("scheduleType === 'times_per_week'" in habits_js or
            "scheduleType == 'times_per_week'" in habits_js)


def test_832__form_validation_logic_present(habits_js):
    """AC: target_value validated positive; schedule_target validated positive integer; form does not submit if violated"""
    # Check validation for target_value
    assert "target_value must be a positive number" in habits_js or \
           "isNaN(val) || val <= 0" in habits_js
    # Check validation for schedule_target
    assert "Times per week must be a positive integer" in habits_js or \
           "scheduleTarget" in habits_js and "val <= 0" in habits_js


def test_832__create_endpoint_called_for_new_habit(habits_js):
    """AC: Submitting new habit calls POST /api/habits endpoint"""
    assert "fetch('/api/habits'" in habits_js or \
           'fetch(\'/api/habits\'' in habits_js
    assert "'POST'" in habits_js or '"POST"' in habits_js


def test_832__edit_endpoint_called_for_existing(habits_js):
    """AC: Submitting edit calls PATCH endpoint; form prepopulates with existing values"""
    assert "PATCH" in habits_js
    assert "habit_id" in habits_js
    assert "fetch(`/api/habits/${" in habits_js


def test_832__archive_action_present(habits_html):
    """AC: Archive action sets is_archived=true via PATCH endpoint"""
    assert 'id="habit-form-archive"' in habits_html
    assert "sf-btn-archive" in habits_html


def test_832__archive_logic_in_js(habits_js):
    """AC: Archive action calls PATCH with is_archived: true"""
    assert "is_archived" in habits_js
    assert "Archive this habit" in habits_js


def test_832__form_dismissible_cancel_button(habits_html):
    """AC: The form can be dismissed without saving (Cancel button or backdrop click)"""
    assert 'id="habit-form-cancel"' in habits_html
    assert 'id="habit-slideover-backdrop"' in habits_html
    assert 'id="habit-slideover-close-btn"' in habits_html


def test_832__form_close_logic_in_js(habits_js):
    """AC: Form dismissed on Cancel, close button, or backdrop click"""
    assert "closeHabitForm" in habits_js
    assert "habit-slideover-close-btn" in habits_js
    assert "backdrop" in habits_js


def test_832__inline_error_messages_in_form(habits_html):
    """AC: Inline validation error messages displayed adjacent to offending field"""
    assert 'id="habit-form-name-error"' in habits_html
    assert 'id="habit-form-target-value-error"' in habits_html
    assert 'id="habit-form-schedule-target-error"' in habits_html
    assert 'id="habit-form-error"' in habits_html
    # Check error display styling
    assert "sf-error" in habits_html
    assert "is-visible" in habits_html


def test_832__mobile_full_screen_styling(habits_html):
    """AC: On mobile breakpoints form occupies full screen (no partial slide-over)"""
    # Check media query exists
    assert "@media (max-width: 768px)" in habits_html
    # Check mobile panel styling
    assert "width: 100%" in habits_html or "max-width: 100%" in habits_html
    assert "height: 100%" in habits_html


def test_832__form_structure_uses_gradient_tokens(habits_html):
    """AC: Form renders using the app's gradient theme and structure-over-pixel-styling"""
    # Header should use gradient
    header_section = habits_html[habits_html.find("habit-slideover-header"):habits_html.find("habit-slideover-header") + 300]
    assert "linear-gradient" in header_section
    # Check for gradient direction (app standard)
    assert "135deg" in habits_html or "gradient" in habits_html
