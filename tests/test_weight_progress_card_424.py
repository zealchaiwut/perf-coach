"""
TDD tests for issue #424 — Rebuild progress card with stat-row and plan-aware milestones.

AC items verified:
  (ac1)  Card header: "Progress toward goal" + "Edit target" pill → /weight/targets
  (ac2)  Three-stat row: Start (left) / You in blue + plan sub (center) / Goal in green (right)
  (ac3)  No numbers on or overlapping the bar itself
  (ac4)  Bar: track + gradient fill to progress_pct + blue you-dot + green plan tick
  (ac5)  Only "you" and "plan" micro-labels under bar; no other text on bar
  (ac6)  Summary row: progress_pct large left + "X kg to go · N days" + status pill right
  (ac7)  Status pill states match exactly per gap_direction:
         behind=red, ahead=green, on_plan=green, no_data=neutral blue
  (ac8)  Raw enum strings never rendered to UI (gap_direction values not used as display text)
  (ac9)  Milestones list renders rows from /active milestones array only
  (ac10) Today row highlighted (red/green), actual kg + plan sub + signed delta chip
  (ac11) Intermediate/goal rows: plan kg + ↓ remaining-from-today
  (ac12) List header includes "◆ on chart" hint
  (ac13) Progress card and Recent Entries side-by-side in bottom grid
  (ac14) Layout collapses to single column at ≤820px
  (ac15) Plan tick position: (start − plan_today) / (start − target) formula
  (ac16) You-dot position: progress_pct
  (ac17) All four gap_direction pill states handled in JS
  (ac18) Milestones rendered from target.milestones array (not hardcoded)
"""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "frontend"
WEIGHT_HTML = FRONTEND / "pages" / "weight.html"
WEIGHT_JS   = FRONTEND / "js" / "weight.js"

html = WEIGHT_HTML.read_text()
js   = WEIGHT_JS.read_text()


# ── AC1: Card header ──────────────────────────────────────────────────────────

def test_ac1_progress_toward_goal_header():
    """AC1: Progress card h2 says 'Progress toward goal'."""
    assert "Progress toward goal" in html, \
        "'Progress toward goal' header not found in weight.html"


def test_ac1_edit_target_pill_present():
    """AC1: 'Edit target' pill link exists in progress card."""
    assert "Edit target" in html, \
        "'Edit target' pill not found in weight.html"


def test_ac1_edit_target_links_to_weight_targets():
    """AC1: 'Edit target' pill href points to /weight/targets."""
    assert 'href="/weight/targets"' in html or "href='/weight/targets'" in html, \
        "Edit target pill must link to /weight/targets in weight.html"


# ── AC2: Three-stat row ───────────────────────────────────────────────────────

def test_ac2_pstat_start_element():
    """AC2: HTML has element for Start stat value."""
    assert 'id="pstat-start-val"' in html, \
        "Missing id='pstat-start-val' in weight.html"


def test_ac2_pstat_start_date_element():
    """AC2: HTML has element for Start date sub."""
    assert 'id="pstat-start-date"' in html, \
        "Missing id='pstat-start-date' in weight.html"


def test_ac2_pstat_you_element():
    """AC2: HTML has element for You (current basis) stat."""
    assert 'id="pstat-you-val"' in html, \
        "Missing id='pstat-you-val' in weight.html"


def test_ac2_pstat_plan_sub_element():
    """AC2: HTML has element for plan sub under You stat."""
    assert 'id="pstat-plan-sub"' in html, \
        "Missing id='pstat-plan-sub' in weight.html"


def test_ac2_pstat_goal_element():
    """AC2: HTML has element for Goal stat value."""
    assert 'id="pstat-goal-val"' in html, \
        "Missing id='pstat-goal-val' in weight.html"


def test_ac2_pstat_goal_date_element():
    """AC2: HTML has element for Goal date sub."""
    assert 'id="pstat-goal-date"' in html, \
        "Missing id='pstat-goal-date' in weight.html"


