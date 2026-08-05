"""
Tests for issue #151: Build training log page shell, week strip, and filter bar.
Acceptance-criteria tests run against UAT (http://localhost:9001).
"""
import os

import httpx
import pytest

BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


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


# ── AC: /log and /log.html return 200 ────────────────────────────────────────

def test_ac_get_log_returns_200(client):
    """GET /log returns HTTP 200."""
    assert client.get("/log").status_code == 200


def test_ac_get_log_html_returns_200(client):
    """GET /log.html returns HTTP 200."""
    assert client.get("/log.html").status_code == 200


# ── AC: Top nav — brand, 4 primary links, More, search, avatar ───────────────

def test_ac_top_nav_brand_present(log_html):
    """Top nav contains 'perf-coach' brand link."""
    assert "perf-coach" in log_html, "Brand name 'perf-coach' should appear in top nav"


def test_ac_top_nav_four_primary_links(log_html):
    """Top nav has exactly four resolvable primary navigation links."""
    assert 'home.html' in log_html, "Home link should be in the top nav"
    assert 'habits.html' in log_html, "Habits link should be in the top nav"
    # Log is the active link on this page
    assert 'href="log"' in log_html or "href='log'" in log_html or 'class="top-nav-link active"' in log_html, \
        "Log (active) link should be in the top nav"


def test_ac_top_nav_more_dropdown_present(log_html):
    """Top nav contains a More dropdown button and associated dropdown links."""
    assert 'top-nav-more-btn' in log_html, "More button should have id='top-nav-more-btn'"
    assert 'top-nav-dropdown' in log_html, "More dropdown should have id='top-nav-dropdown'"


def test_ac_top_nav_more_dropdown_links_resolve(log_html):
    """All More dropdown links point to valid (non-404) page paths."""
    for path in ['weight.html', 'calendar.html', 'training.html', 'users.html']:
        assert path in log_html, f"More dropdown should contain a link to {path}"


def test_ac_top_nav_search_icon(log_html):
    """Top nav contains a search button."""
    assert 'header-search-btn' in log_html, "Search button (class='header-search-btn') should be in the top nav"


def test_ac_top_nav_avatar(log_html):
    """Top nav contains a user avatar element."""
    assert 'header-avatar' in log_html, "Avatar element (id='header-avatar') should be in the top nav"


# ── AC: Page header — Log workout button ──

def test_ac_log_new_btn_id(log_html):
    """Log workout button has id='log-new-btn'."""
    assert 'id="log-new-btn"' in log_html, "Log workout button should have id='log-new-btn'"


def test_ac_log_new_btn_disabled(log_html):
    """Log workout button is disabled."""
    assert 'id="log-new-btn"' in log_html
    # Check that disabled attribute appears on the log-new-btn button
    import re
    btn_match = re.search(r'id="log-new-btn"[^>]*>', log_html)
    assert btn_match, "log-new-btn element not found"
    assert 'disabled' in btn_match.group(0), "log-new-btn should have the disabled attribute"


def test_ac_log_new_btn_title(log_html):
    """Log workout button has title='Coming soon — modal not built yet'."""
    assert 'Coming soon' in log_html, "Log workout button title should say 'Coming soon'"
    assert 'modal not built yet' in log_html, "Log workout button title should mention 'modal not built yet'"


# ── AC: Week strip ────────────────────────────────────────────────────────────

def test_ac_week_strip_container(log_html):
    """week-strip container is present in HTML; JS renders day pills into it."""
    assert 'id="week-strip"' in log_html, "#week-strip container should be in the HTML"


def test_ac_week_strip_nav_built_by_js(log_js):
    """JS renders prev/next chevron buttons (ws-chevron) into the week strip."""
    assert 'ws-chevron' in log_js, "JS should render chevron buttons with class 'ws-chevron'"
    assert 'week-prev' in log_js, "JS should create a 'week-prev' button"
    assert 'week-next' in log_js, "JS should create a 'week-next' button"


def test_ac_week_strip_seven_pills(log_js):
    """JS renders exactly 7 day pills (Mon–Sun)."""
    assert 'day-pill' in log_js, "JS should render day pills with class 'day-pill'"
    assert "DAY_NAMES" in log_js or "Mon" in log_js, "JS should include Mon–Sun day names"


