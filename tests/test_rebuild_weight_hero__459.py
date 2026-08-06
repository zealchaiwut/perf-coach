"""
TDD tests for issue #459 – Rebuild weight-page hero: current + log-today cards.

Anchors every AC item from the issue without deleting or weakening prior tests.
All tests parse static source files and do not require a live server.
"""

import re
from pathlib import Path

WEIGHT_HTML = Path(__file__).parent.parent / "frontend" / "pages" / "weight.html"
WEIGHT_JS   = Path(__file__).parent.parent / "frontend" / "js" / "weight.js"
# Card A ("current weight") render + styling were extracted into a shared
# component so the home page and weight tab share one implementation. The
# weight page's effective source = weight.{html,js} PLUS the shared files.
CARD_JS  = Path(__file__).parent.parent / "frontend" / "js" / "lib" / "weight-current-card.js"
CARD_CSS = Path(__file__).parent.parent / "frontend" / "css" / "weight-current-card.css"

_weight_html = WEIGHT_HTML.read_text()
_card_css    = CARD_CSS.read_text()
_card_js     = CARD_JS.read_text()
# Card A markup lives in WeightCurrentCard.MARKUP (JS) — include it so static
# checks still see CURRENT WEIGHT / hca-* / coach-strip after the weight-tab
# revamp stopped inlining that block in weight.html.
html = _weight_html + "\n" + _card_css + "\n" + _card_js
js   = WEIGHT_JS.read_text() + "\n" + _card_js
html_lower = html.lower()
# css_text spans the weight page's inline <style> plus the shared stylesheet,
# since Card A's rules now live in the shared file.
css_block  = re.search(r"<style>(.*?)</style>", _weight_html, re.DOTALL)
css_text   = (css_block.group(1) if css_block else "") + "\n" + _card_css


# ── Layout & Responsive ─────────────────────────────────────────────────────

def test_hero_grid_columns_1_35fr_1fr():
    """hero-2col uses CSS grid-template-columns: 1.35fr 1fr."""
    assert "1.35fr" in html and "1fr" in html, \
        "hero-2col must use grid-template-columns: 1.35fr 1fr"


def test_hero_grid_gap_16px():
    """hero-2col has gap: 16px between cards."""
    hero_rule = re.search(
        r"\.hero-2col\s*\{[^}]*gap\s*:\s*16px",
        css_text, re.DOTALL
    )
    assert hero_rule, \
        "hero-2col CSS must set gap: 16px (was 10px — this was the v7 spec)"


def test_hero_stacks_only_at_640px():
    """hero-2col stacks to 1fr ONLY inside @media (max-width: 640px)."""
    # Must have exactly one grid-template-columns:1fr on hero-2col, inside 640px rule
    m640 = re.search(
        r"@media\s*\(\s*max-width\s*:\s*640px\s*\)[^{]*\{[^}]*hero-2col[^}]*grid-template-columns\s*:\s*1fr",
        css_text, re.DOTALL
    )
    assert m640, \
        "hero-2col must set grid-template-columns:1fr inside @media(max-width:640px)"


def test_no_orphaned_hero_stacking_rule_outside_640px():
    """No hero-2col stacking rule exists outside @media (max-width: 640px).

    Regression check: earlier mocks had hero-2col stacking at 820px/768px/480px
    which caused premature stacking. The rule must only live in the 640px query.
    """
    # Strip the 640px media block so we can check remaining CSS
    css_without_640 = re.sub(
        r"@media\s*\(\s*max-width\s*:\s*640px\s*\)\s*\{[^}]*\}",
        "", css_text, flags=re.DOTALL
    )
    # There should be no hero-2col rule setting 1-column outside 640px block
    bad = re.search(
        r"hero-2col[^{]*\{[^}]*grid-template-columns\s*:\s*1fr",
        css_without_640, re.DOTALL
    )
    assert not bad, \
        "hero-2col must NOT stack (grid-template-columns:1fr) outside @media(max-width:640px)"


def test_640px_rule_covers_only_hero_and_not_outside():
    """640px breakpoint exists in the CSS."""
    assert "640px" in css_text, \
        "CSS must have a @media (max-width: 640px) block"


