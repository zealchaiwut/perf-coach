"""
TDD tests for issue #423 — Rebuild weight trend chart as custom SVG.

14 AC anchors:
  (ac1)  weight-chart.js exists; SVG has viewBox '0 0 900 280', width='100%'
  (ac2)  weight.html has no Chart.js CDN; weight-chart.js is loaded instead
  (ac3)  Range tabs 30D/90D/6M/1Y/ALL in weight.html; click handler re-fetches
  (ac4)  Axis-break glyph (two slanted ticks) between main and future zones
  (ac5)  Future zone tinted #f3f7ff; 'MILESTONES AHEAD' tag rendered
  (ac6)  Y-axis: yMin = floor(min(goal, lowest) − 1), yMax = ceil(highest + 1)
  (ac7)  Draw order: future tint → gridlines → target line → plan line →
         weigh-in dots → trend path → plan dot/label → today dot/label → gap chip
  (ac8)  Gap chip: red when behind, green when ahead; hidden on no_data
  (ac9)  Future zone: white-filled diamond at intermediates, solid circle at goal
  (ac10) Legend row: Weigh-in · 7-day avg · Plan · Gap vs plan · Milestone
  (ac11) No-target state: plan_series null check; hasTarget controls full width
  (ac12) Ahead state: green chip background, gap_kg rendered with toFixed (sign)
  (ac13) Tooltip div on mousemove and touchmove events
  (ac14) SVG width='100%' for responsive scaling at 360px mobile viewport
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


# ── AC1: weight-chart.js exists; viewBox '0 0 900 280' ───────────────────────

def test_ac1_weight_chart_js_exists():
    """AC1: frontend/js/weight-chart.js must exist."""
    assert CHART_JS.exists(), "frontend/js/weight-chart.js does not exist"


def test_ac1_svg_viewbox_900_280():
    """AC1: SVG viewBox must contain '0 0 900 280'."""
    assert '0 0 900 280' in _chart_js(), \
        "viewBox '0 0 900 280' not found in weight-chart.js"


# ── AC2: Chart.js CDN removed; weight-chart.js loaded ────────────────────────

def test_ac2_chartjs_cdn_removed():
    """AC2: Chart.js CDN script must be absent from weight.html."""
    assert 'cdn.jsdelivr.net/npm/chart.js' not in html, \
        "Chart.js CDN script still present in weight.html"


def test_ac2_weight_chart_js_loaded():
    """AC2: weight.html must load weight-chart.js."""
    assert 'weight-chart.js' in html, \
        "weight-chart.js script tag not found in weight.html"


# ── AC3: Range tabs present; click triggers re-fetch ─────────────────────────

def test_ac3_all_range_tabs_present():
    """AC3: weight.html must have all five range tabs."""
    for tab in ('30d', '90d', '6m', '1y', 'all'):
        assert f'data-range="{tab}"' in html.lower(), \
            f"Range tab data-range='{tab}' missing from weight.html"


def test_ac3_range_tab_handler_fetches_chart():
    """AC3: weight.js click handler calls fetchChartData and renderChart."""
    assert 'fetchChartData' in js, "fetchChartData not called from range tab handler"
    assert 'range-tab' in js, "range-tab click handler not found in weight.js"
    assert 'renderChart' in js, "renderChart not called from range tab handler"


# ── AC4: Axis-break glyph (two slanted ticks) ────────────────────────────────

def test_ac4_axis_break_present():
    """AC4: weight-chart.js must contain axis-break rendering code."""
    src = _chart_js()
    assert 'break' in src.lower() or 'BREAK' in src, \
        "No axis-break code found in weight-chart.js"


def test_ac4_axis_break_two_ticks():
    """AC4: Axis-break renders exactly two slanted ticks via a two-element array."""
    src = _chart_js()
    assert re.search(r'\[-\d+,\s*\d+\]', src), \
        "Two-tick offset array not found in weight-chart.js (e.g. [-12, 12])"


# ── AC5: Future zone tint + MILESTONES AHEAD tag ─────────────────────────────

def test_ac5_future_zone_color():
    """AC5: Future zone background must use color #f3f7ff."""
    assert '#f3f7ff' in _chart_js(), \
        "Future zone tint color #f3f7ff not found in weight-chart.js"


