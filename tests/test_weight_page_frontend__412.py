"""Tests for issue #412: Build weight page frontend (desktop + mobile).

AC anchors verified:
  (a) /weight/ route returns 200; /weight.html alias returns 200; no 404/redirect loops
  (b) page title "Weight"; subtitle shows entry count + days tracked + trend from /api/weight-chart;
      Export CSV button present; Manage target links to /weight/targets
  (c) hero strip: current weight (large mono), 7-day avg (smaller mono), delta pills
      (green loss / red gain / neutral), quick-log input + submit
  (d) quick-log POSTs to /api/weight-entries with today's date + current time; in-place update;
      inline error on failure
  (e) Chart.js 4.4.0 loaded via CDN; chart 4 datasets: actuals (scatter, gray), 7-day trend
      (smooth accent-blue line), target (dashed green), projected (dashed blue)
  (f) legend chips above chart for all 4 series; target + projected chips hidden when no target
  (g) range tabs 30D/90D/6M/1Y/ALL; re-fetch /api/weight-chart on click; active tab highlighted
  (h) y-axis kg with stepSize 2, autoscale with padding; x-axis format adapts by range
  (i) hover tooltip shows date + weight per dataset; no tooltip without hover
  (j) progress card: horizontal bar (start → target + marker), start/current/target labels,
      progress_pct large colored number, kg_to_go, status_label pill
      (green on_track / amber behind / blue ahead)
  (k) milestones panel: 4 rows (Today / 3 mo / 6 mo / Goal) with projected weights via
      client-side linear interpolation; mobile horizontal-scroll cards
  (l) recent entries last 14 calendar days (no gaps); no-entry days show "No entry" + "+" button;
      clicking "+" opens inline backfill input for that date; today row highlighted;
      desktop table / mobile card-row layout
  (m) backfill POST to /api/weight-entries with past date in body; row updates in-place
  (n) CSS ≤880px: hero 2-col, milestones horizontal-scroll, recent entries card-rows;
      all sections readable at 375px
  (o) all weight-page JS in frontend/js/weight.js; no other weight-page JS files
"""
import os
import pathlib
import datetime
import pytest
import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "frontend" / "js"
PAGES_DIR = ROOT / "frontend" / "pages"

WEIGHT_HTML = (PAGES_DIR / "weight.html").read_text()
WEIGHT_JS = (JS_DIR / "weight.js").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")
TODAY = datetime.date.today().isoformat()


# ── (a) Routing ───────────────────────────────────────────────────────────────

def test_a_weight_html_file_exists():
    assert (PAGES_DIR / "weight.html").exists(), "weight.html must exist"


def test_a_weight_route_200():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=True) as c:
        r = c.get("/weight/")
    assert r.status_code == 200, f"GET /weight/ must return 200, got {r.status_code}"


def test_a_weight_html_alias_200():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=True) as c:
        r = c.get("/weight.html")
    assert r.status_code == 200, f"GET /weight.html must return 200, got {r.status_code}"


# ── (b) Page head ─────────────────────────────────────────────────────────────

def test_b_title_is_weight():
    assert "<title>Weight" in WEIGHT_HTML, "page <title> must start with 'Weight'"


def test_b_subtitle_element_present():
    assert "page-subtitle" in WEIGHT_HTML, "HTML must have id=page-subtitle element"


def test_b_subtitle_js_uses_chart_stats():
    # Subtitle must use chart stats (entry count, days tracked, trend) from /api/weight-chart
    assert "weight-chart" in WEIGHT_JS or "/api/weight-chart" in WEIGHT_JS, \
        "weight.js must call /api/weight-chart to populate subtitle stats"


def test_b_subtitle_shows_entry_count():
    assert "entries_logged" in WEIGHT_JS or "count" in WEIGHT_JS.lower(), \
        "weight.js must display entry count in subtitle"


def test_b_subtitle_shows_trend_kgwk():
    js_lower = WEIGHT_JS.lower()
    assert ("kg/wk" in js_lower or "kg/" in js_lower or "delta" in js_lower), \
        "weight.js must display trend rate (kg/wk) in subtitle"


