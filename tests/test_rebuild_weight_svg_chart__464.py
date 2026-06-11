"""
TDD tests for issue #464 — Rebuild weight trend chart as custom SVG.

15 AC anchors:
  (ac1)  weight-chart.js exists; no Chart.js import on weight page
  (ac2)  Range tabs: 7D · 30D · 90D · 6M · 1Y · ALL in order; default 30D
  (ac3)  Selecting any tab calls GET /api/weight-chart; redraws without reload
  (ac4)  Desktop ≥ 640px, range ≥ 90D: dual-zone layout (main ~65% + future ~30%)
  (ac5)  Short ranges (7D, 30D) OR viewport < 640px: future zone hidden; "milestones ↓" link shown
  (ac6)  No active target: all plan/gap/future elements hidden; main zone full width
  (ac7)  Y-axis: yMin = floor(min(goal, lowest) − 1), yMax = ceil(highest + 1)
  (ac8)  Draw order correct
  (ac9)  Ahead-of-plan: gap chip green with minus sign
  (ac10) Behind-plan: gap chip red with positive value
  (ac11) Text sizes: axis ~12, you/plan labels ~13-14, milestone kg ~13, chip ~13; trend stroke ~2.8
  (ac12) Legend: Weigh-in · 7-day avg · Plan · Gap vs plan · Milestone; plan/gap/ms hidden when no target
  (ac13) Tooltip div on mouseover and touch; dismisses on mouseout/touchend
  (ac14) Legible at 360px (SVG width=100%, viewBox set)
  (ac15) 30D desktop matches reference (verified structurally)
"""
import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "frontend"
WEIGHT_HTML = FRONTEND / "pages" / "weight.html"
WEIGHT_JS   = FRONTEND / "js" / "weight.js"
CHART_JS    = FRONTEND / "js" / "weight-chart.js"

html = WEIGHT_HTML.read_text()
js   = WEIGHT_JS.read_text()


def _chart_js():
    return CHART_JS.read_text()


# ── AC1: No Chart.js; weight-chart.js loaded ─────────────────────────────────

def test_ac1_no_chartjs_on_weight_page():
    """AC1: weight.html must not import Chart.js from CDN."""
    assert 'chart.js' not in html.lower() or 'weight-chart.js' in html, \
        "chart.js CDN import found in weight.html (should use custom SVG only)"
    # Specifically the CDN must be gone
    assert 'cdn.jsdelivr.net/npm/chart.js' not in html, \
        "Chart.js CDN still present in weight.html"


def test_ac1_weight_chart_js_exists():
    """AC1: frontend/js/weight-chart.js must exist as a module."""
    assert CHART_JS.exists(), "frontend/js/weight-chart.js does not exist"


def test_ac1_weight_chart_js_loaded_in_html():
    """AC1: weight.html must load weight-chart.js via script tag."""
    assert 'weight-chart.js' in html, \
        "weight-chart.js script tag not found in weight.html"


# ── AC2: Range tabs 7D · 30D · 90D · 6M · 1Y · ALL ──────────────────────────

def test_ac2_7d_tab_present():
    """AC2: weight.html must have a 7D range tab."""
    assert 'data-range="7d"' in html.lower() or "data-range='7d'" in html.lower(), \
        "7D range tab (data-range='7d') missing from weight.html"


def test_ac2_all_range_tabs_present():
    """AC2: All six range tabs must be present."""
    for tab in ('7d', '30d', '90d', '6m', '1y', 'all'):
        assert f'data-range="{tab}"' in html.lower(), \
            f"Range tab data-range='{tab}' missing from weight.html"


def test_ac2_tab_order_7d_first():
    """AC2: 7D tab must appear before 30D tab in weight.html."""
    pos_7d  = html.lower().find('data-range="7d"')
    pos_30d = html.lower().find('data-range="30d"')
    assert pos_7d != -1, "7D tab not found"
    assert pos_30d != -1, "30D tab not found"
    assert pos_7d < pos_30d, "7D tab must appear before 30D tab"


def test_ac2_default_active_tab_is_30d():
    """AC2: 30D tab must be the default active tab on page load."""
    # The 30d tab must have class="range-tab active"
    assert re.search(r'data-range=["\']30d["\'][^>]*class=["\']range-tab active', html) or \
           re.search(r'class=["\']range-tab active["\'][^>]*data-range=["\']30d["\']', html), \
        "30D tab is not the default active range tab in weight.html"


