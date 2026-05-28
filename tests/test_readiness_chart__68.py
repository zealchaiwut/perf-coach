"""
Tests for issue #68: Readiness-Over-Time Chart with 7-Day Rolling Average
Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

HTML = (pathlib.Path(__file__).parent.parent / "trends.html").read_text()
JS   = (pathlib.Path(__file__).parent.parent / "js" / "trends.js").read_text()
MOCK = (pathlib.Path(__file__).parent.parent / "js" / "mock-data.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC-0: Regression guard ────────────────────────────────────────────────────

def test_ac0_trends_page_accessible(client):
    """GET /trends.html must return 200."""
    res = client.get("/trends.html")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"


# ── AC-1: Chart slot exists full-width on Trends page ────────────────────────

def test_ac1_readiness_slot_present():
    """trends.html must contain the readiness chart slot."""
    assert 'id="slot-readiness"' in HTML or "slot-readiness" in HTML, \
        "trends.html must have a slot with id='slot-readiness'"


def test_ac1_readiness_slot_is_full_width():
    """Readiness slot must be full-width (chart-slot--full) to span both grid columns."""
    assert "chart-slot--full" in HTML, \
        "trends.html readiness slot must use chart-slot--full to span the full grid width"
    slot_section = re.search(r'id="slot-readiness"[^>]*>|class="[^"]*slot-readiness[^"]*"', HTML)
    assert slot_section or "slot-readiness" in HTML, \
        "trends.html must contain the readiness chart slot"


def test_ac1_readiness_title_present():
    """Readiness slot must have a descriptive title visible to users."""
    assert "Readiness" in HTML, \
        "trends.html readiness slot must display a 'Readiness' title"


def test_ac1_subtitle_describes_both_series():
    """Readiness slot subtitle must mention the rolling average start condition."""
    assert "7-day" in HTML or "rolling" in HTML.lower(), \
        "trends.html readiness slot subtitle must mention 7-day rolling average"


def test_ac1_y_axis_min_max_configured():
    """Chart.js y-axis must be configured with min:0 and max:100."""
    assert "min: 0" in JS or "min:0" in JS, \
        "trends.js readiness chart y-axis must have min: 0"
    assert "max: 100" in JS or "max:100" in JS, \
        "trends.js readiness chart y-axis must have max: 100"


# ── AC-2: Two distinct lines — raw scores and 7-day rolling average ───────────

def test_ac2_two_datasets_defined():
    """Readiness chart must define at least two datasets (raw + rolling avg)."""
    dataset_count = JS.count("label: '") + JS.count('label: "')
    assert dataset_count >= 2, \
        "trends.js must define at least 2 datasets for the readiness chart"


def test_ac2_raw_line_standard_weight():
    """Raw readiness line must use borderWidth: 2 (standard stroke)."""
    assert "borderWidth: 2" in JS or "borderWidth:2" in JS, \
        "trends.js raw readiness dataset must use borderWidth: 2"


def test_ac2_rolling_avg_heavier_stroke():
    """Rolling average line must use a heavier stroke than the raw line."""
    assert "borderWidth: 2.5" in JS or "borderWidth:2.5" in JS or "borderWidth: 3" in JS, \
        "trends.js rolling average dataset must use a heavier borderWidth than the raw line"


def test_ac2_rolling_avg_visually_distinct():
    """Rolling average line must use borderDash to be visually distinct."""
    assert "borderDash" in JS, \
        "trends.js rolling average dataset must use borderDash for visual distinction"


# ── AC-3: Rolling average starts only after 7 days ───────────────────────────

def test_ac3_rolling_avg_suppressed_before_day_7():
    """Rolling average must return null for the first 6 indices (days 0–5)."""
    assert "i < 6" in JS or "i<6" in JS, \
        "trends.js compute7DayRollingAvg must return null for i < 6 so the line starts only at day 7"


def test_ac3_rolling_avg_guard_for_short_ranges():
    """Rolling average line must not render when fewer than 7 dates are in the view."""
    assert "length >= 7" in JS or "length>=7" in JS or ">= 7" in JS, \
        "trends.js must guard showAvg with a length >= 7 check"


def test_ac3_window_size_is_7():
    """Rolling average window must span exactly 7 days."""
    assert "slice(i - 6, i + 1)" in JS or "i - 6" in JS, \
        "trends.js compute7DayRollingAvg must slice a 7-element window (i-6 to i)"


# ── AC-4: Missing data renders as gaps ────────────────────────────────────────

def test_ac4_raw_line_span_gaps_false():
    """Raw readiness line must use spanGaps: false so missing days appear as gaps."""
    assert "spanGaps: false" in JS or "spanGaps:false" in JS, \
        "trends.js raw readiness dataset must have spanGaps: false"


def test_ac4_null_scores_not_zeroed():
    """Scores for missing days must be null, not zero."""
    assert "null" in JS and ("=== null" in JS or "!== null" in JS or ": null" in JS), \
        "trends.js must preserve null for missing readiness days (not coerce to 0)"


def test_ac4_null_values_in_mock_series():
    """Mock data must include null readiness entries to exercise gap rendering."""
    null_scores = re.findall(r"readiness_score:\s*null", MOCK)
    assert len(null_scores) >= 1, \
        "js/mock-data.js must contain at least one null readiness_score to test gap rendering"


# ── AC-5: Color-coded background bands ───────────────────────────────────────

def test_ac5_band_plugin_registered():
    """trends.js must register a Chart.js plugin that draws background color bands."""
    assert "beforeDraw" in JS, \
        "trends.js must define a Chart.js plugin with a beforeDraw hook for color bands"


def test_ac5_green_band_at_70():
    """Green band must start at y=70 (Sprint 8 threshold)."""
    assert "70" in JS and ("green" in JS.lower() or "22, 163, 74" in JS or "rgba(22" in JS), \
        "trends.js color band plugin must define the green band starting at 70"


def test_ac5_amber_band_40_to_70():
    """Amber band must span y=40 to y=70."""
    assert "40" in JS and ("amber" in JS.lower() or "orange" in JS.lower()
                           or "217, 119, 6" in JS or "f59e0b" in JS.lower()), \
        "trends.js color band plugin must define the amber band between 40 and 70"


def test_ac5_red_band_below_40():
    """Red band must cover y=0 to y=40."""
    assert ("red" in JS.lower() or "220, 38, 38" in JS or "dc2626" in JS.lower()
            or "rgba(220" in JS), \
        "trends.js color band plugin must define a red band below 40"


def test_ac5_three_bands_total():
    """Exactly three bands (red, amber, green) must be defined."""
    band_entries = re.findall(r"\{\s*from:", JS)
    assert len(band_entries) >= 3, \
        f"trends.js color band plugin must define 3 bands (red/amber/green); found {len(band_entries)}"


# ── AC-6: Tooltip content ─────────────────────────────────────────────────────

def test_ac6_tooltip_shows_date():
    """Tooltip title callback must return the ISO date string."""
    assert "title" in JS and ("dates[" in JS or "date" in JS.lower()), \
        "trends.js tooltip callbacks must include a title() that returns the date"


def test_ac6_tooltip_shows_raw_score():
    """Tooltip label callback must render the raw readiness score."""
    assert "Readiness:" in JS or "Readiness" in JS, \
        "trends.js tooltip label callback must display the raw readiness score"


def test_ac6_tooltip_shows_rolling_avg():
    """Tooltip afterBody must include the rolling average value."""
    assert "7-day avg" in JS or "7-day average" in JS, \
        "trends.js tooltip must show '7-day avg' in the afterBody"


def test_ac6_tooltip_missing_data_flag():
    """Tooltip must show a missing-data flag on days where raw score is null."""
    assert "Missing data" in JS or "missing" in JS.lower(), \
        "trends.js tooltip must display a missing-data flag (e.g. '⚠ Missing data') on null days"


def test_ac6_missing_flag_only_on_null_days():
    """Missing-data flag must be conditional on scores[idx] === null."""
    assert "scores[idx] === null" in JS or "scores[idx]==null" in JS or \
           ("scores[" in JS and "=== null" in JS), \
        "trends.js must gate the missing-data flag on the raw score being null"


def test_ac6_interaction_mode_index():
    """Chart.js interaction mode must be 'index' so gap-day tooltips can be triggered."""
    assert "mode: 'index'" in JS or "mode:'index'" in JS or 'mode: "index"' in JS, \
        "trends.js readiness chart interaction mode must be 'index' so tooltips fire on gap days"


# ── AC-7: Data sourced from /trends/summary → readiness.series ───────────────

def test_ac7_reads_readiness_series_from_summary():
    """trends.js must read summary.readiness.series as the data source."""
    assert "readiness.series" in JS or ("readiness" in JS and "series" in JS), \
        "trends.js must consume summary.readiness.series for readiness chart data"


def test_ac7_mock_get_trends_summary_in_mock_data():
    """js/mock-data.js must define mockGetTrendsSummary with a readiness.series field."""
    assert "mockGetTrendsSummary" in MOCK, \
        "js/mock-data.js must define mockGetTrendsSummary (the /trends/summary mock)"
    assert "readiness" in MOCK and "series" in MOCK, \
        "mockGetTrendsSummary must return an object with a readiness.series array"


def test_ac7_no_direct_readiness_api_call():
    """Readiness chart must NOT call /api/readiness directly — only via /trends/summary."""
    # Ensure the data path goes through the summary mock, not a separate endpoint
    assert "mockGetTrendsSummary" in JS or "fetchSummary" in JS, \
        "trends.js must fetch readiness data through mockGetTrendsSummary / fetchSummary"


# ── AC-8: Mobile responsiveness ──────────────────────────────────────────────

def test_ac8_responsive_true():
    """Chart.js config must set responsive: true."""
    assert "responsive: true" in JS or "responsive:true" in JS, \
        "trends.js Chart.js config must set responsive: true"


def test_ac8_maintain_aspect_ratio_false():
    """Chart.js config must set maintainAspectRatio: false for fluid sizing."""
    assert "maintainAspectRatio: false" in JS or "maintainAspectRatio:false" in JS, \
        "trends.js Chart.js config must set maintainAspectRatio: false"


def test_ac8_max_ticks_limit_on_x_axis():
    """X-axis must cap tick labels so they stay legible on narrow screens."""
    assert "maxTicksLimit" in JS, \
        "trends.js must set maxTicksLimit on the x-axis to prevent label overflow on mobile"


def test_ac8_chart_slot_full_spans_grid():
    """Readiness chart slot must span both grid columns via chart-slot--full."""
    assert "chart-slot--full" in HTML, \
        "trends.html readiness slot must use chart-slot--full for full-width layout on mobile"


def test_ac8_viewport_meta_present():
    """trends.html must have a viewport meta tag for proper mobile scaling."""
    assert 'name="viewport"' in HTML, \
        "trends.html must include <meta name='viewport'> for mobile rendering"


# ── AC-9: Empty state when no data ───────────────────────────────────────────

def test_ac9_empty_state_on_all_null():
    """Readiness slot must show an empty state when all scores in the range are null."""
    assert "showEmpty" in JS or "slot-empty" in JS or "slot-empty" in HTML, \
        "trends.js must call showEmpty when all readiness scores for the range are null"


def test_ac9_empty_banner_element_present():
    """trends.html must contain a page-level empty banner for when all charts have no data."""
    assert "trends-empty-banner" in HTML or "empty-banner" in HTML, \
        "trends.html must have an empty-state banner element for the no-data case"