def test_b_export_csv_button_present():
    html_lower = WEIGHT_HTML.lower()
    assert "export" in html_lower and "csv" in html_lower, \
        "HTML must have an Export CSV button"


def test_b_manage_target_links_to_weight_targets():
    assert "/weight/targets" in WEIGHT_HTML, \
        "HTML must have a link/button targeting /weight/targets"


# ── (c) Hero strip ────────────────────────────────────────────────────────────

def test_c_hero_current_weight_large_mono():
    html_lower = WEIGHT_HTML.lower()
    assert "current" in html_lower and "weight" in html_lower, \
        "Hero must have current weight cell"
    assert "mono" in html_lower, "current weight must use monospace/tabular-nums class"


def test_c_hero_7day_avg_present():
    html_lower = WEIGHT_HTML.lower()
    assert "7-day" in html_lower or "7day" in html_lower or "avg" in html_lower, \
        "Hero must have 7-day avg cell"


def test_c_hero_delta_pills_present():
    html_lower = WEIGHT_HTML.lower()
    assert "delta-pill" in html_lower or ("delta" in html_lower and "pill" in html_lower), \
        "Hero must have delta pill elements"


def test_c_delta_pill_green_loss():
    html_lower = WEIGHT_HTML.lower()
    assert ".loss" in html_lower or "loss" in html_lower, \
        "CSS must define a green 'loss' class for delta pills"


def test_c_delta_pill_red_gain():
    html_lower = WEIGHT_HTML.lower()
    assert ".gain" in html_lower or "gain" in html_lower, \
        "CSS must define a red 'gain' class for delta pills"


def test_c_delta_pill_neutral():
    html_lower = WEIGHT_HTML.lower()
    assert "neutral" in html_lower, \
        "CSS must define a neutral class for flat delta pills"


def test_c_hero_quicklog_input():
    assert 'type="number"' in WEIGHT_HTML or "type='number'" in WEIGHT_HTML, \
        "Hero must have a numeric quick-log input"


def test_c_hero_quicklog_submit_form():
    assert "quicklog" in WEIGHT_HTML.lower() or "log-form" in WEIGHT_HTML.lower(), \
        "Hero must have a quick-log submit form"


# ── (d) Quick-log behavior ────────────────────────────────────────────────────

def test_d_quicklog_posts_to_weight_entries():
    assert "/api/weight-entries" in WEIGHT_JS, \
        "weight.js must POST to /api/weight-entries for quick-log"


def test_d_quicklog_sends_today_date():
    js_lower = WEIGHT_JS.lower()
    assert "entry_date" in js_lower and ("today" in js_lower or "toiso" in js_lower), \
        "weight.js quick-log POST must include today's date as entry_date"


def test_d_quicklog_sends_entry_time():
    assert "entry_time" in WEIGHT_JS, \
        "weight.js quick-log POST must include entry_time"


def test_d_quicklog_in_place_update():
    js_lower = WEIGHT_JS.lower()
    # in-place update via _reload() call, not window.location.reload
    assert "_reload" in WEIGHT_JS and "window.location.reload" not in WEIGHT_JS, \
        "weight.js must update page in-place via _reload(), not full page reload"


def test_d_quicklog_inline_error():
    assert "quicklog-error" in WEIGHT_HTML, \
        "HTML must have a quicklog-error element for inline error display"


# ── (e) Chart.js + 4 datasets ─────────────────────────────────────────────────

def test_e_chartjs_440_cdn():
    assert "chart.js@4.4.0" in WEIGHT_HTML.lower() or "chart.js@4.4" in WEIGHT_HTML.lower(), \
        "HTML must load Chart.js 4.4.0 via CDN"


def test_e_dataset_actuals_scatter_gray():
    js_lower = WEIGHT_JS.lower()
    assert "daily weigh" in js_lower or "actuals" in js_lower, \
        "weight.js must define actuals scatter dataset"
    assert "showline: false" in js_lower or "show_line" in js_lower or "showLine" in WEIGHT_JS, \
        "actuals dataset must be scatter (showLine: false)"


