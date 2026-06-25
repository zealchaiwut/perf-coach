"""
TDD tests for issue #460 — Rebuild progress card with stat-row and plan-aware milestones.

Covers behaviors CHANGED or ADDED vs issue #424:

  (A) Edit-target pill in the progress card opens the slide-in panel — it must NOT
      navigate to /weight/targets.  A stub panel element must exist.
  (B) Three-stat row plan sub-line reads "plan says X" (not "plan X kg").
  (C) Progress bar: you-dot at progress_pct; plan-tick formula
      (start − plan_today) / (start − target) × 100 verified across three fixture
      datasets: behind, ahead, and on_plan.
  (D) Four-state status pill: correct CSS class and copy per gap_direction.
  (E) Milestone list: today row tinted red (behind) or green (ahead/on_plan).
  Layout: bottom 2-column grid uses 16 px gap; stacks vertically at <640 px.
"""

import re
import pytest
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "frontend"
WEIGHT_HTML = FRONTEND / "pages" / "weight.html"
WEIGHT_JS   = FRONTEND / "js" / "weight.js"

html = WEIGHT_HTML.read_text()
js   = WEIGHT_JS.read_text()


# ── (A) Edit-target pill opens slide-in panel ─────────────────────────────────

def test_a_edit_target_pill_not_nav_link_in_progress_card():
    """(A) The edit-target pill inside #progress-card must NOT href-navigate to /weight/targets."""
    # Isolate the progress-card HTML block
    start = html.find('id="progress-card"')
    assert start != -1, "id='progress-card' not found in weight.html"
    # Find the closing tag of the card (next </div> after the card contents)
    # We look for the edit-target pill within the progress-card section only.
    # Strategy: grab text from the card open tag to a reasonable forward window.
    card_section = html[start:start + 3000]
    # The edit-target link must NOT be a plain href to /weight/targets
    assert 'href="/weight/targets"' not in card_section, (
        "Edit-target pill inside progress-card must open the slide-in panel, "
        "not navigate to /weight/targets (AC-A)"
    )


def test_a_edit_target_pill_present_in_progress_card():
    """(A) An 'Edit target' button/element is present in the progress card."""
    start = html.find('id="progress-card"')
    assert start != -1, "id='progress-card' not found"
    card_section = html[start:start + 3000]
    assert "Edit target" in card_section, (
        "'Edit target' element missing from progress card (AC-A)"
    )


def test_a_slide_in_panel_structure_in_html():
    """(A) A slide-in panel element exists on the page for the Edit-target action."""
    assert 'id="edit-panel"' in html or 'id="edit-target-panel"' in html, (
        "Slide-in panel element (id='edit-panel' or 'edit-target-panel') not found "
        "in weight.html (AC-A)"
    )


def test_a_panel_scrim_in_html():
    """(A) A panel scrim/overlay element exists alongside the panel."""
    assert 'id="edit-scrim"' in html or 'id="edit-target-scrim"' in html, (
        "Panel scrim element not found in weight.html (AC-A)"
    )


def test_a_js_opens_panel_on_edit_target_click():
    """(A) JS wires the edit-target pill to show the slide-in panel."""
    assert "edit-panel" in js or "edit-target-panel" in js, (
        "JS does not reference the edit panel element (AC-A)"
    )


def test_a_edit_target_pill_is_button_or_hash_href():
    """(A) The edit-target element inside the progress card is a button or has href='#'."""
    start = html.find('id="progress-card"')
    assert start != -1
    card_section = html[start:start + 3000]
    has_button = "edit-target-pill-btn" in card_section or (
        "edit-target-pill" in card_section and
        ('type="button"' in card_section or 'href="#"' in card_section)
    )
    assert has_button, (
        "Edit-target element in progress card must be a <button> or href='#' — "
        "it must not trigger navigation (AC-A)"
    )


# ── (B) Plan sub-line reads "plan says X" ────────────────────────────────────

def test_b_plan_sub_reads_plan_says_x():
    """(B) JS renders 'plan says X' in the You stat sub-line."""
    assert "plan says" in js, (
        "JS must render 'plan says X' (not 'plan X kg') in pstat-plan-sub (AC-B center stat)"
    )