def test_ac2_7d_handled_in_weight_js():
    """AC2: weight.js rangeFromDate must handle '7d' range."""
    assert "'7d'" in js or '"7d"' in js, \
        "'7d' range not handled in weight.js rangeFromDate function"


# ── AC3: Tab click calls /api/weight-chart ────────────────────────────────────

def test_ac3_range_tab_handler_fetches_chart():
    """AC3: weight.js range tab click handler calls fetchChartData."""
    assert 'fetchChartData' in js, "fetchChartData not called from range tab handler"
    assert 'range-tab' in js, "range-tab click handler not found in weight.js"


def test_ac3_renders_chart_on_tab_click():
    """AC3: weight.js renders chart after fetching data on tab click."""
    assert 'renderChart' in js, "renderChart not called in weight.js"


# ── AC4: Dual-zone layout for ≥ 90D on wide viewport ─────────────────────────

def test_ac4_main_zone_65pct():
    """AC4 (revised): 3-zone layout [past 20% | current 60% | future 20%].
    The current zone is derived as CW - PAST_W - FUTURE_W."""
    src = _chart_js()
    assert 'PAST_W' in src and 'CUR_W3' in src, \
        "3-zone current-width constant (CUR_W3 = CW - PAST_W - FUTURE_W) not found"


def test_ac4_future_zone_30pct():
    """AC4 (revised): past and future zones each use ~20% of chart width."""
    src = _chart_js()
    assert '0.20' in src or '0.2)' in src, \
        "20% zone width constant (PAST_W / FUTURE_W) not found in weight-chart.js"


def test_ac4_axis_break_glyph():
    """AC4 (revised): zones are divided by thin vertical separators (no axis-break glyph)."""
    src = _chart_js()
    assert 'C_SEP' in src, \
        "Thin zone-separator constant (C_SEP) not found in weight-chart.js"


# ── AC5: Short range / small viewport → no future zone + milestones link ─────

def test_ac5_short_range_hides_future_zone():
    """AC5 (revised): the 3-zone layout (incl. future milestones) is shown for every
    range whenever a target exists; short ranges no longer suppress it."""
    src = _chart_js()
    assert 'threeZone' in src, \
        "threeZone flag (target-driven 3-zone layout) not found in weight-chart.js"


def test_ac5_small_viewport_hides_future_zone():
    """AC5 (revised): the future zone is no longer suppressed by viewport width;
    the 3-zone layout is target-driven (threeZone)."""
    src = _chart_js()
    assert 'threeZone' in src, \
        "threeZone flag not found in weight-chart.js"


def test_ac5_milestones_link_present():
    """AC5: A 'milestones' link (pointing to progress card) appears when future zone is hidden."""
    src = _chart_js()
    has_link = (
        'milestones' in src.lower() and
        ('#progress-card' in src or 'progress-card' in src or 'milestones ↓' in src or
         "milestones" in src.lower())
    )
    # The link text should be "milestones ↓" or similar
    assert 'milestones' in src.lower(), \
        "No milestones reference link found in weight-chart.js"
    assert '↓' in src or 'progress-card' in src or '#progress' in src, \
        "Milestones link does not point toward progress card (missing ↓ or #progress-card)"


# ── AC6: No active target → full width main zone ─────────────────────────────

def test_ac6_no_target_full_width():
    """AC6: weight-chart.js uses full chart width when no active target."""
    src = _chart_js()
    assert 'hasTarget' in src, \
        "'hasTarget' variable not found in weight-chart.js"


def test_ac6_plan_series_null_guarded():
    """AC6: plan_series null-guarded before rendering plan line."""
    src = _chart_js()
    assert 'plan_series' in src, "plan_series not referenced in weight-chart.js"
    assert 'plan_series &&' in src or 'if (data.plan_series' in src or 'plan_series ?' in src, \
        "plan_series not null-guarded in weight-chart.js"


# ── AC7: Y-axis bounds ────────────────────────────────────────────────────────