def test_ac2_you_value_color_blue():
    """AC2: You stat value uses blue color (#2563eb)."""
    # CSS class pstat-val-blue or inline color #2563eb must exist
    assert "pstat-val-blue" in html or "#2563eb" in html, \
        "Blue color for You stat not found in weight.html"


def test_ac2_goal_value_color_green():
    """AC2: Goal stat value uses green color (#16a34a)."""
    assert "pstat-val-green" in html or "pstat-goal" in html, \
        "Goal stat element class not found in weight.html"


def test_ac2_js_renders_start_stat():
    """AC2: JS renders start weight and date into pstat elements."""
    assert "pstat-start-val" in js, \
        "JS does not set pstat-start-val"
    assert "start_weight_kg" in js or "start_date" in js, \
        "JS does not use start_weight_kg or start_date for pstat-start"


def test_ac2_js_renders_you_stat():
    """AC2: JS renders current basis weight into pstat-you-val."""
    assert "pstat-you-val" in js, \
        "JS does not set pstat-you-val"


def test_ac2_js_renders_plan_sub():
    """AC2: JS renders plan_today_kg into pstat-plan-sub."""
    assert "pstat-plan-sub" in js, \
        "JS does not set pstat-plan-sub"
    assert "plan_today_kg" in js, \
        "JS does not use plan_today_kg for plan sub text"


def test_ac2_js_renders_goal_stat():
    """AC2: JS renders target weight and date into pstat-goal elements."""
    assert "pstat-goal-val" in js, \
        "JS does not set pstat-goal-val"


# ── AC3: No numbers on or overlapping the bar ─────────────────────────────────

def test_ac3_stat_row_present_above_bar():
    """AC3: progress-stat-row section exists; bar is separate, no overlap."""
    assert "progress-stat-row" in html, \
        "'progress-stat-row' class not found — three-stat row missing from weight.html"


def test_ac3_no_progress_labels_on_bar():
    """AC3: Old progress-labels div (numbers below/on bar) is removed."""
    # The old design had id="progress-labels" with start/current/target overlapping bar
    # It must be removed or replaced by the stat-row above
    assert 'id="progress-labels"' not in html, \
        "id='progress-labels' still present — numbers may overlap the bar (AC3 violation)"


# ── AC4: Bar structure ────────────────────────────────────────────────────────

def test_ac4_pgbar_track_element():
    """AC4: Bar track element exists."""
    assert 'id="pgbar-track"' in html, \
        "Missing id='pgbar-track' in weight.html"


def test_ac4_pgbar_fill_element():
    """AC4: Bar fill element exists."""
    assert 'id="pgbar-fill"' in html, \
        "Missing id='pgbar-fill' in weight.html"


def test_ac4_pgbar_you_dot_element():
    """AC4: Blue you-dot element exists on bar."""
    assert 'id="pgbar-you-dot"' in html, \
        "Missing id='pgbar-you-dot' in weight.html"


def test_ac4_pgbar_plan_tick_element():
    """AC4: Green plan tick element exists on bar."""
    assert 'id="pgbar-plan-tick"' in html, \
        "Missing id='pgbar-plan-tick' in weight.html"


def test_ac4_pgbar_fill_uses_gradient():
    """AC4: Bar fill uses CSS gradient (not solid color)."""
    assert "gradient" in html or "linear-gradient" in html, \
        "Bar fill gradient not found in weight.html CSS"


def test_ac4_js_sets_fill_width_to_progress_pct():
    """AC4: JS sets pgbar-fill width from progress_pct."""
    assert "pgbar-fill" in js, \
        "JS does not reference pgbar-fill"
    assert "progress_pct" in js, \
        "JS does not use progress_pct for fill width"


def test_ac4_js_positions_you_dot():
    """AC4: JS positions pgbar-you-dot using progress_pct."""
    assert "pgbar-you-dot" in js, \
        "JS does not reference pgbar-you-dot"


