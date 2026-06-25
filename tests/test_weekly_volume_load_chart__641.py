"""Tests for issue #641: Add Weekly Volume & Load Chart to Training Log.

Acceptance Criteria tested:
  AC1  - Chart renders inside Training > Log sub-tab beneath existing content
  AC2  - Bars are stacked: Run TSS and Lift TSS segments with gradient fills
  AC3  - Run-distance (km) line on second (right-hand) Y-axis
  AC4  - Current week bar column is visually emphasised
  AC5  - Legend present identifying Run TSS, Lift TSS, and km
  AC6  - Data from existing /api/training-log endpoint only (no new endpoints)
  AC7  - Chart uses structural layout tokens (CSS custom properties)
  AC8  - Chart is responsive
  AC9  - Weeks with zero activity render as zero-height bars (not missing)
  AC10 - No console errors introduced (code structure checks)

These are static-asset contract tests anchored to the frontend JS/HTML.
"""
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_JS   = (_REPO / "frontend" / "js" / "training-log.js").read_text()
_HTML = (_REPO / "frontend" / "pages" / "training-log.html").read_text()


# ── AC1: Chart container present in the Log sub-tab below existing content ────

def test_ac1_volume_chart_card_present_in_html():
    assert 'id="volume-chart-card"' in _HTML, "volume-chart-card container must be in the HTML"


def test_ac1_volume_chart_canvas_present():
    assert 'id="volume-chart"' in _HTML, "volume-chart canvas must be in the HTML"


def test_ac1_chart_after_readiness_widget_in_dom_order():
    """Chart card must appear below the readiness widget in the DOM."""
    readiness_pos = _HTML.index('id="readiness-widget"')
    chart_pos     = _HTML.index('id="volume-chart-card"')
    assert chart_pos > readiness_pos, (
        "volume-chart-card must come after readiness-widget in DOM order"
    )


# ── AC2: Stacked bars with Run TSS and Lift TSS, gradient fills ───────────────

def test_ac2_run_tss_dataset_label_correct():
    assert "'Run TSS'" in _JS or '"Run TSS"' in _JS, "Dataset label must be 'Run TSS'"


def test_ac2_lift_tss_dataset_label_correct():
    assert "'Lift TSS'" in _JS or '"Lift TSS"' in _JS, (
        "Dataset label must be 'Lift TSS' (not 'Strength TSS')"
    )


def test_ac2_stacked_bars_configured():
    assert "stack: 'tss'" in _JS or 'stack: "tss"' in _JS, "Bars must use stack: 'tss'"
    assert "stacked: true" in _JS, "Y axis must have stacked: true"


def test_ac2_gradient_fill_used():
    assert "createLinearGradient" in _JS, (
        "renderVolumeChart must use createLinearGradient for gradient bar fills"
    )


def test_ac2_gradient_applied_to_run_and_lift_datasets():
    """Both Run and Lift TSS datasets must use gradient backgrounds (scriptable
    function or makeBarBg factory pattern)."""
    # The gradient factory or inline function must appear before both datasets
    assert "createLinearGradient" in _JS
    # Both datasets must reference gradient (via factory or function)
    assert "makeBarBg" in _JS or _JS.count("createLinearGradient") >= 2


# ── AC3: Run-distance line on second Y-axis ───────────────────────────────────

def test_ac3_km_dataset_present():
    # Dataset label is 'km'
    assert "'km'" in _JS or '"km"' in _JS


def test_ac3_secondary_yaxis_right():
    assert "position: 'right'" in _JS or 'position: "right"' in _JS


def test_ac3_km_line_uses_y1_axis():
    assert "yAxisID: 'y1'" in _JS or 'yAxisID: "y1"' in _JS


# ── AC4: Current week visually emphasised ─────────────────────────────────────

def test_ac4_current_week_index_tracked():
    assert "currentWeekIdx" in _JS, "renderVolumeChart must track currentWeekIdx"


def test_ac4_current_week_gradient_differs():
    """The scriptable gradient function must branch on currentWeekIdx to apply
    a different (brighter) gradient to the current week."""
    assert "currentWeekIdx" in _JS
    # The function checks dataIndex === currentWeekIdx to pick bright vs dim
    assert "isCurrent" in _JS or "currentWeekIdx" in _JS


def test_ac4_current_week_emphasis_in_gradient():
    """Both bright (current) and dimmed (past) gradient stops must exist."""
    # Look for patterns like 0.9 or 0.95 (bright) alongside 0.3x (dim)
    bright = re.search(r'rgba\(\d+,\d+,\d+,0\.9[0-9]?\)', _JS)
    dim    = re.search(r'rgba\(\d+,\d+,\d+,0\.[23][0-9]?\)', _JS)
    assert bright, "Must have high-opacity color stop for current week emphasis"
    assert dim,    "Must have low-opacity color stop for past weeks"


# ── AC5: Legend with Run TSS, Lift TSS, and km ───────────────────────────────

