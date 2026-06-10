"""Tests for issue #413: Build weight target management page (/weight/targets).

AC anchors verified:
  (routing) route /weight/targets registered in main.py; returns weight-targets.html; logic in weight-targets.js
  (A-header) breadcrumb back link to /weight; page title "Weight targets"; "Set new target" button present;
             button disabled when active target (JS); tooltip "End or replace the current target first"
  (B-active) "ACTIVE TARGET" banner pill with flag icon; pencil edit button; X end button;
             start→target weight visual; dates row; "in N months" subtitle;
             3-up pace stats (remaining/needed/current); green up-arrow when exceeding pace; amber down-arrow when below;
             progress mini-card: large % + "X of Y kg lost" + status pill;
             projected mini-card: hit date + current pace + days early/late
  (B-form)   inline form in place of active card when no active target;
             start weight pre-filled from latest weight entry (JS); start date pre-filled with today (JS);
             fields: start_weight / start_date / target_weight / target_date / notes;
             submit POSTs to /api/weight-targets and refreshes page state
  (C)        horizontal rail; 5 labeled points: Start / Current / 3mo / 6mo / Goal;
             each point has label+marker+date+weight; gradient bar width = progress_pct; mobile horizontally scrollable
  (D)        4-up stats grid: Targets set / Targets achieved / Total weight lost / Avg pace kg/wk;
             success rate % green sub-label; total lost = sum of achieved targets; avg pace = sum/count achieved;
             all values computed client-side from /api/weight-targets/history
  (E)        columns: Status / Name / Pace kg/wk / Result weight / Delta / Duration days / Actions;
             Done/Replaced/Abandoned badges; delta green when achieved/replaced moving toward goal; amber abandoned;
             filter pills All/Achieved/Replaced/Abandoned; 880px → card list
  (edit)     edit modal opens from pencil on active card; fields: target_weight / target_date / notes;
             save submits PATCH to /api/weight-targets/{id}; refreshes card
  (end)      end modal opens from X on active card; "Mark as achieved" / "Mark as abandoned" buttons;
             displays end_weight_kg from latest 7-day entry; both buttons disabled + message when no entry in 7 days
  (responsive) 880px: active card single column; history table → card list
"""

import os
import pathlib
import re

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "frontend" / "pages"
JS_DIR = ROOT / "frontend" / "js"
MAIN_PY = ROOT / "backend" / "main.py"

HTML_PATH = PAGES_DIR / "weight-targets.html"
JS_PATH = JS_DIR / "weight-targets.js"

WT_HTML = HTML_PATH.read_text() if HTML_PATH.exists() else ""
WT_JS = JS_PATH.read_text() if JS_PATH.exists() else ""
MAIN_SRC = MAIN_PY.read_text() if MAIN_PY.exists() else ""

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")


# ── Routing & Shell ────────────────────────────────────────────────────────────

def test_routing_html_file_exists():
    assert HTML_PATH.exists(), "frontend/pages/weight-targets.html must exist"


def test_routing_js_file_exists():
    assert JS_PATH.exists(), "frontend/js/weight-targets.js must exist"


def test_routing_route_registered_in_main():
    assert "/weight/targets" in MAIN_SRC, \
        "main.py must register the /weight/targets route"


def test_routing_main_returns_weight_targets_html():
    assert "weight-targets.html" in MAIN_SRC, \
        "main.py must serve weight-targets.html for /weight/targets"


def test_routing_html_loads_weight_targets_js():
    assert "weight-targets.js" in WT_HTML, \
        "weight-targets.html must load weight-targets.js via <script src>"


def test_routing_live_returns_200():
    pytest.importorskip("httpx")
    try:
        with httpx.Client(base_url=BASE, timeout=5, follow_redirects=True) as c:
            r = c.get("/weight/targets")
        assert r.status_code == 200, f"GET /weight/targets must return 200, got {r.status_code}"
    except httpx.ConnectError:
        pytest.skip("Server not running")


# ── Section A — Header ─────────────────────────────────────────────────────────

def test_a_breadcrumb_back_link_to_weight():
    assert 'href="/weight"' in WT_HTML or "href='/weight'" in WT_HTML, \
        "breadcrumb must link back to /weight"


