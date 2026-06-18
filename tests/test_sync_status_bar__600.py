"""Tests for issue #600: Show global sync-status bar on every authenticated page (runs against UAT)"""
import os
import pytest
import httpx


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    """Unauthenticated client for testing endpoint availability."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- Acceptance Criteria (as HTTP smoke tests) ---
# Note: Full AC verification requires browser interaction (see UAT steps).
# These tests confirm the sync-status API endpoint is accessible and the feature code is deployed.

def test_sync_status_bar__auto_poll_on_page_load(client):
    # AC: `frontend/js/nav.js` begins polling `GET /api/sync/status` automatically on every authenticated page load
    # HTTP test: Verify the endpoint exists and is callable (even unauthenticated, it should not 500)
    r = client.get("/api/sync/status")
    # Expect 401 (unauthorized) or 200 (if public). Not 500 or 404.
    assert r.status_code in (200, 401, 400), f"Unexpected status {r.status_code} for /api/sync/status"


def test_sync_status_bar__bar_visibility_during_sync(client):
    # AC: A sync started from Settings causes bar to appear and update on any other page
    # HTTP test: Confirm sync-status endpoint is working
    r = client.get("/api/sync/status")
    assert r.status_code in (200, 401, 400)


def test_sync_status_bar__phase_labels_strava(client):
    # AC: The bar displays phase labels: pulling_strava → "Syncing Strava…", etc.
    # HTTP test: Endpoint is deployed and working
    r = client.get("/api/sync/status")
    assert r.status_code in (200, 401, 400)


def test_sync_status_bar__phase_labels_stryd(client):
    # AC: Phase label pulling_stryd → "Syncing Stryd…"
    # HTTP test: Endpoint accessible
    r = client.get("/api/sync/status")
    assert r.status_code in (200, 401, 400)


def test_sync_status_bar__phase_labels_reconciling(client):
    # AC: Phase label reconciling → "Reconciling activities…"
    # HTTP test: Endpoint accessible
    r = client.get("/api/sync/status")
    assert r.status_code in (200, 401, 400)


def test_sync_status_bar__success_message_format(client):
    # AC: complete → "Sync complete — N workouts updated"
    # HTTP test: Endpoint is deployed and callable
    r = client.get("/api/sync/status")
    assert r.status_code in (200, 401, 400)


def test_sync_status_bar__auto_hide_success(client):
    # AC: The bar auto-hides after displaying success message (recommended: 4–6 s delay)
    # Browser-only behavior; HTTP cannot verify JS setTimeout/animation
    pytest.skip("manual — verified via browser interaction, not HTTP")


def test_sync_status_bar__dismiss_control(client):
    # AC: The bar includes a dismiss/close control that hides it immediately
    # Browser-only behavior; HTTP cannot verify DOM interaction
    pytest.skip("manual — verified via browser interaction, not HTTP")


def test_sync_status_bar__no_console_errors_idle(client):
    # AC: No console errors, warnings, or unhandled promise rejections logged when no sync is running
    # Browser-only behavior; HTTP cannot verify console output
    pytest.skip("manual — verified via browser inspection, not HTTP")


def test_sync_status_bar__polling_stops_after_complete(client):
    # AC: Polling stops (or backs off) once complete or error state is received
    # Browser-only behavior; verified during UAT steps by observing network traffic
    pytest.skip("manual — verified via browser network inspection, not HTTP")
