"""
TDD tests for issue #422 – Rebuild weight page hero with 2-card layout.

These tests verify the frontend HTML and JS structure without a live server.
They parse the source files to confirm AC-required elements, CSS rules, and
JS logic are present and correct.
"""

import re
from pathlib import Path

WEIGHT_HTML = Path(__file__).parent.parent / "frontend" / "pages" / "weight.html"
WEIGHT_JS   = Path(__file__).parent.parent / "frontend" / "js" / "weight.js"

html = WEIGHT_HTML.read_text()
js   = WEIGHT_JS.read_text()


# ── AC: Hero renders as 2-card row with CSS grid 1.35fr / 1fr ─────────────

def test_hero_grid_class_exists():
    """HTML contains the 2-col hero container."""
    assert "hero-2col" in html, "Expected class 'hero-2col' in weight.html"


def test_hero_grid_css_columns():
    """CSS grid-template-columns is 1.35fr / 1fr."""
    # normalise whitespace for matching
    normalised = re.sub(r"\s+", " ", html)
    assert "1.35fr" in normalised and "1fr" in normalised, \
        "Expected grid-template-columns: 1.35fr / 1fr in weight.html CSS"


def test_hero_stacks_at_820px():
    """Media query collapses hero to single column at ≤820px."""
    assert "820px" in html, "Expected @media (max-width: 820px) rule in weight.html"
    # After the 820px breakpoint, hero-2col must switch to grid-template-columns:1fr
    m = re.search(
        r"820px.*?hero-2col.*?grid-template-columns\s*:\s*1fr",
        html, re.DOTALL
    )
    assert m, "hero-2col not set to 1fr column inside 820px media query"


# ── AC: Card A – CURRENT WEIGHT label + relative logged-date sub ──────────

def test_card_a_current_weight_label():
    """Card A contains 'CURRENT WEIGHT' text label."""
    assert "CURRENT WEIGHT" in html, "Expected 'CURRENT WEIGHT' label in weight.html"


def test_card_a_logged_date_element():
    """Card A has element for relative logged-date sub (id used by JS)."""
    assert 'id="hca-date-sub"' in html, \
        "Expected element with id='hca-date-sub' for logged-date sub in weight.html"


# ── AC: Card A middle zone – 7-day avg, 42px weight, change pills ──────────

def test_card_a_avg_element():
    """Card A has 7-day avg element wired to JS."""
    assert 'id="hca-avg"' in html, \
        "Expected element with id='hca-avg' in weight.html"


def test_card_a_weight_element():
    """Card A has large current weight element at 42px monospace."""
    assert 'id="hca-weight"' in html, \
        "Expected element with id='hca-weight' in weight.html"
    assert "42px" in html or "2.625rem" in html, \
        "Expected 42px (or 2.625rem) font-size for current weight in weight.html CSS"


def test_card_a_pills_elements():
    """Card A has week and month change pill elements."""
    assert 'id="hca-pill-week"' in html, "Missing id='hca-pill-week'"
    assert 'id="hca-pill-month"' in html, "Missing id='hca-pill-month'"


def test_change_pills_use_text_arrows():
    """JS uses Unicode text arrows ↓/↑ for pills, not icon-font glyphs."""
    # The render function must use literal Unicode arrows
    assert "↓" in js and "↑" in js, "JS must use Unicode ↓/↑ text arrows for pills"
    # Must NOT use icon-font class patterns (e.g. fa-arrow, icon-, bi-)
    assert not re.search(r'class=["\'][^"\']*(?:fa-arrow|icon-arrow|bi-arrow)', js), \
        "JS must not use icon-font glyph classes for arrows"


# ── AC: Coach strip – 3 states ────────────────────────────────────────────

def test_coach_strip_element_exists():
    """HTML has coach strip element."""
    assert 'id="coach-strip"' in html, "Expected element with id='coach-strip'"


def test_coach_strip_grey_text():
    """Coach strip grey state text is present."""
    assert "No entry yet today" in html or "No entry yet today" in js, \
        "Expected grey coach state text 'No entry yet today'"


def test_coach_strip_amber_text():
    """Coach strip amber state text is present in JS."""
    assert "new day, keep going" in js, \
        "Expected amber coach state wording 'new day, keep going' in weight.js"


def test_coach_strip_green_text():
    """Coach strip green state text is present in JS."""
    assert "on pace this week" in js, \
        "Expected green coach state wording 'on pace this week' in weight.js"


def test_coach_sourced_from_logged_today():
    """JS references logged_today from chart data for coach logic."""
    assert "logged_today" in js, \
        "JS must reference 'logged_today' from /api/weight-chart response"


def test_coach_sourced_from_today_delta():
    """JS references today_delta_kg from chart data for coach logic."""
    assert "today_delta_kg" in js, \
        "JS must reference 'today_delta_kg' from /api/weight-chart response"


# ── AC: Card B – Log Today stepper ────────────────────────────────────────

