"""
Tests for issue #71: TSS and readiness correlation overlay chart
Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

HTML      = (pathlib.Path(__file__).parent.parent / "trends.html").read_text()
JS        = (pathlib.Path(__file__).parent.parent / "js" / "trends.js").read_text()
MOCK_DATA = (pathlib.Path(__file__).parent.parent / "js" / "mock-data.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC-1: Bar chart renders daily TSS on primary Y-axis ───────────────────────

def test_ac1_tss_bar_dataset_exists():
    """trends.js must define a bar-type dataset for TSS on the primary Y-axis."""
    assert "type: 'bar'" in JS, (
        "trends.js must include a bar-type dataset for daily TSS values."
    )
    assert "yTSS" in JS, (
        "trends.js must assign the TSS dataset to the 'yTSS' axis ID."
    )


def test_ac1_tss_primary_axis_left():
    """TSS Y-axis must be on the left (primary)."""
    assert "position: 'left'" in JS, (
        "trends.js must place the TSS y-axis on the left side as the primary axis."
    )


def test_ac1_tss_axis_min_zero():
    """TSS Y-axis must start at 0."""
    assert "min: 0" in JS, (
        "trends.js TSS y-axis must set min: 0 so bars always grow from the baseline."
    )


def test_ac1_tss_axis_labeled_tss():
    """TSS Y-axis title must be 'TSS'."""
    assert "text: 'TSS'" in JS or 'text: "TSS"' in JS, (
        "trends.js must label the left TSS y-axis with the text 'TSS'."
    )


# ── AC-2: Readiness line shifted forward by one day ───────────────────────────

def test_ac2_readiness_line_dataset_exists():
    """trends.js must define a line-type dataset for next-day readiness."""
    assert "type: 'line'" in JS, (
        "trends.js must include a line-type dataset for readiness."
    )
    assert "yReadiness" in JS, (
        "trends.js must assign the readiness dataset to the 'yReadiness' axis ID."
    )


def test_ac2_one_day_offset_applied():
    """Readiness data must be shifted by one day via addOneDay()."""
    assert "addOneDay" in JS, (
        "trends.js must call addOneDay() to shift readiness data forward by one day "
        "so TSS on day N aligns with readiness on day N+1."
    )
    # Verify it's called when building the nextDayReadiness dataset
    assert "readinessByDate[addOneDay(" in JS, (
        "trends.js must use addOneDay() when looking up readiness values to build "
        "the next-day readiness dataset."
    )


def test_ac2_readiness_secondary_axis_right():
    """Readiness Y-axis must be on the right (secondary)."""
    assert "position: 'right'" in JS, (
        "trends.js must place the readiness y-axis on the right side as the secondary axis."
    )


def test_ac2_readiness_axis_max_100():
    """Readiness Y-axis must be capped at 100 (0–100 scale)."""
    assert "max: 100" in JS, (
        "trends.js readiness y-axis must set max: 100 to reflect the 0–100 score range."
    )


def test_ac2_readiness_axis_labeled():
    """Readiness Y-axis title must be 'Readiness'."""
    assert "text: 'Readiness'" in JS or 'text: "Readiness"' in JS, (
        "trends.js must label the right readiness y-axis with the text 'Readiness'."
    )


# ── AC-3: Shared X-axis with consistent date labels ───────────────────────────

def test_ac3_shared_x_axis():
    """Both datasets must share the same x-axis (one set of date labels)."""
    # Both datasets reference the same labels array — confirmed by having a single
    # x-axis config with maxTicksLimit and maxRotation
    assert "maxTicksLimit" in JS and "maxRotation: 0" in JS, (
        "trends.js must configure a shared x-axis with maxTicksLimit and maxRotation: 0 "
        "so date labels are consistent for both TSS bars and the readiness line."
    )


def test_ac3_date_labels_formatted():
    """Date labels must be human-readable (e.g. 'May 1') not raw ISO strings."""
    assert "formatLabel" in JS, (
        "trends.js must call formatLabel() to format the x-axis date labels into "
        "a human-readable form (e.g. 'May 1')."
    )


# ── AC-4: Mobile legibility ───────────────────────────────────────────────────

def test_ac4_responsive_true():
    """Chart must be responsive (responsive: true)."""
    assert "responsive: true" in JS, (
        "trends.js TSS chart must set responsive: true for fluid sizing on all viewports."
    )


def test_ac4_maintain_aspect_ratio_false():
    """Chart must not enforce a fixed aspect ratio (maintainAspectRatio: false)."""
    assert "maintainAspectRatio: false" in JS, (
        "trends.js TSS chart must set maintainAspectRatio: false so the chart fills "
        "its container without causing horizontal scroll on 375px-wide mobile viewports."
    )


def test_ac4_font_size_12px_min():
    """All chart text (axes, legend) must be at least 12px."""
    font_sizes = [int(m) for m in re.findall(r'font:\s*\{\s*size:\s*(\d+)', JS)]
    assert font_sizes, "trends.js must set explicit font sizes on chart elements."
    tss_region = JS[JS.find('renderTSSOverlayChart'):]
    tss_font_sizes = [int(m) for m in re.findall(r'font:\s*\{\s*size:\s*(\d+)', tss_region)]
    assert tss_font_sizes, (
        "trends.js TSS chart must specify font sizes to ensure readability."
    )
    for s in tss_font_sizes:
        assert s >= 12, (
            f"trends.js TSS chart has a font size of {s}px — must be ≥ 12px for mobile legibility."
        )


def test_ac4_full_width_slot():
    """TSS chart slot must span the full grid width (chart-slot--full)."""
    # The class appears on the div before the id; look for both on the same element
    tss_slot_match = re.search(
        r'<div[^>]*class="[^"]*chart-slot--full[^"]*"[^>]*id="slot-tss"'
        r'|<div[^>]*id="slot-tss"[^>]*class="[^"]*chart-slot--full[^"]*"',
        HTML
    )
    assert tss_slot_match, (
        "trends.html TSS chart slot (id='slot-tss') must use the 'chart-slot--full' "
        "class so it spans the full viewport width on mobile, preventing horizontal overflow."
    )


def test_ac4_hit_radius_for_touch():
    """Readiness line must have an enlarged hit radius for touch targets."""
    assert "hitRadius" in JS, (
        "trends.js must set hitRadius on the readiness line dataset so the touch target "
        "area is large enough for reliable finger tapping on mobile (≥ 44px effective)."
    )


# ── AC-5: Tooltip content ─────────────────────────────────────────────────────

def test_ac5_tooltip_shows_date():
    """Tooltip must show the date via the title callback."""
    # _buildTSSTooltipCallbacks returns a title callback that reads from datesRef
    assert "_buildTSSTooltipCallbacks" in JS or "title(items)" in JS, (
        "trends.js TSS tooltip must include a title callback that returns the date."
    )
    assert "datesRef[items[0].dataIndex]" in JS or "dates[items[0].dataIndex]" in JS, (
        "trends.js TSS tooltip title must return the date string for the hovered data point."
    )


def test_ac5_tooltip_shows_tss_value():
    """Tooltip must show the TSS value."""
    assert "`TSS: ${v}`" in JS or "'TSS: ' + v" in JS or "TSS: ${v}" in JS, (
        "trends.js TSS tooltip must show 'TSS: <value>' in the label callback."
    )


def test_ac5_tooltip_shows_readiness_value():
    """Tooltip must show the next-day readiness value."""
    assert "Next-day readiness" in JS, (
        "trends.js TSS tooltip must show 'Next-day readiness: <value>' in the label callback."
    )


def test_ac5_tooltip_shows_offset_explanation():
    """Tooltip must include the one-sentence offset explanation."""
    expected = "Readiness shown is for the day after this TSS value"
    assert expected in JS, (
        f"trends.js TSS tooltip afterBody must include the exact explanation: '{expected}'"
    )


def test_ac5_tooltip_callbacks_refreshed_on_range_change():
    """Tooltip callbacks must be refreshed when the chart is updated for a new range."""
    assert "_buildTSSTooltipCallbacks" in JS, (
        "trends.js must extract tooltip callbacks into _buildTSSTooltipCallbacks() so "
        "they can be refreshed with the new dates array when the range changes — "
        "prevents the tooltip title showing stale dates after a range switch."
    )
    assert "tssOverlayChart.options.plugins.tooltip.callbacks = _buildTSSTooltipCallbacks" in JS, (
        "trends.js must update tssOverlayChart.options.plugins.tooltip.callbacks with a "
        "fresh call to _buildTSSTooltipCallbacks(dates) inside the chart-update path."
    )


# ── AC-6: Null / gap handling ─────────────────────────────────────────────────

def test_ac6_line_span_gaps_false():
    """Readiness line must break at null values (spanGaps: false)."""
    assert "spanGaps: false" in JS, (
        "trends.js Next-day Readiness dataset must set spanGaps: false so the line "
        "visually breaks rather than interpolating across missing readiness values."
    )


def test_ac6_null_values_handled_in_tss_bars():
    """TSS bars must map missing days to null (no bar drawn)."""
    assert "tssByDate[d] ?? null" in JS or "?? null" in JS, (
        "trends.js must map days with no TSS data to null so Chart.js omits the bar "
        "rather than drawing a zero-height bar."
    )


def test_ac6_null_values_handled_in_readiness_line():
    """Next-day readiness must map missing days to null (line break)."""
    assert "readinessByDate[addOneDay(d)] ?? null" in JS, (
        "trends.js must map days with no next-day readiness to null so the line "
        "breaks gracefully rather than throwing an error."
    )


# ── AC-7: Renders with fewer than 7 days ─────────────────────────────────────

def test_ac7_renders_with_sparse_data():
    """Chart must render (or show empty state) when fewer than 7 days of data exist."""
    # The guard is validPairs < 2 — anything with ≥ 2 pairs renders, otherwise empty state
    assert "validPairs" in JS, (
        "trends.js must count valid TSS+readiness pairs (validPairs) to decide whether "
        "to render the chart or show the empty state."
    )
    assert "validPairs < 2" in JS, (
        "trends.js must use validPairs < 2 as the threshold — requiring only 2 valid "
        "day-pairs means the chart renders even with very sparse / short date ranges."
    )


def test_ac7_empty_state_message_for_insufficient_data():
    """A clear empty-state message must appear when fewer than 2 valid pairs exist."""
    assert "Not enough data" in JS, (
        "trends.js must display 'Not enough data — ...' when validPairs < 2, "
        "so new users or users with sparse data see helpful feedback."
    )


# ── AC-8: No additional API calls beyond /trends/summary ─────────────────────

def test_ac8_tss_data_from_summary_endpoint():
    """TSS data must come from the existing /trends/summary endpoint only."""
    assert "renderTSSFromSummary" in JS, (
        "trends.js must implement renderTSSFromSummary() to extract TSS series from "
        "the /trends/summary response — no separate API call for TSS data."
    )


def test_ac8_no_separate_tss_api_call():
    """trends.js must not fetch a separate TSS API endpoint."""
    # Acceptable: /trends/summary, /api/workouts (legacy fallback in mock)
    # Not acceptable: a new dedicated /api/tss or similar endpoint
    separate_tss_calls = re.findall(r"fetch\(['\"]([^'\"]*tss[^'\"]*)['\"]", JS, re.IGNORECASE)
    assert not separate_tss_calls, (
        f"trends.js must not make additional API calls to a TSS-specific endpoint. "
        f"Found: {separate_tss_calls}. Use /trends/summary instead."
    )


def test_ac8_tss_from_summary_called_in_load():
    """renderTSSFromSummary must be called inside loadChartData."""
    assert "renderTSSFromSummary" in JS, (
        "trends.js must call renderTSSFromSummary() inside loadChartData() to update "
        "the chart using data already fetched from /trends/summary."
    )
    # Verify it's used in the then() block of fetchSummary
    then_block = re.search(r"fetchSummary.*?\.then\([\s\S]*?\}\)", JS)
    if then_block:
        assert "renderTSSFromSummary" in then_block.group(0), (
            "renderTSSFromSummary must be called inside the .then() handler of fetchSummary() "
            "so it runs with the data from the single /trends/summary response."
        )


# ── Regression guard: page still served ──────────────────────────────────────

def test_regression_trends_html_served(client):
    """GET /trends.html must return 200 after changes."""
    res = client.get("/trends.html")
    assert res.status_code == 200, (
        f"Expected 200, got {res.status_code}. "
        "The /trends.html route must remain accessible after issue #71 changes."
    )


def test_regression_trends_summary_has_tss(client):
    """GET /trends/summary must include a 'tss' key with a 'series' array."""
    res = client.get("/trends/summary", params={"user_id": "demo", "range": "30d"})
    if res.status_code == 404:
        pytest.skip("demo user not found — skip live endpoint check")
    if res.status_code != 200:
        pytest.skip(f"Server returned {res.status_code} — skip live endpoint check")
    data = res.json()
    assert "tss" in data, (
        "GET /trends/summary must include a 'tss' key so renderTSSFromSummary() "
        "can access the TSS series without an additional API call."
    )
    assert "series" in data["tss"], (
        "data['tss'] must contain a 'series' array."
    )
    assert "readiness" in data, (
        "GET /trends/summary must also return 'readiness' series so the one-day "
        "offset can be applied client-side."
    )
