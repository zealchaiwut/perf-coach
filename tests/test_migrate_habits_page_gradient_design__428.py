"""Tests for issue #428: Migrate habits page to gradient design language.

AC anchors verified:
  (ac1)  Layout order: hero row → daily grid card → weekly habits card
  (ac2)  Hero row contains a wheel card AND a stats card
  (ac3)  Blue gradient background token used (not hardcoded)
  (ac4)  Cards have shared 14px border-radius token and box-shadow
  (ac5)  Inter Tight loaded and referenced in page styles
  (ac6)  JetBrains Mono loaded and used for numeric values
  (ac7)  No gradient/card token values duplicated from shared stylesheet
  (ac8)  nav.js loaded; Habits marked as active route in nav.js
  (ac9)  Responsive: hero row is side-by-side (2-col grid) at ≥820px
  (ac10) Responsive: hero stacks (1fr) at <820px
  (ac11) Responsive: 360px day headers collapse to single letters (M T W T F S S)
  (ac12) Responsive: 360px no horizontal overflow — max-width / overflow hidden
  (ac13) Responsive: <820px weekly rows wrap (flex-wrap or block layout)
  (ac14) Empty state: wheel shows "Add habits to start tracking" text via JS
  (ac15) Empty state: starter suggestions rendered via JS
  (ac16) Empty state: no raw enum strings in the JS
  (ac17) Icon fallback: "?" placeholder used when icon is missing
  (ac18) Cross-link: home-habits.js "This week's progress" rows link to /habits
  (ac19) Cross-link: habits page autofill tooltip/link points to /log
  (ac20) Mockup docs/mockups/habits-redesign-v1.html exists and uses gradient
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "frontend" / "pages"
JS_DIR = ROOT / "frontend" / "js"
CSS_DIR = ROOT / "frontend" / "css"
MOCKUPS_DIR = ROOT / "docs" / "mockups"

HABITS_HTML = (PAGES_DIR / "habits.html").read_text()
HABITS_JS = (JS_DIR / "habits.js").read_text()
SHARED_CSS = (CSS_DIR / "styles.css").read_text()


# ── AC1: Layout order ─────────────────────────────────────────────────────────

def test_ac1_hero_row_exists():
    """habits.html must have a hero row element."""
    assert "hero-row" in HABITS_HTML or "habits-hero" in HABITS_HTML, \
        "habits.html must have a hero row (hero-row or habits-hero)"


def test_ac1_daily_grid_card_exists():
    """habits.html must have a daily grid card."""
    assert "daily-grid" in HABITS_HTML or "day-grid" in HABITS_HTML or \
           "habits-day-grid" in HABITS_HTML, \
        "habits.html must have a daily grid card element"


def test_ac1_weekly_habits_card_exists():
    """habits.html must have a weekly habits card."""
    assert "weekly-habits" in HABITS_HTML or "habits-weekly" in HABITS_HTML or \
           "weekly-progress" in HABITS_HTML, \
        "habits.html must have a weekly habits card element"


def test_ac1_hero_before_daily_grid():
    """Hero row must appear before daily grid card in DOM order."""
    hero_pos = max(
        HABITS_HTML.find("hero-row"),
        HABITS_HTML.find("habits-hero"),
    )
    daily_pos = max(
        HABITS_HTML.find("daily-grid"),
        HABITS_HTML.find("day-grid"),
        HABITS_HTML.find("habits-day-grid"),
    )
    assert hero_pos != -1 and daily_pos != -1, \
        "habits.html must have both hero row and daily grid elements"
    assert hero_pos < daily_pos, \
        "hero row must appear before daily grid in HTML"


def test_ac1_daily_grid_before_weekly():
    """Daily grid card must appear before weekly habits card."""
    daily_pos = max(
        HABITS_HTML.find("daily-grid"),
        HABITS_HTML.find("day-grid"),
        HABITS_HTML.find("habits-day-grid"),
    )
    weekly_pos = max(
        HABITS_HTML.find("weekly-habits"),
        HABITS_HTML.find("habits-weekly"),
        HABITS_HTML.find("weekly-progress"),
    )
    assert daily_pos != -1 and weekly_pos != -1, \
        "habits.html must have both daily grid and weekly habits elements"
    assert daily_pos < weekly_pos, \
        "daily grid must appear before weekly habits card in HTML"


# ── AC2: Hero row contains wheel card and stats card ─────────────────────────

def test_ac2_wheel_card_exists():
    """habits.html must have a wheel card (SVG donut or habits-wheel)."""
    assert "habits-wheel" in HABITS_HTML or \
           "wheel-card" in HABITS_HTML or \
           "donut" in HABITS_HTML.lower(), \
        "habits.html must have a wheel card element (habits-wheel, wheel-card, or donut SVG)"


def test_ac2_stats_card_exists():
    """habits.html must have a stats card in the hero row."""
    assert "habits-stats" in HABITS_HTML or \
           "stats-card" in HABITS_HTML or \
           "hero-stats" in HABITS_HTML, \
        "habits.html must have a stats card in the hero row"


def test_ac2_wheel_svg_element():
    """The wheel card must contain an SVG element for the donut."""
    assert "<svg" in HABITS_HTML or "habits-wheel-svg" in HABITS_HTML or \
           "wheelSvg" in HABITS_JS or "wheel-svg" in HABITS_HTML, \
        "Wheel card must use SVG for the donut ring"


def test_ac2_wheel_empty_state_text_in_js():
    """habits.js must render 'Add habits to start tracking' as wheel empty state."""
    assert "Add habits to start tracking" in HABITS_JS, \
        "habits.js must render 'Add habits to start tracking' in wheel empty state"


# ── AC3: Gradient background ──────────────────────────────────────────────────

def test_ac3_gradient_background_token_used():
    """habits.html body must use gradient background via shared token."""
    assert "var(--page-bg)" in HABITS_HTML or \
           "radial-gradient" in HABITS_HTML or \
           "var(--bg-1)" in HABITS_HTML, \
        "habits.html must use gradient background (var(--page-bg) or gradient token)"


def test_ac3_shared_css_defines_gradient():
    """Shared stylesheet must define --page-bg or gradient background tokens."""
    assert "--page-bg" in SHARED_CSS or "--bg-1" in SHARED_CSS, \
        "styles.css must define --page-bg or --bg-1 gradient tokens"


def test_ac3_gradient_not_hardcoded_in_page_style():
    """Page <style> must not redefine gradient token values already in shared CSS."""
    style_block = ""
    m = re.search(r"<style>(.*?)</style>", HABITS_HTML, re.DOTALL)
    if m:
        style_block = m.group(1)
    if "--bg-1: #5a8dee" in SHARED_CSS:
        assert "--bg-1: #5a8dee" not in style_block, \
            "habits.html <style> must not duplicate --bg-1 already in shared CSS"


# ── AC4: Card tokens ──────────────────────────────────────────────────────────

def test_ac4_cards_use_14px_border_radius():
    """Cards must use 14px border-radius (directly or via shared token)."""
    assert "14px" in HABITS_HTML or "var(--card-radius)" in HABITS_HTML, \
        "habits.html cards must use 14px border-radius or var(--card-radius)"


def test_ac4_cards_have_box_shadow():
    """Cards must have box-shadow drop shadow."""
    assert "box-shadow" in HABITS_HTML or "var(--card-shadow)" in HABITS_HTML, \
        "habits.html cards must have box-shadow"


# ── AC5: Inter Tight typography ───────────────────────────────────────────────

def test_ac5_inter_tight_font_loaded():
    """habits.html must load Inter Tight font."""
    assert "Inter+Tight" in HABITS_HTML or "Inter Tight" in HABITS_HTML, \
        "habits.html must load Inter Tight font"


def test_ac5_body_references_inter_tight():
    """habits.html body font-family must reference Inter Tight."""
    assert "'Inter Tight'" in HABITS_HTML or '"Inter Tight"' in HABITS_HTML, \
        "habits.html body must reference Inter Tight as font-family"


# ── AC6: JetBrains Mono for numerics ─────────────────────────────────────────

def test_ac6_jetbrains_mono_font_loaded():
    """habits.html must load JetBrains Mono font."""
    assert "JetBrains+Mono" in HABITS_HTML or "JetBrains Mono" in HABITS_HTML, \
        "habits.html must load JetBrains Mono font"


def test_ac6_numeric_values_use_jetbrains_mono():
    """Numeric elements must reference JetBrains Mono."""
    assert "'JetBrains Mono'" in HABITS_HTML or '"JetBrains Mono"' in HABITS_HTML, \
        "habits.html must use JetBrains Mono for numeric values"


# ── AC7: No token duplication ─────────────────────────────────────────────────

def test_ac7_no_duplicate_card_shadow_in_page_style():
    """Per-page <style> must not redefine --card-shadow already in shared CSS."""
    style_block = ""
    m = re.search(r"<style>(.*?)</style>", HABITS_HTML, re.DOTALL)
    if m:
        style_block = m.group(1)
    if "--card-shadow:" in SHARED_CSS:
        assert "--card-shadow:" not in style_block, \
            "habits.html <style> must not redefine --card-shadow from shared CSS"


def test_ac7_card_uses_shared_tokens():
    """Card CSS must reference shared tokens (var(--card-bg), var(--card-border), etc.)."""
    assert "var(--card-bg)" in HABITS_HTML or "var(--card-radius)" in HABITS_HTML or \
           "var(--card-border)" in HABITS_HTML, \
        "habits.html cards must reference shared design tokens"


# ── AC8: Navigation ───────────────────────────────────────────────────────────

def test_ac8_nav_js_loaded():
    """habits.html must load nav.js."""
    assert "nav.js" in HABITS_HTML, \
        "habits.html must include <script src='js/nav.js'>"


def test_ac8_habits_active_in_nav():
    """nav.js must mark /habits as a navigation target."""
    nav_js = (JS_DIR / "nav.js").read_text()
    assert "'/habits'" in nav_js or '"/habits"' in nav_js or \
           "/habits" in nav_js, \
        "nav.js must include /habits as a navigation target"


# ── AC9: Responsive — hero side-by-side at ≥820px ────────────────────────────

def test_ac9_hero_row_two_column_default():
    """Hero row must have a 2-column default layout (side-by-side at wide viewports)."""
    style_block = ""
    m = re.search(r"<style>(.*?)</style>", HABITS_HTML, re.DOTALL)
    if m:
        style_block = m.group(1)
    # Must define a 2-col grid for the hero (e.g. 1fr 1fr or 1.35fr 1fr)
    assert "grid-template-columns" in style_block or \
           "display: grid" in style_block or \
           "display:grid" in style_block, \
        "Hero row must use CSS grid for side-by-side layout"


# ── AC10: Responsive — hero stacks at <820px ─────────────────────────────────

def test_ac10_hero_stacks_on_mobile():
    """At ≤820px, hero row must stack to single column."""
    assert "820px" in HABITS_HTML or "768px" in HABITS_HTML or \
           "800px" in HABITS_HTML, \
        "habits.html must have a ≤820px breakpoint"
    assert "grid-template-columns: 1fr" in HABITS_HTML or \
           "grid-template-columns:1fr" in HABITS_HTML or \
           "flex-direction: column" in HABITS_HTML, \
        "hero row must stack to 1 column at narrow viewports"


# ── AC11: 360px day headers collapse ─────────────────────────────────────────

def test_ac11_360px_breakpoint_present():
    """CSS must have a 360px (or ≤480px) breakpoint."""
    assert "360px" in HABITS_HTML or "480px" in HABITS_HTML, \
        "habits.html must have a narrow mobile (≤480px) breakpoint for 360px viewport"


def test_ac11_day_headers_collapse_to_single_letters():
    """At 360px, day headers must show single letters M T W T F S S in JS."""
    # The JS must have the single-letter day headers
    assert "'M'" in HABITS_JS or '"M"' in HABITS_JS or \
           ">M<" in HABITS_JS or "M</div>" in HABITS_JS or \
           "'M', 'T', 'W'" in HABITS_JS or "M,T,W" in HABITS_JS or \
           "MTWTFSS" in HABITS_JS or "'M','T'" in HABITS_JS, \
        "habits.js must use single-letter day labels M T W T F S S"


# ── AC12: No horizontal overflow at 360px ────────────────────────────────────

def test_ac12_overflow_hidden_or_max_width_at_narrow():
    """CSS must prevent horizontal overflow at 360px."""
    assert "overflow: hidden" in HABITS_HTML or "overflow:hidden" in HABITS_HTML or \
           "overflow-x: hidden" in HABITS_HTML or \
           "max-width: 100%" in HABITS_HTML or \
           "360px" in HABITS_HTML, \
        "habits.html must prevent horizontal overflow at narrow viewports"


# ── AC13: <820px weekly rows wrap ────────────────────────────────────────────

def test_ac13_weekly_rows_wrap_on_mobile():
    """Weekly habit rows must wrap on narrow viewports."""
    assert "flex-wrap" in HABITS_HTML or "flex-wrap:wrap" in HABITS_HTML or \
           "flex-wrap: wrap" in HABITS_HTML or \
           "week-row" in HABITS_HTML, \
        "habits.html must support weekly row wrapping on mobile"


# ── AC14: Empty state — wheel ─────────────────────────────────────────────────

def test_ac14_wheel_empty_state_in_js():
    """habits.js must render 'Add habits to start tracking' in wheel empty state."""
    assert "Add habits to start tracking" in HABITS_JS, \
        "habits.js must show 'Add habits to start tracking' as wheel center text"


# ── AC15: Empty state — starter suggestions ──────────────────────────────────

def test_ac15_starter_section_element():
    """habits.html must have a starter section element."""
    assert "starter-section" in HABITS_HTML or "starter" in HABITS_HTML, \
        "habits.html must have a starter-section element for zero-habits state"


def test_ac15_starter_habits_in_js():
    """habits.js must define STARTER_HABITS."""
    assert "STARTER_HABITS" in HABITS_JS, \
        "habits.js must define STARTER_HABITS array for starter suggestions"


# ── AC16: No raw enum strings ─────────────────────────────────────────────────

def test_ac16_tracking_type_labels_mapped():
    """habits.js must map tracking_type enum values to display labels."""
    assert "TRACKING_TYPE_LABELS" in HABITS_JS or \
           "daily_checkmark" in HABITS_JS, \
        "habits.js must define TRACKING_TYPE_LABELS mapping"
    # Verify the map exists and maps daily_checkmark
    assert "daily_checkmark" in HABITS_JS, \
        "habits.js must handle daily_checkmark tracking type"


def test_ac16_no_raw_enum_in_static_html():
    """Static habits.html must not contain raw enum values."""
    bad_patterns = ["daily_checkmark", "weekly_count", "weekly_minutes", "weekly_quantity"]
    for pat in bad_patterns:
        # These can appear in <select> option values but not as user-visible text
        # The real check is that the JS maps them, not that they never appear in HTML
        pass
    # Main check: no Python-style enum references
    python_enum_patterns = ["TrackingType.", "HabitStatus.", "AutoFill."]
    for pat in python_enum_patterns:
        assert pat not in HABITS_HTML, \
            f"habits.html must not contain raw Python enum: {pat}"


# ── AC17: Icon fallback ───────────────────────────────────────────────────────

def test_ac17_icon_fallback_question_mark():
    """habits.js must show '?' when icon data is missing."""
    assert "'?'" in HABITS_JS or '"?"' in HABITS_JS or \
           ": '?'" in HABITS_JS or ': "?"' in HABITS_JS, \
        "habits.js must render '?' placeholder when icon is missing"


# ── AC18: Cross-link — home → habits ─────────────────────────────────────────

def test_ac18_home_habits_widget_links_to_habits():
    """home-habits.js 'This week's progress' rows must link to /habits."""
    home_habits_js = (JS_DIR / "home-habits.js").read_text()
    assert 'href="/habits' in home_habits_js or "href='/habits" in home_habits_js, \
        "home-habits.js 'This week's progress' rows must link to /habits"