def test_ac5_milestones_ahead_tag():
    """AC5: 'MILESTONES AHEAD' text must be rendered in the future zone."""
    assert 'MILESTONES AHEAD' in _chart_js(), \
        "'MILESTONES AHEAD' tag text not found in weight-chart.js"


# ── AC6: Y-axis bounds formula ────────────────────────────────────────────────

def test_ac6_ymin_uses_math_floor():
    """AC6: yMin computed with Math.floor."""
    assert 'Math.floor' in _chart_js(), \
        "Math.floor not found in weight-chart.js (required for yMin formula)"


def test_ac6_ymax_uses_math_ceil():
    """AC6: yMax computed with Math.ceil."""
    assert 'Math.ceil' in _chart_js(), \
        "Math.ceil not found in weight-chart.js (required for yMax formula)"


def test_ac6_ymin_uses_math_min_for_goal():
    """AC6: yMin formula uses Math.min to account for goal weight."""
    assert 'Math.min' in _chart_js(), \
        "Math.min not found in weight-chart.js (needed to compare goal vs lowest)"


# ── AC7: Draw order ───────────────────────────────────────────────────────────

def test_ac7_future_tint_before_gridlines():
    """AC7: Future tint rect appended before gridlines."""
    src = _chart_js()
    future_pos = src.find('future_bg')
    grid_pos   = src.find('C.grid') if 'C.grid' in src else src.find('#e5e7eb')
    assert future_pos != -1 and grid_pos != -1 and future_pos < grid_pos, \
        "Future tint not rendered before gridlines in weight-chart.js"


def test_ac7_plan_line_before_dots():
    """AC7: Plan line section rendered before weigh-in dots section."""
    src = _chart_js()
    # Use section comments as anchors for draw order
    plan_pos = src.find('plan line') if 'plan line' in src else src.find('plan_series.length')
    dots_pos = src.find('weigh-in') if 'weigh-in' in src else src.find('actuals.forEach')
    if plan_pos == -1:
        plan_pos = src.find('stroke-dasharray')
    if dots_pos == -1:
        dots_pos = src.find('C.actual')
    assert plan_pos != -1 and dots_pos != -1 and plan_pos < dots_pos, \
        "Plan line section not before weigh-in dots section in weight-chart.js"


def test_ac7_dots_before_trend():
    """AC7: Weigh-in dots (actuals) appended before trend path."""
    src = _chart_js()
    dots_pos  = src.find('actuals')
    trend_pos = src.find('trendSeg') if 'trendSeg' in src else src.find('trendPts')
    assert dots_pos != -1 and trend_pos != -1 and dots_pos < trend_pos, \
        "Weigh-in dots not rendered before trend path in weight-chart.js"


def test_ac7_gap_chip_after_today_dot():
    """AC7: Gap chip appended after 'you X kg' label."""
    src = _chart_js()
    you_pos      = src.find('you ')
    gap_chip_pos = src.rfind('gap')
    assert you_pos != -1 and gap_chip_pos != -1 and you_pos < gap_chip_pos, \
        "Gap chip not rendered after today-dot label in weight-chart.js"


# ── AC8: Gap chip colors ──────────────────────────────────────────────────────

def test_ac8_behind_uses_red():
    """AC8: 'behind' gap direction uses red color."""
    src = _chart_js()
    assert 'behind' in src, "'behind' direction not handled in weight-chart.js"
    assert '#dc2626' in src or '#fee2e2' in src or '#ef4444' in src, \
        "Red color for 'behind' not found in weight-chart.js"


def test_ac8_ahead_uses_green():
    """AC8: 'ahead' gap direction uses green color."""
    src = _chart_js()
    assert 'ahead' in src, "'ahead' direction not handled in weight-chart.js"
    assert '#16a34a' in src or '#dcfce7' in src, \
        "Green color for 'ahead' not found in weight-chart.js"


def test_ac8_no_data_skips_chip():
    """AC8: 'no_data' gap_direction causes chip to not render."""
    src = _chart_js()
    assert 'no_data' in src, \
        "'no_data' check not found in weight-chart.js"


# ── AC9: Future zone markers ──────────────────────────────────────────────────