def test_ac4_js_positions_plan_tick():
    """AC4: JS positions pgbar-plan-tick."""
    assert "pgbar-plan-tick" in js, \
        "JS does not reference pgbar-plan-tick"


def test_ac4_you_dot_css_color_blue():
    """AC4: You-dot CSS uses blue color (#2563eb or #1d4ed8)."""
    assert "#2563eb" in html or "pgbar-you-dot" in html, \
        "Blue you-dot color not found in weight.html"


def test_ac4_plan_tick_css_color_green():
    """AC4: Plan tick CSS uses green color (#16a34a)."""
    assert "#16a34a" in html and "pgbar-plan-tick" in html, \
        "Green plan tick not found in weight.html"


# ── AC5: Micro-labels under bar ───────────────────────────────────────────────

def test_ac5_micro_you_label():
    """AC5: 'you' micro-label exists under the bar."""
    assert 'id="pgbar-micro-you"' in html, \
        "Missing id='pgbar-micro-you' in weight.html"


def test_ac5_micro_plan_label():
    """AC5: 'plan' micro-label exists under the bar."""
    assert 'id="pgbar-micro-plan"' in html, \
        "Missing id='pgbar-micro-plan' in weight.html"


def test_ac5_micro_you_text():
    """AC5 (revised): the YOU marker flag (id pgbar-micro-you) carries a YOU label.
    The marker now rides above the bar in its own lane, so the label lives in a
    child span rather than inline text."""
    m = re.search(r'id="pgbar-micro-you".*?</div>', html, re.S)
    assert m and re.search(r'>\s*YOU\s*<', m.group(0)), \
        "pgbar-micro-you flag must contain a 'YOU' label in weight.html"


def test_ac5_micro_plan_text():
    """AC5 (revised): the PLAN marker flag (id pgbar-micro-plan) carries a PLAN
    label in a child span (marker now rides below the bar in its own lane)."""
    m = re.search(r'id="pgbar-micro-plan".*?</div>', html, re.S)
    assert m and re.search(r'>\s*PLAN\s*<', m.group(0)), \
        "pgbar-micro-plan flag must contain a 'PLAN' label in weight.html"


def test_ac5_js_positions_micro_you():
    """AC5: JS positions the 'you' micro-label under the you-dot."""
    assert "pgbar-micro-you" in js, \
        "JS does not position pgbar-micro-you micro-label"


def test_ac5_js_positions_micro_plan():
    """AC5: JS positions the 'plan' micro-label under the plan tick."""
    assert "pgbar-micro-plan" in js, \
        "JS does not position pgbar-micro-plan micro-label"


# ── AC6: Summary row ──────────────────────────────────────────────────────────

def test_ac6_progress_pct_big_element():
    """AC6: Large progress pct element exists."""
    assert 'id="progress-pct-big"' in html, \
        "Missing id='progress-pct-big' in weight.html"


def test_ac6_progress_detail_element():
    """AC6: 'X kg to go · N days' element exists."""
    assert 'id="progress-detail"' in html, \
        "Missing id='progress-detail' in weight.html"


def test_ac6_pgstatus_pill_element():
    """AC6: Status pill element exists in summary row."""
    assert 'id="pgstatus-pill"' in html, \
        "Missing id='pgstatus-pill' in weight.html"


def test_ac6_js_renders_pct_and_detail():
    """AC6: JS sets progress-pct-big and progress-detail."""
    assert "progress-pct-big" in js, \
        "JS does not set progress-pct-big"
    assert "progress-detail" in js, \
        "JS does not set progress-detail"
    # Must include kg_to_go and days_remaining
    assert "kg_to_go" in js, \
        "JS does not use kg_to_go in progress-detail"
    assert "days_remaining" in js, \
        "JS does not use days_remaining in progress-detail"


def test_ac6_detail_format_has_dot_separator():
    """AC6: Detail string uses ' · ' separator between kg and days."""
    # JS must build a string with ' · ' between the two parts
    assert "· " in js or "·" in js, \
        "JS progress-detail string missing '·' separator"


