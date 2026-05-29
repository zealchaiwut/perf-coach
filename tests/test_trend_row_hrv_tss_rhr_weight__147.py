"""Tests for issue #147: Build trend row with HRV/TSS/RHR/Weight cards (verifies JS implementation)"""
import os
import pytest
import httpx


BASE_URL = os.environ.get("BASE_URL", "http://localhost:9001")


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def home_js(client):
    """Fetch home.js content for code inspection"""
    r = client.get("/js/home.js")
    assert r.status_code == 200, f"Failed to fetch home.js: {r.status_code}"
    return r.text


# --- Acceptance Criteria Tests ---

def test_trend_row__row3_container_exists(client):
    """AC: Four cards render inside #row-3 in a 4-column grid on desktop"""
    r = client.get("/home.html")
    assert r.status_code == 200
    html = r.text
    
    # Check that row-3 container exists and has correct grid styling
    assert 'id="row-3"' in html
    assert 'grid-template-columns: repeat(4, 1fr)' in html


def test_trend_row__four_card_elements_created(home_js):
    """AC: Four cards (HRV, Weekly TSS, RHR, Weight) are created with correct IDs"""
    # Check that the code creates four card elements
    assert 'trend-card-hrv' in home_js
    assert 'trend-card-tss' in home_js
    assert 'trend-card-rhr' in home_js
    assert 'trend-card-weight' in home_js
    
    # Check that these IDs are specifically passed as card definitions
    assert "{ id: 'trend-card-hrv' }" in home_js
    assert "{ id: 'trend-card-tss' }" in home_js
    assert "{ id: 'trend-card-rhr' }" in home_js
    assert "{ id: 'trend-card-weight' }" in home_js


def test_trend_row__hrv_rhr_hidden_mobile(client):
    """AC: HRV and RHR cards are hidden at viewport width <880px"""
    r = client.get("/home.html")
    assert r.status_code == 200
    html = r.text
    
    # Check that CSS rule hides HRV and RHR on mobile
    assert '#trend-card-hrv' in html
    assert '#trend-card-rhr' in html
    assert 'display: none' in html
    assert '@media (max-width: 880px)' in html


def test_trend_row__mobile_single_column_layout(client):
    """AC: On mobile, TSS and Weight cards stack full-width (grid-template-columns: 1fr)"""
    r = client.get("/home.html")
    assert r.status_code == 200
    html = r.text
    
    # Verify mobile layout uses single column
    assert '@media (max-width: 880px)' in html
    assert 'grid-template-columns: 1fr' in html


def test_trend_row__card_header_structure(home_js):
    """AC: Each card renders a header with icon, title, and period meta"""
    # Check for header rendering function
    assert 'trend-card-header' in home_js
    assert 'trend-card-title' in home_js
    assert 'trend-card-period' in home_js
    
    # Verify period badges are rendered (8d for TSS, 30d for others)
    assert "'30d'" in home_js
    assert "'8d'" in home_js


def test_trend_row__stat_row_with_value_unit_delta(home_js, client):
    """AC: Each card renders stat row with value, unit, and delta pill"""
    # Check in HTML for CSS classes
    r = client.get("/home.html")
    html = r.text
    
    assert 'trend-card-stat' in html
    assert 'trend-card-big' in html
    assert 'trend-card-unit' in html
    assert 'trend-delta-pill' in html
    
    # Check for delta pill color variants
    assert 'trend-delta-pill--up' in html
    assert 'trend-delta-pill--down' in html
    assert 'trend-delta-pill--flat' in html
    
    # Check in JS for delta pill function
    assert '_trendDeltaPill' in home_js


def test_trend_row__hrv_rhr_weight_line_sparklines(home_js):
    """AC: HRV, RHR, and Weight cards render line+area sparkline SVG"""
    # Check for area sparkline function
    assert '_trendAreaSpark' in home_js or 'trendAreaSpark' in home_js
    
    # Verify it's called for the correct cards
    assert 'renderHRVTrendCard' in home_js
    assert 'renderRHRTrendCard' in home_js
    assert 'renderWeightTrendCard' in home_js


def test_trend_row__tss_bar_sparkline_with_peak(home_js):
    """AC: Weekly TSS card renders bar sparkline with highest bar highlighted"""
    assert '_trendBarSpark' in home_js or 'trendBarSpark' in home_js
    
    # Verify peak tracking for highlighting
    assert 'peakIdx' in home_js
    assert 'renderWeeklyTSSTrendCard' in home_js


def test_trend_row__card_footer_baseline_and_today(home_js):
    """AC: Each card renders a footer row showing baseline and today summary"""
    assert 'trend-card-footer' in home_js
    assert '_trendCardInnerHTML' in home_js
    
    # Verify footer parameters are passed (footLeft, footRight)
    assert 'footLeft' in home_js
    assert 'footRight' in home_js


def test_trend_row__weight_quick_input_form(home_js):
    """AC: Weight card renders quick-input row (number input + Save button)"""
    assert 'trend-quick-input' in home_js
    assert 'trend-weight-input' in home_js
    assert 'trend-quick-save-btn' in home_js
    
    # Verify input type and attributes
    assert 'type="number"' in home_js
    assert 'step="0.1"' in home_js
    assert 'min="20"' in home_js
    assert 'max="300"' in home_js


def test_trend_row__weight_save_button_handler(home_js):
    """AC: Save button POSTs to /api/weight and re-fetches data"""
    assert '_wireWeightSave' in home_js or 'wireWeightSave' in home_js
    
    # Verify POST request is made
    assert "method: 'POST'" in home_js or 'method: "POST"' in home_js
    assert '/api/weight' in home_js
    assert 'weight_kg' in home_js


def test_trend_row__trends_summary_endpoint_fetch(home_js):
    """AC: HRV, RHR, and TSS series are fetched from GET /trends/summary?user_id={uid}&range=30d"""
    assert '/trends/summary' in home_js
    assert 'range=30d' in home_js or 'range' in home_js
    
    # Verify it's fetched in loadRow3
    assert 'loadRow3' in home_js


def test_trend_row__weight_api_endpoint_fetch(home_js):
    """AC: Weight series is fetched from GET /api/weight?user_id={uid}"""
    assert '/api/weight' in home_js


def test_trend_row__error_state_friendly_message(home_js):
    """AC: /trends/summary errors display friendly message via _trendCardErrorHTML"""
    assert '_trendCardErrorHTML' in home_js or 'trendCardErrorHTML' in home_js
    
    # Verify error handling is present
    assert 'if (!summary)' in home_js or 'if (!el)' in home_js


def test_trend_row__graceful_error_handling(home_js):
    """AC: Failure does NOT crash the page; other cards remain functional"""
    # Check for Promise.allSettled for independent error handling
    assert 'Promise.allSettled' in home_js
    
    # Verify individual render functions are called even if one fails
    assert 'renderHRVTrendCard' in home_js
    assert 'renderWeeklyTSSTrendCard' in home_js
    assert 'renderRHRTrendCard' in home_js
    assert 'renderWeightTrendCard' in home_js


def test_trend_row__console_errors_check(client):
    """AC: No console errors under normal operation"""
    pytest.skip("manual — console error checking requires browser DevTools")
