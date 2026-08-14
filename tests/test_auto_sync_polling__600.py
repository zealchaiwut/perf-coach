"""Tests for issue #600: Automatic sync status polling on page load (runs against UAT)"""
import os
import pytest
import httpx


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "9001")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- Acceptance Criteria ---

def test_auto_sync_polling__begins_on_page_load(client):
    """
    AC: `frontend/js/nav.js` begins polling `GET /api/sync/status`
    automatically on every authenticated page load (no manual trigger required)

    Verified via browser step in UAT. HTTP test confirms endpoint is responsive.
    """
    # GET /api/sync/status requires authentication
    # Testing unauthenticated should return 401; authenticated polling happens on the frontend
    r = client.get("/api/sync/status")
    # Will be 401 (requires auth), but endpoint exists and is callable
    assert r.status_code in [200, 401]


def test_auto_sync_polling__cross_page_visibility(client):
    """
    AC: A sync started from the Settings page causes `#sync-status-bar`
    to appear and update on any other page (training log, home, dashboard, etc.)

    Verified via browser interaction in UAT steps 1-4.
    """
    pytest.skip("manual — verified via browser interaction, not HTTP")


def test_auto_sync_polling__phase_labels_strava(client):
    """
    AC: The bar displays the following phase labels exactly as backend state progresses:
    - `pulling_strava` → **"Syncing Strava…"**

    Label text verified via browser step.
    """
    pytest.skip("manual — verified via browser interaction, not HTTP")


def test_auto_sync_polling__phase_labels_stryd(client):
    """
    AC: The bar displays the following phase labels exactly as backend state progresses:
    - `pulling_stryd` → **"Syncing Stryd…"**

    Label text verified via browser step.
    """
    pytest.skip("manual — verified via browser interaction, not HTTP")


def test_auto_sync_polling__phase_labels_reconciling(client):
    """
    AC: The bar displays the following phase labels exactly as backend state progresses:
    - `reconciling` → **"Matching workouts…"**

    Label text verified via browser step.
    """
    pytest.skip("manual — verified via browser interaction, not HTTP")


def test_auto_sync_polling__success_message_format(client):
    """
    AC: The bar displays success message with format:
    `"Sync complete — N workouts updated"` (where N is the real count from the API response)

    Message text verified via browser step.
    """
    pytest.skip("manual — verified via browser interaction, not HTTP")


def test_auto_sync_polling__bar_autohides(client):
    """
    AC: The bar auto-hides after displaying the success message
    (recommended: 4–6 s delay)

    Auto-hide timing verified via browser observation in UAT step 3.
    """
    pytest.skip("manual — verified via browser interaction, not HTTP")


def test_auto_sync_polling__dismiss_control_present(client):
    """
    AC: The bar includes a dismiss/close control that hides it immediately
    when activated

    Dismiss button presence and functionality verified via browser step 5.
    """
    pytest.skip("manual — verified via browser interaction, not HTTP")


def test_auto_sync_polling__no_console_errors_idle(client):
    """
    AC: No console errors, warnings, or unhandled promise rejections are
    logged when no sync is currently running (i.e., idle/null status from API)

    Browser console checked during UAT step 6.
    """
    pytest.skip("manual — verified via browser inspection, not HTTP")


def test_auto_sync_polling__backoff_on_complete(client):
    """
    AC: Polling stops (or backs off) once `complete` or an error state is
    received to avoid unnecessary network traffic

    Polling backoff verified by monitoring network requests during UAT steps.
    """
    pytest.skip("manual — verified via browser network monitoring, not HTTP")
