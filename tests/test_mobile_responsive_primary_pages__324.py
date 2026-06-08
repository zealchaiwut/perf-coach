"""Tests for issue #324: Mobile/responsive pass on primary daily-use pages.

Acceptance criteria verified:
(AC-1) All four pages have mobile media queries covering 375px viewport
(AC-2) Global header reflows at ≤480px (flex-wrap, padding, gap in styles.css)
(AC-3) Log page header reflows at ≤599px (flex-wrap added)
(AC-4) Nav tap targets ≥44px enforced in nav.js at ≤880px breakpoint
(AC-5) Calendar grid min-width removed at ≤480px so week strip fits without scroll
(AC-6) Calendar modal constrained to viewport width (width: 90%)
(AC-7) Training form inputs stack at ≤600px (pre-existing breakpoint confirmed)
(AC-8) Home habits grid resized at ≤480px
(AC-9) No new CSS framework introduced
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent

STYLES = (ROOT / "frontend" / "css" / "styles.css").read_text()
NAV_JS = (ROOT / "frontend" / "js" / "nav.js").read_text()
HOME   = (ROOT / "frontend" / "pages" / "home.html").read_text()
LOG    = (ROOT / "frontend" / "pages" / "log.html").read_text()
TRAIN  = (ROOT / "frontend" / "pages" / "training.html").read_text()
CAL    = (ROOT / "frontend" / "pages" / "calendar.html").read_text()


def extract_media_block(text: str, max_width_px: int) -> str:
    """Extract full content of @media (max-width: Npx) { ... } block, handling nested braces."""
    pattern = rf"@media\s*\([^)]*max-width:\s*{max_width_px}px[^)]*\)\s*\{{"
    m = re.search(pattern, text)
    if not m:
        return ""
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start : i - 1]


# ── AC-1: styles.css — header reflows at ≤480px ──────────────────────────────

def test_styles_css_has_480px_media_query():
    """styles.css must have a max-width: 480px media query."""
    assert "max-width: 480px" in STYLES or "max-width:480px" in STYLES, \
        "styles.css missing @media (max-width: 480px) block"


def test_styles_css_header_flex_wrap_at_480px():
    """styles.css must set flex-wrap: wrap on header within the 480px media query."""
    block = extract_media_block(STYLES, 480)
    assert block, "styles.css missing @media (max-width: 480px) block"
    assert "flex-wrap" in block, \
        "styles.css @media 480px must set flex-wrap on header"


def test_styles_css_main_padding_at_480px():
    """styles.css 480px block must set padding on main to reduce horizontal gutters."""
    block = extract_media_block(STYLES, 480)
    assert block, "styles.css missing @media (max-width: 480px) block"
    assert "main" in block and "padding" in block, \
        "styles.css @media 480px must set padding on main"


# ── AC-2: Log page header reflows at ≤599px ──────────────────────────────────

def test_log_html_header_flex_wrap_at_599px():
    """log.html must apply flex-wrap: wrap to header within the ≤599px media query."""
    block = extract_media_block(LOG, 599)
    assert block, "log.html missing @media (max-width: 599px) block"
    assert "flex-wrap" in block, \
        "log.html @media 599px must set flex-wrap: wrap on header"


def test_log_html_header_last_child_flex_wrap():
    """log.html must apply flex-wrap to header's last child div to prevent clipping."""
    assert "header > div:last-child" in LOG or "header>div:last-child" in LOG, \
        "log.html must target header > div:last-child with flex-wrap"


# ── AC-3: Nav tap targets ≥44px ──────────────────────────────────────────────

def test_nav_js_gn_link_min_height_44px():
    """nav.js must set min-height:44px on .gn-link for touch targets."""
    assert ".gn-link{min-height:44px;}" in NAV_JS \
        or ".gn-link { min-height: 44px; }" in NAV_JS \
        or "gn-link{min-height:44px" in NAV_JS, \
        "nav.js must set min-height:44px on .gn-link"


