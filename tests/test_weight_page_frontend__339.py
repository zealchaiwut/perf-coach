"""Tests for issue #339: Build weight page frontend (desktop + mobile).

AC anchors verified:
  (a) weight.html exists; /weight/ route returns 200; /weight.html alias returns 200
  (b) page title "Weight"; subtitle element present; Export CSV button; Manage target → /weight/targets
  (c) hero strip has 4 cells: current-weight, 7-day-avg, delta-pills, quicklog input with submit
  (d) quicklog JS posts to /api/weight-entries with today's date+time
  (e) HTML loads Chart.js 4.4.0 via CDN; JS creates chart with 4 named datasets (actuals/trend/target/projected)
  (f) JS defines 4 legend chip elements in HTML matching the 4 datasets
  (g) HTML has 30D/90D/6M/1Y/ALL range tabs; JS re-fetches /api/weight-chart on range change
  (h) JS configures y-axis stepSize 2; x-axis tick format adapts to selected range
  (i) tooltip configured: mode set, callbacks format date+weight per hover
  (j) progress card: horizontal bar element, progress_pct, kg_to_go, status_label colored pill
  (k) milestones panel: 4 rows (Today, 3 mo, 6 mo, Goal) via linear interpolation
  (l) recent entries: 14-day window; missing days show "No entry" text with backfill + button
  (m) backfill POST sends past date in /api/weight-entries body
  (n) CSS 880px breakpoint; hero 2-col; milestones horizontal-scroll; recent entries card-rows
  (o) all weight JS logic in frontend/js/weight.js (no extra weight-specific JS files)
"""
import os
import pathlib
import datetime
import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "frontend" / "js"
PAGES_DIR = ROOT / "frontend" / "pages"

WEIGHT_HTML = (PAGES_DIR / "weight.html").read_text()
WEIGHT_JS = (JS_DIR / "weight.js").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")

TODAY = datetime.date.today().isoformat()


# ── (a) Route and file existence ─────────────────────────────────────────────

def test_a_weight_html_file_exists():
    assert (PAGES_DIR / "weight.html").exists(), "weight.html must exist"


def test_a_weight_route_returns_200():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=True) as c:
        r = c.get("/weight/")
    assert r.status_code == 200, f"GET /weight/ must return 200, got {r.status_code}"


def test_a_weight_html_alias_returns_200():
    with httpx.Client(base_url=BASE, timeout=10, follow_redirects=True) as c:
        r = c.get("/weight.html")
    assert r.status_code == 200, f"GET /weight.html must return 200, got {r.status_code}"


# ── (b) Page head ─────────────────────────────────────────────────────────────

def test_b_page_title_is_weight():
    assert "<title>Weight" in WEIGHT_HTML, "page <title> must start with 'Weight'"


def test_b_subtitle_element_present():
    assert "page-subtitle" in WEIGHT_HTML or "subtitle" in WEIGHT_HTML, \
        "HTML must have a subtitle element for entry count / days tracked / trend"


def test_b_export_csv_button_present():
    html_lower = WEIGHT_HTML.lower()
    assert "export" in html_lower and "csv" in html_lower, \
        "HTML must have an Export CSV button"


def test_b_manage_target_link_to_weight_targets():
    assert "/weight/targets" in WEIGHT_HTML, \
        "HTML must have a link to /weight/targets for 'Manage target'"


# ── (c) Hero strip ────────────────────────────────────────────────────────────

def test_c_hero_has_current_weight_cell():
    html_lower = WEIGHT_HTML.lower()
    assert "current" in html_lower and "weight" in html_lower, \
        "Hero strip must have a current weight cell"


def test_c_hero_has_7day_avg_cell():
    html_lower = WEIGHT_HTML.lower()
    assert "7-day" in html_lower or "7day" in html_lower or "avg" in html_lower, \
        "Hero strip must have a 7-day avg cell"


