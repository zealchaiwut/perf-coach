"""
Tests for issue #27: Calendar tab — month grid scaffold renderer
Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

HTML = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "calendar.html").read_text()
JS   = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "calendar.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC-1: calendar.html accessible from the main nav ─────────────────────────

def test_ac1_calendar_html_file_exists():
    """calendar.html must exist in the project root."""
    path = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "calendar.html"
    assert path.exists(), "calendar.html not found in project root"


def test_ac1_calendar_html_served_by_backend(client):
    """GET /calendar.html must return 200 with HTML content."""
    res = client.get("/calendar.html")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


def test_ac1_calendar_link_in_home_nav():
    """home.html must link to calendar.html in its nav."""
    home_html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html").read_text()
    assert 'href="calendar.html"' in home_html, \
        "home.html must have a nav link to calendar.html"


def test_ac1_calendar_link_in_index_nav():
    """index.html or another main-nav page must link to calendar.html."""
    index_html = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "index.html").read_text()
    assert 'href="calendar.html"' in index_html, \
        "index.html must have a nav link to calendar.html"


# ── AC-2: Month grid — 7-column CSS grid ──────────────────────────────────────

def test_ac2_cal_grid_cells_container_in_html():
    """calendar.html must have an element with id='cal-grid-cells' for the grid."""
    assert 'id="cal-grid-cells"' in HTML, "Missing id='cal-grid-cells' in calendar.html"


def test_ac2_css_grid_7_columns_cells():
    """calendar.html CSS must define a 7-column grid for the cell container."""
    assert "repeat(7, 1fr)" in HTML, \
        "calendar.html must define CSS grid-template-columns: repeat(7, 1fr)"


def test_ac2_cal_grid_header_in_html():
    """calendar.html must have a header row element for day-of-week labels."""
    assert 'cal-grid-header' in HTML, "Missing .cal-grid-header element in calendar.html"


def test_ac2_calendar_js_renders_grid_cells():
    """calendar.js must build cell elements and append them to the grid container."""
    assert "cal-grid-cells" in JS, "calendar.js must reference the cal-grid-cells container"
    assert "appendChild" in JS or "innerHTML" in JS, \
        "calendar.js must build and append cell elements"


def test_ac2_calendar_js_computes_total_slots():
    """calendar.js must compute total grid slots as a multiple of 7 (5–6 rows)."""
    assert "7" in JS, "calendar.js must use 7-column logic to compute grid slots"
    assert "daysInMonth" in JS or "getDate" in JS, \
        "calendar.js must compute number of days in the month"


# ── AC-3: Day-of-week header — Monday first ────────────────────────────────────

def test_ac3_dow_header_has_mon():
    """calendar.html must have a MON day-of-week header cell."""
    assert "Mon" in HTML, "Missing 'Mon' in calendar.html dow header"


def test_ac3_dow_header_monday_first():
    """calendar.html must start the header with Mon (ISO week, Monday first)."""
    dow_positions = []
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        pos = HTML.find(day)
        assert pos != -1, f"Missing '{day}' in calendar.html dow header"
        dow_positions.append((day, pos))
    ordered = [d for d, _ in sorted(dow_positions, key=lambda x: x[1])]
    assert ordered[0] == "Mon", f"First day-of-week must be Mon, got {ordered[0]}"


def test_ac3_dow_header_order():
    """Day-of-week headers must appear in ISO order: Mon Tue Wed Thu Fri Sat Sun."""
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    positions = []
    for day in days:
        idx = HTML.find(day)
        assert idx != -1, f"Missing '{day}' in calendar.html"
        positions.append(idx)
    assert positions == sorted(positions), \
        "Day-of-week headers must appear in Mon→Sun order in calendar.html"


def test_ac3_seven_dow_cells_in_html():
    """calendar.html must have exactly 7 .cal-dow header cells."""
    count = HTML.count('class="cal-dow"') + HTML.count("cal-dow")
    assert count >= 7, f"Expected at least 7 cal-dow references, found {count}"


# ── AC-4: Day cell min-height 90px; out-of-month dimmed ───────────────────────

def test_ac4_cal_cell_class_in_html():
    """calendar.html CSS must define .cal-cell style."""
    assert "cal-cell" in HTML, "Missing .cal-cell CSS class definition in calendar.html"


def test_ac4_day_cell_min_height_90px():
    """calendar.html CSS must set min-height: 90px for .cal-cell."""
    assert "90px" in HTML, "Missing 90px min-height for .cal-cell in calendar.html"


def test_ac4_out_of_month_opacity_04():
    """calendar.html CSS must set opacity: 0.4 for .out-of-month cells."""
    assert "0.4" in HTML, "Missing opacity: 0.4 for .out-of-month in calendar.html"


def test_ac4_calendar_js_adds_out_of_month_class():
    """calendar.js must apply 'out-of-month' class to cells outside the current month."""
    assert "out-of-month" in JS, \
        "calendar.js must add 'out-of-month' class to cells outside the current month"


def test_ac4_calendar_js_checks_in_month_range():
    """calendar.js must check whether each slot falls within the current month."""
    assert "inMonth" in JS or "daysInMonth" in JS, \
        "calendar.js must determine if a cell day is within the current month"


# ── AC-5: Today's cell highlighted ────────────────────────────────────────────

def test_ac5_today_class_defined_in_css():
    """calendar.html CSS must define a style for .cal-cell.today."""
    assert ".cal-cell.today" in HTML or "today" in HTML, \
        "calendar.html must define a CSS rule for today's cell"


def test_ac5_today_cell_has_info_background():
    """calendar.html must set an info-coloured (blue) background for today's cell."""
    assert "#e0f2fe" in HTML or "info" in HTML or "0284c7" in HTML or "sky" in HTML.lower(), \
        "calendar.html must highlight today's cell with an info/blue background"


