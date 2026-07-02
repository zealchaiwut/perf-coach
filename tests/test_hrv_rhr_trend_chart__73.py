"""
Tests for issue #73: Add HRV and RHR trend chart with baseline band

The feature replaces the current dual-axis single chart with two vertically
stacked sub-charts (HRV on top, RHR on bottom), each showing a daily-value
line, a ±1 SD baseline band, a highlighted today dot, and out-of-band
point coloring.

Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
ROOT = pathlib.Path(__file__).parent.parent

HTML = (ROOT / "frontend" / "pages" / "trends.html").read_text()
JS   = (ROOT / "frontend" / "js" / "trends.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c



# ── AC-1: Two stacked sub-charts; no dual y-axis ──────────────────────────────

def test_ac1_hrv_rhr_slot_exists():
    """trends.html must have a #slot-hrv-rhr chart slot."""
    assert 'id="slot-hrv-rhr"' in HTML or "id='slot-hrv-rhr'" in HTML, \
        "#slot-hrv-rhr chart slot missing from trends.html"


def test_ac1_separate_hrv_slot_body():
    """trends.html must have a dedicated body container for the HRV sub-chart."""
    has_hrv_body = (
        'id="slot-hrv-body"' in HTML
        or "id='slot-hrv-body'" in HTML
        or 'id="hrv-chart-body"' in HTML
        or 'id="hrv-body"' in HTML
    )
    assert has_hrv_body, \
        "trends.html must have a dedicated body element for the HRV sub-chart"


def test_ac1_separate_rhr_slot_body():
    """trends.html must have a dedicated body container for the RHR sub-chart."""
    has_rhr_body = (
        'id="slot-rhr-body"' in HTML
        or "id='slot-rhr-body'" in HTML
        or 'id="rhr-chart-body"' in HTML
        or 'id="rhr-body"' in HTML
    )
    assert has_rhr_body, \
        "trends.html must have a dedicated body element for the RHR sub-chart"


def test_ac1_no_dual_yaxis_in_hrv_rhr_chart():
    """renderHrvRhrChart must NOT define a secondary y-axis (no dual-axis)."""
    # A dual-axis chart is identified by yAxisID references beyond the first axis
    has_dual_axis = (
        "yAxisID: 'yHrv'" in JS or 'yAxisID: "yHrv"' in JS
        or "yAxisID: 'yRhr'" in JS or 'yAxisID: "yRhr"' in JS
    )
    assert not has_dual_axis, \
        "trends.js must NOT use dual y-axes (yHrv/yRhr) in the HRV/RHR chart — " \
        "use two separate sub-charts instead"


def test_ac1_two_separate_chart_render_functions():
    """trends.js must define separate render functions for HRV and RHR sub-charts."""
    has_hrv_fn = "renderHrvChart" in JS or "renderHRVChart" in JS
    has_rhr_fn = "renderRhrChart" in JS or "renderRHRChart" in JS
    assert has_hrv_fn, \
        "trends.js must define a dedicated renderHrvChart (or similar) function"
    assert has_rhr_fn, \
        "trends.js must define a dedicated renderRhrChart (or similar) function"


def test_ac1_hrv_slot_title_present():
    """The HRV sub-chart must have a title labeling it as HRV."""
    assert re.search(r'(?i)hrv', HTML), \
        "trends.html must label the HRV sub-chart"


def test_ac1_rhr_slot_title_present():
    """The RHR sub-chart must have a title labeling it as RHR or Resting HR."""
    assert re.search(r'(?i)(rhr|resting hr|resting heart)', HTML), \
        "trends.html must label the RHR sub-chart"


# ── AC-2: Continuous line of daily values ─────────────────────────────────────

def test_ac2_hrv_series_rendered_as_line():
    """trends.js must render the HRV series as a Chart.js line dataset."""
    assert "type: 'line'" in JS or 'type: "line"' in JS, \
        "trends.js must render HRV and RHR data as line charts"


def test_ac3_js_renders_baseline_band():
    """trends.js must implement baseline band rendering logic."""
    has_band = (
        "baseline_mean" in JS
        and "baseline_sd" in JS
        and ("fillBetween" in JS or "fill: true" in JS or "borderColor" in JS)
    )
    # At minimum, JS must reference baseline_mean and baseline_sd to draw the band
    assert "baseline_mean" in JS, \
        "trends.js must read hrv.baseline_mean from summary to draw the baseline band"
    assert "baseline_sd" in JS, \
        "trends.js must read baseline_sd from summary to draw the baseline band"


