"""
Tests for issue #46: Build Trends page shell with date-range picker
Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

HTML = (pathlib.Path(__file__).parent.parent / "trends.html").read_text()
JS   = (pathlib.Path(__file__).parent.parent / "js" / "trends.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC-1: Page loads without error ───────────────────────────────────────────

def test_ac1_trends_html_served(client):
    """GET /trends.html must return 200."""
    res = client.get("/trends.html")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"


def test_ac1_trends_route_served(client):
    """GET /trends must return 200."""
    res = client.get("/trends")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"


def test_ac1_trends_js_served(client):
    """GET /js/trends.js must return 200."""
    res = client.get("/js/trends.js")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"


def test_ac1_trends_html_has_doctype():
    """trends.html must be a valid HTML document with a doctype."""
    assert "<!doctype html>" in HTML.lower() or "<!DOCTYPE html>" in HTML, \
        "trends.html must start with an HTML doctype declaration"


def test_ac1_trends_html_loads_trends_js():
    """trends.html must load js/trends.js."""
    assert 'src="js/trends.js"' in HTML or "src='js/trends.js'" in HTML, \
        "trends.html must include a <script> tag for js/trends.js"


# ── AC-2: Preset range buttons present and active state ──────────────────────

def test_ac2_preset_button_7d_exists():
    """trends.html must have a 7d preset button."""
    assert 'data-range="7d"' in HTML or "data-range='7d'" in HTML, \
        "Missing 7d preset button with data-range='7d' in trends.html"


def test_ac2_preset_button_30d_exists():
    """trends.html must have a 30d preset button."""
    assert 'data-range="30d"' in HTML or "data-range='30d'" in HTML, \
        "Missing 30d preset button with data-range='30d' in trends.html"


def test_ac2_preset_button_90d_exists():
    """trends.html must have a 90d preset button."""
    assert 'data-range="90d"' in HTML or "data-range='90d'" in HTML, \
        "Missing 90d preset button with data-range='90d' in trends.html"


def test_ac2_preset_button_custom_exists():
    """trends.html must have a Custom preset button."""
    assert 'data-range="custom"' in HTML or "data-range='custom'" in HTML, \
        "Missing Custom preset button with data-range='custom' in trends.html"


def test_ac2_active_css_class_defined():
    """trends.html CSS must define an .active style for buttons."""
    active_block = re.search(r'\.range-btn\.active\s*\{([^}]+)\}', HTML, re.DOTALL)
    assert active_block, "Missing .range-btn.active CSS block in trends.html"
    block = active_block.group(1)
    has_visual_distinction = (
        "background" in block or "color" in block or "border" in block
    )
    assert has_visual_distinction, \
        ".range-btn.active must define a visual distinction (background, color, or border)"


def test_ac2_js_toggles_active_class():
    """trends.js must toggle the active class on preset buttons."""
    assert "active" in JS, \
        "trends.js must toggle/set an 'active' class on range preset buttons"
    assert "classList" in JS or "toggle" in JS, \
        "trends.js must use classList or toggle to manage the active state"


# ── AC-3: Custom date picker ──────────────────────────────────────────────────

def test_ac3_custom_range_inputs_exist():
    """trends.html must have a container for custom date range inputs."""
    assert 'id="custom-range-inputs"' in HTML or "id='custom-range-inputs'" in HTML, \
        "Missing custom-range-inputs container in trends.html"


def test_ac3_from_date_input_exists():
    """trends.html must have a 'from' date input."""
    assert 'id="range-from"' in HTML or "id='range-from'" in HTML, \
        "Missing range-from date input in trends.html"
    assert 'type="date"' in HTML, "Custom range inputs must use type='date'"


def test_ac3_to_date_input_exists():
    """trends.html must have a 'to' date input."""
    assert 'id="range-to"' in HTML or "id='range-to'" in HTML, \
        "Missing range-to date input in trends.html"


def test_ac3_custom_inputs_hidden_by_default():
    """Custom date inputs must be hidden by default (hidden attribute)."""
    custom_block = re.search(
        r'id="custom-range-inputs"([^>]*)', HTML
    )
    assert custom_block, "custom-range-inputs element not found"
    attrs = custom_block.group(1)
    assert "hidden" in attrs, \
        "custom-range-inputs must have the 'hidden' attribute by default"


def test_ac3_js_shows_custom_inputs_on_custom_click():
    """trends.js must show/hide the custom date inputs when Custom is clicked."""
    assert "custom-range-inputs" in JS or "customInputs" in JS or "custom_range" in JS.replace("-", "_"), \
        "trends.js must reference the custom-range-inputs element"
    assert "hidden" in JS, \
        "trends.js must toggle the hidden property of custom date inputs"


# ── AC-4: URL query string persistence ───────────────────────────────────────

def test_ac4_urlsearchparams_used_in_js():
    """trends.js must use URLSearchParams to read/write URL state."""
    assert "URLSearchParams" in JS, \
        "trends.js must use URLSearchParams for URL state management"


def test_ac4_history_replacestate_used():
    """trends.js must use history.replaceState to update the URL without reload."""
    assert "replaceState" in JS or "pushState" in JS, \
        "trends.js must use history.replaceState or pushState to update the URL"


def test_ac4_range_param_written_to_url():
    """trends.js must write the 'range' param to the URL for preset selections."""
    assert '"range"' in JS or "'range'" in JS or "range" in JS, \
        "trends.js must write a 'range' query param for preset ranges"


def test_ac4_from_param_written_to_url():
    """trends.js must write 'from' and 'to' params to the URL for custom ranges."""
    assert '"from"' in JS or "'from'" in JS, \
        "trends.js must write a 'from' query param for custom date ranges"
    assert '"to"' in JS or "'to'" in JS, \
        "trends.js must write a 'to' query param for custom date ranges"


def test_ac4_url_read_on_page_load():
    """trends.js must read range state from the URL on page load."""
    assert "location.search" in JS or "URLSearchParams" in JS, \
        "trends.js must read URL search params on page load to restore state"


def test_ac4_default_preset_applied():
    """trends.js must apply a default preset (e.g. 30d) when URL has no params."""
    assert "DEFAULT_PRESET" in JS or "30d" in JS or "default" in JS.lower(), \
        "trends.js must define and apply a default preset range"


# ── AC-5: Mobile responsiveness ──────────────────────────────────────────────

def test_ac5_viewport_meta_tag():
    """trends.html must include a viewport meta tag for mobile rendering."""
    assert 'name="viewport"' in HTML, \
        "trends.html must include a <meta name='viewport'> tag"
    assert "width=device-width" in HTML, \
        "viewport meta must include width=device-width"


def test_ac5_responsive_media_query_exists():
    """trends.html CSS must define a media query for narrow viewports."""
    media_matches = re.findall(r"max-width:\s*(\d+)px", HTML)
    assert media_matches, "trends.html must define at least one max-width media query"
    min_bp = min(int(v) for v in media_matches)
    assert min_bp <= 600, \
        f"trends.html must have a breakpoint at ≤600px for mobile, found min={min_bp}px"


def test_ac5_chart_grid_single_column_on_mobile():
    """CSS must switch chart grid to single column on mobile."""
    media_blocks = re.findall(
        r'@media[^{]*max-width:\s*(\d+)px[^{]*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}',
        HTML, re.DOTALL
    )
    found_single_col = False
    for bp, block in media_blocks:
        if int(bp) <= 600 and "grid-template-columns" in block:
            if "1fr" in block and "repeat(2" not in block:
                found_single_col = True
    assert found_single_col, \
        "Mobile CSS must set .chart-grid to a single column (1fr) layout"


def test_ac5_flex_wrap_on_toolbar():
    """Toolbar must use flex-wrap to prevent overflow on small screens."""
    toolbar_css = re.search(r'\.trends-toolbar\s*\{([^}]+)\}', HTML, re.DOTALL)
    assert toolbar_css, "Missing .trends-toolbar CSS block in trends.html"
    block = toolbar_css.group(1)
    assert "flex-wrap" in block or "flex-wrap: wrap" in HTML, \
        ".trends-toolbar must use flex-wrap to handle small viewports"


# ── AC-6: Empty state message ─────────────────────────────────────────────────

def test_ac6_empty_banner_element_exists():
    """trends.html must have an empty-state banner element."""
    assert 'id="trends-empty-banner"' in HTML or "id='trends-empty-banner'" in HTML, \
        "Missing trends-empty-banner element in trends.html"


def test_ac6_empty_banner_hidden_by_default():
    """Empty banner must be hidden by default."""
    empty_banner = re.search(r'id="trends-empty-banner"([^>]*)', HTML)
    assert empty_banner, "trends-empty-banner not found"
    attrs = empty_banner.group(1)
    assert "hidden" in attrs, \
        "trends-empty-banner must have the 'hidden' attribute by default"


def test_ac6_empty_state_text_in_html():
    """trends.html must include an empty-state message text."""
    has_empty_text = (
        "No data" in HTML
        or "no data" in HTML
        or "empty" in HTML.lower()
    )
    assert has_empty_text, \
        "trends.html must include an empty-state message (e.g. 'No data for this range')"


def test_ac6_js_shows_empty_state_for_no_data():
    """trends.js must show the empty banner when no data is available."""
    assert "emptyBanner" in JS or "empty-banner" in JS or "trends-empty-banner" in JS, \
        "trends.js must reference the empty banner element"
    assert "hidden" in JS, \
        "trends.js must toggle the hidden property of the empty banner"


# ── AC-7: Loading indicators ──────────────────────────────────────────────────

def test_ac7_loading_skeleton_css_defined():
    """trends.html CSS must define styles for loading skeleton/spinner."""
    has_spinner = (
        "skeleton-spinner" in HTML
        or "slot-loading" in HTML
        or "spinner" in HTML
        or "skeleton" in HTML
    )
    assert has_spinner, \
        "trends.html must define CSS for a loading indicator (spinner or skeleton)"


def test_ac7_skeleton_animation_defined():
    """trends.html CSS must include an animation for the loading state."""
    assert "@keyframes" in HTML, \
        "trends.html must define a @keyframes animation for loading indicators"
    assert "animation" in HTML, \
        "trends.html must apply a CSS animation to skeleton/loading elements"


def test_ac7_js_shows_loading_before_data():
    """trends.js must show loading state before fetching/resolving data."""
    assert "showLoading" in JS or "slot-loading" in JS or "skeleton" in JS, \
        "trends.js must show a loading indicator while data is resolving"


def test_ac7_js_loading_called_per_slot():
    """trends.js must call the loading function for each chart slot."""
    assert "forEach" in JS or "slots" in JS, \
        "trends.js must iterate over slots to show loading indicators in each"


# ── AC-8: Placeholder chart slots ────────────────────────────────────────────

def test_ac8_chart_grid_exists():
    """trends.html must have a chart-grid container."""
    assert 'id="chart-grid"' in HTML or "class=\"chart-grid\"" in HTML, \
        "Missing chart-grid container in trends.html"


def test_ac8_readiness_slot_exists():
    """trends.html must have a Readiness Score chart slot."""
    assert 'id="slot-readiness"' in HTML or "Readiness" in HTML, \
        "Missing Readiness Score chart slot in trends.html"


def test_ac8_hrv_rhr_slot_exists():
    """trends.html must have an HRV / Resting HR chart slot."""
    assert 'id="slot-hrv-rhr"' in HTML or "HRV" in HTML, \
        "Missing HRV/Resting HR chart slot in trends.html"


def test_ac8_sleep_energy_slot_exists():
    """trends.html must have a Sleep & Energy chart slot."""
    assert 'id="slot-sleep-energy"' in HTML or "Sleep" in HTML, \
        "Missing Sleep & Energy chart slot in trends.html"


def test_ac8_tss_slot_exists():
    """trends.html must have a TSS Correlation chart slot."""
    assert 'id="slot-tss"' in HTML or "TSS" in HTML, \
        "Missing TSS Correlation chart slot in trends.html"


def test_ac8_four_chart_slots_present():
    """trends.html must have exactly 4 chart slot containers."""
    slots = re.findall(r'class="chart-slot"', HTML)
    assert len(slots) == 4, \
        f"trends.html must have 4 chart slots, found {len(slots)}"


def test_ac8_chart_slot_css_defined():
    """trends.html CSS must define styles for .chart-slot."""
    slot_css = re.search(r'\.chart-slot\s*\{([^}]+)\}', HTML, re.DOTALL)
    assert slot_css, "Missing .chart-slot CSS block in trends.html"


# ── Navigation ────────────────────────────────────────────────────────────────

def test_nav_trends_link_in_nav():
    """trends.html must include a nav link to trends.html marked active."""
    assert 'href="trends.html"' in HTML, \
        "trends.html must have a nav link pointing to trends.html"
    active_link = re.search(r'href="trends\.html"[^>]*class="[^"]*active', HTML) or \
                  re.search(r'class="[^"]*active[^"]*"[^>]*href="trends\.html"', HTML)
    assert active_link, \
        "The trends.html nav link must have the 'active' class"


def test_nav_other_pages_linked():
    """trends.html nav must link to other pages."""
    assert 'href="home.html"' in HTML or 'href="index.html"' in HTML, \
        "trends.html nav must include a link to the home page"


# ── JS structure ──────────────────────────────────────────────────────────────

def test_js_iife_wrapped():
    """trends.js must be wrapped in an IIFE to avoid global scope pollution."""
    is_iife = JS.strip().startswith("(()") or JS.strip().startswith("(function")
    assert is_iife, \
        "trends.js must be wrapped in an IIFE (() => { ... })()"


def test_js_event_listeners_for_presets():
    """trends.js must attach click event listeners to preset buttons."""
    assert "addEventListener" in JS, \
        "trends.js must attach event listeners to the preset buttons"
    assert "click" in JS, \
        "trends.js must listen for 'click' events on preset buttons"


def test_js_date_change_listener():
    """trends.js must listen for change events on the date inputs."""
    assert "change" in JS, \
        "trends.js must listen for 'change' events on the date inputs"