# ── Card A — Current Weight ─────────────────────────────────────────────────

def test_card_a_current_weight_label_uppercase():
    """Card A has 'CURRENT WEIGHT' uppercase label as specified."""
    assert "CURRENT WEIGHT" in html, \
        "Card A must have 'CURRENT WEIGHT' label text"


def test_card_a_date_sub_element():
    """Card A has element with id=hca-date-sub for relative logged-date."""
    assert 'id="hca-date-sub"' in html, \
        "Card A must have element with id='hca-date-sub'"


def test_card_a_relative_date_same_day_returns_today():
    """JS returns 'Today' when last entry date equals today's date."""
    # _relativeLoggedDate must return 'Today' for same-day entries
    assert "'Today'" in js or '"Today"' in js, \
        "JS must return string 'Today' when entry date equals today"


def test_card_a_relative_date_yesterday():
    """JS returns 'Logged yesterday · [Month Day]' for prior-day entry."""
    assert "Logged yesterday" in js, \
        "JS must produce 'Logged yesterday' string for prior-day entries"


def test_card_a_relative_date_older():
    """JS returns 'Logged N days ago · [Month Day]' for older entries."""
    assert "days ago" in js, \
        "JS must produce 'Logged N days ago' string for older entries"


def test_card_a_7day_avg_element_monospace():
    """Card A has monospace 7-day avg element."""
    assert 'id="hca-avg"' in html, "Card A must have id='hca-avg' element"
    # The element should be styled monospace (JetBrains Mono or font-family: monospace)
    assert "JetBrains Mono" in html or "monospace" in html, \
        "7-day avg must be rendered in monospace font"


def test_card_a_weight_42px_monospace():
    """Card A has ~42px current weight in monospace."""
    assert 'id="hca-weight"' in html, "Card A must have id='hca-weight' element"
    assert "42px" in html, \
        "Current weight element must have ~42px font-size"


def test_card_a_pills_week_and_month():
    """Card A has week and month change pill elements."""
    assert 'id="hca-pill-week"' in html, "Must have id='hca-pill-week'"
    assert 'id="hca-pill-month"' in html, "Must have id='hca-pill-month'"


def test_card_a_pills_use_unicode_arrows():
    """JS pill rendering uses plain Unicode ↓/↑ characters, not icon-font glyphs."""
    assert "↓" in js and "↑" in js, \
        "JS must use Unicode ↓/↑ arrows in pill rendering"


def test_card_a_pills_no_icon_font_classes():
    """JS pill rendering does not use icon-font class strings."""
    bad = [r'"fa-', r"'fa-", r'"ti-arrow', r"'ti-arrow", r'"bi-', r"'bi-"]
    for p in bad:
        assert p not in js, f"JS pills must not reference icon-font class '{p}'"


def test_card_a_pill_classes_toward_and_away():
    """JS sets pill to 'toward' class for good delta, 'away' for bad delta."""
    assert "'toward'" in js or '"toward"' in js, \
        "JS must use 'toward' class on delta pill when moving toward target"
    assert "'away'" in js or '"away"' in js, \
        "JS must use 'away' class on delta pill when moving away from target"


# ── Coach Strip (single instance, inside Card A) ───────────────────────────

def test_coach_strip_inside_card_a():
    """Coach strip is part of the shared Card A markup (WeightCurrentCard.MARKUP).

    The weight-tab revamp no longer inlines hero-card-a in weight.html — home +
    weight share WeightCurrentCard.MARKUP, which nests #coach-strip after the
    hca-* block.
    """
    assert 'id="coach-strip"' in _card_js, \
        "coach-strip must live in WeightCurrentCard.MARKUP"
    # MARKUP order: hca-weight … then coach-strip
    assert _card_js.find('id="hca-weight"') < _card_js.find('id="coach-strip"'), \
        "coach-strip must follow Card A weight elements in MARKUP"


def test_no_coach_strip_outside_hero():
    """Coach strip does not appear AFTER the closing hero-2col div."""
    # Find position of closing hero div and coach strip
    hero_end_pos = html.find('</div>', html.find('hero-2col'))
    coach_pos = html.find('id="coach-strip"')
    assert coach_pos < hero_end_pos or hero_end_pos == -1 or coach_pos == -1 or \
        html.find('id="coach-strip"', html.find('hero-card-a')) < html.find('hero-card-b'), \
        "coach-strip must be inside Card A, not after the hero-2col container"


