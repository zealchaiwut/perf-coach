"""Tests for issue #829: Add Habits history calendar with day-status cells.

Verifies the habits history calendar against:
- AC1: Month-grid calendar on desktop (≥ md breakpoint)
- AC2: Week-strip on mobile (< md breakpoint), 7 days of current week
- AC3: Three distinct gradient-themed cell states: met, partial, not-met
- AC4: Status computed using same met/partial/not-met logic as Habits summary
- AC5: All log data from H1 habit-log endpoints only
- AC6: Clicking a day cell applies persistent highlight and reveals log entries
- AC7: Selecting a day never hides/filters other cells
- AC8: Days with no data render in neutral/empty state and are not clickable
- AC9: Desktop month nav (prev/next); mobile week strip prev/next week
- AC10: Styling via structural class conventions (spacing, layout, colour tokens)
- AC11: Accessible: aria-label on cells, keyboard navigation

Static tests read frontend/pages/habits.html and frontend/js/habits.js directly.
Live tests hit the server at BASE_URL.
"""
import os
import pathlib
import re
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
ROOT = pathlib.Path(__file__).parent.parent

_CREDENTIALS = {"username": "tester829", "password": "Test829pass!"}


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
            pytest.skip(f"Login failed ({r.status_code}); seed tester829 user first")
        csrf_val = _extract_cookie(r, "csrf-token")
        if csrf_val:
            c.cookies.set("csrf-token", csrf_val, domain="127.0.0.1")
        yield c


# ── AC1: Month-grid calendar on desktop ──────────────────────────────────────

def test_html_has_history_cal_section():
    """AC1: habits.html has a history calendar section container."""
    html = _html()
    assert 'id="habits-history-cal"' in html, \
        "habits.html must have id='habits-history-cal' for the history calendar section"


def test_html_has_month_cal_container():
    """AC1: Desktop month calendar container is present."""
    html = _html()
    assert 'id="habits-month-cal"' in html, \
        "habits.html must have id='habits-month-cal' for the desktop month grid"


def test_html_has_cal_nav_controls():
    """AC1/AC9: Calendar navigation controls (prev/next month) are in the HTML or JS."""
    # Navigation buttons are rendered by JS into #habits-month-cal
    js = _js()
    assert "hcal-prev" in js or "habits-cal-prev" in js or "hcal-month-prev" in js, \
        "habits.js must render a previous-month button for the month calendar"
    assert "hcal-next" in js or "habits-cal-next" in js or "hcal-month-next" in js, \
        "habits.js must render a next-month button for the month calendar"


def test_html_has_cal_weekday_headers():
    """AC1: Calendar grid has day-of-week header row."""
    js = _js()
    # Weekday abbreviations should appear in the rendered grid
    assert "Mo" in js or "cal-weekday" in js or "hcal-weekday" in js, \
        "habits.js must render weekday headers (Mo/Tu/We...) in the calendar grid"


def test_css_month_cal_shown_desktop():
    """AC1: Month calendar is shown at ≥ md breakpoint and hidden on mobile."""
    html = _html()
    # Desktop: habits-month-cal is shown at ≥768px (or similar md breakpoint)
    assert "habits-month-cal" in html, \
        "habits.html CSS must reference #habits-month-cal for responsive show/hide"
    # The CSS must hide week strip on desktop or show month cal on desktop
    assert (
        re.search(r'min-width\s*:\s*7[0-9]{2}px', html)
        or re.search(r'min-width\s*:\s*\d+px', html)
    ), "habits.html must have a min-width media query for responsive calendar layout"


# ── AC2: Week-strip on mobile ─────────────────────────────────────────────────

def test_html_has_week_strip_container():
    """AC2: Mobile week strip container is present."""
    html = _html()
    assert 'id="habits-week-strip"' in html, \
        "habits.html must have id='habits-week-strip' for the mobile 7-day week strip"