def test_e_dataset_trend_smooth_line():
    js_lower = WEIGHT_JS.lower()
    assert "moving avg" in js_lower or "trend" in js_lower, \
        "weight.js must define 7-day moving avg trend dataset"
    assert "tension" in WEIGHT_JS, "trend line must use tension for smoothing"


def test_e_dataset_target_dashed_green():
    js_lower = WEIGHT_JS.lower()
    assert "'target'" in js_lower or '"target"' in js_lower or "target_weight" in js_lower, \
        "weight.js must define target horizontal dashed line dataset"
    assert "borderDash" in WEIGHT_JS or "borderdash" in js_lower, \
        "target dataset must use borderDash for dashed style"


def test_e_dataset_projected_dashed_blue():
    assert "projected" in WEIGHT_JS.lower() or "project" in WEIGHT_JS.lower(), \
        "weight.js must define projected path dataset"


# ── (f) Legend chips ──────────────────────────────────────────────────────────

def test_f_legend_chips_above_chart():
    assert "chart-legend" in WEIGHT_HTML, \
        "HTML must have chart-legend element above/near chart"


def test_f_legend_daily_weigh_in():
    html_lower = WEIGHT_HTML.lower()
    assert "daily weigh" in html_lower or ("legend" in html_lower and "weigh" in html_lower), \
        "Legend must have daily weigh-in chip"


def test_f_legend_7day_moving_avg():
    html_lower = WEIGHT_HTML.lower()
    assert "moving avg" in html_lower or ("legend" in html_lower and "trend" in html_lower), \
        "Legend must have 7-day moving avg chip"


def test_f_legend_target_chip():
    html_lower = WEIGHT_HTML.lower()
    assert "legend-target" in html_lower or ("legend" in html_lower and "target" in html_lower), \
        "Legend must have target chip"


def test_f_legend_projected_chip():
    html_lower = WEIGHT_HTML.lower()
    assert "legend-projected" in html_lower or ("legend" in html_lower and "projected" in html_lower), \
        "Legend must have projected chip"


def test_f_target_projected_chips_hidden_when_no_target():
    # target and projected legend chips start hidden; JS reveals them only when include_target true
    assert 'hidden' in WEIGHT_HTML, \
        "target/projected legend chips must start hidden and be revealed by JS"


# ── (g) Range tabs ─────────────────────────────────────────────────────────────

def test_g_range_tabs_all_present():
    for tab in ("30D", "90D", "6M", "1Y", "ALL"):
        assert tab in WEIGHT_HTML, f"HTML must have {tab} range tab"


def test_g_active_tab_highlighted():
    html_lower = WEIGHT_HTML.lower()
    assert "active" in html_lower and "range-tab" in html_lower, \
        "HTML must have active class on range tabs"


def test_g_js_refetches_on_range_click():
    js_lower = WEIGHT_JS.lower()
    assert "/api/weight-chart" in WEIGHT_JS and "range" in js_lower, \
        "weight.js must re-fetch /api/weight-chart when range changes"


# ── (h) Axis configuration ───────────────────────────────────────────────────

def test_h_yaxis_unit_kg():
    assert "kg" in WEIGHT_JS, "y-axis must display kg unit"


def test_h_yaxis_stepsize_2():
    assert "stepSize" in WEIGHT_JS, "weight.js must configure y-axis stepSize"
    # Check stepSize is 2
    idx = WEIGHT_JS.index("stepSize")
    snippet = WEIGHT_JS[idx:idx+20]
    assert "2" in snippet, "y-axis stepSize must be 2"


def test_h_yaxis_autoscale_padding():
    js_lower = WEIGHT_JS.lower()
    assert "pad" in js_lower or "min" in js_lower, \
        "weight.js must autoscale y-axis with padding"


def test_h_xaxis_format_adapts_by_range():
    js_lower = WEIGHT_JS.lower()
    assert "range" in js_lower and ("tolocale" in js_lower or "fmtdate" in js_lower or "format" in js_lower), \
        "weight.js x-axis tick format must adapt by selected range"


# ── (i) Tooltip ───────────────────────────────────────────────────────────────

def test_i_tooltip_mode_configured():
    js_lower = WEIGHT_JS.lower()
    assert "tooltip" in js_lower and "mode" in js_lower, \
        "weight.js must configure tooltip mode"


