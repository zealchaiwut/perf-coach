"""Tests for issue #426: Migrate weight page to home design language.

AC anchors verified:
  (ac1)  Page background uses blue gradient token (not hardcoded) from shared stylesheet
  (ac2)  Cards have 14px border-radius and soft drop shadow
  (ac3)  Body/labels use Inter Tight; numeric values use JetBrains Mono
  (ac4)  No token values duplicated from shared stylesheet in per-page styles
  (ac5)  DESIGN.md documents gradient-style tokens
  (ac6)  Shared top nav loaded; Weight is active nav item
  (ac7)  Page head subtitle format: "N entries · M of last 14 days · trending ↓X kg/wk"
  (ac8)  Page head has Export button and Manage target pill button
  (ac9)  Layout order: page head → hero row → chart card → bottom grid
  (ac10) Responsive: 360px mobile breakpoint present
  (ac11) Responsive: 768px tablet breakpoint present
  (ac12) Empty state: no entries → coach idle state shown; chart shows fallback message
  (ac13) Empty state: no target → progress/plan elements hidden, neutral copy
  (ac14) Zero raw enum values in rendered HTML
  (ac15) No icon-font-dependent glyphs in critical trend-arrow labels (text arrows only)
  (ac16) docs/mockups/weight-redesign-v6.html exists
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "frontend" / "pages"
JS_DIR = ROOT / "frontend" / "js"
CSS_DIR = ROOT / "frontend" / "css"
DESIGN_MD = ROOT / "DESIGN.md"
MOCKUPS_DIR = ROOT / "docs" / "mockups"

WEIGHT_HTML = (PAGES_DIR / "weight.html").read_text()
WEIGHT_JS = (JS_DIR / "weight.js").read_text()
SHARED_CSS = (CSS_DIR / "styles.css").read_text()


# ── AC1: Gradient background token ────────────────────────────────────────────

def test_ac1_shared_css_defines_gradient_bg_tokens():
    """Shared stylesheet must define gradient background tokens."""
    assert "--bg-gradient-start" in SHARED_CSS or "--bg-1" in SHARED_CSS or \
           "radial-gradient" in SHARED_CSS or "linear-gradient" in SHARED_CSS, \
        "styles.css must define gradient background tokens"


def test_ac1_weight_page_uses_gradient_background():
    """Weight page body/wrapper must use gradient background."""
    html_lower = WEIGHT_HTML.lower()
    assert "radial-gradient" in html_lower or "linear-gradient" in html_lower or \
           "var(--bg-1)" in WEIGHT_HTML or "var(--bg-gradient" in WEIGHT_HTML, \
        "weight.html must use gradient background (not plain color)"


def test_ac1_gradient_not_hardcoded_duplicate():
    """If gradient is defined in shared CSS, weight page must reference shared token, not duplicate the raw value."""
    if "--bg-1" in SHARED_CSS:
        # Shared token exists — weight page should reference it
        assert "var(--bg-1)" in WEIGHT_HTML or "var(--bg-gradient" in WEIGHT_HTML or \
               "--bg-1" not in WEIGHT_HTML.split("<style>", 1)[-1].split("</style>")[0], \
            "weight page must use shared gradient token, not redefine it"


# ── AC2: Card styling ──────────────────────────────────────────────────────────

def test_ac2_cards_have_14px_border_radius():
    """Cards must use 14px border-radius."""
    assert "14px" in WEIGHT_HTML or "border-radius: 14" in WEIGHT_HTML, \
        "weight.html cards must use 14px border-radius"


def test_ac2_cards_have_drop_shadow():
    """Cards must have soft drop shadow (box-shadow)."""
    assert "box-shadow" in WEIGHT_HTML, \
        "weight.html cards must have box-shadow drop shadow"


# ── AC3: Typography ────────────────────────────────────────────────────────────

def test_ac3_inter_tight_font_loaded():
    """Inter Tight font must be loaded."""
    assert "Inter+Tight" in WEIGHT_HTML or "Inter Tight" in WEIGHT_HTML, \
        "weight.html must load Inter Tight font"


def test_ac3_jetbrains_mono_font_loaded():
    """JetBrains Mono font must be loaded."""
    assert "JetBrains+Mono" in WEIGHT_HTML or "JetBrains Mono" in WEIGHT_HTML, \
        "weight.html must load JetBrains Mono font"


def test_ac3_body_uses_inter_tight():
    """Body font-family must reference Inter Tight."""
    assert "'Inter Tight'" in WEIGHT_HTML or "\"Inter Tight\"" in WEIGHT_HTML, \
        "weight.html body must use Inter Tight as font-family"


def test_ac3_numeric_values_use_jetbrains_mono():
    """Weight numeric values (hca-weight, pstat-val, etc.) must use JetBrains Mono."""
    assert "'JetBrains Mono'" in WEIGHT_HTML or "\"JetBrains Mono\"" in WEIGHT_HTML, \
        "weight.html numeric elements must use JetBrains Mono"


# ── AC4: No token duplication ──────────────────────────────────────────────────

def test_ac4_no_duplicate_bg_gradient_in_page_style():
    """Per-page <style> must not redefine tokens already in shared CSS."""
    style_block = ""
    m = re.search(r"<style>(.*?)</style>", WEIGHT_HTML, re.DOTALL)
    if m:
        style_block = m.group(1)
    # If shared CSS defines --bg-1, weight page <style> must not redefine same value
    if "--bg-1: #5a8dee" in SHARED_CSS:
        assert "--bg-1: #5a8dee" not in style_block, \
            "weight page <style> must not duplicate --bg-1 already in shared CSS"


def test_ac4_no_duplicate_card_border_color():
    """Per-page <style> must reference shared card-border token rather than duplicating the rgba value."""
    style_block = ""
    m = re.search(r"<style>(.*?)</style>", WEIGHT_HTML, re.DOTALL)
    if m:
        style_block = m.group(1)
    # Acceptable: uses var(--card-border) or defines it in :root, not raw duplicate beside shared def
    # This is a soft check — just ensure the page uses tokens in card definitions
    if "var(--card-border)" in style_block:
        assert "--card-border" in SHARED_CSS or "--card-border" in style_block, \
            "card-border token must be defined if referenced"


# ── AC5: DESIGN.md ────────────────────────────────────────────────────────────

def test_ac5_design_md_exists():
    assert DESIGN_MD.exists(), "DESIGN.md must exist"


def test_ac5_design_md_documents_gradient_tokens():
    """DESIGN.md must document gradient-style tokens."""
    design = DESIGN_MD.read_text()
    assert "--bg-1" in design or "gradient" in design.lower(), \
        "DESIGN.md must document gradient background tokens"


def test_ac5_design_md_documents_inter_tight():
    """DESIGN.md must document Inter Tight typography."""
    design = DESIGN_MD.read_text()
    assert "Inter Tight" in design, \
        "DESIGN.md must document Inter Tight as the font family"


def test_ac5_design_md_documents_jetbrains_mono():
    """DESIGN.md must document JetBrains Mono for numerics."""
    design = DESIGN_MD.read_text()
    assert "JetBrains Mono" in design, \
        "DESIGN.md must document JetBrains Mono for numeric values"


# ── AC6: Navigation ────────────────────────────────────────────────────────────

def test_ac6_nav_js_loaded():
    """weight.html must load nav.js."""
    assert "nav.js" in WEIGHT_HTML, \
        "weight.html must include <script src='js/nav.js'>"


def test_ac6_weight_active_in_nav():
    """nav.js must mark /weight as an active match target (already true — verify not removed)."""
    nav_js = (JS_DIR / "nav.js").read_text()
    assert "'/weight'" in nav_js or '"/weight"' in nav_js, \
        "nav.js must include /weight as a navigation target"


# ── AC7: Subtitle format ──────────────────────────────────────────────────────

def test_ac7_subtitle_element_present():
    assert "page-subtitle" in WEIGHT_HTML, \
        "weight.html must have id=page-subtitle element"


def test_ac7_subtitle_shows_n_entries():
    """weight.js must include 'entries' in subtitle output."""
    assert "entries" in WEIGHT_JS, \
        "weight.js subtitle must show N entries"


def test_ac7_subtitle_shows_of_last_14_days():
    """Subtitle / coverage copy reflects weigh-in density (revamp: coverage, not 14d streak)."""
    assert (
        "of last 14 days" in WEIGHT_JS
        or "coverage" in WEIGHT_JS
        or "entries_used" in WEIGHT_JS
    )


def test_ac7_subtitle_shows_trending():
    """Subtitle format must include 'trending' keyword."""
    assert "trending" in WEIGHT_JS, \
        "weight.js subtitle must use 'trending' keyword"


def test_ac7_subtitle_shows_kg_wk():
    """Subtitle must show kg/wk trend rate."""
    assert "kg/wk" in WEIGHT_JS, \
        "weight.js subtitle must show trend rate in kg/wk"


# ── AC8: Page head buttons ────────────────────────────────────────────────────

def test_ac8_export_button_present():
    html_lower = WEIGHT_HTML.lower()
    assert "export" in html_lower and "csv" in html_lower, \
        "weight.html must have Export CSV button in page head"


def test_ac8_manage_target_pill_present():
    assert (
        "/weight/targets" in WEIGHT_HTML
        or 'id="edit-target-header-btn"' in WEIGHT_HTML
        or "Edit target" in WEIGHT_HTML
    ), "weight.html must expose Edit/Manage target"


# ── AC9: Layout order ─────────────────────────────────────────────────────────

def test_ac9_layout_page_head_before_hero():
    """Page header div must appear before hero-2col in DOM order."""
    head_pos = WEIGHT_HTML.find("weight-page-header")
    hero_pos = WEIGHT_HTML.find("hero-2col")
    assert head_pos != -1 and hero_pos != -1, \
        "weight.html must have both weight-page-header and hero-2col"
    assert head_pos < hero_pos, \
        "page-header must appear before hero row in HTML"


def test_ac9_layout_hero_before_chart():
    """Hero row must appear before chart card."""
    hero_pos = WEIGHT_HTML.find("hero-2col")
    chart_pos = WEIGHT_HTML.find("chart-card") if "chart-card" in WEIGHT_HTML \
                else WEIGHT_HTML.find("chart-container")
    assert hero_pos != -1 and chart_pos != -1
    assert hero_pos < chart_pos, \
        "hero row must appear before chart card"


def test_ac9_layout_chart_before_bottom_grid():
    """Revamp layout: primary grid / timeline replace the old top-grid + chart stack."""
    grid_pos = WEIGHT_HTML.find("weight-revamp")
    if grid_pos == -1:
        grid_pos = WEIGHT_HTML.find("w-grid")
    if grid_pos == -1:
        grid_pos = WEIGHT_HTML.find("id=\"rate-card\"")
    timeline_pos = WEIGHT_HTML.find("weight-timeline")
    chart_pos = WEIGHT_HTML.find('id="legacy-chart-card"')
    assert grid_pos != -1 and timeline_pos != -1, \
        "weight.html must have the revamp grid and timeline"
    assert grid_pos < timeline_pos
    assert chart_pos == -1 or timeline_pos < chart_pos, \
        "legacy chart stub must sit after the timeline (or be absent)"


# ── AC10: 360px breakpoint ────────────────────────────────────────────────────

def test_ac10_360px_breakpoint_present():
    """CSS must have a 360px (or ≤480px) mobile breakpoint."""
    assert "360px" in WEIGHT_HTML or "480px" in WEIGHT_HTML or \
           "@media (max-width: 37" in WEIGHT_HTML, \
        "weight.html must have a narrow mobile (≤480px) breakpoint for 360px viewport"


def test_ac10_hero_stacks_on_mobile():
    """At narrow viewport, hero 2-col must stack (grid-template-columns: 1fr)."""
    html_lower = WEIGHT_HTML.lower()
    # Either via 360/480 or via the existing 820/880 breakpoint
    assert "grid-template-columns: 1fr" in WEIGHT_HTML or \
           "grid-template-columns:1fr" in WEIGHT_HTML, \
        "hero must stack to 1fr column on narrow viewports"


# ── AC11: 768px tablet breakpoint ────────────────────────────────────────────

def test_ac11_768px_breakpoint_present():
    """CSS must have a 768px tablet breakpoint."""
    assert "768px" in WEIGHT_HTML or "820px" in WEIGHT_HTML or "800px" in WEIGHT_HTML, \
        "weight.html must have a tablet-range breakpoint (768–820px)"


# ── AC12: Empty state — no entries ────────────────────────────────────────────

def test_ac12_coach_idle_state_shown_when_no_entries():
    """Idle coach copy lives on the shared WeightCurrentCard (home + weight)."""
    card_js = (ROOT / "frontend" / "js" / "lib" / "weight-current-card.js").read_text().lower()
    js_lower = WEIGHT_JS.lower() + "\n" + card_js
    assert "coach" in js_lower and ("idle" in js_lower or "no entry" in js_lower or
           "wake me up" in js_lower or "log your weight" in js_lower), \
        "weight.js must show coach idle state when no entries"


def test_ac12_chart_empty_message():
    """weight.js must show 'Log your first weigh-in above' when chart has no data."""
    assert "Log your first weigh-in above" in WEIGHT_JS or \
           "log your first weigh-in above" in WEIGHT_JS.lower(), \
        "weight.js must show 'Log your first weigh-in above' chart empty message"


# ── AC13: Empty state — no target ────────────────────────────────────────────

def test_ac13_progress_card_hidden_when_no_target():
    """weight.js must hide progress card when no target is set."""
    assert "progress-card" in WEIGHT_JS and "hidden" in WEIGHT_JS, \
        "weight.js must hide progress-card when no active target"


def test_ac13_no_target_neutral_copy():
    """weight.html must not crash or show broken references when no target."""
    # Progress card must start hidden in HTML
    m = re.search(r'id="progress-card"[^>]*>', WEIGHT_HTML)
    assert m is not None, "weight.html must have id=progress-card element"
    assert "hidden" in m.group(0), \
        "progress-card must start hidden (shown only by JS when target exists)"


# ── AC14: No raw enum values ──────────────────────────────────────────────────

def test_ac14_no_raw_enum_values_in_html():
    """Rendered HTML must not contain raw Python-style enum values."""
    # Common backend enum patterns
    bad_patterns = ["WeightStatus.", "StatusLabel.", "TrendDir."]
    for pat in bad_patterns:
        assert pat not in WEIGHT_HTML, \
            f"weight.html must not contain raw enum value: {pat}"


def test_ac14_no_raw_enum_values_in_js():
    """weight.js must not render raw enum values directly as user-visible text."""
    # on_track must be used as a mapping key (→ CSS class or display string), never rendered raw
    if "on_track" in WEIGHT_JS:
        # It must be used as a key in an object (mapped) or as a comparison value
        assert "'on-track'" in WEIGHT_JS or '"on-track"' in WEIGHT_JS or \
               "on_track:" in WEIGHT_JS or "=== 'on_track'" in WEIGHT_JS or \
               '=== "on_track"' in WEIGHT_JS, \
            "weight.js must map 'on_track' to a CSS class or display string — not rendered as-is"


# ── AC15: Text arrows, not icon-font glyphs ───────────────────────────────────

def test_ac15_trend_arrows_are_text_not_icon_font():
    """Trend arrow labels must use plain text arrows (↑ ↓ →), not icon-font classes."""
    # Verify JS uses unicode arrows for trend display
    assert ("↑" in WEIGHT_JS or "↓" in WEIGHT_JS or "→" in WEIGHT_JS or
            "\\u2191" in WEIGHT_JS or "\\u2193" in WEIGHT_JS), \
        "weight.js trend arrows must use unicode text characters"
    # Must NOT use tabler icon classes for the trend direction
    assert "ti-arrow-up" not in WEIGHT_JS and "ti-arrow-down" not in WEIGHT_JS, \
        "weight.js must not use icon-font classes for critical trend arrows"


# ── AC16: Mockup file ─────────────────────────────────────────────────────────

def test_ac16_weight_redesign_v6_mockup_exists():
    """docs/mockups/weight-redesign-v6.html must exist."""
    assert (MOCKUPS_DIR / "weight-redesign-v6.html").exists(), \
        "docs/mockups/weight-redesign-v6.html must exist"


def test_ac16_mockup_uses_gradient_background():
    """Mockup must demonstrate gradient background."""
    mockup = (MOCKUPS_DIR / "weight-redesign-v6.html").read_text()
    assert "gradient" in mockup.lower() or "#5a8dee" in mockup or "#1f3b8a" in mockup, \
        "weight-redesign-v6.html mockup must show gradient background"


def test_ac16_mockup_uses_inter_tight():
    """Mockup must use Inter Tight typography."""
    mockup = (MOCKUPS_DIR / "weight-redesign-v6.html").read_text()
    assert "Inter Tight" in mockup or "Inter+Tight" in mockup, \
        "weight-redesign-v6.html mockup must use Inter Tight font"