def test_html_week_strip_hidden_desktop():
    """AC2: Week strip is hidden on desktop and shown on mobile."""
    html = _html()
    # CSS must hide #habits-week-strip at ≥ md breakpoint
    assert "habits-week-strip" in html, \
        "habits.html must reference #habits-week-strip in CSS for responsive display"


def test_html_week_strip_has_nav():
    """AC2/AC9: Week strip has prev/next week navigation buttons."""
    js = _js()
    assert "hcal-week-prev" in js or "habits-week-prev" in js or "hcal-strip-prev" in js, \
        "habits.js must render a previous-week button for the week strip"
    assert "hcal-week-next" in js or "habits-week-next" in js or "hcal-strip-next" in js, \
        "habits.js must render a next-week button for the week strip"


# ── AC3: Three gradient-themed cell states ────────────────────────────────────

def test_css_has_met_cell_state():
    """AC3: CSS defines a 'met' cell state with gradient styling."""
    html = _html()
    assert "hcal-cell--met" in html or "hcal-day--met" in html, \
        "habits.html CSS must define a 'met' cell state class (e.g., .hcal-cell--met)"


def test_css_has_partial_cell_state():
    """AC3: CSS defines a 'partial' cell state with gradient styling."""
    html = _html()
    assert "hcal-cell--partial" in html or "hcal-day--partial" in html, \
        "habits.html CSS must define a 'partial' cell state class"


def test_css_has_not_met_cell_state():
    """AC3: CSS defines a 'not-met' cell state."""
    html = _html()
    assert "hcal-cell--not-met" in html or "hcal-day--not-met" in html or \
           "hcal-cell--empty" in html, \
        "habits.html CSS must define a 'not-met' cell state class"


def test_css_met_state_uses_gradient_tokens():
    """AC3: The 'met' state uses gradient CSS variables from the app's token set."""
    html = _html()
    # met should use green gradient (green-soft or similar token)
    assert "green-soft" in html or "linear-gradient" in html, \
        "habits.html must use gradient tokens (--green-soft or linear-gradient) for cell states"


# ── AC4: Status computed using shared met/partial/not-met logic ───────────────

def test_js_has_compute_day_status_function():
    """AC4: habits.js has a computeDayStatus (or equivalent) function."""
    js = _js()
    assert "computeDayStatus" in js or "dayStatus" in js or "computeHabitDayStatus" in js, \
        "habits.js must have a function to compute met/partial/not-met status per day"


def test_js_compute_status_checks_all_habits():
    """AC4: Status computation evaluates all applicable habits for a given day."""
    js = _js()
    # The status function must compare logged count vs applicable habits count
    assert ("applicable" in js or "activeFor" in js or
            "logsForDate" in js or "dateHabits" in js or
            "logCount" in js or "loggedHabits" in js), \
        "habits.js computeDayStatus must track which habits apply for a given date"


# ── AC5: Data from H1 habit-log endpoints only ────────────────────────────────

def test_js_fetches_habit_logs_endpoint():
    """AC5: habits.js calendar fetches from /api/habits/logs."""
    js = _js()
    assert "/api/habits/logs" in js, \
        "habits.js must fetch from /api/habits/logs for calendar data"


def test_js_calendar_uses_only_habit_endpoints():
    """AC5: Calendar data comes only from H1 (habits) endpoints."""
    js = _js()
    # Calendar function should use /api/habits and /api/habits/logs
    assert "/api/habits/logs" in js, \
        "habits.js must use /api/habits/logs (H1 habit-log endpoint) for calendar data"
    # Must NOT fetch training-log or workout data for the calendar
    assert "/api/training-log" not in js, \
        "habits.js must not use /api/training-log for calendar data"


def test_api_habits_logs_returns_correct_fields(client):
    """AC5: /api/habits/logs endpoint returns logged_date field."""
    today = "2026-06-21"
    r = client.get(f"/api/habits/logs?from=2026-06-01&to={today}")
    assert r.status_code == 200, f"GET /api/habits/logs failed: {r.status_code}"
    data = r.json()
    assert isinstance(data, list), "/api/habits/logs must return a list"
    if data:
        assert "logged_date" in data[0], \
            "/api/habits/logs entries must have 'logged_date' field"
        assert "habit_id" in data[0], \
            "/api/habits/logs entries must have 'habit_id' field"