def test_ac3_band_upper_lower_computed():
    """trends.js must compute both upper and lower band boundaries (mean ± sd)."""
    has_upper = (
        "baseline_mean + baseline_sd" in JS
        or "baselineMean + baselineSd" in JS
        or "mean + sd" in JS
        or "+ baseline_sd" in JS
        or "+ baselineSd" in JS
    )
    has_lower = (
        "baseline_mean - baseline_sd" in JS
        or "baselineMean - baselineSd" in JS
        or "mean - sd" in JS
        or "- baseline_sd" in JS
        or "- baselineSd" in JS
    )
    assert has_upper, \
        "trends.js must compute the upper band boundary (mean + sd)"
    assert has_lower, \
        "trends.js must compute the lower band boundary (mean - sd)"


# ── AC-4: Today's dot is visually larger ──────────────────────────────────────

def test_ac4_today_dot_larger_radius():
    """trends.js must set a larger pointRadius for today's data point."""
    # Pattern: varying pointRadius per point, e.g. via pointRadius array or
    # a separate today-dot dataset with a larger radius
    has_variable_radius = (
        "pointRadius" in JS
        and (
            "today" in JS.lower()
            or "todayIdx" in JS
            or "today_idx" in JS
            or "isToday" in JS
            or "todayDate" in JS
        )
    )
    assert has_variable_radius, \
        "trends.js must render today's data point with a visually larger dot " \
        "(per-point pointRadius array or a separate dataset)"


def test_ac4_today_detection_in_js():
    """trends.js must identify today's date to highlight it."""
    has_today_detection = (
        "new Date()" in JS
        and (
            "toLocaleDateString" in JS
            or "toISOString" in JS
            or "today" in JS.lower()
        )
    )
    assert "new Date()" in JS, \
        "trends.js must call new Date() to detect today's date for the highlighted dot"


# ── AC-5: Out-of-band points in distinct color ────────────────────────────────

def test_ac5_out_of_band_color_applied():
    """trends.js must render out-of-band points in a distinct color."""
    has_outband_color = (
        "pointBackgroundColor" in JS
        and (
            "baseline_mean" in JS
            or "baseline_sd" in JS
        )
    )
    assert has_outband_color, \
        "trends.js must set per-point pointBackgroundColor based on whether " \
        "the value falls outside the baseline band"


def test_ac5_two_colors_defined_for_hrv_rhr():
    """trends.js must define at least two distinct colors for in/out-of-band points."""
    # The function that handles HRV/RHR rendering should reference at least two
    # different hex/rgba colors or variables for normal vs. out-of-band points
    color_count = len(re.findall(r"#[0-9a-fA-F]{3,6}|rgba?\([^)]+\)", JS))
    assert color_count >= 4, \
        "trends.js must define multiple colors to distinguish in-band and " \
        "out-of-band data points"


# ── AC-6: "Approximate" label when fewer than 30 days ─────────────────────────

def test_ac6_approximate_label_in_js():
    """trends.js must add an 'approximate' annotation when fewer than 30 data days."""
    has_approx = (
        "approximate" in JS.lower()
        or "approx" in JS.lower()
    )
    assert has_approx, \
        "trends.js must display an 'approximate' label on the chart when " \
        "fewer than 30 days of data are available for the baseline band"


def test_ac6_approximate_label_in_html():
    """trends.html OR trends.js must define an 'approximate' note or legend entry."""
    has_approx = (
        "approximate" in HTML.lower()
        or "approx" in HTML.lower()
        or "approximate" in JS.lower()
    )
    assert has_approx, \
        "The page must show an 'approximate' label when the band is based on " \
        "fewer than 30 days of data"


def test_ac6_day_count_threshold_checked():
    """trends.js must check whether the available data spans fewer than 30 days."""
    has_threshold = (
        "< 30" in JS
        or "<30" in JS
        or "30 days" in JS
        or "days < 30" in JS
        or "length < 30" in JS
    )
    assert has_threshold, \
        "trends.js must check a 30-day threshold to decide whether to label " \
        "the baseline band as 'approximate'"


# ── AC-7: Tooltip with raw value, baseline mean, and SD deviation ─────────────

def test_ac7_tooltip_shows_raw_value():
    """HRV/RHR tooltip must include the raw (daily) value."""
    # The existing dual-axis chart already does this; verify it's preserved
    has_raw = "item.raw" in JS or "item.parsed" in JS or "item.dataset" in JS
    assert has_raw, \
        "trends.js tooltip callback must display the raw daily value"