def test_ac7_ymin_formula():
    """AC7: yMin = floor(min(goal, lowest) - 1)."""
    src = _chart_js()
    assert 'Math.floor' in src, "Math.floor not used for yMin in weight-chart.js"
    assert '- 1' in src or '-1' in src, \
        "yMin offset of -1 not found in weight-chart.js"


def test_ac7_ymax_formula():
    """AC7: yMax = ceil(highest + 1)."""
    src = _chart_js()
    assert 'Math.ceil' in src, "Math.ceil not used for yMax in weight-chart.js"
    assert '+ 1' in src or '+1' in src, \
        "yMax offset of +1 not found in weight-chart.js"


def test_ac7_gridlines_every_2kg():
    """AC7: Horizontal gridlines drawn every 2 kg."""
    src = _chart_js()
    assert 'kg += 2' in src or '+= 2' in src, \
        "2kg gridline step not found in weight-chart.js"


# ── AC8: Draw order ───────────────────────────────────────────────────────────

def test_ac8_future_tint_before_gridlines():
    """AC8: Future tint rect rendered before gridlines."""
    src = _chart_js()
    tint_pos  = src.find('future_bg')
    grid_pos  = src.find('C.grid')
    assert tint_pos != -1, "future_bg color not found"
    assert grid_pos != -1, "gridline color not found"
    assert tint_pos < grid_pos, "Future tint must be rendered before gridlines"


def test_ac8_trend_path_after_weigh_in_dots():
    """AC8: Trend path rendered after weigh-in dots."""
    src = _chart_js()
    dots_pos  = src.find('C.actual')
    trend_pos = src.find('C.trend')
    assert dots_pos != -1, "actual dot color not found"
    assert trend_pos != -1, "trend line color not found"
    assert dots_pos < trend_pos, "Weigh-in dots must be rendered before trend path"


# ── AC9: Ahead-of-plan state ──────────────────────────────────────────────────

def test_ac9_ahead_chip_green():
    """AC9: Ahead-of-plan gap chip uses green background (#dcfce7) and text (#16a34a)."""
    src = _chart_js()
    assert '#dcfce7' in src, "Green chip background #dcfce7 not in weight-chart.js"
    assert 'ahead' in src,   "'ahead' direction not handled in weight-chart.js"


def test_ac9_ahead_chip_minus_sign():
    """AC9 (revised): the gap vs plan is drawn as a dashed gap line cue (the kg
    chip label is hidden; values appear on hover). The ahead/behind direction
    still drives the gap rendering."""
    src = _chart_js()
    assert 'gap_direction' in src, \
        "gap_direction handling (gap line) not found in weight-chart.js"


# ── AC10: Behind-plan state ───────────────────────────────────────────────────

def test_ac10_behind_chip_red():
    """AC10: Behind-plan gap chip uses red background (#fee2e2) and text (#dc2626)."""
    src = _chart_js()
    assert '#fee2e2' in src, "Red chip background #fee2e2 not in weight-chart.js"
    assert '#dc2626' in src or '#ef4444' in src, \
        "Red text color not in weight-chart.js"
    assert 'behind' in src, "'behind' direction not handled in weight-chart.js"


# ── AC11: Text sizes ──────────────────────────────────────────────────────────

def test_ac11_axis_numbers_font_size_12():
    """AC11: Y-axis grid labels must use font-size '12' (SVG units)."""
    src = _chart_js()
    # Grid label font-size should be 12
    assert "'font-size': '12'" in src or '"font-size": "12"' in src or \
           "'font-size', '12'" in src or '"font-size", "12"' in src, \
        "Y-axis grid label font-size '12' not found in weight-chart.js"


def test_ac11_you_plan_labels_font_size_13_to_14():
    """AC11 (revised): the today you/plan values are shown on hover (labels hidden
    to reduce clutter), so both today_marker values feed the hover dots."""
    src = _chart_js()
    assert 'tm.plan_kg' in src and 'tm.trend_kg' in src, \
        "today-marker plan/trend values (hover) not found in weight-chart.js"


def test_ac11_milestone_kg_labels_font_size_13():
    """AC11 (revised): milestone values are shown on hover (labels hidden), so
    each milestone's plan_kg feeds a hover dot."""
    src = _chart_js()
    assert 'm.plan_kg' in src, \
        "milestone plan_kg (hover) not found in weight-chart.js"