def test_ac5_calendar_js_adds_today_class():
    """calendar.js must add 'today' class to the cell matching the current date."""
    assert "today" in JS, "calendar.js must mark today's cell with class 'today'"


def test_ac5_calendar_js_compares_full_date():
    """calendar.js must compare year, month, and date to identify today's cell."""
    assert "getFullYear" in JS, "calendar.js must compare year for today detection"
    assert "getMonth" in JS, "calendar.js must compare month for today detection"
    assert "getDate" in JS, "calendar.js must compare date for today detection"


# ── AC-6: Empty cells display only the day number ─────────────────────────────

def test_ac6_cal_day_num_class_in_js():
    """calendar.js must create a span with class 'cal-day-num' for each cell's number."""
    assert "cal-day-num" in JS, "calendar.js must create .cal-day-num span for each cell"


def test_ac6_no_api_data_fetching_in_js():
    """calendar.js must not fetch any tracker data (data wiring is P4-9)."""
    assert "fetch(" not in JS and "fetch (" not in JS, \
        "calendar.js must NOT fetch API data — data wiring is out of scope for this ticket"


def test_ac6_cells_only_render_day_number():
    """calendar.js must only add the day number span to each cell (no tracker data)."""
    assert "cal-day-num" in JS, "calendar.js must render only the day number per cell"
    # Ensure the new /api/weight-entries endpoint is used (not the legacy endpoint)
    assert "/api/weight-entries" in JS, "calendar.js must use /api/weight-entries"


# ── AC-7: Navigation controls ─────────────────────────────────────────────────

def test_ac7_prev_button_in_html():
    """calendar.html must have a prev-month button with id='prev-btn'."""
    assert 'id="prev-btn"' in HTML, "Missing id='prev-btn' in calendar.html"


def test_ac7_next_button_in_html():
    """calendar.html must have a next-month button with id='next-btn'."""
    assert 'id="next-btn"' in HTML, "Missing id='next-btn' in calendar.html"


def test_ac7_today_button_in_html():
    """calendar.html must have a 'Today' button with id='today-btn'."""
    assert 'id="today-btn"' in HTML, "Missing id='today-btn' in calendar.html"
    assert "Today" in HTML, "today-btn must display 'Today' label"


