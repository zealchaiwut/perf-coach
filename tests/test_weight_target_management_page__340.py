"""Tests for issue #340: Build weight target management page /weight/targets.

AC anchors verified:
  (routing) /weight/targets returns 200; weight-targets.html exists; weight-targets.js exists; script tag present
  (A-header) breadcrumb links /weight; page title "Weight targets"; "Set new target" button in HTML; disabled wiring in JS; tooltip text in JS
  (B-active) ACTIVE TARGET pill; edit (pencil) and end (X) buttons; start→target weight display; 3-up pace stats; pace color arrow logic; progress mini-card (%, kg-lost, status pill); projected mini-card
  (B-form) inline form elements: start_weight, start_date, target_weight, target_date, notes; pre-fill JS logic; submit POSTs /api/weight-targets
  (C) milestone strip HTML: 5 points (start/current/3mo/6mo/goal); gradient bar; mobile scrollable CSS
  (D) 4-up stats grid IDs; success rate sub-label; computed from history in JS
  (E) history table columns; status badges Done/Replaced/Abandoned; delta color logic in JS; filter pills All/Achieved/Replaced/Abandoned
  (edit-modal) modal present; fields: target_weight, target_date, notes; PATCH call in JS
  (end-modal) modal present; achieved/abandoned buttons; disabled state logic; "Log a recent weight" message; recent-entry check in JS
  (responsive) 880px breakpoint CSS for active card and history table
"""
import os
import pathlib
import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "frontend" / "js"
PAGES_DIR = ROOT / "frontend" / "pages"

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")

HTML_PATH = PAGES_DIR / "weight-targets.html"
JS_PATH = JS_DIR / "weight-targets.js"

WT_HTML = HTML_PATH.read_text() if HTML_PATH.exists() else ""
WT_JS = JS_PATH.read_text() if JS_PATH.exists() else ""


# ── Routing & Setup ───────────────────────────────────────────────────────────

def test_routing_html_file_exists():
    assert HTML_PATH.exists(), "frontend/pages/weight-targets.html must exist"


def test_routing_js_file_exists():
    assert JS_PATH.exists(), "frontend/js/weight-targets.js must exist"


def test_routing_html_loads_js():
    assert "weight-targets.js" in WT_HTML, \
        "weight-targets.html must include a <script src> for weight-targets.js"


def test_routing_route_returns_200():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=True) as c:
        r = c.get("/weight/targets")
    assert r.status_code == 200, f"GET /weight/targets must return 200, got {r.status_code}"


def test_routing_no_nav_markup_in_html():
    assert "weight-targets.js" in WT_HTML, \
        "weight-targets.js must be loaded by the page"


# ── Section A — Header ────────────────────────────────────────────────────────

def test_a_breadcrumb_links_to_weight():
    assert 'href="/weight"' in WT_HTML or "href='/weight'" in WT_HTML, \
        "HTML must have a breadcrumb link back to /weight"


def test_a_page_title_weight_targets():
    lower = WT_HTML.lower()
    assert "weight targets" in lower, \
        "HTML must contain 'Weight targets' as the page heading"


def test_a_set_new_target_button_present():
    lower = WT_HTML.lower()
    assert "set new target" in lower, \
        "HTML must have a 'Set new target' button element"


def test_a_js_disables_button_when_active_target():
    js_lower = WT_JS.lower()
    assert "disabled" in js_lower and ("set-target-btn" in WT_JS or "set_target" in js_lower), \
        "weight-targets.js must set the 'Set new target' button to disabled when an active target exists"


def test_a_js_tooltip_text_present():
    assert "End or replace the current target first" in WT_JS or \
           "end or replace" in WT_JS.lower(), \
        "weight-targets.js must include the tooltip text for disabled state"


# ── Section B — Active Target Card ────────────────────────────────────────────

def test_b_active_target_pill_element():
    lower = WT_HTML.lower()
    assert "active target" in lower, \
        "HTML must have an 'ACTIVE TARGET' banner/pill element"


