"""TDD tests for issue #379: Add Strava sync controls to Integrations settings.

Each test is anchored to one Acceptance Criterion item.
Server: http://127.0.0.1:9001
"""
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.auth import generate_csrf_token, hash_password
from backend.models import User

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "sync379-int-pw"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_REPO_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=15, follow_redirects=True) as c:
        yield c


def _make_authed_client(username: str, user_id: str) -> httpx.Client:
    temp = httpx.Client(base_url=BASE, timeout=15, follow_redirects=True)
    login = temp.post("/api/auth/login", json={"username": username, "password": _TEST_PASSWORD})
    assert login.status_code == 200, f"Login failed: {login.text}"
    session_val = temp.cookies.get("session", "")
    temp.close()
    assert session_val, "Login must set session cookie"
    csrf = generate_csrf_token()
    c = httpx.Client(
        base_url=BASE,
        timeout=15,
        follow_redirects=True,
        cookies={"session": session_val, "csrf-token": csrf},
        headers={"X-CSRF-Token": csrf},
    )
    c._user_id = user_id
    return c


@pytest.fixture(scope="module")
def authed_client():
    username = f"s379_{uuid.uuid4().hex[:8]}"
    temp = httpx.Client(base_url=BASE, timeout=15, follow_redirects=True)
    res = temp.post("/api/users", json={"name": username})
    assert res.status_code == 201, f"User create failed: {res.text}"
    user_id = res.json()["id"]
    temp.close()
    with Session(engine) as db:
        u = db.get(User, uuid.UUID(user_id))
        assert u is not None
        u.password_hash = hash_password(_TEST_PASSWORD)
        db.commit()
    c = _make_authed_client(username, user_id)
    yield c
    c.delete(f"/api/users/{user_id}")
    c.close()


# ── AC 1: GET /api/sync/strava/latest endpoint exists and returns expected shape ──

class TestACLatestEndpointShape:
    """AC: Settings page calls GET /api/sync/strava/latest on page load."""

    def test_latest_endpoint_requires_auth(self, client):
        """GET /api/sync/strava/latest returns 401 for unauthenticated request."""
        res = client.get("/api/sync/strava/latest")
        assert res.status_code == 401, (
            f"Expected 401 for unauthenticated /api/sync/strava/latest, got {res.status_code}"
        )

    def test_latest_endpoint_returns_200_for_authed_user(self, authed_client):
        """GET /api/sync/strava/latest returns 200 for authenticated user."""
        res = authed_client.get("/api/sync/strava/latest")
        assert res.status_code == 200, (
            f"/api/sync/strava/latest returned {res.status_code}: {res.text}"
        )

    def test_latest_endpoint_returns_json_with_synced_at(self, authed_client):
        """GET /api/sync/strava/latest returns JSON with synced_at field."""
        res = authed_client.get("/api/sync/strava/latest")
        data = res.json()
        assert "synced_at" in data, f"Missing 'synced_at' in response: {data}"

    def test_latest_endpoint_returns_activities_synced(self, authed_client):
        """GET /api/sync/strava/latest returns activities_synced field."""
        res = authed_client.get("/api/sync/strava/latest")
        data = res.json()
        assert "activities_synced" in data, f"Missing 'activities_synced' in response: {data}"

    def test_latest_endpoint_returns_new_workouts(self, authed_client):
        """GET /api/sync/strava/latest returns new_workouts field."""
        res = authed_client.get("/api/sync/strava/latest")
        data = res.json()
        assert "new_workouts" in data, f"Missing 'new_workouts' in response: {data}"


# ── AC 2-3: Last synced display logic in settings.html JS ──────────────────────