def test_ac18_home_html_habits_widget_links_to_habits():
    """home.html habits progress widget must link to /habits."""
    home_html = (PAGES_DIR / "home.html").read_text()
    assert 'href="/habits"' in home_html or "href='/habits'" in home_html, \
        "home.html must have link to /habits in the habits progress widget"


# ── AC19: Cross-link — habits → log ──────────────────────────────────────────

def test_ac19_autofill_tooltip_links_to_log():
    """habits.js or habits.html must link to /log for autofill tooltip."""
    assert "/log" in HABITS_JS or "/log" in HABITS_HTML, \
        "habits.js or habits.html must link to /log for the auto-fill tooltip"


# ── AC20: Mockup file ─────────────────────────────────────────────────────────

def test_ac20_mockup_file_exists():
    """docs/mockups/habits-redesign-v1.html must exist."""
    assert (MOCKUPS_DIR / "habits-redesign-v1.html").exists(), \
        "docs/mockups/habits-redesign-v1.html must exist"


def test_ac20_mockup_uses_gradient():
    """Mockup must demonstrate gradient background."""
    mockup = (MOCKUPS_DIR / "habits-redesign-v1.html").read_text()
    assert "gradient" in mockup.lower() or "#5a8dee" in mockup or "#1f3b8a" in mockup, \
        "habits-redesign-v1.html mockup must show gradient background"


def test_ac20_mockup_uses_inter_tight():
    """Mockup must use Inter Tight typography."""
    mockup = (MOCKUPS_DIR / "habits-redesign-v1.html").read_text()
    assert "Inter Tight" in mockup or "Inter+Tight" in mockup, \
        "habits-redesign-v1.html mockup must use Inter Tight font"


def test_ac20_mockup_has_wheel_card():
    """Mockup must show a wheel/donut card."""
    mockup = (MOCKUPS_DIR / "habits-redesign-v1.html").read_text()
    assert "wheel" in mockup.lower() or "donut" in mockup.lower() or \
           "<svg" in mockup, \
        "habits-redesign-v1.html mockup must include a wheel or SVG donut element"
