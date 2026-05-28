"""
Tests for issue #119: Polish Training Log — loading, errors, empty state, mobile QA.
Runs against UAT environment (http://localhost:9001)
"""
import os
import uuid

import httpx
import pytest


BASE = os.environ.get("UAT_BASE_URL") or f"http://localhost:{os.environ.get('UAT_PORT', '9001')}"
if not BASE.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

ALICE_USER_ID = "2898f7d7-e2f9-4125-871d-cc4fd5cb40ff"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


# ── AC: /api/training-log returns structured error for bad params ──────────────

def test_training_log_bad_date_range_returns_4xx(client):
    """GET /api/training-log with invalid date params must return 4xx, not 500 or 200."""
    res = client.get("/api/training-log", params={"user_id": ALICE_USER_ID, "from": "not-a-date", "to": "also-not"})
    assert res.status_code in range(400, 500), (
        f"Invalid date params should produce a 4xx response, got {res.status_code}"
    )


def test_training_log_missing_user_id_returns_valid_response(client):
    """GET /api/training-log without user_id returns a well-formed weeks response (user_id is Optional by design)."""
    res = client.get("/api/training-log", params={"from": "2024-01-01", "to": "2024-12-31"})
    assert res.status_code == 200, (
        f"Missing user_id should return 200 with empty weeks list, got {res.status_code}"
    )
    body = res.json()
    assert "weeks" in body, "Response must contain a 'weeks' key even when user_id is absent"


# ── AC: /api/workouts/{id} returns 404 for unknown workout ────────────────────

def test_workout_detail_unknown_id_returns_404(client):
    """GET /api/workouts/{id} with a nonexistent ID must return 404."""
    fake_id = str(uuid.uuid4())
    res = client.get(f"/api/workouts/{fake_id}")
    assert res.status_code == 404, (
        f"Unknown workout id must return 404, got {res.status_code}"
    )


# ── AC: HTML contains error state elements for the workout list ───────────────

def test_log_html_has_list_error_element(client):
    """log.html must contain #log-error-msg for displaying list-level API errors."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="log-error-msg"' in res.text, (
        "log.html must include an element with id='log-error-msg' for list error state"
    )


def test_log_html_error_element_initially_hidden(client):
    """#log-error-msg must be hidden by default (style='display:none')."""
    res = client.get("/log")
    assert res.status_code == 200
    # Verify the error element is hidden by default
    assert 'id="log-error-msg"' in res.text
    idx = res.text.index('id="log-error-msg"')
    surrounding = res.text[max(0, idx - 20):idx + 120]
    assert "display:none" in surrounding or 'style="display:none"' in res.text[res.text.index('id="log-error-msg"'):res.text.index('id="log-error-msg"') + 60], (
        "#log-error-msg must be hidden on page load"
    )


# ── AC: HTML contains detail panel loading and error states ──────────────────

def test_log_html_has_detail_panel_loading(client):
    """log.html must contain #detail-panel-loading for panel loading skeleton."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-panel-loading"' in res.text, (
        "log.html must include #detail-panel-loading for detail panel loading state"
    )


def test_log_html_has_detail_panel_error(client):
    """log.html must contain #detail-panel-error for panel error state."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-panel-error"' in res.text, (
        "log.html must include #detail-panel-error for detail panel error state"
    )


def test_log_html_detail_loading_initially_hidden(client):
    """#detail-panel-loading must be hidden on initial page load."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-panel-loading"' in res.text
    idx = res.text.index('id="detail-panel-loading"')
    surrounding = res.text[max(0, idx - 30):idx + 80]
    assert "display:none" in surrounding, (
        "#detail-panel-loading must be hidden on initial page load"
    )


def test_log_html_detail_error_initially_hidden(client):
    """#detail-panel-error must be hidden on initial page load."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-panel-error"' in res.text
    idx = res.text.index('id="detail-panel-error"')
    surrounding = res.text[max(0, idx - 30):idx + 80]
    assert "display:none" in surrounding, (
        "#detail-panel-error must be hidden on initial page load"
    )


# ── AC: HTML contains a proper empty state ───────────────────────────────────

