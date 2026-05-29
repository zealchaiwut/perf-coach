"""
Tests for issue #47: Trends chart — daily readiness score with 7-day rolling average
Server under test: http://127.0.0.1:9001
"""
import pathlib
import re

import httpx
import pytest

BASE = "http://127.0.0.1:9001"

HTML = (pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "trends.html").read_text()
JS   = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "trends.js").read_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC-0: Trends page must still be accessible (regression guard) ─────────────

def test_ac0_trends_html_served(client):
    """GET /trends.html must return 200 — regression guard from issue #46."""
    res = client.get("/trends.html")
    assert res.status_code == 200, (
        f"Expected 200, got {res.status_code}. "
        "The /trends.html route was removed from backend/main.py — this is a regression."
    )


def test_ac0_trends_route_served(client):
    """GET /trends must return 200 — regression guard from issue #46."""
    res = client.get("/trends")
    assert res.status_code == 200, (
        f"Expected 200, got {res.status_code}. "
        "The /trends route was removed from backend/main.py — this is a regression."
    )


# ── AC-1: Chart.js and dependencies loaded ────────────────────────────────────

def test_ac1_chartjs_cdn_loaded():
    """trends.html must load Chart.js via CDN."""
    assert "chart.js" in HTML.lower() or "Chart.js" in HTML, \
        "trends.html must include Chart.js via CDN <script> tag"


def test_ac1_mock_data_js_loaded():
    """trends.html must load js/mock-data.js before trends.js."""
    mock_pos  = HTML.find("mock-data.js")
    trends_pos = HTML.find("js/trends.js")
    assert mock_pos != -1, "trends.html must load js/mock-data.js"
    assert mock_pos < trends_pos, \
        "js/mock-data.js must be loaded before js/trends.js so MOCK_READINESS is available"


def test_ac1_readiness_api_fetch_in_js():
    """trends.js must call GET /api/readiness with from and to query params."""
    assert "/api/readiness" in JS, \
        "trends.js must fetch from /api/readiness"
    assert "from=" in JS or '"from"' in JS, \
        "trends.js must pass a 'from' query param to /api/readiness"
    assert "to=" in JS or '"to"' in JS, \
        "trends.js must pass a 'to' query param to /api/readiness"


def test_ac1_fetch_called_in_js():
    """trends.js must use the Fetch API to call the readiness endpoint."""
    assert "fetch(" in JS or "fetch`" in JS, \
        "trends.js must use fetch() to call /api/readiness"


# ── AC-2: 7-day rolling average computed client-side ─────────────────────────

def test_ac2_rolling_avg_function_exists():
    """trends.js must define a function to compute the 7-day rolling average."""
    assert "compute7DayRollingAvg" in JS or "rollingAvg" in JS or "rolling" in JS.lower(), \
        "trends.js must define a rolling average computation function"


def test_ac2_rolling_avg_window_size_7():
    """Rolling average must use a 7-day window."""
    assert "7" in JS and ("rolling" in JS.lower() or "avg" in JS.lower() or "average" in JS.lower()), \
        "trends.js rolling average must use a 7-day window"


def test_ac2_rolling_avg_only_drawn_with_7_days():
    """Rolling average line must only be drawn when ≥ 7 days of history are in the view."""
    # The implementation should guard showAvg with a length->=7 check
    assert "length >= 7" in JS or "length>=7" in JS or ">= 7" in JS, \
        "trends.js must only draw the rolling average when the date range has ≥ 7 days"


def test_ac2_rolling_avg_visually_distinct():
    """Rolling average dataset must be visually distinct from the raw readiness line."""
    # Distinct: either a dash pattern (borderDash) or a different border weight
    assert "borderDash" in JS or "borderWidth" in JS, \
        "trends.js rolling average dataset must be visually distinct (borderDash or different borderWidth)"
    assert "borderDash" in JS, \
        "trends.js rolling average dataset must use borderDash to be visually distinct from the raw line"


# ── AC-3: Missing data renders as gaps ────────────────────────────────────────