def test_nav_js_gn_settings_44px_square():
    """nav.js must set width:44px and height:44px on .gn-settings inside the mobile block."""
    assert "gn-settings{width:44px;height:44px;}" in NAV_JS \
        or "gn-settings{width:44px" in NAV_JS, \
        "nav.js must set 44px dimensions on .gn-settings for mobile tap targets"


def test_nav_js_gn_avatar_44px_square():
    """nav.js must set width:44px and height:44px on .gn-avatar inside the mobile block."""
    assert "gn-avatar{width:44px;height:44px;}" in NAV_JS \
        or "gn-avatar{width:44px" in NAV_JS, \
        "nav.js must set 44px dimensions on .gn-avatar for mobile tap targets"


def test_nav_js_gn_logout_min_height_44px():
    """nav.js must set min-height:44px on .gn-logout for touch targets."""
    assert "gn-logout{min-height:44px;}" in NAV_JS \
        or "gn-logout{min-height:44px" in NAV_JS, \
        "nav.js must set min-height:44px on .gn-logout"


def test_nav_js_tap_targets_at_narrow_breakpoint():
    """nav.js tap-target rules must sit inside the ≤880px media query CSS string."""
    assert "max-width:880px" in NAV_JS, "nav.js missing max-width:880px media rule"
    idx_880 = NAV_JS.find("max-width:880px")
    block = NAV_JS[idx_880: idx_880 + 600]
    assert "44px" in block, \
        "nav.js 44px tap-target rules must appear after the max-width:880px declaration"


# ── AC-4: Calendar grid — week strip fits viewport at 375px ──────────────────

def test_calendar_html_cal_grid_min_width_removed_at_480px():
    """calendar.html must set min-width: 0 on .cal-grid inside the ≤480px media query."""
    block = extract_media_block(CAL, 480)
    assert block, "calendar.html missing @media (max-width: 480px) block"
    assert "min-width" in block and "0" in block, \
        "calendar.html @media 480px must set min-width: 0 on .cal-grid"


def test_calendar_html_cal_grid_scroll_overflow_visible_at_480px():
    """calendar.html must set overflow-x: visible on .cal-grid-scroll at ≤480px."""
    block = extract_media_block(CAL, 480)
    assert block, "calendar.html missing @media (max-width: 480px) block"
    assert "overflow-x" in block and "visible" in block, \
        "calendar.html @media 480px must override overflow-x to visible on .cal-grid-scroll"


def test_calendar_html_cal_nav_btn_44px_at_480px():
    """calendar.html must set 44×44px tap targets on .cal-nav-btn at ≤480px."""
    block = extract_media_block(CAL, 480)
    assert block, "calendar.html missing @media (max-width: 480px) block"
    assert "cal-nav-btn" in block and "44px" in block, \
        "calendar.html @media 480px must set 44px dimensions on .cal-nav-btn"


# ── AC-5: Calendar modal constrained to viewport ──────────────────────────────

def test_calendar_html_modal_width_90_percent():
    """calendar.html must set width: 90% on .day-modal-box to constrain within viewport."""
    assert ".day-modal-box" in CAL, "calendar.html missing .day-modal-box rule"
    idx = CAL.find(".day-modal-box")
    context = CAL[idx: idx + 400]
    assert "width" in context and "90%" in context, \
        "calendar.html .day-modal-box must set width: 90%"


# ── AC-6: Training page — form inputs stack vertically at ≤600px ──────────────

def test_training_html_form_stacks_at_600px():
    """training.html must set grid-template-columns: 1fr (single column) at ≤600px."""
    block = extract_media_block(TRAIN, 600)
    assert block, "training.html missing @media (max-width: 600px) block"
    assert "1fr" in block, \
        "training.html @media 600px must set grid-template-columns: 1fr to stack form fields"


def test_training_html_form_actions_stack_at_600px():
    """training.html must stack .form-actions vertically (flex-direction: column) at ≤600px."""
    block = extract_media_block(TRAIN, 600)
    assert block, "training.html missing @media (max-width: 600px) block"
    assert "flex-direction" in block and "column" in block, \
        "training.html @media 600px must set flex-direction: column on .form-actions"