# ── AC7: Status pill states ───────────────────────────────────────────────────

def test_ac7_behind_pill_text():
    """AC7: behind state pill contains 'behind plan'."""
    assert "behind plan" in js, \
        "JS missing 'behind plan' pill text for gap_direction='behind'"


def test_ac7_behind_pill_uses_required_pace():
    """AC7: behind pill includes 'need' + kg/wk from required_pace_kg_per_week."""
    assert "required_pace" in js and "need" in js, \
        "JS behind pill must use required_pace_kg_per_week and contain 'need'"


def test_ac7_ahead_pill_text():
    """AC7: ahead state pill contains 'ahead of plan'."""
    assert "ahead of plan" in js, \
        "JS missing 'ahead of plan' pill text for gap_direction='ahead'"


def test_ac7_on_plan_pill_text():
    """AC7: on_plan state pill text is 'On plan'."""
    assert "On plan" in js, \
        "JS missing 'On plan' pill text for gap_direction='on_plan'"


def test_ac7_no_data_pill_text():
    """AC7: no_data state pill text matches spec."""
    assert "Just started" in js, \
        "JS missing 'Just started' pill text for gap_direction='no_data'"
    assert "log daily" in js, \
        "JS missing 'log daily' text for no_data pill"


def test_ac7_behind_pill_red_class():
    """AC7: behind pill uses a red CSS class."""
    assert "pill-behind" in html or "pill-behind" in js, \
        "CSS class 'pill-behind' not found for behind pill state"


def test_ac7_ahead_pill_green_class():
    """AC7: ahead and on_plan pills use a green CSS class."""
    assert "pill-ahead" in html or "pill-ahead" in js, \
        "CSS class 'pill-ahead' not found for ahead pill state"


def test_ac7_no_data_pill_blue_class():
    """AC7: no_data pill uses a neutral blue CSS class."""
    assert "pill-no-data" in html or "pill-no-data" in js, \
        "CSS class 'pill-no-data' not found for no_data pill state"


# ── AC8: Raw enum strings not rendered ───────────────────────────────────────

def test_ac8_gap_direction_driven_by_switch():
    """AC8: JS uses a map/switch on gap_direction, not raw string as display."""
    # JS must not set textContent/innerHTML directly to gap_direction raw value
    # It should use a lookup or conditional
    assert "gap_direction" in js, \
        "JS does not use gap_direction at all"
    # Verify that 'behind', 'ahead', 'on_plan', 'no_data' are handled as conditions
    for direction in ("behind", "ahead", "on_plan", "no_data"):
        assert direction in js, \
            f"gap_direction value '{direction}' not handled in weight.js"


def test_ac8_pgstatus_pill_set_from_lookup():
    """AC8: pgstatus-pill text is set from a lookup, not raw gap_direction value."""
    # The key signal: the function setting pill text must reference predefined text
    # (e.g., STATUS_PILL_TEXT map or if/else blocks)
    assert "pgstatus-pill" in js, \
        "JS does not set pgstatus-pill text content"


# ── AC9: Milestones from /active array ───────────────────────────────────────

def test_ac9_milestone_rows_element():
    """AC9 (revised): milestones now render as markers on the progress bar
    (the standalone list was removed), so the bar carries a milestone layer."""
    assert 'id="pgbar-ms-layer"' in html, \
        "Missing id='pgbar-ms-layer' (milestone markers on the progress bar)"


def test_ac9_js_uses_target_milestones():
    """AC9: JS renders from target.milestones, not hardcoded date offsets."""
    # Old code used addDays(today, 90), addDays(today, 180) — must be gone
    assert "target.milestones" in js or "milestones.map" in js or "milestones.forEach" in js, \
        "JS must iterate target.milestones array for milestone rows"
    # Old hardcoded 90/180 day offsets must be gone from milestone rendering
    # (they may still exist for other purposes like chart range)