def test_ac3_span_gaps_false_on_raw_dataset():
    """Main readiness dataset must use spanGaps: false so missing days show as gaps."""
    assert "spanGaps" in JS, \
        "trends.js must set spanGaps on the raw readiness dataset"
    assert "spanGaps: false" in JS or "spanGaps:false" in JS, \
        "trends.js raw readiness dataset must have spanGaps: false to render gaps for missing data"


def test_ac3_null_used_for_missing_days():
    """trends.js must map missing days to null (not 0) in the scores array."""
    assert ": null" in JS or "=== null" in JS or "!== null" in JS or "null" in JS, \
        "trends.js must use null for missing readiness data points (not zero or interpolated values)"


def test_ac3_full_date_range_built():
    """trends.js must build the full date range and align scores to it."""
    assert "buildDateRange" in JS or "dateRange" in JS or "dates" in JS, \
        "trends.js must build a full date range and align readiness scores to it"


# ── AC-4: Tooltip ─────────────────────────────────────────────────────────────

def test_ac4_tooltip_callbacks_defined():
    """trends.js must define tooltip callbacks for the readiness chart."""
    assert "tooltip" in JS and "callbacks" in JS, \
        "trends.js must define tooltip callbacks for the readiness chart"


def test_ac4_tooltip_shows_date():
    """Tooltip must include the date."""
    assert "title" in JS, \
        "trends.js tooltip callbacks must include a title (date) callback"


def test_ac4_tooltip_shows_readiness_score():
    """Tooltip must show the raw readiness score."""
    assert "Readiness" in JS or "readiness" in JS, \
        "trends.js tooltip must show the readiness score label"


def test_ac4_tooltip_shows_rolling_avg():
    """Tooltip must show the 7-day rolling average when available."""
    assert "7-day avg" in JS or "7-day average" in JS or "7day" in JS.lower(), \
        "trends.js tooltip must show the 7-day rolling average value"


def test_ac4_touch_interaction_mode():
    """Chart.js interaction must be configured to work on touch devices."""
    # 'nearest' mode with intersect:false enables touch-friendly tooltips
    assert "nearest" in JS, \
        "trends.js Chart.js interaction mode must be 'nearest' for touch-device support"
    assert "intersect: false" in JS or "intersect:false" in JS, \
        "trends.js Chart.js interaction must set intersect: false for mobile tooltip support"


# ── AC-5: Color bands ─────────────────────────────────────────────────────────

def test_ac5_color_band_plugin_exists():
    """trends.js must define a Chart.js plugin for y-axis color bands."""
    assert "beforeDraw" in JS or "bandPlugin" in JS or "Bands" in JS or "bands" in JS, \
        "trends.js must define a Chart.js plugin that draws color bands on the y-axis"


def test_ac5_three_bands_defined():
    """Color bands must cover red, amber (orange), and green thresholds."""
    has_green  = "green" in JS.lower() or "22, 163, 74" in JS or "#16a34a" in JS.lower() or "rgba(22" in JS
    has_amber  = "amber" in JS.lower() or "orange" in JS.lower() or "217, 119, 6" in JS or "f59e0b" in JS.lower()
    has_red    = "red" in JS.lower() or "220, 38, 38" in JS or "dc2626" in JS.lower() or "rgba(220" in JS
    assert has_green,  "trends.js color band plugin must include a green band"
    assert has_amber,  "trends.js color band plugin must include an amber/orange band"
    assert has_red,    "trends.js color band plugin must include a red band"


def test_ac5_thresholds_match_sprint8():
    """Color band thresholds must match Sprint 8 readiness card: red<40, amber 40-69, green≥70."""
    # Green starts at 70
    assert "70" in JS, \
        "trends.js must use 70 as the green threshold boundary (matching Sprint 8)"
    # Amber/red boundary at 40
    assert "40" in JS, \
        "trends.js must use 40 as the amber/red threshold boundary (matching Sprint 8)"


# ── AC-6: Date-range integration ──────────────────────────────────────────────