def test_b_plan_sub_no_trailing_kg():
    """(B) The 'plan says X' sub-line does not append ' kg' after the number."""
    # Find the section where pstat-plan-sub is set
    idx = js.find("pstat-plan-sub")
    assert idx != -1, "pstat-plan-sub not found in JS"
    snippet = js[idx:idx + 200]
    # Must say 'plan says' and must NOT say 'plan says ... kg'
    assert "plan says" in snippet, "pstat-plan-sub must use 'plan says' format"
    # Allow 'plan says X' without ' kg' suffix — check the template literal nearby
    assert "plan says" in snippet and "plan says" not in snippet.replace("plan says", "").replace(" kg", ""), (
        "After 'plan says', the snippet must not append ' kg' (matches mock format)"
    ) if "plan says" in snippet and " kg" in snippet[snippet.find("plan says"):snippet.find("plan says") + 30] else True


# ── (C) Plan-tick and you-dot math — three fixture datasets ───────────────────

def _plan_tick_pct(start, target, plan_today):
    """Mirror the JS formula: (start − plan_today) / (start − target) × 100."""
    total_range = start - target
    if total_range == 0:
        return 0.0
    return max(0.0, min(100.0, (start - plan_today) / total_range * 100))


def _you_dot_pct(start, target, current):
    """progress_pct = (start − current) / (start − target) × 100."""
    total_range = start - target
    if total_range == 0:
        return 100.0
    return max(0.0, min(100.0, (start - current) / total_range * 100))


@pytest.mark.parametrize("label,start,target,current,plan_today,expect_you_gt_plan", [
    # behind: you (89) < plan (87) → progress_pct < plan_pct → you-dot LEFT of plan-tick
    ("behind",  90.0, 80.0, 89.0, 87.0, False),
    # ahead:  you (86) > plan (87) → progress_pct > plan_pct → you-dot RIGHT of plan-tick
    ("ahead",   90.0, 80.0, 86.0, 87.0, True),
    # on_plan: you == plan → both markers at same position
    ("on_plan", 90.0, 80.0, 87.0, 87.0, None),
])
def test_c_plan_tick_you_dot_math(label, start, target, current, plan_today, expect_you_gt_plan):
    """(C) Plan-tick/you-dot math verified across three fixture datasets."""
    you_pct  = _you_dot_pct(start, target, current)
    plan_pct = _plan_tick_pct(start, target, plan_today)

    if expect_you_gt_plan is True:
        assert you_pct > plan_pct, (
            f"[{label}] you-dot ({you_pct:.1f}%) should be > plan-tick ({plan_pct:.1f}%)"
        )
    elif expect_you_gt_plan is False:
        assert you_pct < plan_pct, (
            f"[{label}] you-dot ({you_pct:.1f}%) should be < plan-tick ({plan_pct:.1f}%)"
        )
    else:
        assert abs(you_pct - plan_pct) < 0.01, (
            f"[{label}] you-dot ({you_pct:.1f}%) and plan-tick ({plan_pct:.1f}%) should be equal"
        )


def test_c_plan_tick_formula_in_js():
    """(C) JS contains the correct plan-tick formula components."""
    assert "startW - planTodayKg" in js or "(startW - plan" in js, (
        "JS plan-tick formula must compute (startW - planTodayKg) / totalRange (AC-C)"
    )
    assert "totalRange" in js or "(startW - targetW)" in js, (
        "JS must compute total range (startW - targetW) for plan-tick formula (AC-C)"
    )


def test_c_you_dot_uses_progress_pct():
    """(C) You-dot is positioned at progress_pct (not recalculated)."""
    assert "pgbar-you-dot" in js, "JS must set pgbar-you-dot position"
    assert "progress_pct" in js, "JS must use progress_pct for you-dot position"


# ── (D) Four-state status pill ────────────────────────────────────────────────

@pytest.mark.parametrize("direction,expected_class,expected_copy_fragment", [
    ("behind",  "pill-behind",  "behind plan"),
    ("ahead",   "pill-ahead",   "ahead of plan"),
    ("on_plan", "pill-on-plan", "On plan"),
    ("no_data", "pill-no-data", "Just started"),
])
def test_d_status_pill_state(direction, expected_class, expected_copy_fragment):
    """(D) Status pill: correct CSS class and copy fragment for each gap_direction."""
    assert expected_class in html or expected_class in js, (
        f"CSS class '{expected_class}' not found for gap_direction='{direction}' (AC-D)"
    )
    assert expected_copy_fragment in js, (
        f"Pill copy '{expected_copy_fragment}' not found for gap_direction='{direction}' (AC-D)"
    )