def test_card_b_log_today_label():
    """Card B contains 'LOG TODAY' label."""
    assert "LOG TODAY" in html, "Expected 'LOG TODAY' label in weight.html"


def test_card_b_stepper_input_attributes():
    """Stepper input has step=0.1, min=20, max=300, inputmode=decimal."""
    assert 'step="0.1"' in html or "step='0.1'" in html, \
        "Stepper input missing step='0.1'"
    assert 'min="20"' in html or "min='20'" in html, \
        "Stepper input missing min='20'"
    assert 'max="300"' in html or "max='300'" in html, \
        "Stepper input missing max='300'"
    assert 'inputmode="decimal"' in html or "inputmode='decimal'" in html, \
        "Stepper input missing inputmode='decimal'"


def test_card_b_stepper_buttons():
    """Stepper has decrement and increment buttons."""
    assert 'id="stepper-dec"' in html, "Missing stepper decrement button (id='stepper-dec')"
    assert 'id="stepper-inc"' in html, "Missing stepper increment button (id='stepper-inc')"


def test_card_b_log_submit_button():
    """Card B has log submit button."""
    assert 'id="log-submit-btn"' in html, "Missing log submit button (id='log-submit-btn')"


def test_card_b_stepper_input_id():
    """Stepper input has expected id."""
    assert 'id="stepper-input"' in html, "Missing stepper input (id='stepper-input')"


# ── AC: Log button label live-updates with stepper value ──────────────────

def test_js_updates_log_button_label():
    """JS updates log button label to show current stepper value."""
    # Expect a function that updates the submit button text with current weight
    assert "log-submit-btn" in js, \
        "JS must reference log-submit-btn to update its label"
    assert "Log " in js, \
        "JS must set button text containing 'Log ' prefix followed by weight"


# ── AC: Stepper prefilled with most recent entry weight ───────────────────

def test_js_prefills_stepper():
    """JS prefills stepper with most recent entry weight on load."""
    assert "stepper-input" in js, "JS must reference stepper-input"
    # Look for prefill logic: setting value from chart stats or recent entries
    assert "current_weight_kg" in js or "_recentEntries" in js, \
        "JS must prefill stepper from current_weight_kg or recent entries"


# ── AC: Logged state strip ────────────────────────────────────────────────

def test_logged_strip_element_exists():
    """HTML has logged-state strip element."""
    assert 'id="logged-strip"' in html, \
        "Expected element with id='logged-strip' for post-log state"


def test_logged_strip_has_edit_link():
    """Logged strip has an Edit button/link."""
    assert 'id="edit-link"' in html, \
        "Expected element with id='edit-link' inside logged strip"


def test_js_shows_logged_strip_on_success():
    """JS shows logged strip after successful POST."""
    assert "logged-strip" in js, \
        "JS must show logged-strip element after successful log submission"


# ── AC: 409 race condition handled – fallback to PATCH ───────────────────

def test_js_handles_409_fallback_to_patch():
    """JS handles 409 from POST by falling back to PATCH."""
    assert "409" in js, "JS must handle 409 status from POST /api/weight-entries"
    assert "PATCH" in js, "JS must issue a PATCH request on 409 fallback"
    assert "existing_id" in js, \
        "JS must use existing_id from 409 response body for PATCH fallback"


# ── AC: No icon-font glyphs anywhere in hero ─────────────────────────────

def test_no_icon_font_glyphs_in_html():
    """Hero section uses no icon-font glyph class patterns."""
    hero_section = re.search(
        r'<div[^>]*class="[^"]*hero-2col[^"]*".*?</div>\s*</div>',
        html, re.DOTALL
    )
    if hero_section:
        fragment = hero_section.group()
    else:
        fragment = html  # fall back to full file

    bad_patterns = [
        r'class="[^"]*fa-',
        r'class="[^"]*icon-',
        r'class="[^"]*bi-',
        r'class="[^"]*glyphicon',
        r'class="[^"]*material-icons',
    ]
    for pattern in bad_patterns:
        assert not re.search(pattern, fragment), \
            f"Icon-font glyph pattern '{pattern}' found in hero section"


def test_no_icon_font_glyphs_in_js_hero():
    """JS hero render functions use no icon-font class strings."""
    bad_patterns = [r'"fa-', r"'fa-", r'"icon-', r"'icon-", r'"bi-', r"'bi-"]
    for pattern in bad_patterns:
        assert not re.search(pattern, js), \
            f"Icon-font class reference '{pattern}' found in weight.js"


# ── AC: Coach re-evaluates after log/edit ────────────────────────────────

def test_js_re_evaluates_coach_after_log():
    """JS calls coach render after successful log or edit."""
    # The re-render is implied by calling _reload or a dedicated refresh function
    # that re-fetches chart data (which includes logged_today/today_delta_kg)
    assert "renderCoachStrip" in js or "coach-strip" in js, \
        "JS must update coach strip after log/edit"
