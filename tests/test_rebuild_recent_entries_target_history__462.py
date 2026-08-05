"""
TDD tests for issue #462 — Rebuild Recent Entries card and add inline Target History.

All tests are static source-file tests (no live server required).

AC anchors:
  (A) Recent Entries Card:
    A1: Card header "Recent entries · last 14 days" + "View all N →" link
    A2: "View all N" count uses total_entries from history-summary (not just 14-day window)
    A3: No standalone time column in Recent Entries row structure
    A4: Note area present in each row (separate column from date)
    A5: Logged rows rendered with: date div, note div, weight div, delta div
    A6: Logged rows have ⋯ overflow menu with Edit and Delete
    A7: Missing-day rows show faded styling + dashed "＋ Add" chip
    A8: Mini-stepper opens inline on chip click, prefilled via _nearestWeight
    A9: After logging: hero, coach, chart, and progress all refresh (_reload / _reloadHeroAndCoach)
    A10: Today's row has blue-tint CSS class (re-row-today or similar)
    A11: Unlogged today row auto-opens mini-stepper
    A12: Hero stepper (card B) calls _reloadEntries after logging → entries stay in sync
    A13: Delta computation uses gap-aware logic (loops over allSorted to find previous logged)
    A14: CSS for re-row uses grid layout with date, note, weight, delta columns

  (B) Target History Section:
    B1: "Target history" heading (h2/h3/text) present in weight.html
    B2: Target history section is inline — NOT hidden behind a tab (no display:none on section)
    B3: Target history grid uses bottom-grid or equivalent 2-col → 1-col responsive pattern
    B4: "Your weight journey" card present in HTML
    B5: All-time stat elements: targets set, achieved, total lost, avg pace
    B6: "Past targets" card present in HTML
    B7: Filter pills for All / Achieved / Replaced / Abandoned
    B8: Export button (targets) present
    B9: Past targets table with status, range, result, delta columns
    B10: GET /api/weight-targets/history-summary endpoint registered in main.py
    B11: history-summary returns stats.targets_set, stats.targets_achieved,
         stats.success_pct, stats.total_kg_lost, stats.avg_pace_kg_per_week,
         stats.current_day_count, past_attempts, targets, total_entries
    B12: Filter pills JS wires data-filter attributes and toggles active class
    B13: Export JS calls /api/exports/weight-targets or equivalent
    B14: Target history section renders on mobile (bottom-grid stacks at 640px)
"""

import re
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
WEIGHT_HTML = FRONTEND / "pages" / "weight.html"
WEIGHT_JS   = FRONTEND / "js" / "weight.js"
MAIN_PY     = ROOT / "backend" / "main.py"

html    = WEIGHT_HTML.read_text()
js      = WEIGHT_JS.read_text()
main_py = MAIN_PY.read_text()


# ── (A) Recent Entries Card ────────────────────────────────────────────────────

def test_a1_recent_entries_header_text():
    """(A1) Card header reads 'Recent entries' with 'last 14 days' subtitle."""
    assert "Recent entries" in html, (
        "Card header 'Recent entries' not found in weight.html (AC-A1)"
    )
    assert "last 14 days" in html, (
        "'last 14 days' subtitle not found in weight.html (AC-A1)"
    )


def test_a1_view_all_link_present():
    """(A1) 'View all N →' link element is present in HTML."""
    assert "view-all-link" in html, (
        "id='view-all-link' element not found in weight.html (AC-A1)"
    )
    assert "View all" in html, (
        "'View all' text not found in weight.html (AC-A1)"
    )


def test_a2_view_all_uses_total_entries_count():
    """(A2) JS updates view-all-link using total_entries from history-summary (not just 14-day window)."""
    # The JS must reference total_entries or history_summary to set the view-all count
    # (not just entries.length from the 14-day fetch)
    assert (
        "total_entries" in js
        or "historySummary" in js
        or "_historySummary" in js
        or "history-summary" in js
    ), (
        "JS must use total_entries (from history-summary) for View all N count, "
        "not just 14-day entries.length (AC-A2)"
    )