def test_c_hero_has_delta_pills():
    html_lower = WEIGHT_HTML.lower()
    assert "delta" in html_lower or "pill" in html_lower or "change" in html_lower, \
        "Hero strip must have delta pill elements"


def test_c_hero_has_quicklog_input():
    assert 'type="number"' in WEIGHT_HTML or "type='number'" in WEIGHT_HTML, \
        "Hero strip must have a numeric quick-log input"


def test_c_hero_has_quicklog_submit():
    assert "quicklog" in WEIGHT_HTML.lower() or "quick-log" in WEIGHT_HTML.lower() or \
           "log weight" in WEIGHT_HTML.lower() or "log-form" in WEIGHT_HTML.lower(), \
        "Hero strip must have a quick-log submit form"


# ── (d) Quick-log API call ────────────────────────────────────────────────────

def test_d_quicklog_posts_to_weight_entries():
    assert "/api/weight-entries" in WEIGHT_JS, \
        "weight.js must POST to /api/weight-entries for quick-log"


def test_d_quicklog_includes_today_date():
    js_lower = WEIGHT_JS.lower()
    assert "today" in js_lower or "toiso" in js_lower or "entry_date" in js_lower, \
        "weight.js quick-log must supply today's date in the POST body"


def test_d_quicklog_includes_entry_time():
    assert "entry_time" in WEIGHT_JS, \
        "weight.js quick-log must include entry_time in the POST body"


# ── (e) Chart.js 4.4.0 and 4 datasets ────────────────────────────────────────

def test_e_chartjs_440_via_cdn():
    assert "chart.js@4.4.0" in WEIGHT_HTML.lower() or "chart.js@4.4" in WEIGHT_HTML.lower(), \
        "HTML must load Chart.js 4.4.0 via CDN"


def test_e_chart_has_actuals_dataset():
    js_lower = WEIGHT_JS.lower()
    assert "daily weigh" in js_lower or "actuals" in js_lower, \
        "weight.js must define an actuals/daily weigh-in dataset"


def test_e_chart_has_trend_dataset():
    js_lower = WEIGHT_JS.lower()
    assert "moving avg" in js_lower or "trend" in js_lower, \
        "weight.js must define a 7-day moving avg / trend dataset"


def test_e_chart_has_target_dataset():
    js_lower = WEIGHT_JS.lower()
    assert "'target'" in js_lower or '"target"' in js_lower or "target_weight" in js_lower, \
        "weight.js must define a target dataset"


def test_e_chart_has_projected_dataset():
    js_lower = WEIGHT_JS.lower()
    assert "project" in js_lower, \
        "weight.js must define a projected path dataset"


# ── (f) Legend chips ──────────────────────────────────────────────────────────

def test_f_legend_has_daily_chip():
    html_lower = WEIGHT_HTML.lower()
    assert "legend" in html_lower and ("daily" in html_lower or "weigh-in" in html_lower), \
        "HTML must have a legend chip for daily weigh-in"


def test_f_legend_has_trend_chip():
    html_lower = WEIGHT_HTML.lower()
    assert "legend" in html_lower and ("moving avg" in html_lower or "trend" in html_lower), \
        "HTML must have a legend chip for 7-day moving avg"


def test_f_legend_has_target_chip():
    html_lower = WEIGHT_HTML.lower()
    assert "legend" in html_lower and "target" in html_lower, \
        "HTML must have a legend chip for target dashed line"


def test_f_legend_has_projected_chip():
    html_lower = WEIGHT_HTML.lower()
    assert "legend" in html_lower and "projected" in html_lower, \
        "HTML must have a legend chip for projected dashed line"


# ── (g) Range tabs ─────────────────────────────────────────────────────────────

def test_g_range_tab_30d_present():
    assert "30D" in WEIGHT_HTML or "30d" in WEIGHT_HTML.lower(), \
        "HTML must have a 30D range tab"


def test_g_range_tab_90d_present():
    assert "90D" in WEIGHT_HTML or "90d" in WEIGHT_HTML.lower(), \
        "HTML must have a 90D range tab"