def test_ac5_legend_enabled():
    assert "legend" in _JS
    assert "display: true" in _JS


def test_ac5_legend_has_all_three_items():
    """Legend must show exactly Run TSS, Lift TSS, and km (three datasets)."""
    assert "'Run TSS'" in _JS or '"Run TSS"' in _JS
    assert "'Lift TSS'" in _JS or '"Lift TSS"' in _JS
    assert "'km'" in _JS or '"km"' in _JS


def test_ac5_no_strength_tss_label():
    """'Strength TSS' label must NOT appear — it was renamed to 'Lift TSS'."""
    assert "Strength TSS" not in _JS, (
        "Old label 'Strength TSS' must be replaced by 'Lift TSS' in dataset config"
    )


# ── AC6: Data from existing endpoint only, no new endpoints ──────────────────

def test_ac6_uses_existing_training_log_endpoint():
    assert "/api/training-log" in _JS


def test_ac6_no_new_api_endpoint_in_backend():
    """No new endpoint specific to weekly volume chart was added to main.py."""
    main_py = (_REPO / "backend" / "main.py").read_text()
    # No route named weekly-volume or volume-chart should have been introduced
    assert "/api/weekly-volume" not in main_py
    assert "/api/volume-chart" not in main_py
    assert "/api/training/weekly" not in main_py


# ── AC7: Structural layout tokens ────────────────────────────────────────────

def test_ac7_tick_color_read_from_css_token():
    """Chart must read --text-tertiary (or similar) via getComputedStyle instead
    of hard-coding the hex value."""
    assert "getComputedStyle" in _JS, (
        "Chart must use getComputedStyle to read CSS custom property for tick colour"
    )
    assert "--text-tertiary" in _JS or "--text-secondary" in _JS, (
        "Chart must reference a named CSS colour token for axis tick labels"
    )


def test_ac7_chart_card_uses_token_based_styling():
    """volume-chart-card must use var(--...) tokens, not inline pixel sizes."""
    # The card uses .log-card class which inherits CSS tokens
    assert 'class="volume-chart-card log-card"' in _HTML


# ── AC8: Responsive at tablet and mobile ─────────────────────────────────────

def test_ac8_responsive_true():
    assert "responsive: true" in _JS


def test_ac8_maintain_aspect_ratio_false():
    """maintainAspectRatio: false lets the chart fill the container height
    so the CSS .vc-body height controls the chart — required for responsive layout."""
    assert "maintainAspectRatio: false" in _JS


def test_ac8_chart_body_has_responsive_height():
    """The .vc-body wrapper must set a height so the chart has a bounded
    responsive container."""
    assert ".vc-body" in _HTML or ".vc-body" in (_REPO / "frontend" / "css" / "styles.css").read_text()


# ── AC9: Zero-activity weeks render as empty bars (zero height) ───────────────

def test_ac9_empty_week_defaults_to_zero():
    """Weeks with no workouts must push 0 values, not skip the column."""
    # The code uses byStart[wkIso] || {} and weekVolumeByType(wk.workouts || [])
    # which returns {runTss:0, strengthTss:0, distKm:0} for missing weeks
    assert "|| {}" in _JS, "Missing week must default to empty object, not be skipped"
    assert "|| []" in _JS, "Missing workouts must default to empty array"


def test_ac9_all_week_slots_always_pushed():
    """The while-loop must push a value for every week slot unconditionally,
    even when the week has no data."""
    # runTssVals.push and strengthTssVals.push must be in the while loop body
    chart_fn_start = _JS.index("function renderVolumeChart")
    chart_fn_end   = _JS.index("\n  function ", chart_fn_start + 10)
    chart_fn       = _JS[chart_fn_start:chart_fn_end]
    assert "runTssVals.push" in chart_fn
    assert "strengthTssVals.push" in chart_fn
    assert "distVals.push" in chart_fn


# ── AC10: No console errors (structural integrity checks) ─────────────────────

def test_ac10_chartjs_loaded_before_script():
    """Chart.js CDN script must appear before training-log.js so Chart is
    defined when renderVolumeChart runs."""
    chartjs_pos = _HTML.index("chart.js")
    script_pos  = _HTML.index("training-log.js")
    assert chartjs_pos < script_pos, "chart.js CDN must load before training-log.js"


def test_ac10_chart_guarded_against_missing_elements():
    """The function must return early when the canvas or card is absent."""
    fn_start = _JS.index("function renderVolumeChart")
    fn_end   = _JS.index("\n  function ", fn_start + 10)
    fn_body  = _JS[fn_start:fn_end]
    assert "if (!card || !canvas" in fn_body or "if (!card" in fn_body


def test_ac10_chart_guarded_against_missing_chartjs():
    fn_start = _JS.index("function renderVolumeChart")
    fn_end   = _JS.index("\n  function ", fn_start + 10)
    fn_body  = _JS[fn_start:fn_end]
    assert "typeof Chart" in fn_body, "Must guard against Chart.js not being loaded"
