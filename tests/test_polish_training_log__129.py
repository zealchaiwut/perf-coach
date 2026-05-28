"""
Tests for issue #129: Polish Training Log — skeletons, errors, edit actions, mobile.
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


# ── Skeleton CSS ──────────────────────────────────────────────────────────────

def test_log_html_has_skeleton_shimmer_animation(client):
    """log.html must define @keyframes skeleton-shimmer for loading animation."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "skeleton-shimmer" in res.text, (
        "log.html must define @keyframes skeleton-shimmer for list/panel loading animation"
    )


def test_log_html_has_skeleton_row_class(client):
    """log.html must define .skeleton-row for list loading placeholder."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "skeleton-row" in res.text, (
        "log.html must define .skeleton-row CSS for list skeleton rows"
    )


def test_log_html_has_skeleton_stat_grid_class(client):
    """log.html must define .skeleton-stat-grid for detail panel loading."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "skeleton-stat-grid" in res.text, (
        "log.html must define .skeleton-stat-grid CSS for detail panel loading"
    )


# ── List error state ──────────────────────────────────────────────────────────

def test_log_html_has_list_error_element(client):
    """log.html must include #log-error-msg for list-level API error state."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="log-error-msg"' in res.text, (
        "log.html must include #log-error-msg for list error state"
    )


def test_log_html_list_error_initially_hidden(client):
    """#log-error-msg must be hidden with display:none on page load."""
    res = client.get("/log")
    assert res.status_code == 200
    idx = res.text.index('id="log-error-msg"')
    surrounding = res.text[max(0, idx - 30):idx + 80]
    assert "display:none" in surrounding, (
        "#log-error-msg must have display:none on initial load"
    )


def test_log_html_list_error_has_retry_button(client):
    """The list error state must include a retry button."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="log-retry-btn"' in res.text, (
        "log.html must include #log-retry-btn inside the list error state"
    )


# ── Detail panel loading skeleton ─────────────────────────────────────────────

def test_log_html_has_detail_panel_loading(client):
    """log.html must include #detail-panel-loading for the panel skeleton state."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-panel-loading"' in res.text, (
        "log.html must include #detail-panel-loading for detail panel loading skeleton"
    )


def test_log_html_detail_panel_loading_initially_hidden(client):
    """#detail-panel-loading must be hidden with display:none on page load."""
    res = client.get("/log")
    assert res.status_code == 200
    idx = res.text.index('id="detail-panel-loading"')
    surrounding = res.text[max(0, idx - 30):idx + 80]
    assert "display:none" in surrounding, (
        "#detail-panel-loading must have display:none on initial load"
    )


# ── Detail panel error state ──────────────────────────────────────────────────

def test_log_html_has_detail_panel_error(client):
    """log.html must include #detail-panel-error for the panel error state."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-panel-error"' in res.text, (
        "log.html must include #detail-panel-error for detail panel error state"
    )


def test_log_html_detail_panel_error_initially_hidden(client):
    """#detail-panel-error must be hidden with display:none on page load."""
    res = client.get("/log")
    assert res.status_code == 200
    idx = res.text.index('id="detail-panel-error"')
    surrounding = res.text[max(0, idx - 30):idx + 80]
    assert "display:none" in surrounding, (
        "#detail-panel-error must have display:none on initial load"
    )


# ── Empty state ───────────────────────────────────────────────────────────────

def test_log_html_has_empty_state_element(client):
    """log.html must include #log-empty-msg for the zero-workouts empty state."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="log-empty-msg"' in res.text, (
        "log.html must include #log-empty-msg for the empty state"
    )


def test_log_html_empty_state_initially_hidden(client):
    """#log-empty-msg must be hidden with display:none on page load."""
    res = client.get("/log")
    assert res.status_code == 200
    idx = res.text.index('id="log-empty-msg"')
    surrounding = res.text[max(0, idx - 30):idx + 80]
    assert "display:none" in surrounding, (
        "#log-empty-msg must have display:none on initial load"
    )


def test_log_html_empty_state_has_cta(client):
    """The empty state must contain a #log-empty-cta call-to-action button."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="log-empty-cta"' in res.text, (
        "log.html must include #log-empty-cta inside the empty state"
    )


# ── Detail panel action buttons ───────────────────────────────────────────────

def test_log_html_has_detail_edit_btn(client):
    """log.html must include #detail-edit-btn in the detail panel footer."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-edit-btn"' in res.text, (
        "log.html must include #detail-edit-btn in the detail panel footer"
    )


def test_log_html_has_detail_strava_btn(client):
    """log.html must include #detail-strava-btn in the detail panel footer."""
    res = client.get("/log")
    assert res.status_code == 200
    assert 'id="detail-strava-btn"' in res.text, (
        "log.html must include #detail-strava-btn in the detail panel footer"
    )