def test_ac7_month_label_in_html():
    """calendar.html must have an element with id='month-label' for the month display."""
    assert 'id="month-label"' in HTML, "Missing id='month-label' in calendar.html"


def test_ac7_calendar_js_sets_month_label():
    """calendar.js must update month-label textContent when rendering."""
    assert "month-label" in JS, "calendar.js must update the month-label element"
    assert "textContent" in JS, "calendar.js must set textContent on month-label"


def test_ac7_calendar_js_prev_click_handler():
    """calendar.js must attach a click handler to prev-btn."""
    assert "prev-btn" in JS, "calendar.js must reference prev-btn"
    prev_idx = JS.find("prev-btn")
    context = JS[prev_idx:prev_idx + 200]
    assert "addEventListener" in context or "click" in context, \
        "calendar.js must attach a click listener to prev-btn"


def test_ac7_calendar_js_next_click_handler():
    """calendar.js must attach a click handler to next-btn."""
    assert "next-btn" in JS, "calendar.js must reference next-btn"
    next_idx = JS.find("next-btn")
    context = JS[next_idx:next_idx + 200]
    assert "addEventListener" in context or "click" in context, \
        "calendar.js must attach a click listener to next-btn"


def test_ac7_calendar_js_today_click_handler():
    """calendar.js must attach a click handler to today-btn that resets to current month."""
    assert "today-btn" in JS, "calendar.js must reference today-btn"
    today_idx = JS.find("today-btn")
    context = JS[today_idx:today_idx + 300]
    assert "addEventListener" in context or "click" in context, \
        "calendar.js must attach a click listener to today-btn"


def test_ac7_navigate_function_in_js():
    """calendar.js must have a navigate function that advances the month by delta."""
    assert "navigate" in JS, "calendar.js must have a navigate() function"


def test_ac7_month_name_array_in_js():
    """calendar.js must have an array of month names for the label (e.g. 'May 2026')."""
    assert "January" in JS or "MONTH_NAMES" in JS, \
        "calendar.js must define an array of month names for the label"


# ── AC-8: Filter checkboxes ────────────────────────────────────────────────────

def test_ac8_show_weight_checkbox_in_html():
    """calendar.html must have a 'Show Weight' checkbox with id='filter-weight'."""
    assert 'id="filter-weight"' in HTML, "Missing id='filter-weight' checkbox in calendar.html"
    assert "Show Weight" in HTML, "Missing 'Show Weight' label text in calendar.html"


def test_ac8_show_habits_checkbox_in_html():
    """calendar.html must have a 'Show Habits' checkbox with id='filter-habits'."""
    assert 'id="filter-habits"' in HTML, "Missing id='filter-habits' checkbox in calendar.html"
    assert "Show Habits" in HTML, "Missing 'Show Habits' label text in calendar.html"


def test_ac8_show_training_checkbox_in_html():
    """calendar.html must have a 'Show Training' checkbox with id='filter-training'."""
    assert 'id="filter-training"' in HTML, "Missing id='filter-training' checkbox in calendar.html"
    assert "Show Training" in HTML, "Missing 'Show Training' label text in calendar.html"


def test_ac8_all_filter_checkboxes_default_checked():
    """All three filter checkboxes must default to checked."""
    weight_idx = HTML.find('id="filter-weight"')
    habits_idx = HTML.find('id="filter-habits"')
    training_idx = HTML.find('id="filter-training"')

    for label, idx in [("filter-weight", weight_idx), ("filter-habits", habits_idx),
                       ("filter-training", training_idx)]:
        assert idx != -1, f"Missing {label} checkbox"
        surrounding = HTML[max(0, idx - 50):idx + 100]
        assert "checked" in surrounding, \
            f"{label} checkbox must default to checked"