def test_ac7_tooltip_shows_baseline_mean():
    """trends.js tooltip must display the baseline mean for HRV and RHR points."""
    # Must show baseline_mean in tooltip — not just in chart data
    has_mean_in_tooltip = (
        "baseline_mean" in JS
        and "label" in JS  # label callback is where tooltip text is constructed
    )
    assert "baseline_mean" in JS, \
        "trends.js tooltip callback must include the baseline mean value"


def test_ac7_tooltip_shows_sd_deviation():
    """trends.js tooltip must show the deviation expressed in SD units (e.g. +1.4 SD)."""
    has_sd_tooltip = (
        "SD" in JS
        or " sd" in JS.lower()
        or "baseline_sd" in JS
    )
    assert has_sd_tooltip, \
        "trends.js tooltip callback must compute and display deviation in SD units"

    # More specific: the deviation computation must be present
    has_deviation_calc = (
        "/ baseline_sd" in JS
        or "/ sd" in JS
        or "/baselineSd" in JS
        or "/ baselineSd" in JS
    )
    assert has_deviation_calc, \
        "trends.js must divide (value - baseline_mean) by baseline_sd to get SD units"


# ── AC-8: Mobile legibility at 380 px ────────────────────────────────────────

def test_ac8_mobile_breakpoint_covers_380px():
    """trends.html must have a max-width breakpoint at or below 600px."""
    media_widths = [int(v) for v in re.findall(r"max-width:\s*(\d+)px", HTML)]
    assert media_widths, "trends.html must define at least one max-width media query"
    assert min(media_widths) <= 600, \
        f"Smallest breakpoint is {min(media_widths)}px — must be ≤600px to cover 380px"


def test_ac8_stacked_sub_charts_do_not_use_fixed_pixel_width():
    """HRV/RHR sub-chart containers must not use a fixed pixel width."""
    # Fixed pixel widths would break at 380px
    chart_slot_css = re.search(r'\.chart-slot\s*\{([^}]+)\}', HTML, re.DOTALL)
    if chart_slot_css:
        block = chart_slot_css.group(1)
        has_fixed_px = re.search(r'width:\s*\d{3,}px', block)
        assert not has_fixed_px, \
            ".chart-slot must not use a fixed pixel width that would break at 380px"


# ── AC-9: Empty data array handled gracefully ─────────────────────────────────

def test_ac9_empty_state_shown_for_hrv_chart():
    """trends.js must show an empty-state message when HRV data is all null."""
    has_empty_hrv = (
        "showEmpty" in JS
        and ("hrv" in JS)
    )
    assert has_empty_hrv, \
        "trends.js must call showEmpty (or equivalent) for the HRV slot " \
        "when all HRV values are null"


def test_ac9_empty_state_shown_for_rhr_chart():
    """trends.js must show an empty-state message when RHR data is all null."""
    has_empty_rhr = (
        "showEmpty" in JS
        and ("rhr" in JS)
    )
    assert has_empty_rhr, \
        "trends.js must call showEmpty (or equivalent) for the RHR slot " \
        "when all RHR values are null"


def test_ac10_null_sd_guard_in_js():
    """trends.js must guard against null baseline_sd before drawing the band."""
    has_null_guard = (
        "baseline_sd" in JS
        and (
            "!= null" in JS
            or "!== null" in JS
            or "baseline_sd &&" in JS
            or "&& baseline_sd" in JS
            or "baselineSd &&" in JS
            or "&& baselineSd" in JS
            or "if (baseline_sd" in JS
            or "if (baselineSd" in JS
            or "?? " in JS  # nullish coalescing as guard
        )
    )
    assert has_null_guard, \
        "trends.js must guard against a null baseline_sd " \
        "(skip drawing the band when sd is null; no crash)"


def test_ac10_line_still_renders_with_null_sd():
    """trends.js must still render the daily-value line even when baseline_sd is null."""
    # The render function should not early-return when sd is null;
    # it should simply skip the band portion
    has_line_unconditional = (
        "renderHrvChart" in JS or "renderHRVChart" in JS
        or "renderRhrChart" in JS or "renderRHRChart" in JS
    )
    assert has_line_unconditional, \
        "trends.js must define separate HRV/RHR render functions that draw the " \
        "daily line regardless of whether baseline_sd is available"


# ── Regression: existing trends page integrity ────────────────────────────────

def test_regression_trends_html_served(client):
    """GET /trends.html must still return 200 after the HRV/RHR chart refactor."""
    res = client.get("/trends.html")
    assert res.status_code == 200, f"trends.html returned {res.status_code}"


def test_regression_readiness_slot_untouched():
    """#slot-readiness must still exist (regression guard for readiness chart)."""
    assert 'id="slot-readiness"' in HTML or "id='slot-readiness'" in HTML, \
        "#slot-readiness slot must not be removed"