def test_log_html_strava_btn_initially_hidden(client):
    """#detail-strava-btn must be hidden with display:none by default (shown only when strava_activity_url is present)."""
    res = client.get("/log")
    assert res.status_code == 200
    idx = res.text.index('id="detail-strava-btn"')
    surrounding = res.text[max(0, idx - 30):idx + 80]
    assert "display:none" in surrounding, (
        "#detail-strava-btn must be hidden by default; only shown when workout has strava_activity_url"
    )


# ── JS error handling ─────────────────────────────────────────────────────────

def test_training_log_js_defines_render_list_error(client):
    """training-log.js must define renderListError() for the list error state."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "renderListError" in res.text, (
        "training-log.js must define renderListError() to handle list API failures"
    )


def test_training_log_js_references_detail_panel_loading(client):
    """training-log.js must reference detail-panel-loading to show/hide panel skeleton."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "detail-panel-loading" in res.text, (
        "training-log.js must toggle detail-panel-loading visibility during detail fetch"
    )


def test_training_log_js_references_detail_panel_error(client):
    """training-log.js must reference detail-panel-error to show panel error state."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "detail-panel-error" in res.text, (
        "training-log.js must toggle detail-panel-error visibility on detail fetch failure"
    )


def test_training_log_js_hides_panel_loading_on_success(client):
    """training-log.js must set detail-panel-loading display to 'none' after content loads."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    src = res.text
    assert "detail-panel-loading" in src
    assert "'none'" in src or '"none"' in src, (
        "training-log.js must set detail-panel-loading display to 'none' after successful fetch"
    )


def test_training_log_js_checks_strava_activity_url(client):
    """training-log.js must check strava_activity_url to conditionally show the Strava button."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "strava_activity_url" in res.text, (
        "training-log.js must read workout.strava_activity_url to control Strava button visibility"
    )


def test_training_log_js_links_edit_to_workout_edit(client):
    """training-log.js must set the Edit button href to /workout-edit/{id}."""
    res = client.get("/js/training-log.js")
    assert res.status_code == 200
    assert "workout-edit" in res.text, (
        "training-log.js must link the Edit button to /workout-edit/{id}"
    )


# ── CSS classes ───────────────────────────────────────────────────────────────

def test_log_html_has_empty_state_css(client):
    """log.html must define .empty-state CSS class."""
    res = client.get("/log")
    assert res.status_code == 200
    assert ".empty-state" in res.text, (
        "log.html must define .empty-state CSS for the empty state container"
    )


def test_log_html_has_list_error_state_css(client):
    """log.html must define .list-error-state CSS class."""
    res = client.get("/log")
    assert res.status_code == 200
    assert ".list-error-state" in res.text, (
        "log.html must define .list-error-state CSS for the list error visual treatment"
    )


def test_log_html_has_detail_error_state_css(client):
    """log.html must define .detail-error-state CSS class."""
    res = client.get("/log")
    assert res.status_code == 200
    assert ".detail-error-state" in res.text, (
        "log.html must define .detail-error-state CSS for the detail panel error treatment"
    )


def test_log_html_has_detail_panel_footer_css(client):
    """log.html must define .detail-panel-footer CSS for the action button row."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "detail-panel-footer" in res.text, (
        "log.html must define .detail-panel-footer CSS for the Edit/Strava button footer"
    )


# ── Mobile layout ─────────────────────────────────────────────────────────────

def test_log_html_has_mobile_media_query(client):
    """log.html must include a @media (max-width: 599px) block for mobile layout."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "max-width: 599px" in res.text or "max-width:599px" in res.text, (
        "log.html must include a @media (max-width: 599px) block for mobile layout"
    )


def test_log_html_week_pills_overflow_auto(client):
    """log.html must set overflow-x: auto on .week-pills to make week strip scrollable."""
    res = client.get("/log")
    assert res.status_code == 200
    assert "overflow-x: auto" in res.text or "overflow-x:auto" in res.text, (
        "log.html must set overflow-x: auto on .week-pills to prevent overflow at 375px"
    )


def test_log_html_mobile_detail_panel_full_width(client):
    """On mobile the detail panel must cover the full screen (width: 100%)."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    mobile_idx = src.rfind("max-width: 599px")
    if mobile_idx == -1:
        mobile_idx = src.rfind("max-width:599px")
    assert mobile_idx != -1, "Mobile media query must exist"
    mobile_section = src[mobile_idx:mobile_idx + 1000]
    assert "detail-panel" in mobile_section and "100%" in mobile_section, (
        "The detail panel must be set to width: 100% inside the mobile media query"
    )