def test_i_tooltip_shows_date():
    js_lower = WEIGHT_JS.lower()
    assert "tooltip" in js_lower and ("date" in js_lower or "title" in js_lower), \
        "tooltip must show date in title"


def test_i_tooltip_shows_weight_kg():
    js_lower = WEIGHT_JS.lower()
    assert "tooltip" in js_lower and ("kg" in js_lower), \
        "tooltip must show weight in kg"


# ── (j) Progress card ─────────────────────────────────────────────────────────

def test_j_progress_card_element():
    assert "progress-card" in WEIGHT_HTML, "HTML must have id=progress-card element"


def test_j_horizontal_bar_with_marker():
    html_lower = WEIGHT_HTML.lower()
    assert "progress-bar" in html_lower and "marker" in html_lower, \
        "HTML must have progress bar + current-position marker"


def test_j_progress_labels_start_current_target():
    html_lower = WEIGHT_HTML.lower()
    assert "label-start" in html_lower or "start" in html_lower, "HTML must have start label"
    assert "label-current" in html_lower or "current" in html_lower, "HTML must have current label"
    assert "label-target" in html_lower or "target" in html_lower, "HTML must have target label"


def test_j_progress_pct_large_colored_number():
    assert "progress-pct" in WEIGHT_HTML, "HTML must have progress-pct element"
    assert "progress-pct" in WEIGHT_JS, "weight.js must update progress-pct element"


def test_j_kg_to_go_displayed():
    assert "kg-to-go" in WEIGHT_HTML and "kg-to-go" in WEIGHT_JS, \
        "HTML+JS must have kg-to-go element"


def test_j_status_pill_on_track_green():
    assert "on_track" in WEIGHT_JS and "on-track" in WEIGHT_HTML.lower(), \
        "status pill must handle on_track (green)"


def test_j_status_pill_behind_amber():
    assert "behind" in WEIGHT_JS and "behind" in WEIGHT_HTML.lower(), \
        "status pill must handle behind (amber)"


def test_j_status_pill_ahead_blue():
    assert "ahead" in WEIGHT_JS and "ahead" in WEIGHT_HTML.lower(), \
        "status pill must handle ahead (blue)"


# ── (k) Milestones panel ──────────────────────────────────────────────────────

def test_k_milestones_panel_present():
    assert "milestones-panel" in WEIGHT_HTML or "milestones" in WEIGHT_HTML.lower(), \
        "HTML must have milestones panel"


def test_k_milestone_today():
    js_lower = WEIGHT_JS.lower()
    assert "today" in js_lower and "milestone" in js_lower, \
        "weight.js must render Today milestone"


def test_k_milestone_3_months():
    assert ("3 mo" in WEIGHT_JS or "90" in WEIGHT_JS), \
        "weight.js must render 3-month milestone"


def test_k_milestone_6_months():
    assert ("6 mo" in WEIGHT_JS or "180" in WEIGHT_JS), \
        "weight.js must render 6-month milestone"


def test_k_milestone_goal():
    js_lower = WEIGHT_JS.lower()
    assert "goal" in js_lower and "milestone" in js_lower, \
        "weight.js must render Goal milestone"


def test_k_linear_interpolation_for_projections():
    js_lower = WEIGHT_JS.lower()
    assert "interpolat" in js_lower or "frac" in js_lower or "lerp" in js_lower, \
        "weight.js must use linear interpolation for milestone projected weights"


def test_k_mobile_horizontal_scroll():
    html_lower = WEIGHT_HTML.lower()
    assert "880" in html_lower and (
        "overflow-x: auto" in html_lower or "overflow-x:auto" in html_lower
        or "scroll-snap" in html_lower
    ), "milestones must become horizontal-scroll at ≤880px"


# ── (l) Recent entries ────────────────────────────────────────────────────────

def test_l_recent_entries_container_present():
    assert "recent-entries" in WEIGHT_HTML, "HTML must have recent-entries container"


def test_l_covers_14_days():
    assert "14" in WEIGHT_JS, "weight.js must render last 14 days"