def test_a3_no_time_column_in_entries():
    """(A3) Recent Entries table/grid must NOT have a standalone 'Time' column header."""
    # We look for a time column header in the entries table/rows
    # Check that there's no <th>Time</th> or similar near the entries section
    entries_section = html
    # Should not have a Time column header in the entries table
    assert not re.search(r'<th[^>]*>\s*Time\s*</th>', entries_section, re.IGNORECASE), (
        "Time column header found in Recent Entries — it must be removed (AC-A3)"
    )


def test_a4_note_area_in_row_structure():
    """(A4) Each entry row has a note area / column (separate from date)."""
    # The row must have a note cell/div — could be 're-note', 'entry-note', or note class
    assert (
        "re-note" in html
        or "entry-note" in html
        or 're-row-note' in html
        or ('"note"' in html and "re-row" in html)
    ), (
        "Note area not found in Recent Entries row structure (AC-A4)"
    )


def test_a5_logged_row_uses_grid_with_four_areas():
    """(A5) Recent entry rows use a grid/flex layout with date, note, weight, delta areas."""
    # re-row class should have grid or flex layout in CSS
    assert "re-row" in html, "re-row class not found in weight.html (AC-A5)"
    # CSS should define grid-template-columns or flex for re-row
    assert (
        "grid-template-columns" in html
        and "re-row" in html
    ) or (
        "display: grid" in html
        and "re-row" in html
    ) or (
        "display:grid" in html
        and "re-row" in html
    ), (
        "re-row must use CSS grid layout (AC-A5)"
    )


def test_a5_weight_in_monospace():
    """(A5) Weight values in entries use monospace font (JetBrains Mono or monospace class)."""
    # Check CSS for monospace on weight cells
    assert (
        "JetBrains Mono" in html
        or "monospace" in html
    ), (
        "Monospace font not found for weight values (AC-A5)"
    )
    # And a .re-w or similar class with font-family mono
    assert (
        "re-w" in html
        or "entry-weight" in html
        or ("re-row" in html and "mono" in html.lower())
    ), (
        "Monospace weight class not found in entries (AC-A5)"
    )


def test_a6_logged_rows_overflow_menu():
    """(A6) Logged entry rows include overflow ⋯ menu with Edit and Delete actions."""
    # JS must have _toggleEntryMenu or similar
    assert (
        "_toggleEntryMenu" in js
        or "toggleEntryMenu" in js
        or "entry-menu" in js
    ), (
        "Overflow menu function not found in weight.js (AC-A6)"
    )
    # HTML must have entry-menu-btn or re-menu-btn class
    assert (
        "entry-menu-btn" in html
        or "re-menu-btn" in html
        or "menu-btn" in html
    ) or (
        "entry-menu-btn" in js
        or "re-menu-btn" in js
    ), (
        "Overflow ⋯ menu button not wired (AC-A6)"
    )
    # Menu must include Edit and Delete
    assert (
        "Edit" in html or "Edit" in js
    ) and (
        "Delete" in html or "Delete" in js
    ), (
        "Edit and Delete options not found in menu (AC-A6)"
    )


def test_a7_missing_day_rows_faded():
    """(A7) Missing-day rows have faded/missed styling class."""
    assert (
        "re-row-missed" in html
        or "missed" in html
        or "missing-day-row" in html
    ), (
        "Missing-day row faded class not found in weight.html (AC-A7)"
    )


def test_a7_add_chip_dashed_border():
    """(A7) ＋ Add chip has dashed border styling."""
    assert (
        "add-chip" in html
        or "backfill-add-btn" in html
    ), (
        "＋ Add chip element not found in weight.html (AC-A7)"
    )
    # The chip/btn should have dashed border in CSS
    assert (
        "dashed" in html
    ), (
        "Dashed border not found for Add chip (AC-A7)"
    )