def test_log_html_mobile_close_btn_tap_target(client):
    """The detail close button must have a 44px tap target inside the mobile media query."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    mobile_idx = src.rfind("max-width: 599px")
    if mobile_idx == -1:
        mobile_idx = src.rfind("max-width:599px")
    assert mobile_idx != -1, "Mobile media query must exist"
    mobile_section = src[mobile_idx:mobile_idx + 1000]
    assert "detail-close-btn" in mobile_section, (
        ".detail-close-btn must be styled inside the mobile media query"
    )
    close_idx = mobile_section.find("detail-close-btn")
    surrounding = mobile_section[close_idx:close_idx + 200]
    assert "44px" in surrounding, (
        ".detail-close-btn must have a 44px dimension in the mobile media query for tap target"
    )


def test_log_html_main_nav_scrollable_on_mobile(client):
    """log.html must make .main-nav overflow-x scrollable on mobile to prevent page overflow."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    mobile_idx = src.rfind("max-width: 599px")
    if mobile_idx == -1:
        mobile_idx = src.rfind("max-width:599px")
    assert mobile_idx != -1, "Mobile media query must exist"
    mobile_section = src[mobile_idx:mobile_idx + 600]
    assert "main-nav" in mobile_section and "overflow-x" in mobile_section, (
        ".main-nav must have overflow-x set in the mobile media query to prevent page overflow at 375px"
    )


def test_log_html_mobile_hides_workout_primary_metric(client):
    """log.html must hide .workout-primary-metric on mobile to reduce row overflow."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    mobile_idx = src.rfind("max-width: 599px")
    if mobile_idx == -1:
        mobile_idx = src.rfind("max-width:599px")
    assert mobile_idx != -1, "Mobile media query must exist"
    mobile_section = src[mobile_idx:mobile_idx + 1000]
    assert "workout-primary-metric" in mobile_section, (
        ".workout-primary-metric must be hidden inside the mobile media query"
    )
    pm_idx = mobile_section.find("workout-primary-metric")
    surrounding = mobile_section[pm_idx:pm_idx + 80]
    assert "display: none" in surrounding or "display:none" in surrounding, (
        ".workout-primary-metric must be set to display:none in the mobile media query"
    )


def test_log_html_mobile_hides_source_pill(client):
    """log.html must hide .source-pill on mobile to keep rows compact."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    mobile_idx = src.rfind("max-width: 599px")
    if mobile_idx == -1:
        mobile_idx = src.rfind("max-width:599px")
    assert mobile_idx != -1, "Mobile media query must exist"
    mobile_section = src[mobile_idx:mobile_idx + 1000]
    assert "source-pill" in mobile_section, (
        ".source-pill must be hidden inside the mobile media query"
    )


def test_log_html_mobile_day_pill_reduced_size(client):
    """log.html must set a reduced min-width for .day-pill inside the mobile media query."""
    res = client.get("/log")
    assert res.status_code == 200
    src = res.text
    mobile_idx = src.rfind("max-width: 599px")
    if mobile_idx == -1:
        mobile_idx = src.rfind("max-width:599px")
    assert mobile_idx != -1, "Mobile media query must exist"
    mobile_section = src[mobile_idx:mobile_idx + 1200]
    assert "day-pill" in mobile_section, (
        ".day-pill must be resized inside the mobile media query to fit at 375px"
    )


# ── API shape ─────────────────────────────────────────────────────────────────

def test_workout_detail_unknown_id_returns_404(client):
    """GET /api/workouts/{id} with a nonexistent UUID must return 404."""
    fake_id = str(uuid.uuid4())
    res = client.get(f"/api/workouts/{fake_id}")
    assert res.status_code == 404, (
        f"Unknown workout id must return 404, got {res.status_code}"
    )


def test_workout_detail_includes_strava_url_field(client):
    """GET /api/workouts/{id} response must include the strava_activity_url field."""
    res = client.get(
        "/api/training-log",
        params={"user_id": ALICE_USER_ID, "from": "2020-01-01", "to": "2030-12-31"},
    )
    assert res.status_code == 200
    weeks = res.json().get("weeks", [])
    for week in weeks:
        for entry in week.get("entries", []):
            if entry.get("type") != "rest" and entry.get("id"):
                workout_id = entry["id"]
                detail_res = client.get(f"/api/workouts/{workout_id}")
                assert detail_res.status_code == 200
                body = detail_res.json()
                assert "strava_activity_url" in body, (
                    "Workout detail response must include strava_activity_url field"
                )
                return
    pytest.skip("No workouts available for Alice to test strava_activity_url field")


def test_training_log_bad_date_returns_4xx(client):
    """GET /api/training-log with invalid date params must return 4xx."""
    res = client.get(
        "/api/training-log",
        params={"user_id": ALICE_USER_ID, "from": "not-a-date", "to": "also-bad"},
    )
    assert res.status_code in range(400, 500), (
        f"Invalid date params must return 4xx, got {res.status_code}"
    )