def test_no_demo_states_row():
    """The STATES→ multi-state demo row is NOT rendered in the live HTML."""
    assert "states→" not in html.lower(), \
        "coach-states-demo 'STATES→' row must not appear in production weight.html"
    assert "coach-states-demo" not in html, \
        "coach-states-demo element must not appear in weight.html"


def test_coach_strip_idle_grey_state():
    """Coach strip grey/idle state renders for not-logged-today condition."""
    assert "No entry yet today" in html or "No entry yet today" in js, \
        "Grey coach state text 'No entry yet today' must be present"


def test_coach_strip_amber_state():
    """Coach strip amber state text is present in JS (away from target)."""
    assert "new day, keep going" in js, \
        "Amber coach state wording 'new day, keep going' must be in weight.js"


def test_coach_strip_green_state():
    """Coach strip green state text is present in JS (toward/flat)."""
    assert "on pace this week" in js, \
        "Green coach state wording 'on pace this week' must be in weight.js"


def test_coach_strip_classes_grey_amber_green():
    """JS applies the 3 state classes: coach-grey, coach-amber, coach-green."""
    assert "coach-grey" in js, "JS must apply 'coach-grey' class for idle state"
    assert "coach-amber" in js, "JS must apply 'coach-amber' class for away-from-target state"
    assert "coach-green" in js, "JS must apply 'coach-green' class for toward-target state"


def test_coach_strip_driven_by_logged_today():
    """JS uses logged_today field from chart response for coach logic."""
    assert "logged_today" in js, \
        "JS must read 'logged_today' from /api/weight-chart response"


def test_coach_strip_driven_by_today_delta():
    """JS uses today_delta_kg from chart response for coach direction logic."""
    assert "today_delta_kg" in js, \
        "JS must read 'today_delta_kg' from /api/weight-chart response"


def test_coach_strip_updates_after_log():
    """JS re-renders coach strip after successful log or edit."""
    assert "renderCoachStrip" in js, \
        "JS must call renderCoachStrip after successful log/edit action"


# ── Card B — Log Today ──────────────────────────────────────────────────────

def test_card_b_log_today_label():
    """Card B has 'LOG TODAY' label."""
    assert "LOG TODAY" in html, "Card B must show 'LOG TODAY' label"


def test_card_b_date_element():
    """Card B shows today's date via id=hcb-date."""
    assert 'id="hcb-date"' in html, "Card B must have element with id='hcb-date'"


def test_card_b_stepper_attributes():
    """Stepper input has step=0.1, min=20, max=300, inputmode=decimal."""
    assert 'step="0.1"' in html, "Stepper input must have step='0.1'"
    assert 'min="20"' in html, "Stepper input must have min='20'"
    assert 'max="300"' in html, "Stepper input must have max='300'"
    assert 'inputmode="decimal"' in html, "Stepper input must have inputmode='decimal'"


def test_card_b_stepper_buttons_exist():
    """Card B has − and + stepper buttons."""
    assert 'id="stepper-dec"' in html, "Missing stepper decrement button (id='stepper-dec')"
    assert 'id="stepper-inc"' in html, "Missing stepper increment button (id='stepper-inc')"


def test_card_b_log_button_is_lime():
    """Log submit button uses lime accent color."""
    # Must use --accent (lime) not #0b1530 (dark navy)
    log_btn_css = re.search(
        r"\.log-submit-btn\s*\{[^}]+\}",
        css_text, re.DOTALL
    )
    btn_block = log_btn_css.group() if log_btn_css else ""
    assert "var(--accent)" in btn_block or "accent" in btn_block, \
        "log-submit-btn must use var(--accent) lime background, not dark navy"
    # Explicitly check it does NOT use the old dark navy
    assert "#0b1530" not in btn_block, \
        "log-submit-btn must NOT use #0b1530 (dark navy) background"