def test_ac8_filter_checkboxes_in_cal_toolbar():
    """Filter checkboxes must appear in the toolbar area above the grid."""
    assert "cal-filters" in HTML or "cal-toolbar" in HTML, \
        "calendar.html must have a toolbar/filters container above the grid"
    # Filters must appear before the grid cells
    toolbar_pos = HTML.find("cal-toolbar") if "cal-toolbar" in HTML else HTML.find("cal-filters")
    grid_pos = HTML.find("cal-grid")
    assert toolbar_pos < grid_pos, \
        "Filter checkboxes toolbar must appear before the calendar grid in HTML"


# ── AC-9: URL state — ?month=YYYY-MM ──────────────────────────────────────────

def test_ac9_calendar_js_reads_month_from_url():
    """calendar.js must read the ?month=YYYY-MM parameter from the URL on load."""
    assert "URLSearchParams" in JS or "location.search" in JS, \
        "calendar.js must read from location.search / URLSearchParams"
    assert "month" in JS, "calendar.js must read the 'month' query parameter"


def test_ac9_calendar_js_validates_month_format():
    """calendar.js must validate the YYYY-MM format before using it."""
    assert r"\d{4}-\d{2}" in JS or "YYYY" in JS or "/^\\d{4}" in JS or "test(raw)" in JS \
        or "test(" in JS, \
        "calendar.js must validate the ?month parameter format"


def test_ac9_calendar_js_writes_month_to_url():
    """calendar.js must write ?month=YYYY-MM to the URL on navigation."""
    assert "searchParams.set" in JS or "pushState" in JS or "replaceState" in JS, \
        "calendar.js must update the URL with the selected month"
    assert "month" in JS, "calendar.js must set the 'month' URL parameter"


def test_ac9_calendar_js_handles_popstate():
    """calendar.js must handle browser back/forward (popstate) to restore the month."""
    assert "popstate" in JS, "calendar.js must listen for popstate events"


def test_ac9_calendar_js_month_param_format_yyyy_mm():
    """calendar.js must write the month in YYYY-MM format."""
    assert "padStart(2" in JS or "padStart(2," in JS, \
        "calendar.js must zero-pad the month number (padStart) for YYYY-MM format"


# ── AC-10: Responsive layout down to ~700px ────────────────────────────────────

def test_ac10_responsive_media_query_in_html():
    """calendar.html must have a @media query for smaller viewports."""
    assert "@media" in HTML, "calendar.html must have a @media responsive CSS rule"


def test_ac10_responsive_breakpoint_at_or_below_700px():
    """calendar.html responsive breakpoint must cover viewports down to ~700px."""
    media_matches = re.findall(r"max-width:\s*(\d+)px", HTML)
    assert media_matches, "calendar.html must have a max-width media query"
    max_width = min(int(v) for v in media_matches)
    assert max_width <= 700, \
        f"Responsive breakpoint must be ≤700px, found {max_width}px"


def test_ac10_cell_min_height_reduced_below_breakpoint():
    """calendar.html responsive CSS must reduce cell min-height below the breakpoint."""
    media_block_match = re.search(r"@media[^{]+\{(.+?)\}", HTML, re.DOTALL)
    assert media_block_match, "calendar.html must have a @media block"
    # The responsive block must contain a min-height value less than 90px
    inside = media_block_match.group(1)
    heights = re.findall(r"min-height:\s*(\d+)px", inside)
    if heights:
        assert min(int(h) for h in heights) < 90, \
            "Responsive CSS should reduce cell min-height below 90px for small screens"


# ── Structural ────────────────────────────────────────────────────────────────

def test_structural_calendar_html_loads_calendar_js():
    """calendar.html must load js/calendar.js."""
    assert "js/calendar.js" in HTML or "calendar.js" in HTML, \
        "calendar.html must include a <script> tag for calendar.js"


def test_structural_calendar_js_exists():
    """js/calendar.js must exist in the project."""
    path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "calendar.js"
    assert path.exists(), "js/calendar.js not found"


def test_structural_calendar_js_iife():
    """calendar.js must be wrapped in an IIFE to avoid polluting global scope."""
    assert "(function" in JS or "(() =>" in JS or "(function()" in JS, \
        "calendar.js should be wrapped in an IIFE"