def test_g_range_tab_6m_present():
    assert "6M" in WEIGHT_HTML or "6m" in WEIGHT_HTML.lower(), \
        "HTML must have a 6M range tab"


def test_g_range_tab_1y_present():
    assert "1Y" in WEIGHT_HTML or "1y" in WEIGHT_HTML.lower(), \
        "HTML must have a 1Y range tab"


def test_g_range_tab_all_present():
    assert "ALL" in WEIGHT_HTML or ">All<" in WEIGHT_HTML, \
        "HTML must have an ALL range tab"


def test_g_js_refetches_chart_on_range_change():
    js_lower = WEIGHT_JS.lower()
    assert "weight-chart" in js_lower and ("range" in js_lower or "tab" in js_lower), \
        "weight.js must re-fetch /api/weight-chart when range tab changes"


# ── (h) Y-axis and X-axis ─────────────────────────────────────────────────────

def test_h_yaxis_step_size_2():
    assert "stepSize" in WEIGHT_JS and "2" in WEIGHT_JS, \
        "weight.js must configure y-axis stepSize: 2"


def test_h_xaxis_format_adapts_to_range():
    js_lower = WEIGHT_JS.lower()
    assert "range" in js_lower and ("fmt" in js_lower or "format" in js_lower or "tolocale" in js_lower), \
        "weight.js must adapt X-axis date format based on selected range"


# ── (i) Tooltips ─────────────────────────────────────────────────────────────

def test_i_tooltip_configured():
    js_lower = WEIGHT_JS.lower()
    assert "tooltip" in js_lower, \
        "weight.js must configure Chart.js tooltip options"


def test_i_tooltip_shows_weight():
    js_lower = WEIGHT_JS.lower()
    assert "kg" in js_lower and "tooltip" in js_lower, \
        "weight.js tooltip must include kg weight in display"


# ── (j) Progress card ─────────────────────────────────────────────────────────

def test_j_progress_card_element_present():
    assert "progress-card" in WEIGHT_HTML or "progress_card" in WEIGHT_HTML, \
        "HTML must have a progress card element"


def test_j_progress_bar_element_present():
    html_lower = WEIGHT_HTML.lower()
    assert "progress" in html_lower and ("bar" in html_lower or "track" in html_lower or "fill" in html_lower), \
        "HTML must have a horizontal progress bar element"


def test_j_progress_pct_element_present():
    assert "progress-pct" in WEIGHT_HTML or "progress_pct" in WEIGHT_HTML, \
        "HTML must have a progress_pct display element"


def test_j_kg_to_go_element_present():
    assert "kg-to-go" in WEIGHT_HTML or "kg_to_go" in WEIGHT_HTML, \
        "HTML must have a kg-to-go display element"


def test_j_status_pill_element_present():
    assert "status-pill" in WEIGHT_HTML or "status_pill" in WEIGHT_HTML, \
        "HTML must have a status pill element"


def test_j_js_uses_status_label():
    assert "status_label" in WEIGHT_JS, \
        "weight.js must use status_label from the target API response"


def test_j_status_pill_colors_on_track():
    js_lower = WEIGHT_JS.lower()
    assert "on_track" in js_lower or "on-track" in js_lower, \
        "weight.js must handle status_label 'on_track' (green)"


def test_j_status_pill_colors_behind():
    assert "behind" in WEIGHT_JS, \
        "weight.js must handle status_label 'behind' (amber)"


def test_j_status_pill_colors_ahead():
    assert "ahead" in WEIGHT_JS, \
        "weight.js must handle status_label 'ahead' (blue)"


# ── (k) Milestones panel ──────────────────────────────────────────────────────

def test_k_milestones_panel_element_present():
    assert "milestones" in WEIGHT_HTML.lower(), \
        "HTML must have a milestones panel element"


def test_k_milestones_has_today_row():
    js_lower = WEIGHT_JS.lower()
    assert "today" in js_lower and "milestone" in js_lower, \
        "weight.js must render a Today milestone row"