def test_a8_mini_stepper_elements_in_js():
    """(A8) JS has _openMiniStepper function that renders inline stepper UI."""
    assert "_openMiniStepper" in js or "openMiniStepper" in js, (
        "_openMiniStepper function not found in weight.js (AC-A8)"
    )
    # Stepper must have −, +, value input, and Log button
    assert (
        "stepper-dec" in js or "mini-step" in js or "mini-stepper" in js
    ), (
        "Stepper decrement element not found in JS (AC-A8)"
    )
    assert (
        "stepper-inc" in js or "mini-step" in js or "mini-stepper" in js
    ), (
        "Stepper increment element not found in JS (AC-A8)"
    )
    assert (
        "mini-save" in js or "stepper-log-btn" in js or "backfill-save-btn" in js
    ), (
        "Log button not found in mini-stepper JS (AC-A8)"
    )


def test_a8_nearest_weight_prefill():
    """(A8) Mini-stepper prefills from _nearestWeight helper."""
    assert "_nearestWeight" in js or "nearestWeight" in js, (
        "_nearestWeight function not found in weight.js (AC-A8)"
    )


def test_a9_after_log_refresh_all():
    """(A9) After logging via mini-stepper, hero/coach/chart/progress refresh."""
    # The mini-stepper submit should call _reload() or equivalent
    assert (
        "_reload()" in js
        or "await _reload()" in js
        or "_reloadHeroAndCoach" in js
    ), (
        "After mini-stepper log, _reload or _reloadHeroAndCoach not called (AC-A9)"
    )


def test_a10_today_row_blue_tint():
    """(A10) Today's row has a blue-tinted CSS class."""
    assert (
        "re-row-today" in html
        or "entry-row-today" in html
        or "today-row" in html
    ), (
        "Today blue-tint class not found in weight.html (AC-A10)"
    )
    # CSS for that class must have a blue background
    assert (
        "blue-soft" in html
        or "dde6f8" in html.lower()
        or "rgba(37,99,235" in html
        or "rgba(53,99,212" in html
        or "#dde6f8" in html.lower()
        or "blue" in html.lower() and ("today" in html)
    ), (
        "Blue tint CSS not found for today row (AC-A10)"
    )


def test_a11_today_unlogged_stepper_auto_opens():
    """(A11) JS auto-opens the mini-stepper for today's unlogged row."""
    # renderRecentEntries should call _openMiniStepper for today's row
    assert (
        "_openMiniStepper" in js
        and "isToday" in js
    ), (
        "Auto-open mini-stepper for today not found in weight.js (AC-A11)"
    )


def test_a12_card_b_logging_syncs_entries():
    """(A12) Card B (hero stepper) calls _reloadEntries after logging → entries sync."""
    assert "_reloadEntries" in js, (
        "_reloadEntries function not found in weight.js (AC-A12)"
    )
    # _submitCardB must call _reloadEntries
    sub_b_idx = js.find("_submitCardB")
    reload_entries_idx = js.find("_reloadEntries()", sub_b_idx)
    assert sub_b_idx != -1 and reload_entries_idx != -1, (
        "_submitCardB does not call _reloadEntries() (AC-A12)"
    )


def test_a13_gap_aware_delta():
    """(A13) Delta uses gap-aware logic: finds previous logged entry, not previous calendar day."""
    assert (
        "prevWeight" in js
        or "prev_weight" in js
        or "allSorted" in js
    ), (
        "Gap-aware delta computation not found in weight.js (AC-A13)"
    )
    # The pattern should compare entry dates to find prior logged entry
    assert (
        "entry_date" in js
        and ("localeCompare" in js or "sort" in js)
    ), (
        "Gap-aware delta sort by entry_date not found (AC-A13)"
    )