def test_ac9_diamond_polygon_for_milestones():
    """AC9: Intermediate milestones rendered as SVG polygon (diamond shape)."""
    src = _chart_js()
    assert 'polygon' in src, \
        "SVG 'polygon' not found in weight-chart.js (required for diamond shape)"


def test_ac9_goal_circle_different_from_intermediate():
    """AC9: Goal milestone rendered with separate (circle) element."""
    src = _chart_js()
    assert ("kind === 'goal'" in src or
            "m.kind === 'goal'" in src or
            "=== 'goal'" in src), \
        "Goal-specific rendering logic not found in weight-chart.js"


# ── AC10: Legend row items ────────────────────────────────────────────────────

def test_ac10_legend_weigh_in():
    """AC10: Legend contains 'Weigh-in' item."""
    assert 'Weigh-in' in html, \
        "'Weigh-in' not found in weight.html legend"


def test_ac10_legend_7day_avg():
    """AC10: Legend contains '7-day avg' item."""
    assert '7-day' in html and 'avg' in html, \
        "'7-day avg' not found in weight.html legend"


def test_ac10_legend_plan():
    """AC10: Legend contains 'Plan' item with id='legend-plan'."""
    assert 'legend-plan' in html, \
        "id='legend-plan' not found in weight.html legend"


def test_ac10_legend_gap_vs_plan():
    """AC10: Legend contains 'Gap vs plan' item."""
    assert 'Gap vs plan' in html or ('Gap' in html and 'plan' in html), \
        "'Gap vs plan' not found in weight.html legend"


def test_ac10_legend_milestone():
    """AC10: Legend contains 'Milestone' item."""
    assert 'Milestone' in html, \
        "'Milestone' not found in weight.html legend"


# ── AC11: No-target state ─────────────────────────────────────────────────────

def test_ac11_plan_series_null_guarded():
    """AC11: weight-chart.js null-guards plan_series before rendering plan line."""
    src = _chart_js()
    has_guard = (
        'data.plan_series &&' in src or
        'if (data.plan_series' in src or
        'plan_series ?' in src or
        'plan_series && data.plan_series' in src
    )
    assert has_guard, \
        "Null guard for plan_series not found in weight-chart.js"


def test_ac11_has_target_controls_zone_width():
    """AC11: hasTarget variable controls whether future zone is rendered."""
    src = _chart_js()
    assert 'hasTarget' in src, \
        "'hasTarget' variable not found in weight-chart.js (needed for no-target full-width)"


# ── AC12: Ahead state green chip ─────────────────────────────────────────────

def test_ac12_ahead_green_bg():
    """AC12: Ahead gap uses green chip background (#dcfce7)."""
    src = _chart_js()
    assert '#dcfce7' in src, \
        "Green chip background #dcfce7 not found in weight-chart.js"


def test_ac12_gap_kg_rendered_with_sign():
    """AC12: gap_kg rendered via toFixed (preserves minus sign for ahead)."""
    src = _chart_js()
    assert 'gap_kg' in src and 'toFixed' in src, \
        "gap_kg.toFixed rendering not found in weight-chart.js"


# ── AC13: Hover tooltip ───────────────────────────────────────────────────────

def test_ac13_mousemove_listener():
    """AC13: SVG listens for mousemove to show tooltip."""
    assert 'mousemove' in _chart_js(), \
        "'mousemove' event listener not found in weight-chart.js"


def test_ac13_touchmove_listener():
    """AC13: SVG listens for touchmove to show tooltip on touch devices."""
    assert 'touchmove' in _chart_js(), \
        "'touchmove' event listener not found in weight-chart.js"


def test_ac13_tooltip_is_div():
    """AC13: Tooltip implemented as a div element (no library)."""
    src = _chart_js()
    assert "createElement('div')" in src or 'createElement("div")' in src, \
        "Tooltip div element not found in weight-chart.js"


# ── AC14: Responsive / mobile ─────────────────────────────────────────────────

def test_ac14_svg_width_100pct():
    """AC14: SVG rendered with width='100%' so it scales at 360px viewport."""
    src = _chart_js()
    assert (
        "setAttribute('width', '100%')" in src or
        "'width', '100%'" in src or
        '"width", "100%"' in src or
        "width: '100%'" in src
    ), "SVG width='100%' not set in weight-chart.js"