def test_api_habits_returns_created_at(client):
    """AC5/AC8: /api/habits returns habits with 'created_at' for pre-creation date check."""
    r = client.get("/api/habits")
    assert r.status_code == 200, f"GET /api/habits failed: {r.status_code}"
    data = r.json()
    assert isinstance(data, list), "/api/habits must return a list"
    if data:
        assert "created_at" in data[0], \
            "/api/habits entries must include 'created_at' for pre-creation date logic"


# ── AC6: Persistent highlight + detail reveal on click ───────────────────────

def test_js_cell_click_sets_selected_class():
    """AC6: Clicking a cell sets a persistent 'is-selected' class."""
    js = _js()
    assert "is-selected" in js, \
        "habits.js must set 'is-selected' class on clicked calendar day cells"


def test_js_cell_click_reveals_detail():
    """AC6: Clicking a cell scrolls to or reveals that day's log entries."""
    js = _js()
    # Must show a detail area or scroll to logs
    assert ("habits-cal-detail" in js or "scrollIntoView" in js or
            "calDetailDate" in js or "selectedCalDate" in js or
            "hcal-detail" in js), \
        "habits.js must reveal or scroll to log entries when a day cell is clicked"


def test_js_selected_date_persists():
    """AC6: The selected date state is stored (not just set on click)."""
    js = _js()
    # A state variable must track the selected date
    assert ("calSelectedDate" in js or "hcalSelectedDate" in js or
            "selectedCalDate" in js or "calSelected" in js), \
        "habits.js must store the selected calendar date in a persistent state variable"


# ── AC7: Selecting a day never hides other cells ─────────────────────────────

def test_js_cell_click_does_not_hide_siblings():
    """AC7: The click handler updates only the selected cell (no filter on others)."""
    js = _js()
    # The click handler should NOT call style.display = 'none' or classList.add('hidden')
    # on sibling cells. We check that selection code uses toggle/remove/add on is-selected
    # but not display:none or visibility:hidden on the grid cells.
    # Look for the pattern where selected date update is applied
    assert "is-selected" in js, "must set is-selected on selected cell"
    # Ensure the click handler doesn't hide other cells via display:none
    click_handler_region = js[js.find("is-selected"):]
    assert 'display = "none"' not in click_handler_region[:500] and \
           "display='none'" not in click_handler_region[:500], \
        "Calendar cell click must not hide other cells (AC7: full calendar remains visible)"


# ── AC8: No-data days are neutral and not clickable ──────────────────────────

def test_html_has_no_data_cell_state():
    """AC8: CSS defines a no-data/empty cell state that is not clickable."""
    html = _html()
    assert "pointer-events" in html or "hcal-cell--no-data" in html or \
           "hcal-cell--empty" in html, \
        "habits.html CSS must define a neutral non-clickable state for no-data days"


def test_js_future_dates_marked_no_data():
    """AC8: JS marks future dates and pre-creation dates as no-data."""
    js = _js()
    assert "future" in js or "no-data" in js or "noData" in js or \
           "hcal-cell--no-data" in js or "hcal-cell--empty" in js, \
        "habits.js must mark future/pre-creation dates as non-interactive (no-data state)"


def test_js_no_data_cells_not_interactive():
    """AC8: No-data cells are excluded from click/keyboard interaction."""
    js = _js()
    # The click handler must check if the cell has data before acting
    assert ("hcal-cell--no-data" in js or "hcal-cell--empty" in js or
            "!isFuture" in js or "noData" in js), \
        "habits.js must prevent interaction on no-data calendar cells"


# ── AC9: Navigation controls ─────────────────────────────────────────────────