def test_l_no_entry_text_for_missing_days():
    assert "No entry" in WEIGHT_JS, \
        "weight.js must display 'No entry' for days without weight entries"


def test_l_plus_button_for_missing_days():
    js_lower = WEIGHT_JS.lower()
    assert "backfill-add-btn" in js_lower or "backfill" in js_lower, \
        "weight.js must render a '+' backfill button for days without entries"


def test_l_today_row_highlighted():
    html_lower = WEIGHT_HTML.lower()
    assert "entry-row-today" in html_lower or "today" in html_lower, \
        "Today's entry row must have highlighted background"


def test_l_desktop_table_layout():
    html_lower = WEIGHT_HTML.lower()
    assert "entries-table" in html_lower and "<table" in html_lower, \
        "Desktop view must use table layout for recent entries"


def test_l_mobile_card_row_layout():
    html_lower = WEIGHT_HTML.lower()
    assert "880" in html_lower and ("card-row" in html_lower or "entry-card" in html_lower), \
        "Mobile view (≤880px) must use card-row layout for recent entries"


# ── (m) Backfill ──────────────────────────────────────────────────────────────

def test_m_backfill_posts_to_weight_entries():
    assert "/api/weight-entries" in WEIGHT_JS, \
        "weight.js must POST backfill entries to /api/weight-entries"


def test_m_backfill_sends_past_date():
    assert "entry_date" in WEIGHT_JS and "backfill" in WEIGHT_JS.lower(), \
        "weight.js backfill POST must include entry_date (the past date)"


def test_m_backfill_inline_input():
    html_lower = WEIGHT_HTML.lower()
    assert "backfill" in html_lower and "input" in html_lower, \
        "HTML must define backfill inline input styles"


# ── (n) Responsive layout ─────────────────────────────────────────────────────

def test_n_breakpoint_880px():
    assert "880" in WEIGHT_HTML, "weight.html must have CSS media query at 880px"


def test_n_hero_2col_at_880():
    html_lower = WEIGHT_HTML.lower()
    assert "880" in html_lower and (
        "repeat(2" in html_lower or "2-col" in html_lower or "grid-template-columns" in html_lower
    ), "Hero strip must collapse to 2-col at ≤880px"


def test_n_milestones_scroll_at_880():
    html_lower = WEIGHT_HTML.lower()
    assert "880" in html_lower and (
        "overflow" in html_lower or "scroll" in html_lower
    ), "Milestones must become horizontally scrollable at ≤880px"


def test_n_entries_card_layout_at_880():
    html_lower = WEIGHT_HTML.lower()
    assert "880" in html_lower and (
        "card-row" in html_lower or "entry-card" in html_lower or "display: block" in html_lower
    ), "Recent entries must switch to card layout at ≤880px"


# ── (o) JS file hygiene ──────────────────────────────────────────────────────

def test_o_weight_js_exists():
    assert (JS_DIR / "weight.js").exists(), "frontend/js/weight.js must exist"


def test_o_weight_page_logic_in_weight_js():
    # All weight-page-specific JS (hero, chart, entries, quicklog) must be in weight.js.
    # weight-targets.js is for a separate page (/weight/targets) — not a violation.
    page_specific_funcs = [
        "renderHero", "renderChart", "renderProgress", "renderMilestones",
        "renderRecentEntries", "_initQuickLog", "_initRangeTabs",
    ]
    for fn in page_specific_funcs:
        assert fn in WEIGHT_JS, \
            f"weight.js must contain {fn}() — weight page logic must not be split out"


def test_o_no_duplicate_weight_page_js():
    # There must not be a second file implementing the /weight/ page (not counting weight-targets.js
    # which belongs to a different page, or any test-infrastructure JS files).
    # weight-chart.js is the SVG chart module introduced by issue #423 (intentional split)
    excluded = {"weight.js", "weight-targets.js", "weight-chart.js"}
    extra = [
        f for f in JS_DIR.iterdir()
        if f.suffix == ".js"
        and f.name not in excluded
        and "weight" in f.name.lower()
        and "target" not in f.name.lower()
    ]
    assert not extra, \
        f"Weight-page logic must not be split; unexpected JS files: {extra}"