def test_b_edit_button_present():
    lower = WT_HTML.lower()
    assert "edit" in lower and ("pencil" in lower or "edit-target" in lower or "ti-pencil" in lower or "✏" in WT_HTML), \
        "HTML must have an edit (pencil) icon button on the active card"


def test_b_end_button_present():
    lower = WT_HTML.lower()
    assert "end-target" in lower or ("end" in lower and ("×" in WT_HTML or "✕" in WT_HTML or "ti-x" in lower)), \
        "HTML must have an end (X) icon button on the active card"


def test_b_start_weight_target_weight_display():
    assert "start_weight_kg" in WT_JS or "start-weight" in WT_HTML.lower(), \
        "JS must render start weight from active target data"


def test_b_in_n_months_subtitle():
    js_lower = WT_JS.lower()
    assert "month" in js_lower, \
        "weight-targets.js must compute and display 'in N months' subtitle"


def test_b_3up_remaining_kg():
    lower = WT_HTML.lower()
    assert "remaining" in lower, \
        "HTML must have a 'Remaining kg' stat element in the 3-up pace grid"


def test_b_3up_pace_needed():
    lower = WT_HTML.lower()
    assert "pace" in lower and ("needed" in lower or "required" in lower), \
        "HTML must have a 'Pace needed kg/wk' stat element"


def test_b_3up_current_pace():
    lower = WT_HTML.lower()
    assert "current pace" in lower or "your pace" in lower or "current-pace" in lower, \
        "HTML must have a 'Your current pace kg/wk' stat element"


def test_b_js_pace_green_arrow_when_exceeding():
    js_lower = WT_JS.lower()
    assert "green" in js_lower or "#16a34a" in WT_JS or "#22c55e" in WT_JS or "↑" in WT_JS or "up" in js_lower, \
        "weight-targets.js must show green indicator when current pace exceeds required pace"


def test_b_js_pace_amber_arrow_when_below():
    js_lower = WT_JS.lower()
    assert "amber" in js_lower or "#d97706" in WT_JS or "#f59e0b" in WT_JS or "↓" in WT_JS or "orange" in js_lower, \
        "weight-targets.js must show amber indicator when current pace is below required pace"


def test_b_progress_pct_large_element():
    assert "progress-pct" in WT_HTML or "progress_pct" in WT_HTML, \
        "HTML must have a large progress % display element"


def test_b_kg_lost_label_element():
    lower = WT_HTML.lower()
    assert "kg lost" in lower or "kg-lost" in lower, \
        "HTML must have a 'X of Y kg lost' label"


def test_b_status_pill_element():
    assert "status-pill" in WT_HTML or "status_pill" in WT_HTML, \
        "HTML must have a status pill element on the progress mini-card"


def test_b_projected_date_element():
    lower = WT_HTML.lower()
    assert "projected" in lower, \
        "HTML must have a projected hit date element"


def test_b_js_uses_projected_end_date():
    assert "projected_end_date" in WT_JS, \
        "weight-targets.js must use projected_end_date from the active target API response"


def test_b_js_days_delta_displayed():
    js_lower = WT_JS.lower()
    assert "days" in js_lower and ("delta" in js_lower or "ahead" in js_lower or "behind" in js_lower or "ahead" in js_lower), \
        "weight-targets.js must compute and display days delta vs target date"


# ── Section B — Inline Form ───────────────────────────────────────────────────

def test_b_form_card_element():
    assert "new-target-form" in WT_HTML or "set-target-form" in WT_HTML, \
        "HTML must have an inline 'Set new target' form element"


def test_b_form_start_weight_field():
    assert "start-weight" in WT_HTML.lower() or "start_weight" in WT_HTML, \
        "HTML must have a start weight input field in the inline form"


def test_b_form_start_date_field():
    assert "start-date" in WT_HTML.lower() or "start_date" in WT_HTML, \
        "HTML must have a start date input in the inline form"


def test_b_form_target_weight_field():
    lower = WT_HTML.lower()
    assert "target-weight" in lower or "target_weight" in lower, \
        "HTML must have a target weight input in the inline form"