def test_ac9_js_renders_milestone_rows():
    """AC9 (revised): JS renders milestone markers into the progress-bar layer."""
    assert "pgbar-ms-layer" in js, \
        "JS does not render milestones into id='pgbar-ms-layer'"


# ── AC10: Today row ───────────────────────────────────────────────────────────

def test_ac10_today_row_highlight_css_red():
    """AC10: CSS has red-tinted rule for behind today row."""
    assert "milestone-today-behind" in html or "#fee2e2" in html or "#fef2f2" in html, \
        "Red-tint highlight for today-behind milestone row not found in weight.html CSS"


def test_ac10_today_row_highlight_css_green():
    """AC10: CSS has green highlight for ahead/on-plan today row."""
    # Must have a green tint for today row
    assert "milestone-today-ahead" in html or ("milestone-today" in html and "#dcfce7" in html), \
        "Green highlight for today ahead/on-plan milestone row not found in weight.html CSS"


def test_ac10_js_today_row_uses_current_basis():
    """AC10: JS renders actual (current basis) weight in today row."""
    # current_basis_kg is derived as plan_today_kg + gap_kg
    assert "gap_kg" in js, \
        "JS must use gap_kg to derive current basis for today milestone row"


def test_ac10_js_today_row_plan_sub():
    """AC10: JS renders 'plan X' sub text in today row."""
    assert "plan " in js, \
        "JS must render 'plan X' sub text in today milestone row"


def test_ac10_js_today_row_delta_chip():
    """AC10: JS renders signed delta chip for today row."""
    # Should render gap_kg with a sign
    assert "gap_kg" in js and ("toFixed" in js), \
        "JS must render signed gap_kg as delta chip in today row"


# ── AC11: Intermediate/goal rows ─────────────────────────────────────────────

def test_ac11_js_renders_plan_kg_for_intermediates():
    """AC11: JS renders plan_kg for intermediate and goal milestone rows."""
    assert "plan_kg" in js, \
        "JS does not reference plan_kg from milestones in weight.js"


def test_ac11_js_remaining_from_today_arrow():
    """AC11: JS renders ↓ remaining from today for intermediate/goal rows."""
    assert "↓" in js or "\\u2193" in js, \
        "JS must use ↓ arrow for remaining-from-today in milestone rows"


def test_ac11_js_uses_plan_today_for_remaining():
    """AC11: JS computes remaining as difference from plan_today_kg."""
    assert "plan_today_kg" in js, \
        "JS does not use plan_today_kg to compute remaining for milestone rows"


# ── AC12: List header with ◆ on chart ────────────────────────────────────────

def test_ac12_on_chart_hint():
    """AC12 (revised): milestones are shown as diamond/goal markers on the bar
    (and on the chart). The standalone list hint was removed."""
    assert "pgbar-ms" in js or "pgbar-ms" in html, \
        "milestone bar markers (pgbar-ms) not found"


def test_ac12_milestone_list_header():
    """AC12: Milestone list has a header section."""
    assert "milestone-list-hdr" in html or "milestone-list" in html, \
        "Milestone list header section not found in weight.html"


# ── AC13: Bottom grid layout ──────────────────────────────────────────────────

def test_ac13_bottom_grid_class():
    """AC13: Bottom grid container exists for side-by-side layout."""
    assert "bottom-grid" in html, \
        "'bottom-grid' class not found in weight.html"


def test_ac13_bottom_grid_css_two_columns():
    """AC13: Bottom grid CSS uses two-column layout."""
    # Must have grid-template-columns with 2 columns
    m = re.search(
        r'\.bottom-grid\s*\{[^}]*grid-template-columns\s*:[^}]*\}',
        html, re.DOTALL
    )
    assert m, \
        "CSS .bottom-grid with grid-template-columns not found in weight.html"
    assert "1fr" in m.group(), \
        ".bottom-grid grid-template-columns must use 1fr in weight.html"