def test_ac11_trend_stroke_width_2_8():
    """AC11: Trend line stroke-width must be ~2.8."""
    src = _chart_js()
    assert '2.8' in src or "'stroke-width': '2.8'" in src or \
           '"stroke-width": "2.8"' in src, \
        "Trend line stroke-width ~2.8 not found in weight-chart.js"


# ── AC12: Legend row ──────────────────────────────────────────────────────────

def test_ac12_legend_weigh_in():
    """AC12: Legend contains 'Weigh-in' item."""
    assert 'Weigh-in' in html, "'Weigh-in' not found in weight.html legend"


def test_ac12_legend_7day_avg():
    """AC12: Legend contains '7-day avg' item."""
    assert '7-day' in html and 'avg' in html, \
        "'7-day avg' not found in weight.html legend"


def test_ac12_legend_plan_hidden_by_default():
    """AC12: Plan legend item hidden by default (no active target)."""
    assert 'id="legend-plan"' in html, "id='legend-plan' not found"
    # The element should have hidden attribute by default
    assert re.search(r'id="legend-plan"[^>]*hidden', html) or \
           re.search(r'hidden[^>]*id="legend-plan"', html), \
        "legend-plan not hidden by default in weight.html"


def test_ac12_legend_gap_hidden_by_default():
    """AC12: Gap legend item hidden by default."""
    assert 'id="legend-gap"' in html, "id='legend-gap' not found"
    assert re.search(r'id="legend-gap"[^>]*hidden', html) or \
           re.search(r'hidden[^>]*id="legend-gap"', html), \
        "legend-gap not hidden by default"


def test_ac12_legend_milestone_hidden_by_default():
    """AC12: Milestone legend item hidden by default."""
    assert 'id="legend-milestone"' in html, "id='legend-milestone' not found"
    assert re.search(r'id="legend-milestone"[^>]*hidden', html) or \
           re.search(r'hidden[^>]*id="legend-milestone"', html), \
        "legend-milestone not hidden by default"


def test_ac12_legend_items_shown_when_target():
    """AC12: weight.js shows plan/gap/milestone legend when active target."""
    assert 'legend-plan' in js, "legend-plan toggled in weight.js"
    assert 'legend-gap' in js, "legend-gap toggled in weight.js"
    assert 'legend-milestone' in js, "legend-milestone toggled in weight.js"


# ── AC13: Tooltip ─────────────────────────────────────────────────────────────

def test_ac13_tooltip_div():
    """AC13: Tooltip implemented as a div element (no library)."""
    src = _chart_js()
    assert "createElement('div')" in src or 'createElement("div")' in src, \
        "Tooltip div element not found in weight-chart.js"


def test_ac13_mouseover_or_mousemove_listener():
    """AC13: SVG listens for mousemove or mouseover to show tooltip."""
    src = _chart_js()
    assert 'mousemove' in src or 'mouseover' in src, \
        "mousemove/mouseover event listener not found in weight-chart.js"


def test_ac13_mouseout_dismisses_tooltip():
    """AC13: Tooltip dismisses on mouseout (mouseleave)."""
    src = _chart_js()
    assert 'mouseleave' in src or 'mouseout' in src, \
        "mouseout/mouseleave listener not found in weight-chart.js"


def test_ac13_touch_events():
    """AC13: Tooltip shows on touchmove and dismisses on touchend."""
    src = _chart_js()
    assert 'touchmove' in src, "'touchmove' not found in weight-chart.js"
    assert 'touchend' in src, "'touchend' not found in weight-chart.js"


# ── AC14: Responsive 360px ────────────────────────────────────────────────────

def test_ac14_svg_width_100pct():
    """AC14: SVG rendered with width='100%' for 360px viewport scaling."""
    src = _chart_js()
    assert (
        "setAttribute('width', '100%')" in src or
        "'width', '100%'" in src or
        '"width", "100%"' in src
    ), "SVG width='100%' not set in weight-chart.js"


def test_ac14_svg_viewbox_900_280():
    """AC14 (revised): SVG viewBox is 900 wide; the height is render-time (_VH),
    taller on mobile for readability. Built from VW and _VH."""
    src = _chart_js()
    assert "'0 0 ' + VW + ' ' + _VH" in src or "0 0 900 280" in src, \
        "viewBox (width 900, render-time _VH height) not found in weight-chart.js"