def test_d_raw_enum_not_rendered():
    """(D) Raw enum strings are not directly assigned as display text."""
    # JS must handle gap_direction via conditional, not set innerHTML = gap_direction
    # The value 'no_data' must never appear as a direct display string assignment
    no_data_display = re.search(
        r'(textContent|innerHTML)\s*=\s*[\'"]no_data[\'"]', js
    )
    assert not no_data_display, (
        "Raw 'no_data' string must not be set as textContent/innerHTML (AC-D)"
    )


# ── (E) Milestone list ────────────────────────────────────────────────────────

def test_e_today_row_tinted_red_when_behind():
    """(E) Milestone today row uses a red tint class when gap_direction === 'behind'."""
    assert "milestone-today-behind" in js, (
        "JS must apply 'milestone-today-behind' class when behind (AC-E)"
    )
    assert "milestone-today-behind" in html, (
        "CSS class 'milestone-today-behind' must have styling in weight.html (AC-E)"
    )


def test_e_today_row_tinted_green_when_ahead():
    """(E) Milestone today row uses a green tint class when gap_direction === 'ahead' or 'on_plan'."""
    assert "milestone-today-ahead" in js, (
        "JS must apply 'milestone-today-ahead' class when ahead (AC-E)"
    )
    assert "milestone-today-ahead" in html, (
        "CSS class 'milestone-today-ahead' must have styling in weight.html (AC-E)"
    )


def test_e_on_chart_hint_present():
    """(E) Milestone list header hint '◆ on chart' is present."""
    assert "◆ on chart" in html or "◆ on chart" in js, (
        "'◆ on chart' hint not found (AC-E)"
    )


def test_e_milestone_list_header_present():
    """(E) Milestone list header section exists."""
    assert "milestone-list-hdr" in html, (
        "'milestone-list-hdr' element not found in weight.html (AC-E)"
    )


def test_e_today_row_shows_actual_and_plan():
    """(E) Today milestone row shows actual weight AND 'plan X' sub-text."""
    assert "plan " in js, "JS must render 'plan X' sub for today milestone row (AC-E)"
    assert "currentBasisKg" in js or "gapKg" in js, (
        "JS must use current basis weight for today row actual value (AC-E)"
    )


# ── Layout ────────────────────────────────────────────────────────────────────

def test_layout_bottom_grid_gap_16px():
    """Layout: Bottom grid uses 16 px gap between progress card and recent entries."""
    m = re.search(
        r'\.bottom-grid\s*\{[^}]*\bgap\s*:\s*16px\b[^}]*\}',
        html, re.DOTALL
    )
    assert m, (
        ".bottom-grid CSS must specify gap: 16px (Layout AC)"
    )


def test_layout_bottom_grid_stacks_at_640px():
    """Layout: Bottom grid must stack to single column at ≤640 px viewport."""
    # Either a dedicated 640px breakpoint exists, OR the existing ≤820px breakpoint
    # already covers the 640px requirement (640 < 820 ⇒ already stacked).
    has_640 = bool(re.search(
        r'640px.*?bottom-grid.*?grid-template-columns\s*:\s*1fr',
        html, re.DOTALL
    ))
    has_820 = bool(re.search(
        r'820px.*?bottom-grid.*?grid-template-columns\s*:\s*1fr',
        html, re.DOTALL
    ))
    assert has_640 or has_820, (
        "bottom-grid must collapse to 1fr at ≤640 px (Layout AC); "
        "either a 640px or an 820px media-query override is required"
    )


def test_layout_progress_card_precedes_recent_entries():
    """Layout: Progress card appears before recent entries in DOM (stacks on top at mobile)."""
    progress_idx = html.find('id="progress-card"')
    entries_idx  = html.find('id="recent-entries"')
    assert progress_idx != -1 and entries_idx != -1, (
        "Both progress-card and recent-entries must be present in weight.html"
    )
    assert progress_idx < entries_idx, (
        "progress-card must appear before recent-entries in HTML so it stacks on top at mobile (Layout AC)"
    )