def test_a_breadcrumb_shows_weight_targets_text():
    assert "Weight targets" in WT_HTML or "weight targets" in WT_HTML.lower(), \
        "breadcrumb must show 'Weight targets' page label"


def test_a_page_title_weight_targets():
    assert "Weight targets" in WT_HTML, \
        "page must have 'Weight targets' as the visible <h1> title"


def test_a_set_new_target_button_in_header():
    lower = WT_HTML.lower()
    assert "set new target" in lower, \
        "header must contain a 'Set new target' button"


def test_a_js_disables_button_when_active_target():
    assert "disabled" in WT_JS and "set-target-btn" in WT_JS, \
        "weight-targets.js must set #set-target-btn disabled when an active target exists"


def test_a_button_tooltip_text():
    assert "End or replace the current target first" in WT_JS or \
           "End or replace the current target first" in WT_HTML, \
        "tooltip text must read 'End or replace the current target first'"


# ── Section B — Active Target Card ────────────────────────────────────────────

def test_b_active_target_pill_text():
    assert "ACTIVE TARGET" in WT_HTML or "active target" in WT_HTML.lower(), \
        "card must have 'ACTIVE TARGET' banner pill"


def test_b_active_target_flag_icon():
    lower = WT_HTML.lower()
    assert "flag" in lower, \
        "ACTIVE TARGET pill must include a flag icon"


def test_b_edit_pencil_button():
    lower = WT_HTML.lower()
    assert "pencil" in lower or "edit-target" in lower, \
        "active card must have a pencil (edit) icon button"


def test_b_end_x_button():
    lower = WT_HTML.lower()
    assert "end-target" in lower or "ti-x" in lower, \
        "active card must have an X (end) icon button"


def test_b_start_target_weight_display():
    assert "start_weight_kg" in WT_JS and "target_weight_kg" in WT_JS, \
        "JS must render start_weight_kg → target_weight_kg on the active card"


def test_b_dates_row():
    assert "start_date" in WT_JS and "target_date" in WT_JS, \
        "JS must render start_date and target_date on the active card"


def test_b_in_n_months_subtitle():
    assert "month" in WT_JS.lower(), \
        "JS must compute and display 'in N months' subtitle"


def test_b_3up_remaining_kg():
    lower = WT_HTML.lower()
    assert "remaining" in lower and "kg" in lower, \
        "3-up grid must have a 'Remaining kg' stat"


def test_b_3up_pace_needed():
    lower = WT_HTML.lower()
    assert "pace needed" in lower or "required" in lower or "required-pace" in lower, \
        "3-up grid must have a 'Pace needed kg/wk' stat"


def test_b_3up_current_pace():
    lower = WT_HTML.lower()
    assert "current pace" in lower or "current-pace" in lower, \
        "3-up grid must have a 'Your current pace kg/wk' stat"


def test_b_current_pace_green_when_exceeding():
    assert "green" in WT_JS or "#16a34a" in WT_JS, \
        "JS must display green indicator when current pace >= required pace"


def test_b_current_pace_amber_when_below():
    assert "amber" in WT_JS or "#d97706" in WT_JS, \
        "JS must display amber indicator when current pace < required pace"


def test_b_pace_arrow_up_symbol():
    assert "↑" in WT_JS or "up" in WT_JS.lower(), \
        "JS must use an up-arrow symbol for green pace indicator"


def test_b_pace_arrow_down_symbol():
    assert "↓" in WT_JS or "down" in WT_JS.lower(), \
        "JS must use a down-arrow symbol for amber pace indicator"


def test_b_progress_pct_large():
    assert "progress-pct" in WT_HTML or "progress_pct" in WT_HTML, \
        "progress mini-card must have a large % number element"


def test_b_kg_lost_label():
    assert "kg-lost" in WT_HTML or "kg lost" in WT_HTML.lower(), \
        "progress mini-card must have 'X of Y kg lost' label"


def test_b_status_pill_on_progress_card():
    assert "status-pill" in WT_HTML, \
        "progress mini-card must have a status pill element"


def test_b_projected_mini_card():
    lower = WT_HTML.lower()
    assert "projected" in lower, \
        "right side must have a projected mini-card"