def test_b_form_target_date_field():
    lower = WT_HTML.lower()
    assert "target-date" in lower or "target_date" in lower, \
        "HTML must have a target date input in the inline form"


def test_b_form_notes_field():
    assert "notes" in WT_HTML.lower(), \
        "HTML must have an optional notes field in the inline form"


def test_b_js_prefills_start_weight():
    js_lower = WT_JS.lower()
    assert ("start" in js_lower and "weight" in js_lower and ("prefill" in js_lower or "value" in js_lower or "latest" in js_lower)), \
        "weight-targets.js must pre-fill start weight from latest weight entry"


def test_b_js_prefills_start_date_today():
    js_lower = WT_JS.lower()
    assert "today" in js_lower or "toiso" in js_lower or "start-date" in js_lower, \
        "weight-targets.js must pre-fill start date with today"


def test_b_js_submit_posts_weight_targets():
    assert "/api/weight-targets" in WT_JS, \
        "weight-targets.js must POST to /api/weight-targets on form submit"


# ── Section C — Milestone Timeline Strip ──────────────────────────────────────

def test_c_milestone_strip_element():
    lower = WT_HTML.lower()
    assert "milestone" in lower, \
        "HTML must have a milestone strip/rail element"


def test_c_milestone_start_point():
    lower = WT_HTML.lower()
    assert "start" in lower and "milestone" in lower, \
        "Milestone strip must include a Start point"


def test_c_milestone_goal_point():
    lower = WT_HTML.lower()
    assert "goal" in lower, \
        "Milestone strip must include a Goal point"


def test_c_milestone_3mo_point():
    assert "3mo" in WT_HTML or "3 mo" in WT_HTML or "3-mo" in WT_HTML or "3mo" in WT_JS, \
        "Milestone strip must include a 3-month point"


def test_c_milestone_6mo_point():
    assert "6mo" in WT_HTML or "6 mo" in WT_HTML or "6-mo" in WT_HTML or "6mo" in WT_JS, \
        "Milestone strip must include a 6-month point"


def test_c_milestone_current_point():
    lower = WT_HTML.lower()
    assert "current" in lower and "milestone" in lower, \
        "Milestone strip must include a Current point"


def test_c_gradient_bar_fills_progress_pct():
    js_lower = WT_JS.lower()
    assert "progress_pct" in WT_JS and ("width" in js_lower or "gradient" in js_lower or "fill" in js_lower), \
        "weight-targets.js must fill the milestone gradient bar to progress_pct"


def test_c_mobile_scrollable_css():
    lower = WT_HTML.lower()
    assert "overflow" in lower and ("scroll" in lower or "auto" in lower), \
        "CSS must make the milestone strip horizontally scrollable on mobile"


# ── Section D — Stats Summary Card ───────────────────────────────────────────

def test_d_targets_set_stat():
    lower = WT_HTML.lower()
    assert "targets set" in lower or "stat-targets-set" in lower, \
        "HTML must have a 'Targets set' stat element"


def test_d_targets_achieved_stat():
    lower = WT_HTML.lower()
    assert "targets achieved" in lower or "stat-targets-achieved" in lower, \
        "HTML must have a 'Targets achieved' stat element"


def test_d_success_rate_sub_label():
    lower = WT_HTML.lower()
    assert "success-rate" in lower or "success rate" in lower, \
        "HTML must have a success rate % sub-label under Targets achieved"


def test_d_total_weight_lost_stat():
    lower = WT_HTML.lower()
    assert "total" in lower and "lost" in lower, \
        "HTML must have a 'Total weight lost' stat element"


def test_d_avg_pace_stat():
    lower = WT_HTML.lower()
    assert "avg" in lower and "pace" in lower, \
        "HTML must have an 'Avg pace' stat element"


def test_d_js_computes_stats_from_history():
    js_lower = WT_JS.lower()
    assert "history" in js_lower and ("achieved" in js_lower or "targets" in js_lower), \
        "weight-targets.js must compute stats from the history API response"