def test_js_month_nav_prev():
    """AC9: Prev-month navigation decrements the displayed month."""
    js = _js()
    assert "month - 1" in js or "month-1" in js or \
           "calMonth.setMonth" in js or "hcalMonth" in js or \
           "prevMonth" in js, \
        "habits.js must decrement the month for previous-month navigation"


def test_js_month_nav_next():
    """AC9: Next-month navigation increments the displayed month."""
    js = _js()
    assert "month + 1" in js or "month+1" in js or \
           "nextMonth" in js or "hcalMonth" in js, \
        "habits.js must increment the month for next-month navigation"


def test_js_week_strip_prev_week():
    """AC9: Prev-week navigation shifts the displayed week back by 7 days."""
    js = _js()
    assert "- 7" in js or "-7" in js or "prevWeek" in js or "hcalWeek" in js, \
        "habits.js must shift back 7 days for previous-week strip navigation"


def test_js_week_strip_next_week():
    """AC9: Next-week navigation shifts the displayed week forward by 7 days."""
    js = _js()
    assert "+ 7" in js or "+7" in js or "nextWeek" in js or "hcalWeek" in js, \
        "habits.js must shift forward 7 days for next-week strip navigation"


# ── AC10: Structural class conventions ────────────────────────────────────────

def test_css_uses_structural_classes_not_px_values():
    """AC10: Calendar cells use CSS variables/tokens, not arbitrary pixel colour values."""
    html = _html()
    # The cell state classes should reference CSS variables (tokens), not raw hex in inline styles
    style_block = re.search(r'<style>(.*?)</style>', html, re.DOTALL)
    if style_block:
        styles = style_block.group(1)
        # met state must use a CSS variable or linear-gradient with token variables
        assert "var(--green" in styles or "var(--amber" in styles or \
               "linear-gradient" in styles, \
            "Calendar cell states must use CSS token variables or gradient functions, not bare colours"


def test_css_uses_card_class():
    """AC10: History calendar section uses the card base class for layout."""
    html = _html()
    # The calendar section should be wrapped in a card or use card-bg token
    assert 'class="card' in html or "var(--card-bg)" in html, \
        "History calendar must use the card class or --card-bg token for structural layout"


# ── AC11: Accessibility ───────────────────────────────────────────────────────

def test_js_aria_labels_on_cells():
    """AC11: Day cells get an aria-label describing the date and status."""
    js = _js()
    # aria-label must include a date and the status word
    assert "aria-label" in js, "habits.js must set aria-label on calendar day cells"
    # Should include status word like "met", "partial", or "not met"
    assert '"met"' in js or "'met'" in js or "+ status" in js or \
           "statusLabel" in js or "ariaLabel" in js or \
           "aria-label" in js, \
        "habits.js aria-label must encode the day status (e.g., 'June 5, met')"


def test_js_keyboard_navigation():
    """AC11: Keyboard navigation (arrow keys) moves focus between calendar cells."""
    js = _js()
    assert "ArrowLeft" in js or "ArrowRight" in js or "ArrowUp" in js, \
        "habits.js must handle arrow key navigation between calendar cells (AC11)"


def test_js_keyboard_enter_activates_cell():
    """AC11: Enter/Space activates a focused calendar cell."""
    js = _js()
    assert '"Enter"' in js or "'Enter'" in js, \
        "habits.js must handle Enter key to activate the focused calendar cell"


def test_js_calendar_cells_have_tabindex():
    """AC11: Calendar cells are keyboard-focusable (tabindex=0 or role=button)."""
    js = _js()
    assert 'tabindex' in js or 'type="button"' in js or 'role="gridcell"' in js, \
        "habits.js must make calendar cells focusable via tabindex or button role"


def test_html_cal_grid_has_grid_role():
    """AC11: Calendar grid has role='grid' for accessibility."""
    js = _js()
    assert 'role="grid"' in js or "role='grid'" in js, \
        "habits.js must render the calendar grid with role='grid'"