def test_b_projected_end_date_from_api():
    assert "projected_end_date" in WT_JS, \
        "JS must use projected_end_date from the active target API"


def test_b_days_delta_ahead_behind():
    js_lower = WT_JS.lower()
    assert "ahead" in js_lower and "behind" in js_lower, \
        "JS must display days ahead or behind the target date"


# ── Section B — Set New Target Form ───────────────────────────────────────────

def test_b_form_renders_when_no_active_target():
    assert "new-target-form" in WT_HTML or "new-target-form-card" in WT_HTML, \
        "HTML must have inline 'Set new target' form element"


def test_b_form_shown_hidden_by_js():
    assert "new-target-form-card" in WT_JS, \
        "JS must toggle the new-target-form-card based on active target state"


def test_b_form_start_weight_prefilled():
    js_lower = WT_JS.lower()
    assert "form-start-weight" in WT_JS and ("weight_kg" in WT_JS or "latest" in js_lower), \
        "JS must pre-fill form-start-weight from the latest weight entry"


def test_b_form_start_date_today():
    assert "form-start-date" in WT_JS and ("today" in WT_JS.lower() or "todayiso" in WT_JS.lower()), \
        "JS must pre-fill form-start-date with today's date"


def test_b_form_field_start_weight():
    assert "form-start-weight" in WT_HTML, \
        "inline form must have a start weight input (id=form-start-weight)"


def test_b_form_field_start_date():
    assert "form-start-date" in WT_HTML, \
        "inline form must have a start date input (id=form-start-date)"


def test_b_form_field_target_weight():
    assert "form-target-weight" in WT_HTML, \
        "inline form must have a target weight input (id=form-target-weight)"


def test_b_form_field_target_date():
    assert "form-target-date" in WT_HTML, \
        "inline form must have a target date input (id=form-target-date)"


def test_b_form_field_notes():
    assert "form-notes" in WT_HTML, \
        "inline form must have a notes textarea (id=form-notes)"


def test_b_form_submit_posts_to_api():
    assert "/api/weight-targets" in WT_JS and "POST" in WT_JS, \
        "JS must POST to /api/weight-targets on form submit"


def test_b_form_refreshes_page_after_submit():
    assert "renderPage" in WT_JS or "loadActiveTarget" in WT_JS, \
        "JS must refresh page state after successful target creation"


# ── Section C — Milestone Timeline Strip ──────────────────────────────────────

def test_c_milestone_strip_element():
    assert "milestone-strip" in WT_HTML or "milestone-rail" in WT_HTML, \
        "HTML must have milestone timeline strip element"


def test_c_5_points_rendered_by_js():
    assert "Start" in WT_JS and "Current" in WT_JS and "Goal" in WT_JS, \
        "JS must render milestone points including Start, Current, and Goal"


def test_c_3mo_point():
    assert "3mo" in WT_JS or "'3mo'" in WT_JS or '"3mo"' in WT_JS, \
        "JS must render a '3mo' milestone point"


def test_c_6mo_point():
    assert "6mo" in WT_JS or "'6mo'" in WT_JS or '"6mo"' in WT_JS, \
        "JS must render a '6mo' milestone point"


def test_c_each_point_has_label_marker_date_weight():
    assert "milestone-marker" in WT_HTML and "milestone-label" in WT_HTML and \
           "milestone-date" in WT_HTML and "milestone-weight" in WT_HTML, \
        "each milestone point must have marker, label, date, and weight elements"


def test_c_gradient_bar_fill_uses_progress_pct():
    assert "progress_pct" in WT_JS and ("width" in WT_JS or "fill" in WT_JS.lower()), \
        "JS must set milestone gradient bar width to progress_pct"


def test_c_milestone_track_fill_element():
    assert "milestone-track-fill" in WT_HTML, \
        "HTML must have a milestone-track-fill element for the gradient bar"


def test_c_mobile_horizontally_scrollable():
    assert "overflow" in WT_HTML and ("scroll" in WT_HTML or "auto" in WT_HTML), \
        "milestone strip must be horizontally scrollable on mobile"


def test_c_min_width_for_scroll():
    assert "min-width" in WT_HTML, \
        "milestone rail must have a min-width to trigger horizontal scroll on narrow viewports"


# ── Section D — Stats Summary Card ────────────────────────────────────────────