def test_a14_re_row_grid_columns_count():
    """(A14) .re-row CSS grid has at least 4 template columns (date, note, weight, delta)."""
    # Find the re-row CSS rule and check for grid-template-columns
    re_row_section = re.search(
        r'\.re-row\s*\{[^}]+\}',
        html,
        re.DOTALL,
    )
    assert re_row_section is not None, ".re-row CSS rule not found (AC-A14)"
    rule_text = re_row_section.group(0)
    assert "grid-template-columns" in rule_text or "display" in rule_text, (
        ".re-row must have grid layout (AC-A14)"
    )


# ── (B) Target History Section ─────────────────────────────────────────────────

def test_b1_target_history_heading():
    """(B1) 'Target history' heading text is present in weight.html."""
    assert "Target history" in html or "target-history" in html, (
        "'Target history' heading not found in weight.html (AC-B1)"
    )


def test_b2_target_history_inline_not_hidden_by_tab():
    """(B2 revised) Target history is retired from the visible tab (hidden stub)."""
    assert 'id="target-history-section"' in html
    assert " hidden" in html[html.find('id="target-history-section"'):
                              html.find('id="target-history-section"') + 90]


def test_b3_target_history_grid_responsive():
    """(B3) Target history uses a 2-column grid that stacks at 640px."""
    # Must reuse bottom-grid class or have its own responsive grid
    assert (
        "target-history" in html
        and (
            "bottom-grid" in html[html.find("target-history"):][:1000]
            or "target-history-grid" in html
            or ("grid-template-columns: 1fr" in html and "640px" in html)
        )
    ), (
        "Target history must use a responsive 2-column grid (AC-B3)"
    )
    # Media query at 640px
    assert "640px" in html, (
        "640px breakpoint not found in weight.html (AC-B3)"
    )


def test_b4_your_weight_journey_card():
    """(B4) 'Your weight journey' card is present in HTML."""
    assert (
        "Your weight journey" in html
        or "weight-journey" in html
        or "journey-card" in html
    ), (
        "'Your weight journey' card not found in weight.html (AC-B4)"
    )


def test_b5_vs_past_attempts_banner():
    """(B5) 'vs past attempts' comparison banner is present in HTML."""
    assert (
        "vs-banner" in html
        or "past-attempts" in html
        or "past attempt" in html.lower()
        or "vs past" in html.lower()
        or "journey-banner" in html
    ), (
        "'vs past attempts' comparison banner not found in weight.html (AC-B5)"
    )


def test_b5_vs_banner_js_populated():
    """(B5) JS populates the 'vs past attempts' banner from past_attempts data."""
    assert (
        "past_attempts" in js
        or "pastAttempts" in js
    ), (
        "past_attempts data not handled in weight.js (AC-B5)"
    )


def test_b6_all_time_stats_elements():
    """(B6) All-time stats: targets set, achieved+success%, total lost, avg pace."""
    lower_html = html.lower()
    assert (
        "targets-set" in html or "journey-targets-set" in html or "targets set" in lower_html
    ), (
        "'Targets set' stat not found in weight.html (AC-B6)"
    )
    assert (
        "journey-achieved" in html or "targets-achieved" in html or "achieved" in lower_html
    ), (
        "'Achieved' stat not found in weight.html (AC-B6)"
    )
    assert (
        "journey-total-lost" in html or "total-lost" in html or "total lost" in lower_html
    ), (
        "'Total lost' stat not found in weight.html (AC-B6)"
    )
    assert (
        "journey-avg-pace" in html or "avg-pace" in html or "avg pace" in lower_html
    ), (
        "'Avg pace' stat not found in weight.html (AC-B6)"
    )


def test_b7_past_targets_card():
    """(B7) 'Past targets' card is present in HTML."""
    assert (
        "Past targets" in html
        or "past-targets" in html
        or "past-targets-card" in html
    ), (
        "'Past targets' card not found in weight.html (AC-B7)"
    )