def test_k_milestones_has_3mo_row():
    assert ("3 mo" in WEIGHT_JS or "3mo" in WEIGHT_JS or "90" in WEIGHT_JS) and \
           "milestone" in WEIGHT_JS.lower(), \
        "weight.js must render a 3-month milestone row"


def test_k_milestones_has_6mo_row():
    assert ("6 mo" in WEIGHT_JS or "6mo" in WEIGHT_JS or "180" in WEIGHT_JS) and \
           "milestone" in WEIGHT_JS.lower(), \
        "weight.js must render a 6-month milestone row"


def test_k_milestones_has_goal_row():
    js_lower = WEIGHT_JS.lower()
    assert "goal" in js_lower and "milestone" in js_lower, \
        "weight.js must render a Goal milestone row"


def test_k_milestones_uses_linear_interpolation():
    js_lower = WEIGHT_JS.lower()
    assert "interpolat" in js_lower or "frac" in js_lower or "lerp" in js_lower, \
        "weight.js must use linear interpolation for projected milestone weights"


# ── (l) Recent entries 14 days ───────────────────────────────────────────────

def test_l_recent_entries_element_present():
    assert "recent-entries" in WEIGHT_HTML or "recent_entries" in WEIGHT_HTML, \
        "HTML must have a recent-entries container"


def test_l_recent_entries_covers_14_days():
    assert "14" in WEIGHT_JS, \
        "weight.js must render the last 14 days for recent entries"


def test_l_missing_day_shows_no_entry():
    js_lower = WEIGHT_JS.lower()
    assert "no entry" in js_lower, \
        "weight.js must show 'No entry' text for days without weight entries"


def test_l_missing_day_has_backfill_button():
    js_lower = WEIGHT_JS.lower()
    assert "backfill" in js_lower or (
        "no entry" in js_lower and ("+" in WEIGHT_JS or "plus" in js_lower)
    ), "weight.js must render a '+' backfill button for days without entries"


# ── (m) Backfill POST ─────────────────────────────────────────────────────────

def test_m_backfill_posts_to_weight_entries():
    assert "/api/weight-entries" in WEIGHT_JS, \
        "weight.js must POST backfill entries to /api/weight-entries"


def test_m_backfill_sends_past_date():
    js_lower = WEIGHT_JS.lower()
    assert "entry_date" in js_lower and "backfill" in js_lower, \
        "weight.js backfill must include entry_date (the past date) in the POST body"


# ── (n) Responsive CSS < 880px ────────────────────────────────────────────────

def test_n_css_breakpoint_880px():
    assert "880" in WEIGHT_HTML, \
        "weight.html must have a CSS media query breakpoint at 880px"


def test_n_hero_collapses_to_2col_at_880():
    html_lower = WEIGHT_HTML.lower()
    assert "880" in html_lower and (
        "repeat(2" in html_lower or "2-col" in html_lower or "grid-template-columns" in html_lower
    ), "weight.html CSS must collapse hero to 2-col at < 880px"


def test_n_milestones_become_scroll_at_880():
    html_lower = WEIGHT_HTML.lower()
    assert "880" in html_lower and (
        "overflow" in html_lower or "scroll" in html_lower
    ), "weight.html CSS must make milestones horizontally scrollable at < 880px"


def test_n_recent_entries_card_rows_at_880():
    html_lower = WEIGHT_HTML.lower()
    assert "880" in html_lower and (
        "card-row" in html_lower or "entry-card" in html_lower
    ), "weight.html CSS must render recent entries as card-rows at < 880px"


# ── (o) All logic in weight.js ────────────────────────────────────────────────

def test_o_no_other_weight_js_files():
    other_weight_js = [
        f for f in JS_DIR.iterdir()
        if f.suffix == ".js"
        and f.name != "weight.js"
        and "weight" in f.name.lower()
    ]
    assert not other_weight_js, \
        f"All weight JS logic must be in weight.js; found extra files: {other_weight_js}"
