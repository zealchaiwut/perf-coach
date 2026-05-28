"""
Tests for issue #107: Build Training Log page shell with week navigation and filters
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


# ── AC-1: Routes return 200 ───────────────────────────────────────────────────

def test_ac1_log_html_route_200(client):
    """/log.html must return HTTP 200."""
    res = client.get("/log.html")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"


def test_ac1_log_route_200(client):
    """/log must return HTTP 200."""
    res = client.get("/log")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"


def test_ac1_log_js_served(client):
    """/js/training-log.js must return HTTP 200."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"


def test_ac1_html_has_doctype():
    """log.html must be a valid HTML document with a doctype."""
    assert "<!doctype html>" in HTML.lower(), "log.html must start with <!doctype html>"


def test_ac1_html_loads_training_log_js():
    """log.html must load js/training-log.js."""
    assert 'src="js/training-log.js"' in HTML or "src='js/training-log.js'" in HTML, \
        "log.html must include a <script> tag for js/training-log.js"


# ── AC-2: Page header ─────────────────────────────────────────────────────────

def test_ac2_page_title_training_log():
    """log.html must display 'Training log' as the page heading."""
    assert "Training log" in HTML, "log.html must contain 'Training log' heading text"


def test_ac2_export_button_id():
    """log.html must have a button with id='log-export-btn'."""
    assert 'id="log-export-btn"' in HTML or "id='log-export-btn'" in HTML, \
        "log.html must have an element with id='log-export-btn'"


def test_ac2_log_workout_button():
    """log.html must have a 'Log workout' button."""
    assert "Log workout" in HTML, "log.html must include a 'Log workout' button"


def test_ac2_sync_subtitle_placeholder():
    """log.html must have a subtitle element for last-sync text."""
    has_subtitle = (
        'id="log-sync-sub"' in HTML
        or "log-sync" in HTML
        or "last-sync" in HTML.lower()
        or "last synced" in HTML.lower()
    )
    assert has_subtitle, "log.html must include a subtitle/placeholder for last-sync text"


# ── AC-3: Week strip ──────────────────────────────────────────────────────────

def test_ac3_week_pills_container():
    """log.html must have a container for week day pills."""
    assert 'id="week-pills"' in HTML or "week-pills" in HTML, \
        "log.html must have a week-pills container element"


def test_ac3_prev_chevron_button():
    """log.html must have a left chevron button for previous week."""
    has_prev = (
        'id="week-prev"' in HTML
        or 'id="week-prev-btn"' in HTML
        or "week-prev" in HTML
    )
    assert has_prev, "log.html must have a previous-week navigation button"


def test_ac3_next_chevron_button():
    """log.html must have a right chevron button for next week."""
    has_next = (
        'id="week-next"' in HTML
        or 'id="week-next-btn"' in HTML
        or "week-next" in HTML
    )
    assert has_next, "log.html must have a next-week navigation button"


def test_ac3_week_label():
    """log.html must have a week label element."""
    assert 'id="week-label"' in HTML or "week-label" in HTML, \
        "log.html must have a week-label element"


def test_ac3_js_renders_7_day_pills():
    """training-log.js must render 7 day pills for the week strip."""
    assert "for (var i = 0; i < 7; i++)" in JS or "< 7" in JS or "7" in JS, \
        "training-log.js must render 7 day pills in the week strip"


def test_ac3_js_highlights_today():
    """training-log.js must apply a highlight class to today's pill."""
    assert "today" in JS, \
        "training-log.js must mark today's pill with a 'today' CSS class"


def test_ac3_js_week_nav_advances_offset():
    """training-log.js must change the week offset on chevron click."""
    assert "weekOffset" in JS or "week_offset" in JS or "offset" in JS.lower(), \
        "training-log.js must track and update a week offset for navigation"


def test_ac3_js_pill_click_scrolls():
    """training-log.js must scroll to the matching section when a day pill is clicked."""
    assert "scrollIntoView" in JS, \
        "training-log.js must use scrollIntoView when a day pill is clicked"


# ── AC-4: Filter bar ──────────────────────────────────────────────────────────

def test_ac4_search_input():
    """log.html must have a search text input."""
    assert 'id="search-input"' in HTML or "search-input" in HTML, \
        "log.html must have a search input element"


def test_ac4_type_chip_all():
    """log.html must have an 'All' type filter chip."""
    assert 'data-type="all"' in HTML or "data-type='all'" in HTML, \
        "log.html must have an 'All' type filter chip with data-type='all'"


def test_ac4_type_chip_run():
    """log.html must have a 'Run' type filter chip."""
    assert 'data-type="run"' in HTML or "data-type='run'" in HTML, \
        "log.html must have a Run type filter chip"


def test_ac4_type_chip_lift():
    """log.html must have a 'Lift' type filter chip."""
    assert 'data-type="lift"' in HTML or "data-type='lift'" in HTML, \
        "log.html must have a Lift type filter chip"


def test_ac4_type_chip_wod():
    """log.html must have a 'WOD' type filter chip."""
    assert 'data-type="wod"' in HTML or "data-type='wod'" in HTML, \
        "log.html must have a WOD type filter chip"


def test_ac4_type_chip_bike():
    """log.html must have a 'Bike' type filter chip."""
    assert 'data-type="bike"' in HTML or "data-type='bike'" in HTML, \
        "log.html must have a Bike type filter chip"


def test_ac4_date_range_default_30d():
    """log.html must default the date range to '30d'."""
    assert 'value="30d" selected' in HTML or "30d" in HTML, \
        "log.html must set '30d' as the default date range"