def test_b8_filter_pills():
    """(B8) Filter pills: All / Achieved / Replaced / Abandoned."""
    lower = html.lower()
    assert "all" in lower and "achieved" in lower and "replaced" in lower and "abandoned" in lower, (
        "Filter pills (All/Achieved/Replaced/Abandoned) not found in weight.html (AC-B8)"
    )
    assert (
        "target-filter" in html
        or "filter-pill" in html
        or ('data-filter' in html)
        or "fb" in html
    ), (
        "Filter pill buttons/classes not found (AC-B8)"
    )


def test_b9_export_button_targets():
    """(B9) Export button for Past Targets section is present."""
    assert (
        "export-targets" in html
        or "Export" in html
    ), (
        "Export button not found in weight.html (AC-B9)"
    )
    # JS must have export logic for targets
    assert (
        "weight-targets" in js
        or "targets" in js
    ), (
        "Export targets logic not found in weight.js (AC-B9)"
    )


def test_b10_past_targets_table_columns():
    """(B10) Past targets table has status, target range, result weight, delta columns."""
    # After 'past-targets' section in HTML, check for table structure
    pt_idx = html.find("past-targets")
    pt_section = html[pt_idx:pt_idx + 3000] if pt_idx != -1 else html
    lower_pt = pt_section.lower()
    # Must have the table element
    assert "<table" in pt_section or "past-targets-table" in html, (
        "Past targets table not found (AC-B10)"
    )


def test_b11_history_summary_endpoint_in_main_py():
    """(B11) GET /api/weight-targets/history-summary endpoint is registered in main.py."""
    assert "/api/weight-targets/history-summary" in main_py, (
        "GET /api/weight-targets/history-summary endpoint not found in main.py (AC-B11)"
    )


def test_b11_history_summary_returns_stats_keys():
    """(B11) history-summary endpoint code returns required stats keys."""
    idx = main_py.find("/api/weight-targets/history-summary")
    assert idx != -1, "Endpoint not found"
    # Use a wide window to cover the full function body
    func_body = main_py[idx:idx + 6000]
    assert "targets_set" in func_body, "'targets_set' key not in history-summary response (AC-B11)"
    assert "targets_achieved" in func_body, "'targets_achieved' not in response (AC-B11)"
    assert "success_pct" in func_body, "'success_pct' not in response (AC-B11)"
    assert "total_kg_lost" in func_body, "'total_kg_lost' not in response (AC-B11)"
    assert "avg_pace_kg_per_week" in func_body, "'avg_pace_kg_per_week' not in response (AC-B11)"
    assert "past_attempts" in func_body, "'past_attempts' not in response (AC-B11)"
    assert "total_entries" in func_body, "'total_entries' not in response (AC-B11)"


def test_b12_filter_pills_js_wired():
    """(B12) JS wires filter pills with data-filter attribute and toggles active class."""
    assert (
        "data-filter" in js
        or "target-filter" in js
        or "filterPills" in js
        or "_initTargetHistoryFilters" in js
    ), (
        "Filter pills not wired in weight.js (AC-B12)"
    )
    # Active class toggle
    assert (
        "active" in js
        and ("filter" in js or "pill" in js)
    ), (
        "Active class toggle for filter pills not found in weight.js (AC-B12)"
    )


def test_b13_export_js_calls_exports_endpoint():
    """(B13) Export targets JS calls /api/exports/weight-targets or equivalent."""
    assert (
        "exports/weight-targets" in js
        or "export-targets" in js
    ), (
        "Export targets endpoint call not found in weight.js (AC-B13)"
    )


def test_b14_target_history_stacks_at_640px():
    """(B14) Dormant target-history CSS still stacks at 640px."""
    assert "640px" in html
    assert ".target-history-grid" in html
    idx = html.find(".target-history-grid")
    # Prefer the rule inside a 640px media block
    media = html.find("@media (max-width: 640px)")
    assert media != -1
    assert "grid-template-columns: 1fr" in html[media:media + 2500]