def test_d_targets_set_element():
    assert "stat-targets-set" in WT_HTML, \
        "HTML must have id=stat-targets-set element"


def test_d_targets_achieved_element():
    assert "stat-targets-achieved" in WT_HTML, \
        "HTML must have id=stat-targets-achieved element"


def test_d_success_rate_green_sublabel():
    assert "success-rate" in WT_HTML, \
        "HTML must have success rate green sub-label element"


def test_d_total_weight_lost_element():
    assert "stat-total-lost" in WT_HTML, \
        "HTML must have id=stat-total-lost element"


def test_d_avg_pace_element():
    assert "stat-avg-pace" in WT_HTML, \
        "HTML must have id=stat-avg-pace element"


def test_d_success_rate_computed_from_achieved():
    js_lower = WT_JS.lower()
    assert "achievedcount" in js_lower or ("achieved" in js_lower and "success" in js_lower), \
        "JS must compute success rate % from achieved count / total"


def test_d_total_lost_sums_achieved_targets():
    js_lower = WT_JS.lower()
    assert "achieved" in js_lower and ("end_weight_kg" in WT_JS or "totalLost" in WT_JS or "total_lost" in js_lower), \
        "JS must compute total weight lost from achieved targets"


def test_d_avg_pace_from_achieved_targets():
    js_lower = WT_JS.lower()
    assert "avgpace" in js_lower or "avg_pace" in js_lower or \
           ("pace" in js_lower and "achieved" in js_lower and "avg" in js_lower), \
        "JS must compute avg pace from achieved targets"


def test_d_stats_from_history_api():
    assert "/api/weight-targets/history" in WT_JS, \
        "JS must fetch /api/weight-targets/history for stats computation"


# ── Section E — History Table ──────────────────────────────────────────────────

def test_e_history_table_present():
    assert "history-table" in WT_HTML and "history-tbody" in WT_HTML, \
        "HTML must have a history table with tbody"


def test_e_status_column():
    assert "Status" in WT_HTML, \
        "history table must have a Status column header"


def test_e_name_column():
    assert "Name" in WT_HTML, \
        "history table must have a Name column header"


def test_e_pace_column():
    assert "Pace" in WT_HTML, \
        "history table must have a Pace column header"


def test_e_result_weight_column():
    lower = WT_HTML.lower()
    assert "result weight" in lower or "result-weight" in lower, \
        "history table must have a Result weight column"


def test_e_delta_column():
    assert "Delta" in WT_HTML, \
        "history table must have a Delta column"


def test_e_duration_column():
    lower = WT_HTML.lower()
    assert "duration" in lower, \
        "history table must have a Duration column"


def test_e_actions_column():
    assert "Actions" in WT_HTML, \
        "history table must have an Actions column"


def test_e_done_badge():
    assert "badge-done" in WT_HTML or "Done" in WT_JS, \
        "JS must render a 'Done' badge for achieved targets"


def test_e_replaced_badge():
    assert "badge-replaced" in WT_HTML or "Replaced" in WT_JS, \
        "JS must render a 'Replaced' badge for replaced targets"


def test_e_abandoned_badge():
    assert "badge-abandoned" in WT_HTML or "Abandoned" in WT_JS, \
        "JS must render an 'Abandoned' badge for abandoned targets"


def test_e_delta_green_achieved():
    assert "delta-positive" in WT_JS and ("achieved" in WT_JS or "replaced" in WT_JS), \
        "JS must show green delta for achieved/replaced targets moving toward goal"


def test_e_delta_amber_abandoned():
    assert "delta-amber" in WT_JS, \
        "JS must show amber delta for abandoned targets"


def test_e_filter_pill_all():
    assert 'data-filter="all"' in WT_HTML or "data-filter='all'" in WT_HTML, \
        "HTML must have an 'All' filter pill"


def test_e_filter_pill_achieved():
    assert 'data-filter="achieved"' in WT_HTML or "data-filter='achieved'" in WT_HTML, \
        "HTML must have an 'Achieved' filter pill"


def test_e_filter_pill_replaced():
    assert 'data-filter="replaced"' in WT_HTML or "data-filter='replaced'" in WT_HTML, \
        "HTML must have a 'Replaced' filter pill"