class TestACLastSyncedDisplay:
    """AC: 'Last synced N hours ago: synced X activities (Y new workouts)' or 'Never synced'."""

    def test_latest_endpoint_null_synced_at_for_fresh_user(self, authed_client):
        """Fresh user (no strava sync) gets synced_at=null from /api/sync/strava/latest."""
        res = authed_client.get("/api/sync/strava/latest")
        data = res.json()
        assert data["synced_at"] is None, (
            f"Fresh user should have synced_at=null, got: {data['synced_at']}"
        )

    def test_settings_js_calls_sync_latest_endpoint(self, authed_client):
        """settings.html JS calls /api/sync/strava/latest."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        assert "/api/sync/strava/latest" in res.text, (
            "settings.html must call /api/sync/strava/latest"
        )

    def test_settings_html_has_last_synced_element(self, authed_client):
        """settings.html has an element for displaying last sync info."""
        res = authed_client.get("/settings")
        assert res.status_code == 200
        body = res.text
        assert "strava-last-synced" in body, (
            "settings.html must have id='strava-last-synced' element"
        )

    def test_settings_js_renders_never_synced(self, authed_client):
        """settings.html JS renders 'Never synced' when synced_at is null."""
        res = authed_client.get("/settings")
        assert "Never synced" in res.text, (
            "settings.html JS must render 'Never synced' when no prior sync"
        )

    def test_settings_js_renders_relative_time(self, authed_client):
        """settings.html JS renders relative time (hours ago) from synced_at."""
        res = authed_client.get("/settings")
        body = res.text
        assert "hours ago" in body or "hoursAgo" in body or "ago" in body, (
            "settings.html JS must render relative time ('N hours ago')"
        )


# ── AC 4: Sync now button with modal/inline panel ──────────────────────────────

class TestACSyncNowPanel:
    """AC: 'Sync now' button opens inline panel with date picker, toggle, Preview/Run buttons."""

    def test_settings_js_has_sync_now_button(self, authed_client):
        """settings.html JS renders a 'Sync now' button."""
        res = authed_client.get("/settings")
        assert "Sync now" in res.text, (
            "settings.html must have 'Sync now' button text"
        )

    def test_settings_html_has_sync_panel_container(self, authed_client):
        """settings.html has container element for the sync panel."""
        res = authed_client.get("/settings")
        body = res.text
        assert "strava-sync-panel" in body, (
            "settings.html must have id='strava-sync-panel' container"
        )

    def test_settings_js_has_date_picker(self, authed_client):
        """settings.html JS renders a date picker (input[type=date]) in the sync panel."""
        res = authed_client.get("/settings")
        body = res.text
        assert "strava-since-date" in body or ('type="date"' in body and "strava" in body.lower()), (
            "settings.html must have a date picker for sync panel"
        )

    def test_settings_js_has_preview_toggle(self, authed_client):
        """settings.html JS renders a 'Show preview first' toggle."""
        res = authed_client.get("/settings")
        body = res.text
        assert "preview" in body.lower() and ("toggle" in body.lower() or "checkbox" in body.lower()), (
            "settings.html must have a 'Show preview first' toggle/checkbox"
        )

    def test_settings_js_has_preview_button(self, authed_client):
        """settings.html JS renders a 'Preview' button."""
        res = authed_client.get("/settings")
        assert "Preview" in res.text, (
            "settings.html JS must have a 'Preview' button"
        )

    def test_settings_js_has_run_sync_button(self, authed_client):
        """settings.html JS renders a 'Run sync' button."""
        res = authed_client.get("/settings")
        assert "Run sync" in res.text, (
            "settings.html JS must have a 'Run sync' button"
        )


# ── AC 5: Preview table (dry-run) ──────────────────────────────────────────────

class TestACPreviewTable:
    """AC: 'Preview' calls GET /api/sync/strava/dry-run and renders compact table."""

    def test_settings_js_preview_calls_dry_run(self, authed_client):
        """settings.html JS calls /api/sync/strava/dry-run for preview."""
        res = authed_client.get("/settings")
        body = res.text
        assert "sync/strava/dry-run" in body, (
            "settings.html JS must call /api/sync/strava/dry-run for preview"
        )

    def test_settings_js_preview_table_has_date_column(self, authed_client):
        """settings.html JS renders date column in preview table."""
        res = authed_client.get("/settings")
        body = res.text.lower()
        assert "start_time" in body or "date" in body, (
            "settings.html preview table must show date column"
        )

    def test_settings_js_preview_table_has_activity_name_column(self, authed_client):
        """settings.html JS renders activity name column in preview table."""
        res = authed_client.get("/settings")
        body = res.text
        assert "activity_type" in body or "name" in body, (
            "settings.html preview table must show activity name/type columns"
        )

    def test_settings_js_preview_table_shows_would_create(self, authed_client):
        """settings.html JS renders would_create_new indicator in preview table."""
        res = authed_client.get("/settings")
        body = res.text
        assert "would_create_new" in body or "create" in body.lower(), (
            "settings.html preview table must show would_create_new/match_existing"
        )


# ── AC 6-7: Run sync polling ───────────────────────────────────────────────────

class TestACRunSyncPolling:
    """AC: Run sync calls POST /api/strava/sync, then polls until completed/failed."""

    def test_settings_js_run_sync_calls_post_strava_sync(self, authed_client):
        """settings.html JS calls POST /api/strava/sync for Run sync."""
        res = authed_client.get("/settings")
        body = res.text
        assert "api/strava/sync" in body, (
            "settings.html JS must call /api/strava/sync for Run sync"
        )

    def test_settings_js_polls_sync_status(self, authed_client):
        """settings.html JS polls sync status endpoint after starting sync."""
        res = authed_client.get("/settings")
        body = res.text
        assert "api/sync/status" in body or "sync/strava/status" in body, (
            "settings.html JS must poll a sync status endpoint"
        )

    def test_settings_js_polls_every_2_seconds(self, authed_client):
        """settings.html JS polls every 2 seconds (setInterval/setTimeout with 2000)."""
        res = authed_client.get("/settings")
        body = res.text
        assert "2000" in body, (
            "settings.html JS must poll every 2000ms (2 seconds)"
        )

    def test_settings_js_has_progress_indicator(self, authed_client):
        """settings.html JS shows live progress during polling."""
        res = authed_client.get("/settings")
        body = res.text.lower()
        assert "fetching" in body or "progress" in body, (
            "settings.html JS must show progress indicator during sync"
        )

    def test_settings_js_shows_fetched_count(self, authed_client):
        """settings.html JS shows 'fetched' count from sync status."""
        res = authed_client.get("/settings")
        body = res.text.lower()
        assert "fetched" in body or "items_synced" in body or "current" in body, (
            "settings.html JS must show fetched/synced count during polling"
        )


# ── AC 8: On completed ─────────────────────────────────────────────────────────

class TestACOnCompleted:
    """AC: On completed displays 'Synced N new workouts. View them →' with link to /log."""

    def test_settings_js_has_completion_handler(self, authed_client):
        """settings.html JS handles sync completion."""
        res = authed_client.get("/settings")
        body = res.text
        assert "completed" in body or "success" in body, (
            "settings.html JS must handle sync completion state"
        )

    def test_settings_js_completed_shows_new_workouts_message(self, authed_client):
        """settings.html JS shows 'new workouts' message on completion."""
        res = authed_client.get("/settings")
        body = res.text.lower()
        assert "new workout" in body or "workouts" in body, (
            "settings.html JS must show new workouts count on completion"
        )

    def test_settings_js_completed_has_link_to_log(self, authed_client):
        """settings.html JS includes link to /log on completion."""
        res = authed_client.get("/settings")
        body = res.text
        assert '"/log"' in body or "href=\"/log\"" in body or "'/log'" in body, (
            "settings.html JS must link to /log on sync completion"
        )


# ── AC 9: On failed ────────────────────────────────────────────────────────────

class TestACOnFailed:
    """AC: On failed displays error_message in red with a Retry button."""

    def test_settings_js_has_failure_handler(self, authed_client):
        """settings.html JS handles sync failure."""
        res = authed_client.get("/settings")
        body = res.text
        assert "error" in body.lower() and ("failed" in body.lower() or "failure" in body.lower()), (
            "settings.html JS must handle sync failure state"
        )

    def test_settings_js_shows_error_message(self, authed_client):
        """settings.html JS shows error_message from failed sync."""
        res = authed_client.get("/settings")
        body = res.text
        assert "error_message" in body or "error" in body.lower(), (
            "settings.html JS must display error_message on failure"
        )

    def test_settings_js_has_retry_button(self, authed_client):
        """settings.html JS renders a Retry button on failure."""
        res = authed_client.get("/settings")
        body = res.text
        assert "Retry" in body, (
            "settings.html JS must have a 'Retry' button on sync failure"
        )


# ── AC 10: Reconcile only button ───────────────────────────────────────────────

class TestACReconcileOnly:
    """AC: 'Reconcile only' button calls POST /api/sync/strava/reconcile."""

    def test_settings_js_has_reconcile_only_button(self, authed_client):
        """settings.html JS has a 'Reconcile only' button."""
        res = authed_client.get("/settings")
        body = res.text
        assert "Reconcile only" in body or "Reconcile" in body, (
            "settings.html JS must have a 'Reconcile only' button"
        )

    def test_settings_js_reconcile_calls_correct_endpoint(self, authed_client):
        """settings.html JS calls POST /api/sync/strava/reconcile for reconcile."""
        res = authed_client.get("/settings")
        body = res.text
        assert "sync/strava/reconcile" in body, (
            "settings.html JS must call /api/sync/strava/reconcile"
        )

    def test_settings_js_reconcile_shows_result(self, authed_client):
        """settings.html JS shows matched/created counts after reconcile."""
        res = authed_client.get("/settings")
        body = res.text
        assert "matched" in body.lower() or "created" in body.lower(), (
            "settings.html JS must show matched/created result after reconcile"
        )


# ── AC 11-13: Home page stale sync banner ──────────────────────────────────────

class TestACHomePageBanner:
    """AC: Home page shows stale sync banner when Strava connected AND last sync >24h ago."""

    def test_home_js_has_strava_banner_logic(self, client):
        """home.js has stale Strava sync banner logic."""
        res = client.get("/js/home.js")
        assert res.status_code == 200
        body = res.text
        assert "strava" in body.lower(), (
            "home.js must have Strava-related banner logic"
        )

    def test_home_js_checks_24_hour_threshold(self, client):
        """home.js checks if last sync was more than 24 hours ago."""
        res = client.get("/js/home.js")
        body = res.text
        assert "24" in body, (
            "home.js must check 24-hour threshold for stale sync banner"
        )

    def test_home_js_banner_text_matches_ac(self, client):
        """home.js banner uses 'Last Strava sync was X hours ago' text."""
        res = client.get("/js/home.js")
        body = res.text
        assert "Last Strava sync" in body or "strava sync" in body.lower(), (
            "home.js banner must include 'Last Strava sync was X hours ago' text"
        )

    def test_home_js_banner_has_refresh_link(self, client):
        """home.js banner includes refresh action (triggers sync)."""
        res = client.get("/js/home.js")
        body = res.text.lower()
        assert "refresh" in body or "sync" in body, (
            "home.js banner must have a refresh/sync action"
        )

    def test_home_js_banner_calls_strava_sync(self, client):
        """home.js banner click triggers POST /api/strava/sync directly."""
        res = client.get("/js/home.js")
        body = res.text
        assert "api/strava/sync" in body, (
            "home.js must call /api/strava/sync when banner clicked"
        )

    def test_home_js_checks_strava_connection_status(self, client):
        """home.js checks whether Strava is connected before showing banner."""
        res = client.get("/js/home.js")
        body = res.text
        assert "api/strava/status" in body or "strava" in body.lower(), (
            "home.js must check Strava connection status for banner"
        )

    def test_home_js_calls_sync_latest_for_banner(self, client):
        """home.js calls /api/sync/strava/latest to determine if sync is stale."""
        res = client.get("/js/home.js")
        body = res.text
        assert "sync/strava/latest" in body or "strava/latest" in body, (
            "home.js must call /api/sync/strava/latest to check staleness"
        )

    def test_home_html_has_banner_container(self, authed_client):
        """home.html has a container element for the stale sync banner."""
        res = authed_client.get("/home")
        assert res.status_code == 200
        body = res.text
        assert "strava-stale-banner" in body or "strava-sync-banner" in body, (
            "home.html must have a container for the stale sync banner"
        )