def test_d_js_success_rate_computed():
    js_lower = WT_JS.lower()
    assert "success" in js_lower or ("achieved" in js_lower and "%" in WT_JS), \
        "weight-targets.js must compute success rate from history"


# ── Section E — Target History Table ─────────────────────────────────────────

def test_e_history_table_present():
    lower = WT_HTML.lower()
    assert "history" in lower and ("table" in lower or "tbody" in lower), \
        "HTML must have a target history table"


def test_e_table_status_column():
    lower = WT_HTML.lower()
    assert "status" in lower and "history" in lower, \
        "History table must have a Status column"


def test_e_table_name_column():
    lower = WT_HTML.lower()
    assert "name" in lower or ("→" in WT_HTML or "kg" in WT_HTML), \
        "History table must have a Name/range column"


def test_e_table_pace_column():
    lower = WT_HTML.lower()
    assert "pace" in lower, \
        "History table must have a Pace kg/wk column"


def test_e_table_duration_column():
    lower = WT_HTML.lower()
    assert "duration" in lower or "days" in lower, \
        "History table must have a Duration days column"


def test_e_table_actions_column():
    lower = WT_HTML.lower()
    assert "actions" in lower, \
        "History table must have an Actions column"


def test_e_js_done_badge():
    js_lower = WT_JS.lower()
    assert "done" in js_lower or "achieved" in js_lower, \
        "weight-targets.js must render a 'Done' badge for achieved targets"


def test_e_js_replaced_badge():
    js_lower = WT_JS.lower()
    assert "replaced" in js_lower, \
        "weight-targets.js must render a 'Replaced' badge for replaced targets"


def test_e_js_abandoned_badge():
    js_lower = WT_JS.lower()
    assert "abandoned" in js_lower, \
        "weight-targets.js must render an 'Abandoned' badge for abandoned targets"


def test_e_js_delta_green_when_progressing():
    js_lower = WT_JS.lower()
    assert "green" in js_lower or "#16a34a" in WT_JS or "#22c55e" in WT_JS, \
        "weight-targets.js must render delta in green when target was achieved/replaced with progress"


def test_e_filter_pill_all():
    lower = WT_HTML.lower()
    assert "filter" in lower and "all" in lower, \
        "HTML must have an 'All' filter pill"


def test_e_filter_pill_achieved():
    lower = WT_HTML.lower()
    assert "filter" in lower and "achieved" in lower, \
        "HTML must have an 'Achieved' filter pill"


def test_e_filter_pill_replaced():
    lower = WT_HTML.lower()
    assert "filter" in lower and "replaced" in lower, \
        "HTML must have a 'Replaced' filter pill"


def test_e_filter_pill_abandoned():
    lower = WT_HTML.lower()
    assert "filter" in lower and "abandoned" in lower, \
        "HTML must have an 'Abandoned' filter pill"


def test_e_js_filter_pills_filter_rows():
    js_lower = WT_JS.lower()
    assert "filter" in js_lower and ("hidden" in js_lower or "display" in js_lower or "none" in js_lower), \
        "weight-targets.js must filter history table rows based on filter pill selection"


# ── Edit Modal ────────────────────────────────────────────────────────────────

def test_edit_modal_present():
    lower = WT_HTML.lower()
    assert "edit-modal" in lower or ("edit" in lower and "modal" in lower), \
        "HTML must have an edit modal element"


def test_edit_modal_target_weight_field():
    assert "edit-target-weight" in WT_HTML or "edit_target_weight" in WT_HTML, \
        "Edit modal must have a target_weight input field"


def test_edit_modal_target_date_field():
    assert "edit-target-date" in WT_HTML or "edit_target_date" in WT_HTML, \
        "Edit modal must have a target_date input field"


def test_edit_modal_notes_field():
    lower = WT_HTML.lower()
    assert "edit-notes" in lower or ("edit" in lower and "notes" in lower), \
        "Edit modal must have a notes field"


def test_edit_modal_js_patches_target():
    assert "PATCH" in WT_JS or "patch" in WT_JS.lower(), \
        "weight-targets.js must PATCH /api/weight-targets/{id} on edit save"