def test_log_html_has_empty_state_element(client):
    """log.html must contain #log-empty-msg for empty state rendering."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="log-empty-msg"' in res.text, (
        "log.html must include #log-empty-msg for empty state"
    )


def test_log_html_empty_state_has_cta(client):
    """The empty state must include a call-to-action button to log a workout."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="log-empty-cta"' in res.text, (
        "log.html must include #log-empty-cta button in the empty state"
    )


def test_log_html_empty_state_initially_hidden(client):
    """#log-empty-msg must be hidden by default."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="log-empty-msg"' in res.text
    idx = res.text.index('id="log-empty-msg"')
    surrounding = res.text[max(0, idx - 30):idx + 80]
    assert "display:none" in surrounding, (
        "#log-empty-msg must be hidden on initial page load"
    )


# ── AC: HTML contains skeleton loading CSS ───────────────────────────────────

def test_log_html_has_skeleton_row_css(client):
    """log.html must define .skeleton-row for list loading animation."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "skeleton-row" in res.text, (
        "log.html must define .skeleton-row CSS for list loading skeleton"
    )


def test_log_html_has_skeleton_stat_grid_css(client):
    """log.html must define .skeleton-stat-grid for detail panel loading."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "skeleton-stat-grid" in res.text, (
        "log.html must define .skeleton-stat-grid CSS for detail panel loading"
    )


def test_log_html_has_skeleton_shimmer_animation(client):
    """log.html must define the skeleton-shimmer @keyframes animation."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "skeleton-shimmer" in res.text, (
        "log.html must define @keyframes skeleton-shimmer for loading animation"
    )


# ── AC: Detail panel footer buttons are present ──────────────────────────────

def test_log_html_has_detail_edit_btn(client):
    """log.html must include #detail-edit-btn in the detail panel footer."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-edit-btn"' in res.text, (
        "log.html must include #detail-edit-btn (required by training-log.js)"
    )


def test_log_html_has_detail_strava_btn(client):
    """log.html must include #detail-strava-btn in the detail panel footer."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-strava-btn"' in res.text, (
        "log.html must include #detail-strava-btn (required by training-log.js)"
    )


# ── AC: JS error handling for training-log API ───────────────────────────────

def test_training_log_js_shows_error_on_api_failure(client):
    """training-log.js must call renderListError() when the API request fails."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "renderListError" in res.text, (
        "training-log.js must define and call renderListError() to handle API failures"
    )


def test_training_log_js_no_mock_fallback_on_error(client):
    """training-log.js must not fall back to mock data silently on API error."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    # The catch block in applyFilters must not call mockFetch
    # Find the applyFilters catch block and ensure mockFetch is not the fallback
    catch_idx = src.find("} catch (_) {")
    assert catch_idx != -1, "applyFilters must have a catch block"
    catch_block = src[catch_idx:catch_idx + 200]
    assert "mockFetch" not in catch_block, (
        "applyFilters catch block must not silently fall back to mockFetch — it must show an error"
    )


def test_training_log_js_shows_panel_loading_state(client):
    """training-log.js must toggle #detail-panel-loading visibility during fetch."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "detail-panel-loading" in res.text, (
        "training-log.js must reference detail-panel-loading to show/hide panel loading state"
    )


def test_training_log_js_shows_panel_error_state(client):
    """training-log.js must toggle #detail-panel-error visibility on fetch failure."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "detail-panel-error" in res.text, (
        "training-log.js must reference detail-panel-error to show panel error state"
    )


def test_training_log_js_hides_loading_on_success(client):
    """training-log.js must hide #detail-panel-loading after successful fetch."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    # After fetch success, loading should be hidden
    assert "detail-panel-loading" in src
    # Verify loading is set to none in the success handler
    assert "'none'" in src or '"none"' in src, (
        "training-log.js must set detail-panel-loading display to 'none' after content loads"
    )


# ── AC: Mobile layout — CSS supports small viewports ─────────────────────────

def test_log_html_has_mobile_media_query(client):
    """log.html must include a mobile media query at max-width: 599px."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "max-width: 599px" in res.text or "max-width:599px" in res.text, (
        "log.html must include a @media (max-width: 599px) block for mobile layout"
    )


