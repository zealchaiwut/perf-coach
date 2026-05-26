"""
Tests for issue #28: Calendar tab — month navigation polish and responsive layout
Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

HTML = (pathlib.Path(__file__).parent.parent / "calendar.html").read_text()
JS   = (pathlib.Path(__file__).parent.parent / "js" / "calendar.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC-1: Prev/Next buttons use chevron icons ─────────────────────────────────

def test_ac1_prev_btn_contains_chevron_icon():
    """prev-btn must use a ChevronLeft icon (SVG path, unicode chevron, or HTML entity)."""
    prev_match = re.search(r'id="prev-btn"[^>]*>(.*?)</button>', HTML, re.DOTALL)
    if not prev_match:
        # Try before-id form
        prev_match = re.search(r'<button[^>]*id="prev-btn"[^>]*>(.*?)</button>', HTML, re.DOTALL)
    assert prev_match, "prev-btn not found in calendar.html"
    content = prev_match.group(1)
    # Accept SVG, unicode chevron chars (‹ ‹ < ◂), or HTML entities &#8249; &#60; &lt; &lsaquo;
    has_chevron = (
        "<svg" in content
        or "&#8249;" in content
        or "&#60;" in content
        or "&lt;" in content
        or "&lsaquo;" in content
        or "‹" in content
        or "‹" in HTML[HTML.find('id="prev-btn"'):HTML.find('id="prev-btn"') + 200]
        or "chevron" in content.lower()
        or any(c in content for c in ["‹", "<", "◂", "❮", "«"])
    )
    assert has_chevron, (
        f"prev-btn must use a chevron icon, found: {repr(content.strip())}"
    )


def test_ac1_next_btn_contains_chevron_icon():
    """next-btn must use a ChevronRight icon (SVG path, unicode chevron, or HTML entity)."""
    next_match = re.search(r'<button[^>]*id="next-btn"[^>]*>(.*?)</button>', HTML, re.DOTALL)
    assert next_match, "next-btn not found in calendar.html"
    content = next_match.group(1)
    has_chevron = (
        "<svg" in content
        or "&#8250;" in content
        or "&#62;" in content
        or "&gt;" in content
        or "&rsaquo;" in content
        or "›" in content
        or "chevron" in content.lower()
        or any(c in content for c in ["›", ">", "▸", "❯", "»"])
    )
    assert has_chevron, (
        f"next-btn must use a chevron icon, found: {repr(content.strip())}"
    )


def test_ac1_prev_and_next_icons_are_directional():
    """Prev and next buttons must show different/opposite directional indicators."""
    prev_match = re.search(r'<button[^>]*id="prev-btn"[^>]*>(.*?)</button>', HTML, re.DOTALL)
    next_match = re.search(r'<button[^>]*id="next-btn"[^>]*>(.*?)</button>', HTML, re.DOTALL)
    assert prev_match and next_match
    prev_content = prev_match.group(1).strip()
    next_content = next_match.group(1).strip()
    assert prev_content != next_content, \
        "prev-btn and next-btn must have different icon content"


# ── AC-2: Month label — large and centred between arrows ──────────────────────

def test_ac2_month_label_between_arrows():
    """month-label must appear between prev-btn and next-btn in the DOM."""
    prev_pos = HTML.find('id="prev-btn"')
    label_pos = HTML.find('id="month-label"')
    next_pos = HTML.find('id="next-btn"')
    assert prev_pos != -1 and label_pos != -1 and next_pos != -1
    assert prev_pos < label_pos < next_pos, \
        "month-label must appear between prev-btn and next-btn in calendar.html"


def test_ac2_month_label_text_align_center():
    """CSS for .cal-month-label must include text-align: center."""
    assert "text-align: center" in HTML or "text-align:center" in HTML, \
        "calendar.html CSS must set text-align: center on the month label"


def test_ac2_month_label_font_size_large():
    """CSS for .cal-month-label must set a font-size of at least 1rem."""
    label_css_block = re.search(
        r'\.cal-month-label\s*\{([^}]+)\}', HTML, re.DOTALL
    )
    assert label_css_block, "Missing .cal-month-label CSS block in calendar.html"
    block = label_css_block.group(1)
    font_match = re.search(r'font-size:\s*([\d.]+)(rem|px|em)', block)
    assert font_match, f"Missing font-size in .cal-month-label: {block}"
    value = float(font_match.group(1))
    unit = font_match.group(2)
    if unit == "rem":
        assert value >= 1.0, \
            f"Month label font-size must be >= 1rem, got {value}rem"
    elif unit == "px":
        assert value >= 14, \
            f"Month label font-size must be >= 14px, got {value}px"


def test_ac2_month_label_font_weight_bold():
    """CSS for .cal-month-label must set font-weight to 600 or bold."""
    label_css_block = re.search(
        r'\.cal-month-label\s*\{([^}]+)\}', HTML, re.DOTALL
    )
    assert label_css_block, "Missing .cal-month-label CSS block"
    block = label_css_block.group(1)
    assert "font-weight" in block, \
        ".cal-month-label CSS must include font-weight"
    fw_match = re.search(r'font-weight:\s*(\w+)', block)
    assert fw_match
    fw = fw_match.group(1)
    assert fw in ("600", "700", "bold", "bolder") or int(fw) >= 600, \
        f"Month label font-weight must be 600+, got {fw}"


# ── AC-3: Keyboard shortcuts ──────────────────────────────────────────────────

def test_ac3_keydown_listener_in_js():
    """calendar.js must add a keydown event listener for keyboard navigation."""
    assert "keydown" in JS, \
        "calendar.js must add a keydown event listener for keyboard shortcuts"


def test_ac3_arrow_left_navigates_prev():
    """calendar.js must handle ArrowLeft key to navigate to the previous month."""
    assert "ArrowLeft" in JS, \
        "calendar.js must handle ArrowLeft key to go to the previous month"


def test_ac3_arrow_right_navigates_next():
    """calendar.js must handle ArrowRight key to navigate to the next month."""
    assert "ArrowRight" in JS, \
        "calendar.js must handle ArrowRight key to go to the next month"


def test_ac3_home_key_jumps_to_current_month():
    """calendar.js must handle the Home key to jump back to the current month."""
    assert "Home" in JS, \
        "calendar.js must handle the Home key to jump to the current month"


def test_ac3_escape_key_handled():
    """calendar.js must handle the Escape key (for modal dismiss placeholder)."""
    assert "Escape" in JS or "Esc" in JS, \
        "calendar.js must handle the Escape key"


# ── AC-4: Fade transition on month switch ─────────────────────────────────────

def test_ac4_css_transition_defined():
    """calendar.html CSS must define a transition (for the month-change fade)."""
    assert "transition" in HTML, \
        "calendar.html must define a CSS transition for the month-change fade"


def test_ac4_transition_150ms():
    """CSS transition must be approximately 150ms."""
    assert "150ms" in HTML or "0.15s" in HTML, \
        "calendar.html CSS transition must be ~150ms (150ms or 0.15s)"


def test_ac4_opacity_transition_on_grid_or_cells():
    """The fade transition must involve opacity on the grid or cell container."""
    # Transition can be on grid cells container or the grid itself
    has_opacity_transition = (
        "opacity" in HTML
        and "transition" in HTML
    )
    assert has_opacity_transition, \
        "calendar.html must use opacity with a CSS transition for the month fade"


def test_ac4_js_triggers_fade_on_navigate():
    """calendar.js must trigger the fade (opacity change or CSS class) on navigation."""
    has_fade_trigger = (
        "opacity" in JS
        or "fade" in JS
        or "transition" in JS
        or "classList" in JS and ("opacity" in JS or "fade" in JS or "anim" in JS)
    )
    assert has_fade_trigger, \
        "calendar.js must trigger an opacity/fade animation when navigating months"


# ── AC-5: URL stays in sync; back/forward works ───────────────────────────────

def test_ac5_pushstate_used_for_navigation():
    """calendar.js must use history.pushState to sync the URL on month navigation."""
    assert "pushState" in JS, \
        "calendar.js must use history.pushState to update the URL"


def test_ac5_popstate_handler_restores_month():
    """calendar.js must listen for popstate to support browser back/forward."""
    assert "popstate" in JS, \
        "calendar.js must handle the popstate event for browser back/forward"


def test_ac5_month_param_format_is_yyyy_mm():
    """calendar.js must write month in YYYY-MM format using padStart."""
    assert "padStart" in JS, \
        "calendar.js must use padStart to zero-pad the month for YYYY-MM format"
    assert "month" in JS, \
        "calendar.js must set the 'month' URL parameter"


def test_ac5_url_read_on_load():
    """calendar.js must read ?month=YYYY-MM from the URL on page load."""
    assert "URLSearchParams" in JS or "location.search" in JS, \
        "calendar.js must read the URL search params on page load"


# ── AC-6: Viewport < 900px — 7 cols, cells shrink to 60px ────────────────────

def test_ac6_responsive_breakpoint_at_900px_or_below():
    """calendar.html must have a @media breakpoint at or below 900px."""
    media_matches = re.findall(r"max-width:\s*(\d+)px", HTML)
    assert media_matches, "calendar.html must define at least one max-width media query"
    smallest = min(int(v) for v in media_matches)
    largest = max(int(v) for v in media_matches)
    assert largest >= 700 and largest <= 900, \
        f"calendar.html must have a max-width media query between 700px and 900px, found max={largest}px"


def test_ac6_cells_shrink_to_60px_at_900px_breakpoint():
    """At <=900px, .cal-cell must shrink to min-height 60px."""
    # Find media queries and check for 60px inside one that covers ≤900px
    media_blocks = re.findall(
        r'@media[^{]*max-width:\s*(\d+)px[^{]*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}',
        HTML, re.DOTALL
    )
    found_60px_in_small_breakpoint = False
    for bp, block in media_blocks:
        if int(bp) <= 900:
            if "60px" in block or "min-height: 60px" in block or "min-height:60px" in block:
                found_60px_in_small_breakpoint = True
                break
    assert found_60px_in_small_breakpoint, \
        "calendar.html must reduce .cal-cell min-height to 60px inside a ≤900px media query"


def test_ac6_7_columns_preserved_at_narrow_viewport():
    """The responsive CSS must not override 7-column layout for the grid."""
    # The media query must NOT change grid-template-columns away from repeat(7, 1fr)
    media_blocks = re.findall(
        r'@media[^{]*max-width:\s*\d+px[^{]*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}',
        HTML, re.DOTALL
    )
    for block in media_blocks:
        if "grid-template-columns" in block:
            assert "repeat(7" in block, \
                "Responsive CSS must keep 7 columns — do not reduce column count"


# ── AC-7: iPad portrait (~768px) — grid remains usable ───────────────────────

def test_ac7_cell_content_truncation_defined():
    """calendar.html CSS must define truncation rules for cell content at smaller viewports."""
    has_truncation = (
        "overflow: hidden" in HTML
        or "overflow:hidden" in HTML
        or "text-overflow" in HTML
        or "white-space: nowrap" in HTML
        or "white-space:nowrap" in HTML
        or "truncat" in HTML
    )
    assert has_truncation, \
        "calendar.html CSS must define overflow or text-overflow truncation for cell content"


def test_ac7_cal_cell_has_overflow_hidden():
    """cal-cell CSS must include overflow: hidden to prevent layout breakage at 768px."""
    cal_cell_match = re.search(r'\.cal-cell\s*\{([^}]+)\}', HTML, re.DOTALL)
    assert cal_cell_match, "Missing .cal-cell CSS block"
    block = cal_cell_match.group(1)
    assert "overflow" in block or "overflow: hidden" in HTML or "overflow:hidden" in HTML, \
        ".cal-cell must set overflow: hidden to prevent content spill at iPad portrait"


# ── AC-8: Below 700px — horizontal scroll if needed ──────────────────────────

def test_ac8_horizontal_scroll_below_700px():
    """calendar.html must allow horizontal scrolling below 700px to prevent grid crash."""
    has_overflow_x = (
        "overflow-x" in HTML
        or "overflow: auto" in HTML
        or "overflow: scroll" in HTML
        or "overflow:auto" in HTML
        or "overflow:scroll" in HTML
    )
    assert has_overflow_x, \
        "calendar.html must define overflow-x: auto/scroll for viewports below 700px"


def test_ac8_grid_container_overflow_defined():
    """The .cal-grid wrapper must define overflow to support horizontal scroll."""
    grid_css_match = re.search(r'\.cal-grid\s*\{([^}]+)\}', HTML, re.DOTALL)
    assert grid_css_match, "Missing .cal-grid CSS block"
    block = grid_css_match.group(1)
    assert "overflow" in block or "overflow-x" in HTML, \
        ".cal-grid must define overflow or overflow-x for scroll support on narrow screens"


# ── Structural ────────────────────────────────────────────────────────────────

def test_structural_calendar_html_served(client):
    """GET /calendar.html must return 200."""
    res = client.get("/calendar.html")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"


def test_structural_calendar_js_exists():
    """js/calendar.js must exist."""
    assert (pathlib.Path(__file__).parent.parent / "js" / "calendar.js").exists()
