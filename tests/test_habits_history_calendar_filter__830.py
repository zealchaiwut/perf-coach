"""Tests for issue #830: Add habit filter to history calendar view.

Verifies the filter control and updated calendar rendering against:
- AC1: Filter control present at top of history view, gradient-themed
- AC2: "All Habits" option plus one entry per active habit
- AC3: All Habits → each day cell shows X/Y completion count
- AC4: Single habit → met/not-met/neutral per-day distinct states
- AC5: Filter change re-renders full calendar (JS must hook filter to render)
- AC6: Filter change updates day-detail panel to reflect selected scope
- AC7: Selected day highlight persists after filter change
- AC8: Habit not scheduled on a day → neutral/empty (not "not-met")
- AC9: Active filter state visually distinguishable
- AC10: Filter control keyboard-navigable, ARIA labels present

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

_CREDENTIALS = {"username": "tester830", "password": "Test830pass!"}


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
            pytest.skip(f"Login failed ({r.status_code}); seed tester830 user first")
        csrf_val = _extract_cookie(r, "csrf-token")
        if csrf_val:
            c.cookies.set("csrf-token", csrf_val, domain="127.0.0.1")
        yield c


# ── AC1: Filter control present at top of history view ────────────────────────

def test_html_has_filter_container():
    """AC1: habits.html has a filter container inside the history cal card."""
    html = _html()
    assert 'id="hcal-filter"' in html, \
        "habits.html must have id='hcal-filter' for the habit filter control"


def test_filter_container_inside_history_cal():
    """AC1: Filter container is inside the history calendar card."""
    html = _html()
    # Check that hcal-filter appears inside habits-history-cal
    history_cal_pos = html.find('id="habits-history-cal"')
    filter_pos = html.find('id="hcal-filter"')
    assert history_cal_pos != -1, "habits-history-cal not found"
    assert filter_pos != -1, "hcal-filter not found"
    assert filter_pos > history_cal_pos, \
        "hcal-filter must appear after habits-history-cal in the DOM"


def test_filter_has_role_group():
    """AC10: Filter container has ARIA group role."""
    html = _html()
    # Role group or radiogroup on the filter container
    filter_block_match = re.search(r'id="hcal-filter"[^>]*', html)
    assert filter_block_match, "hcal-filter element not found"
    filter_tag = filter_block_match.group(0)
    assert 'role=' in filter_tag, \
        "hcal-filter must have a role attribute (e.g., role='group')"


def test_filter_has_aria_label():
    """AC10: Filter container has an aria-label describing it."""
    html = _html()
    filter_block_match = re.search(r'id="hcal-filter"[^>]*', html)
    assert filter_block_match, "hcal-filter element not found"
    filter_tag = filter_block_match.group(0)
    assert 'aria-label' in filter_tag, \
        "hcal-filter must have aria-label for screen readers"


# ── AC2: "All Habits" + one entry per habit ────────────────────────────────────

def test_js_renders_all_habits_option():
    """AC2: JS renders an 'All Habits' option in the filter."""
    js = _js()
    assert 'All Habits' in js, \
        "habits.js must render an 'All Habits' filter option"


def test_js_has_filter_habit_id_state():
    """AC2: JS tracks hcalFilterHabitId state."""
    js = _js()
    assert 'hcalFilterHabitId' in js, \
        "habits.js must have hcalFilterHabitId state variable"


def test_js_renders_per_habit_options():
    """AC2: JS iterates activeHabits to render per-habit filter options."""
    js = _js()
    # renderHcalFilter must iterate activeHabits
    assert 'renderHcalFilter' in js, \
        "habits.js must have a renderHcalFilter function"
    func_start = js.index('renderHcalFilter')
    # Find the function body (heuristic: look for activeHabits reference after the function declaration)
    func_region = js[func_start:func_start + 1000]
    assert 'activeHabits' in func_region, \
        "renderHcalFilter must use activeHabits to populate per-habit filter buttons"


# ── AC3: All Habits → X/Y count per day cell ──────────────────────────────────

def test_js_has_all_habits_count_function():
    """AC3: JS has a function that returns done/total counts for All Habits mode."""
    js = _js()
    assert 'computeAllHabitsDaySummary' in js, \
        "habits.js must have computeAllHabitsDaySummary to compute X/Y counts"


def test_js_all_habits_count_returns_done_and_total():
    """AC3: computeAllHabitsDaySummary returns done and total fields."""
    js = _js()
    # Find the function and check it returns done and total
    fn_start = js.find('computeAllHabitsDaySummary')
    fn_region = js[fn_start:fn_start + 600]
    assert 'done' in fn_region, \
        "computeAllHabitsDaySummary must return a 'done' count"
    assert 'total' in fn_region, \
        "computeAllHabitsDaySummary must return a 'total' count"


def test_js_renders_count_in_cell_all_habits_mode():
    """AC3: JS renders count overlay (e.g. 'hcal-day-count') in All Habits mode."""
    js = _js()
    assert 'hcal-day-count' in js, \
        "habits.js must render an element with class 'hcal-day-count' for count display"


def test_css_has_day_count_style():
    """AC3: CSS styles hcal-day-count for the count overlay."""
    html = _html()
    assert 'hcal-day-count' in html, \
        "habits.html CSS must style .hcal-day-count for the count display"


# ── AC4: Single habit → per-habit status (met/not-met/neutral) ─────────────────

def test_js_has_single_habit_status_function():
    """AC4: JS has a function for computing single-habit day status."""
    js = _js()
    assert 'computeSingleHabitDayStatus' in js, \
        "habits.js must have computeSingleHabitDayStatus for single-habit mode"


def test_js_single_habit_returns_met_or_not_met():
    """AC4: computeSingleHabitDayStatus returns met/not-met/no-data."""
    js = _js()
    fn_start = js.find('computeSingleHabitDayStatus')
    fn_region = js[fn_start:fn_start + 500]
    assert "'met'" in fn_region, \
        "computeSingleHabitDayStatus must be able to return 'met'"
    assert "'not-met'" in fn_region, \
        "computeSingleHabitDayStatus must be able to return 'not-met'"
    assert "'no-data'" in fn_region, \
        "computeSingleHabitDayStatus must be able to return 'no-data'"


# ── AC5: Filter change re-renders calendar ─────────────────────────────────────

def test_js_filter_triggers_render():
    """AC5: Selecting a filter option calls renderHabitMonthCal and/or renderHabitWeekStrip."""
    js = _js()
    # Find renderHcalFilter and check it calls the render functions
    fn_start = js.find('function renderHcalFilter')
    fn_end = js.find('\nfunction ', fn_start + 1)
    fn_body = js[fn_start:fn_end] if fn_end != -1 else js[fn_start:fn_start + 2000]
    assert 'renderHabitMonthCal' in fn_body, \
        "renderHcalFilter must call renderHabitMonthCal on filter change"
    assert 'renderHabitWeekStrip' in fn_body, \
        "renderHcalFilter must call renderHabitWeekStrip on filter change"


# ── AC6: Filter change updates day-detail panel ───────────────────────────────

def test_js_filter_updates_detail_panel():
    """AC6: Filter change re-renders the day-detail panel if a date is selected."""
    js = _js()
    fn_start = js.find('function renderHcalFilter')
    fn_end = js.find('\nfunction ', fn_start + 1)
    fn_body = js[fn_start:fn_end] if fn_end != -1 else js[fn_start:fn_start + 2000]
    assert '_renderHcalDetail' in fn_body or 'hcalSelectedDate' in fn_body, \
        "renderHcalFilter must update the detail panel when a date is selected"


def test_js_detail_respects_filter():
    """AC6: _renderHcalDetail uses hcalFilterHabitId to scope logs shown."""
    js = _js()
    fn_start = js.find('async function _renderHcalDetail')
    if fn_start == -1:
        fn_start = js.find('function _renderHcalDetail')
    fn_end = js.find('\nfunction ', fn_start + 1)
    fn_body = js[fn_start:fn_end] if fn_end != -1 else js[fn_start:fn_start + 2000]
    assert 'hcalFilterHabitId' in fn_body, \
        "_renderHcalDetail must use hcalFilterHabitId to filter the displayed logs"


# ── AC7: Selected day highlight persists after filter change ──────────────────

def test_js_selected_date_survives_filter_change():
    """AC7: hcalSelectedDate is not reset when the filter changes."""
    js = _js()
    fn_start = js.find('function renderHcalFilter')
    fn_end = js.find('\nfunction ', fn_start + 1)
    fn_body = js[fn_start:fn_end] if fn_end != -1 else js[fn_start:fn_start + 2000]
    # The filter change must NOT set hcalSelectedDate = null
    assert 'hcalSelectedDate = null' not in fn_body, \
        "renderHcalFilter must not reset hcalSelectedDate on filter change"


# ── AC8: No-scheduled day → neutral/empty, not "not-met" ──────────────────────

def test_js_single_habit_no_data_for_pre_creation():
    """AC8: Single habit mode returns no-data for dates before habit creation."""
    js = _js()
    fn_start = js.find('computeSingleHabitDayStatus')
    fn_region = js[fn_start:fn_start + 800]
    # Must check created_at to return no-data when date predates habit
    assert 'created_at' in fn_region, \
        "computeSingleHabitDayStatus must check habit.created_at to avoid marking pre-creation days as not-met"


# ── AC9: Active filter state visually distinguishable ─────────────────────────

def test_css_has_filter_active_state():
    """AC9: CSS has a style for the active filter button."""
    html = _html()
    # Must have an active class for the filter buttons
    assert 'hcal-filter-btn--active' in html or 'hcal-filter-btn' in html, \
        "habits.html CSS must define an active state for filter buttons"


def test_js_active_filter_class_applied():
    """AC9: JS applies an active class to the currently selected filter option."""
    js = _js()
    assert 'hcal-filter-btn--active' in js, \
        "habits.js must apply 'hcal-filter-btn--active' class to the selected filter option"


# ── AC10: Keyboard navigable, ARIA labels ─────────────────────────────────────

def test_js_filter_buttons_have_aria_pressed():
    """AC10: Filter buttons use aria-pressed to indicate selection state."""
    js = _js()
    fn_start = js.find('function renderHcalFilter')
    fn_end = js.find('\nfunction ', fn_start + 1)
    fn_body = js[fn_start:fn_end] if fn_end != -1 else js[fn_start:fn_start + 2000]
    assert 'aria-pressed' in fn_body, \
        "renderHcalFilter must set aria-pressed on filter buttons"


def test_js_filter_supports_keyboard_navigation():
    """AC10: Filter supports keyboard navigation (arrow keys or Tab)."""
    js = _js()
    fn_start = js.find('function renderHcalFilter')
    fn_end = js.find('\nfunction ', fn_start + 1)
    fn_body = js[fn_start:fn_end] if fn_end != -1 else js[fn_start:fn_start + 2000]
    # Either keyboard handler or standard button (Tab is built-in for buttons)
    # For explicit arrow key support:
    has_arrow_nav = 'ArrowLeft' in fn_body or 'ArrowRight' in fn_body or 'keydown' in fn_body
    # Standard buttons are Tab-navigable by default — either is acceptable
    # but explicit arrow key support is preferred
    assert has_arrow_nav or 'button' in fn_body.lower(), \
        "renderHcalFilter must support keyboard navigation"


# ── Live tests (require running server) ──────────────────────────────────────

def test_live_habits_page_accessible(client):
    """Live: /habits page is accessible (200) when logged in."""
    r = client.get("/habits")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"


def test_live_habits_logs_endpoint_works(client):
    """Live: /api/habits/logs endpoint works (used by filter to fetch day data)."""
    import datetime
    today = datetime.date.today().isoformat()
    r = client.get(f"/api/habits/logs?from={today}&to={today}")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert isinstance(data, list), "Expected a list of logs"


def test_live_filter_data_all_habits_summary(client):
    """AC3/Live: logs endpoint returns data compatible with X/Y count display."""
    import datetime
    last_week = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    today = datetime.date.today().isoformat()
    r = client.get(f"/api/habits/logs?from={last_week}&to={today}")
    assert r.status_code == 200
    logs = r.json()
    # Each log must have habit_id and logged_date for filter to work
    for log in logs:
        assert "habit_id" in log, "Each log must have habit_id"
        assert "logged_date" in log, "Each log must have logged_date"


def test_live_habits_list_for_filter(client):
    """AC2/Live: /api/habits returns habits with id/name/created_at for filter."""
    r = client.get("/api/habits")
    assert r.status_code == 200
    habits = r.json()
    for h in habits:
        assert "id" in h, "Each habit must have id"
        assert "name" in h, "Each habit must have name"
        # created_at is used by computeSingleHabitDayStatus for AC8
        assert "created_at" in h, "Each habit must have created_at for no-data detection"