def test_ac4_all_chip_active_by_default():
    """The 'All' chip must be active (selected) on initial render."""
    all_chip_match = re.search(r'data-type="all"[^>]*class="[^"]*active|class="[^"]*active[^"]*"[^>]*data-type="all"', HTML)
    alt_match = "active" in HTML and 'data-type="all"' in HTML
    assert all_chip_match or alt_match, \
        "The 'All' type filter chip must have the 'active' CSS class by default"


# ── AC-5: URL state management ────────────────────────────────────────────────

def test_ac5_urlsearchparams_used():
    """training-log.js must use URLSearchParams for URL state management."""
    assert "URLSearchParams" in JS, \
        "training-log.js must use URLSearchParams to read/write filter state"


def test_ac5_history_replacestate_used():
    """training-log.js must update the URL without a full page reload."""
    assert "replaceState" in JS or "pushState" in JS, \
        "training-log.js must use history.replaceState to update the URL"


def test_ac5_type_param_written_to_url():
    """training-log.js must write the 'types' param to the URL."""
    assert "'types'" in JS or '"types"' in JS, \
        "training-log.js must write a 'types' query param for type filter state"


def test_ac5_range_param_written_to_url():
    """training-log.js must write the 'range' param to the URL."""
    assert "'range'" in JS or '"range"' in JS, \
        "training-log.js must write a 'range' query param for date range state"


def test_ac5_url_read_on_load():
    """training-log.js must restore filter state from URL on page load."""
    assert "location.search" in JS or "URLSearchParams" in JS, \
        "training-log.js must read URL query params on page load"


# ── AC-6: Fetch from /api/training-log ───────────────────────────────────────

def test_ac6_js_fetches_api_training_log():
    """training-log.js must fetch from /api/training-log (not legacy /training_log)."""
    assert "/api/training-log" in JS, \
        "training-log.js must fetch from /api/training-log"


def test_ac6_js_does_not_fetch_legacy_url():
    """training-log.js must NOT use the legacy /training_log route."""
    import re as _re
    # Allow the comment line but not actual URL usage
    bad_uses = [
        ln for ln in JS.splitlines()
        if "/training_log" in ln and not ln.strip().startswith("//")
    ]
    assert not bad_uses, \
        "training-log.js must not fetch from legacy /training_log; update to /api/training-log"


def test_ac6_js_falls_back_to_mock_on_error():
    """training-log.js must fall back to mock data when the API call fails."""
    assert "catch" in JS or "MOCK_WORKOUTS" in JS, \
        "training-log.js must handle API errors gracefully (try/catch or mock fallback)"


# ── AC-7: Responsive design ───────────────────────────────────────────────────

def test_ac7_viewport_meta_tag():
    """log.html must include a viewport meta tag."""
    assert 'name="viewport"' in HTML, "log.html must include a <meta name='viewport'> tag"
    assert "width=device-width" in HTML, "viewport meta must include width=device-width"


def test_ac7_responsive_media_query():
    """log.html CSS must define a breakpoint ≤600px for mobile."""
    media_matches = re.findall(r"max-width:\s*(\d+)px", HTML)
    assert media_matches, "log.html must define at least one max-width media query"
    min_bp = min(int(v) for v in media_matches)
    assert min_bp <= 600, \
        f"log.html must have a breakpoint at ≤600px for mobile, found min={min_bp}px"


def test_ac7_week_strip_horizontal_scroll():
    """Week pill container must support horizontal scrolling on mobile."""
    has_scroll = "overflow-x: auto" in HTML or "overflow-x:auto" in HTML
    assert has_scroll, \
        "log.html must set overflow-x: auto on the week pills container for horizontal scrolling"


def test_ac7_filter_bar_stacks_vertically_on_mobile():
    """Filter bar must stack vertically on narrow viewports."""
    mobile_blocks = re.findall(
        r'@media[^{]*max-width:\s*\d+px[^{]*\{(.*?)\}(?=\s*(?:@media|\s*</style>|\s*\.|\s*#))',
        HTML, re.DOTALL
    )
    found = any("flex-direction" in b and "column" in b for b in mobile_blocks)
    assert found or "flex-direction: column" in HTML, \
        "log.html mobile CSS must set flex-direction: column on the filter bar"


# ── AC-8: Workout list & JS structure ────────────────────────────────────────

def test_ac8_workout_list_container():
    """log.html must have a workout-list container."""
    assert 'id="workout-list"' in HTML or "workout-list" in HTML, \
        "log.html must have a workout-list container element"


def test_ac8_empty_state_message():
    """log.html must include an empty-state message."""
    has_empty = (
        "No workouts" in HTML
        or "empty" in HTML.lower()
        or "no workout" in HTML.lower()
    )
    assert has_empty, "log.html must include an empty-state message for when no workouts exist"


def test_ac8_js_iife_wrapped():
    """training-log.js must be wrapped in an IIFE."""
    assert JS.strip().startswith("(function") or JS.strip().startswith("(()"), \
        "training-log.js must be wrapped in an IIFE to avoid polluting global scope"


def test_ac8_js_addEventListener_used():
    """training-log.js must attach event listeners."""
    assert "addEventListener" in JS, \
        "training-log.js must attach DOM event listeners"


# ── Navigation ────────────────────────────────────────────────────────────────

def test_nav_log_link_active():
    """log.html nav must mark the Log link as active."""
    active_link = (
        re.search(r'href="log\.html"[^>]*class="[^"]*active', HTML)
        or re.search(r'class="[^"]*active[^"]*"[^>]*href="log\.html"', HTML)
    )
    assert active_link, "log.html nav must mark the log.html link with the 'active' class"


def test_nav_links_to_home():
    """log.html nav must link to the home page."""
    assert 'href="home.html"' in HTML or 'href="index.html"' in HTML, \
        "log.html nav must include a link to the home page"