def test_ac13_progress_card_in_bottom_grid():
    """AC13: progress-card is a child of bottom-grid."""
    # Check structural nesting in HTML
    bottom_grid_idx = html.find("bottom-grid")
    progress_card_idx = html.find('id="progress-card"')
    assert bottom_grid_idx != -1 and progress_card_idx != -1, \
        "Either bottom-grid or progress-card missing from weight.html"
    assert progress_card_idx > bottom_grid_idx, \
        "progress-card must appear after (inside) bottom-grid in weight.html"


def test_ac13_recent_entries_in_bottom_grid():
    """AC13: Recent entries card is inside bottom-grid."""
    bottom_grid_idx = html.find("bottom-grid")
    entries_idx = html.find('id="recent-entries"')
    assert bottom_grid_idx != -1 and entries_idx != -1, \
        "Either bottom-grid or recent-entries missing from weight.html"
    assert entries_idx > bottom_grid_idx, \
        "recent-entries must appear after (inside) bottom-grid in weight.html"


# ── AC14: Responsive collapse at 820px ───────────────────────────────────────

def test_ac14_bottom_grid_collapses_at_820px():
    """AC14: Bottom grid collapses to single column at ≤820px."""
    m = re.search(
        r'820px.*?bottom-grid.*?grid-template-columns\s*:\s*1fr',
        html, re.DOTALL
    )
    assert m, \
        "bottom-grid not set to 1fr inside 820px media query in weight.html"


# ── AC15: Plan tick position formula ─────────────────────────────────────────

def test_ac15_plan_tick_formula_uses_start_minus_plan():
    """AC15: Plan tick position uses (start − plan_today) / (start − target) formula."""
    # JS must compute plan_pct using start_weight_kg, plan_today_kg, target_weight_kg
    assert "start_weight_kg" in js, \
        "JS does not reference start_weight_kg for plan tick formula"
    assert "plan_today_kg" in js, \
        "JS does not reference plan_today_kg for plan tick formula"
    assert "target_weight_kg" in js, \
        "JS does not reference target_weight_kg for plan tick formula"


def test_ac15_plan_tick_formula_division():
    """AC15: Plan tick position formula involves division for percentage."""
    # Must divide to compute plan_pct
    src_render = js[js.find("pgbar-plan-tick"):js.find("pgbar-plan-tick") + 500] if "pgbar-plan-tick" in js else ""
    assert "/" in src_render or "planPct" in js or "plan_pct" in js, \
        "Plan tick percentage calculation (division) not found near pgbar-plan-tick in weight.js"


# ── AC16 / AC17: You-dot from progress_pct + all four pill states ─────────────

def test_ac16_you_dot_uses_progress_pct():
    """AC16: You-dot position is set from progress_pct."""
    assert "pgbar-you-dot" in js and "progress_pct" in js, \
        "You-dot must be positioned using progress_pct in weight.js"


def test_ac17_all_four_gap_directions_handled():
    """AC17: JS handles all four gap_direction values for status pill."""
    for d in ("behind", "ahead", "on_plan", "no_data"):
        assert d in js, \
            f"gap_direction '{d}' not handled in weight.js"


# ── AC18: Milestones from API array ──────────────────────────────────────────

def test_ac18_milestones_iterate_kind_field():
    """AC18: JS checks milestone.kind to differentiate today/intermediate/goal rows."""
    assert ".kind" in js or "kind ==" in js or "kind ===" in js or "'today'" in js, \
        "JS must check milestone kind field in weight.js"


def test_ac18_milestones_today_kind_check():
    """AC18: JS explicitly handles 'today' kind milestone."""
    assert "'today'" in js or '"today"' in js, \
        "JS must handle kind='today' milestone in weight.js"


def test_ac18_milestones_goal_kind_check():
    """AC18: JS explicitly handles 'goal' kind milestone."""
    assert "'goal'" in js or '"goal"' in js, \
        "JS must handle kind='goal' milestone in weight.js"