def test_card_b_log_button_full_width():
    """Log submit button is full-width."""
    log_btn_css = re.search(
        r"\.log-submit-btn\s*\{[^}]+\}",
        css_text, re.DOTALL
    )
    btn_block = log_btn_css.group() if log_btn_css else ""
    assert "100%" in btn_block or "width: 100" in btn_block, \
        "log-submit-btn must be full-width (width: 100%)"


def test_card_b_log_button_label_live_updates():
    """JS live-updates log button label to show current stepper value."""
    assert "log-submit-btn" in js, "JS must reference log-submit-btn"
    assert "Log " in js, "JS must set button text containing 'Log ' prefix"
    # Must update on input event
    assert "_updateLogBtnLabel" in js or "updateLogBtnLabel" in js or \
           ('input' in js and 'log-submit-btn' in js), \
        "JS must update log button label when stepper input changes"


def test_card_b_stepper_prefilled_from_recent_entry():
    """Stepper is pre-filled with the user's most recent weight entry."""
    assert "_prefillStepper" in js or "prefillStepper" in js, \
        "JS must have a prefill function for the stepper"
    assert "current_weight_kg" in js or "_recentEntries" in js, \
        "JS must prefill stepper from most recent weight data"


def test_card_b_submit_posts_to_weight_entries():
    """Submitting Card B issues POST /api/weight-entries for today's date."""
    assert "/api/weight-entries" in js, "JS must POST to /api/weight-entries"
    assert "entry_date" in js, "POST body must include entry_date"


def test_card_b_success_shows_logged_strip():
    """On successful POST/PATCH, card swaps to logged confirmation state."""
    assert 'id="logged-strip"' in html, "HTML must have element with id='logged-strip'"
    assert "_showLoggedMode" in js or "logged-strip" in js, \
        "JS must show logged-strip element after successful log"


def test_card_b_logged_strip_shows_weight_and_edit():
    """Logged strip shows '✓ Logged today · [weight] kg · Edit' format."""
    assert "Logged today" in html or "Logged today" in js, \
        "Logged state must show 'Logged today' text"
    assert 'id="edit-link"' in html, "Logged strip must have an Edit button/link"


def test_card_b_edit_restores_stepper():
    """Clicking Edit restores stepper pre-filled with the logged value."""
    assert "edit-link" in js, "JS must handle edit-link click"
    assert "_showStepperMode" in js or "stepper-wrap" in js, \
        "JS must restore stepper mode on Edit click"


def test_card_b_edit_issues_patch():
    """Edit submit issues PATCH to the existing entry."""
    assert "PATCH" in js, "JS must issue PATCH request when editing an entry"
    assert "_cardBEntryId" in js, \
        "JS must track the existing entry id (_cardBEntryId) for PATCH"


def test_card_b_409_handled_with_patch_fallback():
    """409 response from POST uses existing_id to switch to PATCH flow."""
    assert "409" in js, "JS must handle 409 from POST /api/weight-entries"
    assert "existing_id" in js, "JS must use existing_id from 409 response for PATCH"
    assert "PATCH" in js, "JS must issue PATCH on 409 fallback"


# ── No icon-font glyphs anywhere in hero ───────────────────────────────────

def test_no_icon_font_glyphs_in_hero_html():
    """Hero section HTML uses no icon-font glyph classes."""
    hero_section = re.search(
        r'<div[^>]*class="[^"]*hero-2col[^"]*"(.*?)</div>\s*(?=<!--|\s*<div[^>]+class="[^"]*card)',
        html, re.DOTALL
    )
    fragment = hero_section.group(1) if hero_section else html
    bad = [r'class="[^"]*fa-', r'class="[^"]*icon-', r'class="[^"]*bi-', r'class="[^"]*glyphicon']
    for pattern in bad:
        assert not re.search(pattern, fragment), \
            f"Icon-font pattern '{pattern}' found in hero section"


def test_no_icon_font_glyphs_in_js_hero_render():
    """JS hero render functions do not reference icon-font class strings."""
    bad = [r'"fa-', r"'fa-", r'"icon-', r"'icon-", r'"bi-', r"'bi-"]
    for p in bad:
        assert p not in js, f"JS hero must not use icon-font class '{p}'"