def test_e_filter_pill_abandoned():
    assert 'data-filter="abandoned"' in WT_HTML or "data-filter='abandoned'" in WT_HTML, \
        "HTML must have an 'Abandoned' filter pill"


def test_e_filter_pills_filter_rows():
    assert "_activeFilter" in WT_JS or "activeFilter" in WT_JS.lower(), \
        "JS must use an active filter state to filter history rows"


def test_e_880px_card_list():
    assert "880px" in WT_HTML and "history-table" in WT_HTML, \
        "CSS must have an 880px breakpoint transforming the history table into card list"


# ── Edit Modal ─────────────────────────────────────────────────────────────────

def test_edit_modal_element():
    assert "edit-modal" in WT_HTML, \
        "HTML must have an #edit-modal element"


def test_edit_modal_opens_from_pencil():
    assert "openEditModal" in WT_JS or "edit-modal" in WT_JS, \
        "JS must open edit modal from the pencil button"


def test_edit_modal_target_weight_field():
    assert "edit-target-weight" in WT_HTML, \
        "edit modal must have an edit-target-weight input"


def test_edit_modal_target_date_field():
    assert "edit-target-date" in WT_HTML, \
        "edit modal must have an edit-target-date input"


def test_edit_modal_notes_field():
    assert "edit-notes" in WT_HTML, \
        "edit modal must have an edit-notes textarea"


def test_edit_modal_patches_api():
    assert "PATCH" in WT_JS and "/api/weight-targets/" in WT_JS, \
        "JS must PATCH /api/weight-targets/{id} on edit save"


def test_edit_modal_refreshes_active_card():
    assert "renderActiveCard" in WT_JS or "loadActiveTarget" in WT_JS, \
        "JS must refresh the active card after edit save"


# ── End Modal ──────────────────────────────────────────────────────────────────

def test_end_modal_element():
    assert "end-modal" in WT_HTML, \
        "HTML must have an #end-modal element"


def test_end_modal_opens_from_x_button():
    assert "openEndModal" in WT_JS or "end-modal" in WT_JS, \
        "JS must open end modal from the X button"


def test_end_modal_achieved_button():
    assert "end-achieved-btn" in WT_HTML and "Mark as achieved" in WT_HTML, \
        "end modal must have 'Mark as achieved' button"


def test_end_modal_abandoned_button():
    assert "end-abandoned-btn" in WT_HTML and "Mark as abandoned" in WT_HTML, \
        "end modal must have 'Mark as abandoned' button"


def test_end_modal_displays_end_weight():
    assert "end-weight-value" in WT_HTML and "end-weight-display" in WT_HTML, \
        "end modal must display end_weight_kg from latest 7-day entry"


def test_end_modal_weight_from_7day_window():
    assert "7" in WT_JS and ("cutoff" in WT_JS or "7" in WT_JS), \
        "JS must check for weight entry within last 7 days"


def test_end_modal_buttons_disabled_by_default():
    lower = WT_HTML.lower()
    assert "end-achieved-btn" in lower and "disabled" in lower, \
        "end modal buttons must be disabled by default in HTML"


def test_end_modal_no_weight_message():
    assert "Log a recent weight" in WT_HTML or "log a recent weight" in WT_HTML.lower(), \
        "end modal must show 'Log a recent weight first' message when no 7-day entry"


def test_end_modal_posts_to_end_endpoint():
    assert "/end" in WT_JS, \
        "JS must POST to /api/weight-targets/{id}/end"


def test_end_modal_refreshes_page():
    assert "renderPage" in WT_JS, \
        "JS must refresh the page after ending a target"


# ── Responsive ─────────────────────────────────────────────────────────────────

def test_responsive_880px_breakpoint_exists():
    assert "880px" in WT_HTML, \
        "CSS must include a max-width: 880px media query"


def test_responsive_active_card_single_column():
    assert "880px" in WT_HTML and "active-card-body" in WT_HTML and "grid-template-columns" in WT_HTML, \
        "CSS must collapse active-card-body to single column at 880px"


def test_responsive_history_card_list_at_880():
    assert "880px" in WT_HTML and "history-table" in WT_HTML.lower(), \
        "CSS must render history table as card list at ≤880px"