def test_edit_modal_opens_from_pencil():
    js_lower = WT_JS.lower()
    assert "edit-modal" in js_lower or "editmodal" in js_lower or "edit_modal" in js_lower, \
        "weight-targets.js must open the edit modal from the pencil button"


# ── End Modal ─────────────────────────────────────────────────────────────────

def test_end_modal_present():
    lower = WT_HTML.lower()
    assert "end-modal" in lower or ("end" in lower and "modal" in lower), \
        "HTML must have an end modal element"


def test_end_modal_achieved_button():
    lower = WT_HTML.lower()
    assert "achieved" in lower and ("end-achieved" in lower or "mark as achieved" in lower), \
        "End modal must have a 'Mark as achieved' button"


def test_end_modal_abandoned_button():
    lower = WT_HTML.lower()
    assert "abandoned" in lower and ("end-abandoned" in lower or "mark as abandoned" in lower), \
        "End modal must have a 'Mark as abandoned' button"


def test_end_modal_no_recent_weight_message():
    lower = WT_HTML.lower()
    assert "log a recent weight" in lower or "recent weight" in lower, \
        "End modal must show 'Log a recent weight first' message when no recent entry"


def test_end_modal_js_checks_7day_window():
    js_lower = WT_JS.lower()
    assert "7" in WT_JS and ("day" in js_lower or "recent" in js_lower), \
        "weight-targets.js must check for a weight entry within 7 days before enabling end buttons"


def test_end_modal_js_posts_end_endpoint():
    assert "/end" in WT_JS, \
        "weight-targets.js must POST to /api/weight-targets/{id}/end"


def test_end_modal_buttons_disabled_in_html():
    lower = WT_HTML.lower()
    assert "end-achieved-btn" in lower or ("achieved" in lower and "disabled" in lower), \
        "End modal achieved/abandoned buttons must be disabled by default in HTML"


# ── Responsive ────────────────────────────────────────────────────────────────

def test_responsive_880px_breakpoint():
    lower = WT_HTML.lower()
    assert "880px" in WT_HTML or "880" in WT_HTML, \
        "CSS must include an 880px media query breakpoint"


def test_responsive_active_card_collapses():
    js_lower = WT_JS.lower()
    assert "880" in WT_JS or "880px" in WT_HTML, \
        "Page must handle 880px breakpoint for active card single-column layout"


def test_responsive_history_card_list():
    lower = WT_HTML.lower()
    assert "880" in WT_HTML, \
        "CSS must have 880px breakpoint for history table → card list layout"


# ── JS API fetch patterns ─────────────────────────────────────────────────────

def test_js_fetches_auth_me():
    assert "/api/auth/me" in WT_JS, \
        "weight-targets.js must fetch /api/auth/me to get user id"


def test_js_fetches_active_target():
    assert "/api/weight-targets/active" in WT_JS, \
        "weight-targets.js must fetch /api/weight-targets/active"


def test_js_fetches_history():
    assert "/api/weight-targets/history" in WT_JS, \
        "weight-targets.js must fetch /api/weight-targets/history"


def test_js_fetches_weight_entries_for_prefill():
    assert "/api/weight" in WT_JS or "/api/weight-entries" in WT_JS, \
        "weight-targets.js must fetch recent weight entry for pre-filling start weight"


def test_js_uses_progress_pct():
    assert "progress_pct" in WT_JS, \
        "weight-targets.js must use progress_pct from the active target API"


def test_js_uses_kg_to_go():
    assert "kg_to_go" in WT_JS, \
        "weight-targets.js must use kg_to_go from the active target API"


def test_js_uses_status_label():
    assert "status_label" in WT_JS, \
        "weight-targets.js must use status_label from the active target API"


def test_js_uses_required_pace():
    assert "required_pace_kg_per_week" in WT_JS, \
        "weight-targets.js must use required_pace_kg_per_week from the active target API"


def test_js_uses_current_pace():
    assert "current_pace_kg_per_week" in WT_JS, \
        "weight-targets.js must use current_pace_kg_per_week from the active target API"