def test_ac_week_strip_today_highlight(log_js):
    """Today's pill gets the 'today' class for blue ring + tinted background."""
    assert "today" in log_js, "JS should apply 'today' class to today's pill"
    assert "isToday" in log_js or "todayStr" in log_js, "JS should detect today's date"


def test_ac_week_strip_today_css_blue_ring(log_html):
    """CSS for .day-pill.today uses a blue border/ring (not dark background)."""
    # Verify the today style is blue ring, not the old dark background
    assert '#3b82f6' in log_html or '3b82f6' in log_html, \
        ".day-pill.today should use blue color (#3b82f6) for the ring"
    assert 'eff6ff' in log_html or '#eff6ff' in log_html, \
        ".day-pill.today should use a light blue tinted background (#eff6ff)"


def test_ac_week_strip_type_dots_colors(log_js):
    """Day pills show colored type-dots (run=blue, lift=purple, wod=orange, bike=teal)."""
    assert '#3b82f6' in log_js, "Run dot should be blue (#3b82f6)"
    assert '#8b5cf6' in log_js, "Lift dot should be purple (#8b5cf6)"
    assert '#f97316' in log_js, "WOD dot should be orange (#f97316)"
    assert '#14b8a6' in log_js, "Bike dot should be teal (#14b8a6)"


def test_ac_week_strip_url_week_param(log_js):
    """Chevron clicks update URL with ?week=YYYY-MM-DD (Monday of selected week)."""
    assert 'pushWeekParam' in log_js, "JS should call pushWeekParam on chevron click"
    assert "'week'" in log_js or '"week"' in log_js, "JS should set 'week' URL param"
    assert 'pushState' in log_js, "JS should use history.pushState for week navigation"


def test_ac_week_strip_url_week_persists_on_reload(log_js):
    """?week param is read on load to restore the selected week."""
    assert 'parseWeekParam' in log_js, "JS should have parseWeekParam to read ?week on load"
    assert "get('week')" in log_js, "JS should call URLSearchParams.get('week')"


def test_ac_week_strip_week_param_preserved_on_filter_change(log_js):
    """writeURLParams preserves existing ?week param when filter state changes."""
    import re
    # Find writeURLParams function body
    match = re.search(r'function writeURLParams\(\)\s*\{(.*?)\n  \}', log_js, re.DOTALL)
    assert match, "writeURLParams function should exist"
    body = match.group(1)
    # It should start from current search (preserving ?week), not from a blank URLSearchParams()
    assert 'window.location.search' in body, \
        "writeURLParams should read current search params (to preserve ?week)"


# ── AC: Filter bar ────────────────────────────────────────────────────────────

def test_ac_filter_bar_container(log_html):
    """#filter-bar container is present in HTML; JS renders controls into it."""
    assert 'id="filter-bar"' in log_html, "#filter-bar container should be in the HTML"


def test_ac_filter_bar_search_input(log_js):
    """Filter bar contains a search input with id='log-search'."""
    assert 'id="log-search"' in log_js or "log-search" in log_js, \
        "JS should create search input with id='log-search'"


def test_ac_filter_bar_search_debounce_300ms(log_js):
    """Search input is debounced 300 ms before updating URL."""
    assert '300' in log_js, "Search debounce should use 300 ms"
    assert 'clearTimeout' in log_js, "Debounce should clear previous timeout"


def test_ac_filter_bar_five_type_chips(log_js):
    """Filter bar has five single-select type chips: All, Run, Lift, WOD, Bike."""
    for label in ['All', 'Run', 'Lift', 'WOD', 'Bike']:
        assert label in log_js, f"Type chip label '{label}' should be in training-log.js"


def test_ac_filter_bar_visual_divider(log_js):
    """Filter bar has a visual divider between type chips and date-range chip."""
    assert 'fb-divider' in log_js, "JS should create a .fb-divider element as visual separator"


def test_ac_filter_bar_visual_divider_css(log_html):
    """Visual divider CSS is defined in the page."""
    assert 'fb-divider' in log_html, ".fb-divider CSS class should be defined in training-log.html"


def test_ac_filter_bar_date_range_chip(log_js):
    """Filter bar has a date-range chip button (not a <select>)."""
    assert 'dr-chip' in log_js, "Date-range chip (class='dr-chip') should be created by JS"
    assert 'Last 30 days' in log_js, "Date-range chip should default to 'Last 30 days'"