def test_log_html_week_pills_overflow_auto(client):
    """log.html must set overflow-x: auto on .week-pills for small viewports."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "overflow-x: auto" in res.text or "overflow-x:auto" in res.text, (
        "log.html must set overflow-x: auto on .week-pills to prevent page overflow at 375px"
    )


def test_log_html_mobile_hides_primary_metric(client):
    """log.html must hide .workout-primary-metric inside the mobile media query."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    assert "workout-primary-metric" in src, (
        "log.html must reference .workout-primary-metric in CSS (should hide on mobile)"
    )
    # Search within the mobile media query block, not the first (desktop) occurrence
    mobile_idx = src.rfind("max-width: 599px")
    if mobile_idx == -1:
        mobile_idx = src.rfind("max-width:599px")
    assert mobile_idx != -1, "Mobile media query must exist"
    mobile_section = src[mobile_idx:mobile_idx + 1000]
    assert "workout-primary-metric" in mobile_section, (
        ".workout-primary-metric must appear inside the mobile media query"
    )
    pm_idx = mobile_section.find("workout-primary-metric")
    surrounding = mobile_section[pm_idx:pm_idx + 80]
    assert "display: none" in surrounding or "display:none" in surrounding, (
        ".workout-primary-metric must be set to display:none in the mobile media query to avoid overflow"
    )


def test_log_html_mobile_hides_source_pill(client):
    """log.html must hide .source-pill on mobile to reduce row width."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    idx = src.find(".source-pill { display: none") if ".source-pill { display: none" in src else src.find("source-pill")
    assert idx != -1, "log.html must hide .source-pill on mobile"


def test_log_html_mobile_day_pill_size(client):
    """log.html must set a reduced min-width for .day-pill on mobile (≤44px) to fit 7 pills at 375px."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    # Check that in the mobile media query, day-pill has a smaller min-width than the default 46px
    assert "day-pill" in src
    # Find mobile section
    mobile_idx = src.rfind("max-width: 599px")
    if mobile_idx == -1:
        mobile_idx = src.rfind("max-width:599px")
    assert mobile_idx != -1, "Mobile media query must exist"
    mobile_section = src[mobile_idx:mobile_idx + 500]
    assert "day-pill" in mobile_section, (
        ".day-pill must be resized in the mobile media query to fit all 7 pills at 375px"
    )


def test_log_html_main_nav_scrollable_on_mobile(client):
    """log.html must make .main-nav scrollable on mobile to prevent page overflow."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    mobile_idx = src.rfind("max-width: 599px")
    if mobile_idx == -1:
        mobile_idx = src.rfind("max-width:599px")
    assert mobile_idx != -1
    mobile_section = src[mobile_idx:mobile_idx + 600]
    assert "main-nav" in mobile_section and ("overflow-x" in mobile_section or "overflow" in mobile_section), (
        ".main-nav must be scrollable in the mobile media query to contain nav overflow at 375px"
    )


# ── AC: Consistent visual design ─────────────────────────────────────────────

def test_log_html_empty_state_css(client):
    """log.html must define .empty-state CSS class for the empty state container."""
    res = client.get("/log")
    assert res.status_code == 200
    assert ".empty-state" in res.text, (
        "log.html must define .empty-state CSS for the empty state visual treatment"
    )


def test_log_html_list_error_state_css(client):
    """log.html must define .list-error-state CSS class for the list error state."""
    res = client.get("/log")
    assert res.status_code == 200
    assert ".list-error-state" in res.text, (
        "log.html must define .list-error-state CSS for the list error visual treatment"
    )


def test_log_html_detail_error_state_css(client):
    """log.html must define .detail-error-state CSS class for the panel error state."""
    res = client.get("/log")
    assert res.status_code == 200
    assert ".detail-error-state" in res.text, (
        "log.html must define .detail-error-state CSS for the detail panel error treatment"
    )


def test_log_html_detail_panel_footer_css(client):
    """log.html must define .detail-panel-footer CSS for the action buttons."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "detail-panel-footer" in res.text, (
        "log.html must define .detail-panel-footer CSS (was missing after feature/116 merge)"
    )