def test_training_html_exercise_table_scrollable():
    """training.html must wrap exercise table in overflow-x: auto to prevent page overflow."""
    assert "table-scroll" in TRAIN, "training.html missing .table-scroll wrapper"
    table_scroll_match = re.search(r"\.table-scroll\s*\{([^}]*)\}", TRAIN, re.DOTALL)
    assert table_scroll_match, "training.html missing .table-scroll CSS rule"
    block = table_scroll_match.group(1)
    assert "overflow-x" in block and "auto" in block, \
        "training.html .table-scroll must set overflow-x: auto"


# ── AC-7: Home page — habits grid fits within 375px ──────────────────────────

def test_home_html_habits_week_row_at_480px():
    """home.html must reduce the habits week-row grid column size at ≤480px."""
    block = extract_media_block(HOME, 480)
    assert block, "home.html missing @media (max-width: 480px) block"
    assert "week-row" in block or "habits" in block, \
        "home.html @media 480px must adjust habits .week-row grid"


def test_home_html_habits_single_column_at_880px():
    """home.html must switch to single-column grid layout at ≤880px."""
    block = extract_media_block(HOME, 880)
    assert block, "home.html missing @media (max-width: 880px) block"
    assert "1fr" in block, \
        "home.html @media 880px must use single-column layout (grid-template-columns: 1fr)"


# ── AC-8: No new CSS framework ────────────────────────────────────────────────

def test_no_bootstrap_introduced():
    """None of the modified files must reference Bootstrap."""
    for name, content in [("styles.css", STYLES), ("nav.js", NAV_JS),
                           ("home.html", HOME), ("log.html", LOG),
                           ("training.html", TRAIN), ("calendar.html", CAL)]:
        assert "bootstrap" not in content.lower(), \
            f"{name} must not introduce Bootstrap"


def test_no_tailwind_introduced():
    """None of the modified files must reference Tailwind CSS."""
    for name, content in [("styles.css", STYLES), ("home.html", HOME),
                           ("log.html", LOG), ("training.html", TRAIN),
                           ("calendar.html", CAL)]:
        assert "tailwind" not in content.lower(), \
            f"{name} must not introduce Tailwind CSS"


def test_no_new_framework_cdn_links():
    """HTML pages must not add new CDN links for CSS frameworks."""
    frameworks = ["bulma", "foundation", "materialize", "uikit", "semantic-ui",
                  "pure.css", "skeleton.css"]
    for name, content in [("home.html", HOME), ("log.html", LOG),
                           ("training.html", TRAIN), ("calendar.html", CAL)]:
        for fw in frameworks:
            assert fw not in content.lower(), \
                f"{name} must not introduce {fw} CSS framework"


# ── Structural: all four pages have mobile media queries ─────────────────────

def test_home_html_has_media_queries():
    """home.html must contain at least one @media query for responsive layout."""
    assert "@media" in HOME, "home.html must have @media responsive rules"


def test_log_html_has_mobile_media_query():
    """log.html must contain a @media query covering 375px."""
    media_widths = [int(m) for m in re.findall(r"max-width:\s*(\d+)px", LOG)]
    assert any(w <= 599 for w in media_widths), \
        "log.html must have a max-width ≤599px media query covering 375px viewport"


def test_training_html_has_mobile_media_query():
    """training.html must contain a @media query covering 375px."""
    media_widths = [int(m) for m in re.findall(r"max-width:\s*(\d+)px", TRAIN)]
    assert any(w <= 600 for w in media_widths), \
        "training.html must have a max-width ≤600px media query covering 375px viewport"


def test_calendar_html_has_mobile_media_query():
    """calendar.html must contain a @media query covering 375px."""
    media_widths = [int(m) for m in re.findall(r"max-width:\s*(\d+)px", CAL)]
    assert any(w <= 480 for w in media_widths), \
        "calendar.html must have a max-width ≤480px media query covering 375px viewport"


def test_styles_css_has_mobile_media_query():
    """styles.css must contain a @media query for narrow (≤480px) viewports."""
    media_widths = [int(m) for m in re.findall(r"max-width:\s*(\d+)px", STYLES)]
    assert any(w <= 480 for w in media_widths), \
        "styles.css must have a max-width ≤480px media query"