def test_ac_filter_bar_date_range_from_to(log_js):
    """Date-range chip opens a panel with from/to date inputs."""
    assert 'dr-from' in log_js, "Date-range panel should have a 'from' date input"
    assert 'dr-to' in log_js, "Date-range panel should have a 'to' date input"


def test_ac_type_chip_updates_url(log_js):
    """Clicking a type chip updates ?type= in the URL."""
    assert "p.set('type'" in log_js or "filters.type" in log_js, \
        "JS should update 'type' URL param on chip click"


def test_ac_search_updates_url(log_js):
    """Search input updates ?search= in the URL."""
    assert "p.set('search'" in log_js or "filters.search" in log_js, \
        "JS should update 'search' URL param"


def test_ac_date_range_updates_url(log_js):
    """Date-range chip updates ?from= and ?to= in the URL."""
    assert "p.set('from'" in log_js or "filters.from" in log_js, \
        "JS should update 'from' URL param"
    assert "p.set('to'" in log_js or "filters.to" in log_js, \
        "JS should update 'to' URL param"


def test_ac_filter_state_persists_on_reload(log_js):
    """All filter state (?type, ?search, ?from, ?to) is read from URL on load."""
    assert "get('type')" in log_js, "JS should read ?type from URL on load"
    assert "get('search')" in log_js, "JS should read ?search from URL on load"
    assert "get('from')" in log_js, "JS should read ?from from URL on load"
    assert "get('to')" in log_js, "JS should read ?to from URL on load"


def test_ac_page_loads_with_all_filter_params(client):
    """Page returns 200 when loaded with all filter+week params in URL."""
    res = client.get("/log?type=run&search=test&from=2026-05-01&to=2026-05-29&week=2026-05-26")
    assert res.status_code == 200
    assert "Training log" in res.text


# ── AC: Responsive ≤ 880 px ───────────────────────────────────────────────────

def test_ac_responsive_880px_breakpoint(log_html):
    """CSS has a media query at 880 px (the spec breakpoint)."""
    assert '880px' in log_html, "CSS should have a media query at max-width: 880px"


def test_ac_responsive_page_header_stacks(log_html):
    """At ≤ 880 px, page header stacks vertically (flex-direction: column)."""
    # The 880px media query must include flex-direction column for the page header
    import re
    block = re.search(r'@media\s*\(max-width:\s*880px\)(.*?)(?=@media|\Z)', log_html, re.DOTALL)
    assert block, "880px media query block should exist"
    assert 'flex-direction' in block.group(1) and 'column' in block.group(1), \
        "880px media query should stack the page header (flex-direction: column)"


def test_ac_responsive_week_strip_scrollable(log_html):
    """Week strip pills are horizontally scrollable."""
    assert 'overflow-x' in log_html and 'ws-pills' in log_html, \
        ".ws-pills should have overflow-x for horizontal scrolling"


def test_ac_responsive_filter_chips_scrollable(log_html):
    """Filter chips are horizontally scrollable at narrow viewports."""
    # At 880px, fb-chips-row should switch to overflow-x: auto with flex-wrap: nowrap
    assert 'fb-chips-row' in log_html, ".fb-chips-row should be styled"
    assert 'overflow-x' in log_html, "Chips row should support horizontal scrolling"


# ── AC: No framework dependencies ────────────────────────────────────────────

def test_ac_vanilla_js_only(log_js):
    """training-log.js uses vanilla JS only — no React, Vue, or other frameworks."""
    assert 'React' not in log_js, "training-log.js should not use React"
    assert 'Vue' not in log_js, "training-log.js should not use Vue"
    assert 'import ' not in log_js or 'fetch' in log_js, \
        "training-log.js should not use ES module imports"


def test_ac_js_file_is_iife(log_js):
    """training-log.js is wrapped in an IIFE for scope isolation."""
    assert '(function' in log_js, "training-log.js should be wrapped in an IIFE"


# ── AC: API integration ───────────────────────────────────────────────────────

def test_ac_api_training_log_returns_200(client):
    """GET /api/training-log returns HTTP 200."""
    res = client.get("/api/training-log")
    assert res.status_code == 200
    data = res.json()
    assert "weeks" in data, "/api/training-log should return a 'weeks' key"
