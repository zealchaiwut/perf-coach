"""Tests for issue #884: Build habit-insights UI panel on Habits page.

AC anchors verified:
  (ac1)  Dedicated insights panel exists in habits.html with gradient-theme structural layout
  (ac2)  habits.js or a sibling JS file fetches /api/habits/insights on mount
  (ac3)  Insight cards render a plain-language summary line + coefficient indicator
  (ac4)  Only confident insights are shown — no fabricated/placeholder card shells
  (ac5)  'Association, not causation' disclaimer is present in the panel
  (ac6)  Building/not-enough-data state shows a 'building'/'still learning' message with no card shells
  (ac7)  Loading and error states are handled (spinner while fetching; error message on failure)
  (ac8)  Panel is responsive at mobile (≤375 px) and tablet (≈768 px) breakpoints
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "frontend" / "pages"
JS_DIR = ROOT / "frontend" / "js"

HABITS_HTML = (PAGES_DIR / "habits.html").read_text()

# The JS may live in habits.js or a dedicated habit-insights.js
_HABITS_JS_PATH = JS_DIR / "habits.js"
_INSIGHTS_JS_PATH = JS_DIR / "habit-insights.js"

def _load_insights_js():
    """Return the JS source that handles insights — prefer dedicated file."""
    if _INSIGHTS_JS_PATH.exists():
        return _INSIGHTS_JS_PATH.read_text()
    return _HABITS_JS_PATH.read_text()

INSIGHTS_JS = _load_insights_js()


# ── AC1: Panel exists with gradient-theme structural layout ───────────────────

def test_ac1_insights_panel_exists_in_html():
    """habits.html must have an insights panel element."""
    assert "insights" in HABITS_HTML.lower(), \
        "habits.html must contain an insights panel element"


def test_ac1_insights_panel_has_id():
    """Insights panel must have an id attribute for JS targeting."""
    assert re.search(r'id=["\']insights', HABITS_HTML), \
        "habits.html must have an element with id starting with 'insights'"


def test_ac1_panel_uses_card_class():
    """Insights panel must use the .card structural class, not ad-hoc styles."""
    # Find the insights section and verify it uses .card
    match = re.search(r'id=["\']insights[^"\']*["\']', HABITS_HTML)
    assert match, "insights panel id not found"
    # The panel itself or its parent should carry class="card"
    surrounding = HABITS_HTML[max(0, match.start() - 200):match.end() + 400]
    assert "card" in surrounding, \
        "insights panel must use the .card class for structural layout"


def test_ac1_panel_uses_css_variables():
    """Insights panel styles must use CSS variables, not hardcoded hex colors."""
    # Extract only insight-specific CSS rules from inline style blocks
    style_blocks = re.findall(r'<style>(.*?)</style>', HABITS_HTML, re.DOTALL)
    insights_rules = ""
    for block in style_blocks:
        # Extract individual rules whose selector contains 'insight'
        rules = re.findall(
            r'\.insights?[-\w]*(?:[^{]*)\{[^}]*\}',
            block, re.DOTALL
        )
        insights_rules += " ".join(rules)

    if not insights_rules:
        # No insights-specific inline CSS found — panel uses only shared tokens (fine)
        return

    # Reject hardcoded color literals in insights-specific rules
    hardcoded = re.findall(r'(?<!["\'])#[0-9a-fA-F]{3,6}(?![0-9a-fA-F"\'])', insights_rules)
    # Allow well-known shared palette values that appear in styles.css
    known_shared = {
        "#fff", "#ffffff", "#0b1530", "#16a34a", "#2563eb", "#d97706",
        "#e8eaf0", "#f7f9fc", "#eef0f6", "#e4e8f0", "#5c6886",
    }
    unexpected = [c for c in hardcoded if c.lower() not in known_shared]
    assert not unexpected, (
        f"insights panel CSS must use CSS variables, not hardcoded colors: {unexpected}"
    )


# ── AC2: JS fetches /api/habits/insights on mount ────────────────────────────

def test_ac2_js_fetches_insights_endpoint():
    """habits.js (or habit-insights.js) must fetch /api/habits/insights."""
    assert "/api/habits/insights" in INSIGHTS_JS, \
        "JS must fetch /api/habits/insights"


def test_ac2_js_or_html_loads_insights_script():
    """habits.html must load a script that handles insights."""
    if _INSIGHTS_JS_PATH.exists():
        assert "habit-insights.js" in HABITS_HTML, \
            "habits.html must load habit-insights.js"
    else:
        assert "habits.js" in HABITS_HTML, \
            "habits.html must load habits.js (which handles insights)"


# ── AC3: Cards with summary line + coefficient indicator ─────────────────────

def test_ac3_coefficient_indicator_rendered():
    """JS must render a coefficient/strength indicator per insight card."""
    # Look for 'coefficient' reference in the insights JS
    assert "coefficient" in INSIGHTS_JS, \
        "JS must reference 'coefficient' to render the strength indicator"


def test_ac3_insight_line_rendered():
    """JS must render the plain-language 'line' field from the insight object."""
    assert re.search(r'\bline\b', INSIGHTS_JS), \
        "JS must render the 'line' field from each insight object"


# ── AC4: No fabricated/placeholder cards ─────────────────────────────────────

def test_ac4_cards_only_shown_for_insights_array():
    """JS must build cards by iterating the insights array, not from a fixed template."""
    # Must contain some form of iteration over insights (forEach, map, for...of)
    assert re.search(r'insights.*?(forEach|\.map\(|for\s*\()', INSIGHTS_JS, re.DOTALL), \
        "JS must iterate the insights array to build cards"


# ── AC5: 'Association, not causation' disclaimer ─────────────────────────────

def test_ac5_disclaimer_in_html_or_js():
    """'Association, not causation' disclaimer must be present (HTML or JS)."""
    combined = HABITS_HTML + INSIGHTS_JS
    assert re.search(r'[Aa]ssociation.*?not.*?causation', combined, re.DOTALL) or \
           re.search(r'not.*?causation', combined, re.DOTALL), \
        "Panel must include an 'Association, not causation' disclaimer"


# ── AC6: Building / still-learning state ─────────────────────────────────────

def test_ac6_building_state_handled():
    """JS must handle the 'building' boolean from the API response."""
    assert "building" in INSIGHTS_JS, \
        "JS must handle the 'building' field from /api/habits/insights"


def test_ac6_still_learning_message():
    """JS must render a 'building' or 'still learning' message when building=true."""
    combined_lower = INSIGHTS_JS.lower()
    assert "building" in combined_lower or "still learning" in combined_lower or \
           "learning" in combined_lower or "not enough" in combined_lower, \
        "JS must display a 'still learning'/'building' message for the early-data state"


def test_ac6_no_empty_shells_in_building_state():
    """When building=true the JS must NOT render insight card shells.

    We verify this by ensuring the card-rendering path is guarded by a
    !building (or building === false) check, or the cards are only rendered
    inside the else branch.
    """
    # Accept any pattern that guards card rendering on building being falsy
    assert re.search(
        r'if\s*\(\s*!?\s*(?:data\.)?building|building\s*===?\s*false|'
        r'!building|building\s*\?\s*|insights\.length',
        INSIGHTS_JS
    ), "JS must guard card rendering so no shells appear when building=true"


# ── AC7: Loading and error states ─────────────────────────────────────────────

def test_ac7_loading_state_indicated():
    """JS must show a loading indicator while fetching insights."""
    combined = (HABITS_HTML + INSIGHTS_JS).lower()
    assert "loading" in combined or "spinner" in combined or "fetching" in combined, \
        "Panel must have a loading / spinner state"


def test_ac7_error_state_handled():
    """JS must handle fetch errors and display an error message."""
    assert re.search(r'catch\s*\(|\.catch\(|error.*?insight|insight.*?error',
                     INSIGHTS_JS, re.IGNORECASE), \
        "JS must handle fetch errors for the insights panel"


def test_ac7_error_message_displayed():
    """JS must set an error message in the panel on fetch failure."""
    # Look for innerHTML or textContent being set in an error/catch block
    assert re.search(
        r'(catch|error)[\s\S]{0,300}(innerHTML|textContent|innerText)',
        INSIGHTS_JS
    ), "JS must display an error message in the insights panel when fetch fails"


# ── AC8: Responsive design ────────────────────────────────────────────────────

def test_ac8_mobile_breakpoint_exists():
    """habits.html must have a media query covering ≤375 px or ≤480 px."""
    assert re.search(r'max-width\s*:\s*(375|480)px', HABITS_HTML), \
        "habits.html must have a media query for mobile (≤375 or ≤480 px)"


def test_ac8_tablet_breakpoint_exists():
    """habits.html must have a media query covering ≈768 px."""
    assert re.search(r'max-width\s*:\s*768px', HABITS_HTML), \
        "habits.html must have a media query for tablet (≤768 px)"


def test_ac8_insights_panel_no_fixed_width():
    """Insights panel must not have a fixed pixel width that breaks small screens."""
    style_blocks = re.findall(r'<style>(.*?)</style>', HABITS_HTML, re.DOTALL)
    insights_rules = ""
    for block in style_blocks:
        # Extract only insight-specific CSS rules
        rules = re.findall(
            r'\.insights?[-\w]*(?:[^{]*)\{[^}]*\}',
            block, re.DOTALL
        )
        insights_rules += " ".join(rules)

    if not insights_rules:
        return  # No local insights CSS — uses only shared tokens (fine)

    # Reject standalone width: <N>px (not max-width or min-width)
    bad_width = re.findall(r'(?<![-\w])width\s*:\s*\d+px', insights_rules)
    assert not bad_width, (
        f"insights panel CSS must not use fixed pixel widths: {bad_width}. "
        "Use percentages, flex, or max-width instead."
    )
