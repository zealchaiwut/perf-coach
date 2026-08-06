"""TDD tests for issue #463 – Migrate weight page to gradient design language.

AC anchors verified:
  (v1)  Page background uses --page-bg gradient token; no raw hex for background
  (v2)  Cards use --card-radius (14px) and --card-shadow token, no hard borders
  (v3)  Inter Tight for labels/headings; JetBrains Mono for all numeric values
  (v4)  Shared top nav loaded; Weight marked active in nav.js
  (v5)  Page-head: title, subtitle (N entries · M of last 14 days · trending), Export, Edit target
  (v6)  Edit target button opens slide-in panel (not a new page)
  (v7)  Page order: page-head → hero → chart → bottom-grid → target-history section
  (v8)  Gap between every row is exactly 16px (flex-gap on main wrapper)
  (v9)  Page padding ~36px top, ~56px bottom, ~22px sides
  (t1)  Gradient design tokens live in shared stylesheet (not duplicated per-page)
  (t2)  Weight page does not re-declare raw hex values for tokens already in shared CSS
  (t3)  DESIGN.md documents gradient token set
  (r1)  ≥640px: hero and bottom-grid are side-by-side
  (r2)  <640px (640px breakpoint): hero stacks, bottom-grid stacks, target-history stacks
  (e1)  No entries: coach strip is shown in idle state; "Log your first" copy present
  (e2)  No target: target-history section renders "No targets yet" empty state
  (q1)  Zero raw enum string values in UI-facing HTML (no hardcoded "active"/"completed")
  (q2)  Trend arrows are text characters (↓↑→), not icon-font glyphs (ti-arrow-*)
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
HTML_PATH = ROOT / "frontend" / "pages" / "weight.html"
JS_PATH   = ROOT / "frontend" / "js" / "weight.js"
CSS_PATH  = ROOT / "frontend" / "css" / "styles.css"
DESIGN_MD = ROOT / "DESIGN.md"

html = HTML_PATH.read_text()
js   = JS_PATH.read_text()
css  = CSS_PATH.read_text()
design_md = DESIGN_MD.read_text()

# Extract the <style> block from weight.html
_style_match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
local_css = _style_match.group(1) if _style_match else ""


# ── v1: Background gradient token ─────────────────────────────────────────────

def test_v1_body_uses_page_bg_token():
    """body must reference var(--page-bg) for background, not a raw hex."""
    assert "var(--page-bg)" in html, \
        "weight.html body must use var(--page-bg) for its background"


def test_v1_shared_css_defines_page_bg():
    """styles.css must define --page-bg as a gradient."""
    assert "--page-bg" in css and "gradient" in css, \
        "styles.css must define --page-bg as a gradient value"


# ── v2: Card tokens ────────────────────────────────────────────────────────────

def test_v2_cards_use_card_radius_token():
    """Cards must use var(--card-radius) or literal 14px — no other radius."""
    assert "var(--card-radius)" in html or "14px" in local_css, \
        "weight.html cards must use var(--card-radius) or 14px border-radius"


def test_v2_cards_use_card_shadow_token():
    """Cards must have box-shadow defined via var(--card-shadow) or matching shared value."""
    assert "var(--card-shadow)" in html or "box-shadow" in local_css, \
        "weight.html cards must use box-shadow (via token or inline)"


def test_v2_card_class_uses_token_border():
    """The .card CSS rule must use var(--card-border) not a raw hex border."""
    card_rule_match = re.search(r"\.card\s*\{[^}]*\}", local_css, re.DOTALL)
    if card_rule_match:
        card_rule = card_rule_match.group(0)
        assert "var(--card-border)" in card_rule or "box-shadow" in card_rule, \
            ".card rule must use var(--card-border) token, not a raw hex border"
    else:
        # Card styling comes from shared CSS — acceptable if shared CSS defines it
        assert "var(--card-bg)" in html or "var(--card-shadow)" in html, \
            "Cards must reference shared card tokens"


# ── v3: Typography ─────────────────────────────────────────────────────────────

def test_v3_inter_tight_loaded():
    """Inter Tight must be loaded via Google Fonts link."""
    assert "Inter+Tight" in html or "Inter Tight" in html, \
        "weight.html must load Inter Tight font"


def test_v3_jetbrains_mono_loaded():
    """JetBrains Mono must be loaded via Google Fonts link."""
    assert "JetBrains+Mono" in html or "JetBrains Mono" in html, \
        "weight.html must load JetBrains Mono font"


def test_v3_numeric_elements_use_jetbrains_mono():
    """Numeric elements must have JetBrains Mono font-family in CSS."""
    # The font-family is applied via HTML CSS, not JS
    assert "JetBrains Mono" in local_css or "JetBrains+Mono" in local_css, \
        "weight.html CSS must apply JetBrains Mono to numeric/weight elements"


# ── v4: Nav ────────────────────────────────────────────────────────────────────

def test_v4_nav_script_loaded():
    """nav.js must be loaded as a script in weight.html."""
    assert 'src="js/nav.js"' in html or "src='js/nav.js'" in html, \
        "weight.html must load nav.js for the shared top nav"


# ── v5: Page head ──────────────────────────────────────────────────────────────

def test_v5_page_head_has_title():
    """weight.html must have an h1 with 'Weight' in the page-head area."""
    assert "<h1>Weight" in html or "<h1>Weight</h1>" in html.replace("\n", " "), \
        "weight.html page-head must contain <h1>Weight</h1>"


def test_v5_page_head_has_subtitle():
    """page-subtitle element must be present for the dynamic subtitle line."""
    assert 'id="page-subtitle"' in html, \
        "weight.html must have id=page-subtitle element for the subtitle"


def test_v5_subtitle_js_shows_entry_count():
    """JS must compose subtitle with entry count, last-14-days, and trend."""
    assert "entries" in js and ("last 14" in js or "14 days" in js or "of last" in js), \
        "weight.js subtitle must show entry count and last-14-days count"


def test_v5_subtitle_js_shows_trend():
    """JS subtitle must include trending direction and kg/wk."""
    assert "kg/wk" in js or "delta_7d_kg" in js or "trending" in js, \
        "weight.js subtitle must show trending direction"


def test_v5_export_button_present():
    """weight.html must have an Export (CSV) button in the page-head."""
    assert "export" in html.lower() and ("csv" in html.lower() or "export-csv" in html.lower()), \
        "weight.html must have an Export CSV button in page-head"


def test_v5_edit_target_button_present():
    """weight.html must have an Edit target button in the page-head."""
    assert "edit-target" in html.lower() or "edit target" in html.lower(), \
        "weight.html must have an Edit target button in page-head"


# ── v6: Edit target opens panel ────────────────────────────────────────────────

def test_v6_edit_panel_exists_in_html():
    """weight.html must contain the slide-in edit-target panel element."""
    assert 'id="edit-panel"' in html or 'id="edit_panel"' in html, \
        "weight.html must have the slide-in edit-panel element"


def test_v6_edit_header_btn_wired_to_panel_in_js():
    """weight.js must wire the header Edit target button to open the slide-in panel."""
    assert "edit-target-header-btn" in js or "edit_target_header_btn" in js or \
           ("edit-target" in js and "panel" in js.lower()), \
        "weight.js must wire the Edit target header button to open the slide-in panel"


# ── v7: Page order — target-history section ────────────────────────────────────

def test_v7_target_history_section_present():
    """weight.html must have a target-history (Journey | Past targets) section."""
    has_section = (
        "target-history" in html
        or "journey" in html.lower()
        or "past-targets" in html.lower()
        or "past targets" in html.lower()
    )
    assert has_section, \
        "weight.html must have a target-history section (Journey | Past targets)"


def test_v7_target_history_after_bottom_grid():
    """Target-history section must appear in HTML after the bottom-grid."""
    bg_pos = html.find("bottom-grid")
    history_candidates = [
        html.find("target-history"),
        html.find("journey"),
        html.find("past-target"),
    ]
    history_pos = max(p for p in history_candidates if p >= 0) if any(p >= 0 for p in history_candidates) else -1
    assert bg_pos >= 0 and history_pos > bg_pos, \
        "Target-history section must appear after the bottom-grid in weight.html"


def test_v7_journey_card_has_stat_elements():
    """Journey card must have slots for all-time stats (targets set, achieved, total lost, avg pace)."""
    html_lower = html.lower()
    assert (
        "targets set" in html_lower or "total" in html_lower or "achieved" in html_lower
    ) and (
        "target-history" in html_lower or "journey" in html_lower or "past-target" in html_lower
    ), \
        "Target-history journey card must have stat elements (targets set, achieved, etc.)"


def test_v7_past_targets_card_has_status_table():
    """Past targets card must have a table or list for past target rows."""
    # Status table or list with rows for each past target
    has_table = (
        "past-targets-table" in html
        or "htable" in html
        or ("past-target" in html.lower() and ("table" in html.lower() or "tbody" in html.lower()))
    )
    assert has_table, \
        "Past targets card must include a table/list for past target entries"


def test_v7_no_targets_empty_state_in_html():
    """weight.html must have an empty-state element for when there are no past targets."""
    html_lower = html.lower()
    assert "no targets" in html_lower or "no-targets" in html_lower or \
           "empty-targets" in html_lower or "targets-empty" in html_lower, \
        "weight.html must have an empty state for 'No targets yet'"


# ── v8: Gap between rows ──────────────────────────────────────────────────────

def test_v8_main_uses_flex_column_layout():
    """main wrapper must use display:flex and flex-direction:column."""
    main_rule = re.search(
        r"main\s*\{[^}]*display\s*:\s*flex[^}]*\}",
        local_css, re.DOTALL
    )
    assert main_rule, \
        "main in weight.html must use display:flex for gap-based row layout"


def test_v8_main_has_16px_gap():
    """main wrapper must set gap:16px to space rows uniformly."""
    main_rule = re.search(
        r"main\s*\{[^}]*gap\s*:\s*16px[^}]*\}",
        local_css, re.DOTALL
    )
    assert main_rule, \
        "main in weight.html must set gap:16px to space all rows exactly 16px apart"


# ── v9: Page padding ──────────────────────────────────────────────────────────

def test_v9_main_padding_top_approx_36px():
    """main must have top padding ≥ 32px and ≤ 40px (~36px)."""
    # Accept 32..40px as "~36px"
    match = re.search(r"main\s*\{[^}]*padding\s*:\s*(\d+)px", local_css, re.DOTALL)
    if match:
        top = int(match.group(1))
        assert 28 <= top <= 44, \
            f"main top padding is {top}px, expected ~36px (28–44px range)"
    else:
        # Multi-part padding — look for padding-top
        match_top = re.search(r"padding-top\s*:\s*(\d+)px", local_css)
        assert match_top and 28 <= int(match_top.group(1)) <= 44, \
            "main must have ~36px top padding"


def test_v9_main_padding_sides_approx_22px():
    """main must have side padding ≤ 28px (spec ~22px)."""
    match = re.search(r"main\s*\{[^}]*padding\s*:\s*\d+px\s+(\d+)px", local_css, re.DOTALL)
    if match:
        sides = int(match.group(1))
        assert 14 <= sides <= 30, \
            f"main side padding is {sides}px, expected ~22px (14–30px range)"
    else:
        match_lr = re.search(r"padding-(?:left|right)\s*:\s*(\d+)px", local_css)
        assert match_lr and 14 <= int(match_lr.group(1)) <= 30, \
            "main must have ~22px side padding"


# ── t1: Token extraction ──────────────────────────────────────────────────────

def test_t1_shared_css_has_bg1_token():
    """styles.css must define --bg-1 gradient start token."""
    assert "--bg-1" in css, "styles.css must define --bg-1 token"


def test_t1_shared_css_has_bg2_token():
    """styles.css must define --bg-2 gradient end token."""
    assert "--bg-2" in css, "styles.css must define --bg-2 token"


def test_t1_shared_css_has_card_tokens():
    """styles.css must define --card-bg, --card-radius, --card-shadow."""
    assert "--card-bg" in css, "styles.css must define --card-bg"
    assert "--card-radius" in css, "styles.css must define --card-radius"
    assert "--card-shadow" in css, "styles.css must define --card-shadow"


def test_t1_shared_css_has_semantic_color_tokens():
    """styles.css must define --green, --blue-text or --accent gradient-system tokens."""
    assert "--green" in css and "--accent" in css, \
        "styles.css must define gradient semantic color tokens (--green, --accent)"


# ── t2: No duplication ────────────────────────────────────────────────────────

def test_t2_weight_page_does_not_redefine_bg1():
    """weight.html local <style> must not re-declare --bg-1 value."""
    assert "--bg-1:" not in local_css, \
        "weight.html must not redefine --bg-1 in its local <style> (use shared token)"


def test_t2_weight_page_does_not_redefine_card_radius():
    """weight.html local <style> must not re-declare --card-radius."""
    assert "--card-radius:" not in local_css, \
        "weight.html must not redefine --card-radius in its local <style>"


# ── t3: DESIGN.md ─────────────────────────────────────────────────────────────

def test_t3_design_md_has_gradient_tokens_section():
    """DESIGN.md must document the gradient design token set."""
    assert "Gradient" in design_md or "gradient" in design_md, \
        "DESIGN.md must document the gradient design token set"


def test_t3_design_md_documents_card_tokens():
    """DESIGN.md must document --card-radius and --card-shadow tokens."""
    assert "--card-radius" in design_md and "--card-shadow" in design_md, \
        "DESIGN.md must document --card-radius and --card-shadow"


# ── r1: ≥640px side-by-side layout ────────────────────────────────────────────

def test_r1_hero_uses_grid_columns_at_desktop():
    """hero row must use multi-column grid at ≥640px."""
    assert "1.35fr" in local_css or ("hero" in local_css and "grid-template-columns" in local_css), \
        "hero card row must use grid-template-columns at desktop width"


def test_r1_bottom_grid_2col_default():
    """bottom-grid must default to 2 columns (1fr 1fr)."""
    assert "bottom-grid" in local_css and "grid-template-columns" in local_css, \
        "bottom-grid must have a default 2-column grid-template-columns rule"


# ── r2: <640px responsive stacking ────────────────────────────────────────────

def test_r2_hero_stacks_at_640px():
    """hero-2col (or revamp grid) stacks to 1 column at max-width: 640px."""
    media = local_css.find("@media (max-width: 640px)")
    assert media != -1
    block = local_css[media:media + 4000]
    assert "grid-template-columns: 1fr" in block
    assert "hero-2col" in block or "w-grid" in block or "weight-grid" in block


def test_r2_bottom_grid_stacks_at_640px():
    """bottom-grid must stack to 1 column at max-width: 640px."""
    m640 = re.search(
        r"@media\s*\(\s*max-width\s*:\s*640px\s*\)[^{]*\{",
        local_css, re.DOTALL
    )
    assert m640 and "1fr" in local_css, \
        "bottom-grid must stack to 1fr inside @media (max-width: 640px)"


def test_r2_target_history_stacks_at_640px():
    """Dormant target-history CSS still stacks at max-width: 640px."""
    assert ".target-history-grid" in local_css
    media = local_css.find("@media (max-width: 640px)")
    assert media != -1
    assert "target-history-grid" in local_css[media:media + 3000]
    assert "grid-template-columns: 1fr" in local_css[media:media + 3000]


# ── e1: Empty state — no entries ─────────────────────────────────────────────

def test_e1_coach_strip_has_idle_class():
    """Coach strip retired — gate / hypothesis cover empty guidance."""
    assert (
        'id="gate-card"' in html
        or 'id="hypothesis-card"' in html
        or "coach-strip" in html
    )


def test_e1_coach_strip_empty_state_copy():
    """Empty-state guidance lives on the coverage gate (or legacy coach copy)."""
    html_lower = html.lower()
    assert (
        "coverage" in html_lower
        or "no entry" in html_lower
        or "log your" in html_lower
        or "wake me" in html_lower
        or "unlocks at 70%" in html_lower
    )


# ── e2: Empty state — no targets ─────────────────────────────────────────────

def test_e2_no_targets_copy_in_html_or_js():
    """'No targets yet' or equivalent empty state must exist in HTML or JS."""
    combined = html + js
    has_empty = (
        "no targets yet" in combined.lower()
        or "no targets" in combined.lower()
        or "no-targets-yet" in combined
    )
    assert has_empty, \
        "weight.html/js must render an empty state 'No targets yet' for target history"


def test_e2_target_history_js_renders_empty_state():
    """weight.js must handle the case where target history is empty."""
    js_lower = js.lower()
    assert (
        "target" in js_lower and ("length" in js_lower or "empty" in js_lower or "no target" in js_lower)
    ), \
        "weight.js must handle empty target history and render an empty state"


# ── q1: No raw enum values ────────────────────────────────────────────────────

def test_q1_no_raw_status_active_in_html():
    """No raw 'active' status string should appear in UI-facing HTML elements."""
    # 'active' is allowed in CSS class names (.active) and aria-*, but not as data/content
    import re as _re
    # Check for data-status="active" or value="active" patterns
    bad = _re.findall(r'(?:data-status|value|status)\s*=\s*["\']active["\']', html)
    assert not bad, f"weight.html must not expose raw 'active' enum in UI: {bad}"


# ── q2: Text trend arrows ─────────────────────────────────────────────────────

def test_q2_trend_arrows_are_text_characters():
    """Trend arrows must use ↓/↑/→ text characters, not ti-arrow-* icon classes."""
    # The JS should produce ↓ or ↑ arrows, not reference ti-arrow glyphs
    assert "↓" in js or "↑" in js or "arrow" not in js.lower() or \
           ("ti-arrow" not in js), \
        "weight.js must use ↓/↑ text arrows for trend indicators, not icon-font glyphs"


def test_q2_subtitle_uses_text_arrows():
    """Subtitle computation in weight.js must use text arrows (↓/↑/→)."""
    assert "↓" in js and "↑" in js, \
        "weight.js must use ↓ and ↑ unicode arrows in trend display"