def test_ac6_load_chart_data_uses_range_state():
    """loadChartData must be called with the current range state."""
    assert "loadChartData" in JS or "loadChart" in JS, \
        "trends.js must define a loadChartData function that accepts range state"


def test_ac6_resolve_date_window_exists():
    """trends.js must resolve the from/to date window from the range state."""
    assert "resolveDateWindow" in JS or ("from" in JS and "to" in JS), \
        "trends.js must convert the range state into from/to date boundaries"


def test_ac6_chart_updates_on_range_change():
    """Chart must update when the date range changes."""
    assert "applyRangeState" in JS, \
        "trends.js must call applyRangeState (which calls loadChartData) when range changes"
    assert "loadChartData" in JS, \
        "trends.js must reload chart data when the range state changes"


# ── AC-7: Mobile rendering ────────────────────────────────────────────────────

def test_ac7_responsive_chart_config():
    """Chart.js config must set responsive: true."""
    assert "responsive: true" in JS or "responsive:true" in JS, \
        "trends.js Chart.js config must set responsive: true"


def test_ac7_maintain_aspect_ratio_false():
    """Chart.js config must set maintainAspectRatio: false to allow fluid sizing."""
    assert "maintainAspectRatio: false" in JS or "maintainAspectRatio:false" in JS, \
        "trends.js Chart.js config must set maintainAspectRatio: false for responsive sizing"


def test_ac7_canvas_sizing_css_in_html():
    """trends.html must define CSS to size the canvas within its slot."""
    has_canvas_css = (
        "canvas" in HTML and
        ("width" in HTML or "height" in HTML)
    )
    assert has_canvas_css, \
        "trends.html must include CSS to size the Chart.js canvas within its slot"


def test_ac7_chart_slot_body_min_height():
    """chart-slot-body must have a min-height so the chart has room to render."""
    slot_body_css = re.search(r'\.chart-slot-body\s*\{([^}]+)\}', HTML, re.DOTALL)
    assert slot_body_css, "Missing .chart-slot-body CSS block"
    block = slot_body_css.group(1)
    assert "min-height" in block, \
        ".chart-slot-body must define a min-height so Chart.js canvas has room to render"


def test_ac7_max_tick_limit_for_narrow_screens():
    """Chart.js x-axis must limit ticks so labels stay legible on narrow screens."""
    assert "maxTicksLimit" in JS or "maxTicks" in JS, \
        "trends.js must set maxTicksLimit on the x-axis to keep labels readable on small screens"


# ── AC-8: Empty state when no data ───────────────────────────────────────────

def test_ac8_empty_state_when_no_data():
    """trends.js must show the empty state when the API returns no readiness data."""
    assert "showEmpty" in JS or "empty" in JS.lower(), \
        "trends.js must call showEmpty when no readiness data is available for the range"


def test_ac8_has_any_data_guard():
    """trends.js must check whether any data was returned before rendering the chart."""
    assert "hasAnyData" in JS or "some(" in JS or "length === 0" in JS or ".length" in JS, \
        "trends.js must guard against rendering the chart when no data is present"


# ── AC-9: Mock data fallback ───────────────────────────────────────────────────

def test_ac9_mock_fallback_on_api_error():
    """trends.js must fall back to MOCK_READINESS when the API request fails."""
    assert "catch" in JS, \
        "trends.js must catch API fetch errors and fall back to mock data"
    assert "MOCK_READINESS" in JS or "mock" in JS.lower(), \
        "trends.js must reference MOCK_READINESS as a fallback data source"


def test_ac9_mock_readiness_defined_in_mock_data_js():
    """js/mock-data.js must define MOCK_READINESS with at least 7 entries."""
    mock_js = (pathlib.Path(__file__).parent.parent / "frontend" / "js" / "mock-data.js").read_text()
    assert "MOCK_READINESS" in mock_js, \
        "js/mock-data.js must define the MOCK_READINESS constant"
    entries = re.findall(r"readiness_score", mock_js)
    assert len(entries) >= 7, \
        f"MOCK_READINESS must have ≥ 7 entries (for rolling average); found {len(entries)}"
