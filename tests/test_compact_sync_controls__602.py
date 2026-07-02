"""TDD tests for issue #602: Add compact sync controls with real last-sync times.

Each test class is anchored to one Acceptance Criterion item.
Integration tests hit a live server at http://127.0.0.1:9001.
"""
import uuid

import httpx
import pytest
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.auth import generate_csrf_token, hash_password
from backend.models import User
from tests._admin_helpers import admin_cookies as _admin_cookies

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "sync602-int-pw"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_REPO_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


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
    username = f"s602_{uuid.uuid4().hex[:8]}"
    temp = httpx.Client(base_url=BASE, timeout=15, follow_redirects=True)
    res = temp.post("/api/users", json={"name": username}, cookies=_admin_cookies())
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
    c.delete(f"/api/users/{user_id}", cookies=_admin_cookies())
    c.close()


# ── AC: strava latest endpoint returns synced_at ──────────────────────────────

class TestACStravaLatestEndpoint:
    """AC: Last-sync times are fetched from GET /api/sync/strava/latest on page load."""

    def test_requires_auth(self, client):
        """GET /api/sync/strava/latest returns 401 for unauthenticated request."""
        res = client.get("/api/sync/strava/latest")
        assert res.status_code == 401, f"Expected 401, got {res.status_code}"

    def test_returns_200_authed(self, authed_client):
        """GET /api/sync/strava/latest returns 200 for authenticated user."""
        res = authed_client.get("/api/sync/strava/latest")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

    def test_returns_synced_at_field(self, authed_client):
        """GET /api/sync/strava/latest response includes synced_at (may be null)."""
        res = authed_client.get("/api/sync/strava/latest")
        data = res.json()
        assert "synced_at" in data, f"Missing synced_at in {data}"

    def test_fresh_user_returns_null_synced_at(self, authed_client):
        """A user who has never synced gets synced_at=null."""
        res = authed_client.get("/api/sync/strava/latest")
        data = res.json()
        assert data["synced_at"] is None, (
            f"Fresh user should have synced_at=null, got {data['synced_at']}"
        )


# ── AC: stryd latest endpoint returns synced_at ───────────────────────────────

class TestACStrydLatestEndpoint:
    """AC: Last-sync times are fetched from GET /api/sync/stryd/latest on page load."""

    def test_requires_auth(self, client):
        """GET /api/sync/stryd/latest returns 401 for unauthenticated request."""
        res = client.get("/api/sync/stryd/latest")
        assert res.status_code == 401, f"Expected 401, got {res.status_code}"

    def test_returns_200_authed(self, authed_client):
        """GET /api/sync/stryd/latest returns 200 for authenticated user."""
        res = authed_client.get("/api/sync/stryd/latest")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

    def test_returns_synced_at_field(self, authed_client):
        """GET /api/sync/stryd/latest response includes synced_at (may be null)."""
        res = authed_client.get("/api/sync/stryd/latest")
        data = res.json()
        assert "synced_at" in data, f"Missing synced_at in {data}"

    def test_fresh_user_returns_null_synced_at(self, authed_client):
        """A user who has never synced gets synced_at=null."""
        res = authed_client.get("/api/sync/stryd/latest")
        data = res.json()
        assert data["synced_at"] is None, (
            f"Fresh user should have synced_at=null, got {data['synced_at']}"
        )


# ── AC: training-log.html has sync chip elements ─────────────────────────────

class TestACSyncChipHTML:
    """AC: Training-log page header displays a single-row sync chip."""

    def test_training_log_has_sync_chip(self, authed_client):
        """training-log.html contains a sync chip element."""
        res = authed_client.get("/log")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert 'id="sync-chip"' in res.text, (
            "training-log.html must contain id=\"sync-chip\""
        )

    def test_training_log_has_sync_time_strava(self, authed_client):
        """training-log.html contains element for Strava last-sync time."""
        res = authed_client.get("/log")
        assert 'id="sync-time-strava"' in res.text, (
            "training-log.html must contain id=\"sync-time-strava\""
        )

    def test_training_log_has_sync_time_stryd(self, authed_client):
        """training-log.html contains element for Stryd last-sync time."""
        res = authed_client.get("/log")
        assert 'id="sync-time-stryd"' in res.text, (
            "training-log.html must contain id=\"sync-time-stryd\""
        )

    def test_training_log_has_sync_all_btn(self, authed_client):
        """training-log.html contains a Sync button in the chip."""
        res = authed_client.get("/log")
        assert 'id="sync-all-btn"' in res.text, (
            "training-log.html must contain id=\"sync-all-btn\""
        )


# ── AC: training-log.js fetches sync times on page load ──────────────────────

class TestACSyncTimesJS:
    """AC: Last-sync times are fetched from both API endpoints on page load."""

    def test_training_log_js_fetches_strava_latest(self):
        """training-log.js calls /api/sync/strava/latest."""
        js_path = _REPO_ROOT / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        assert "/api/sync/strava/latest" in content, (
            "training-log.js must call /api/sync/strava/latest to load last-sync time"
        )

    def test_training_log_js_fetches_stryd_latest(self):
        """training-log.js calls /api/sync/stryd/latest."""
        js_path = _REPO_ROOT / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        assert "/api/sync/stryd/latest" in content, (
            "training-log.js must call /api/sync/stryd/latest to load last-sync time"
        )

    def test_training_log_js_posts_stryd_sync(self):
        """training-log.js POSTs to /api/stryd/sync when Sync button clicked."""
        js_path = _REPO_ROOT / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        assert "/api/stryd/sync" in content, (
            "training-log.js must POST to /api/stryd/sync when Sync button is clicked"
        )

    def test_training_log_js_posts_strava_sync(self):
        """training-log.js POSTs to /api/strava/sync when Sync button clicked."""
        js_path = _REPO_ROOT / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        assert "/api/strava/sync" in content, (
            "training-log.js must POST to /api/strava/sync when Sync button is clicked"
        )

    def test_training_log_js_handles_409_as_ok(self):
        """training-log.js treats 409 from sync endpoints as 'already running', not error."""
        js_path = _REPO_ROOT / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        assert "409" in content, (
            "training-log.js must handle 409 response from sync endpoints (already running)"
        )

    def test_training_log_js_uses_reltime(self):
        """training-log.js uses relative-time formatting (e.g. '2h ago', 'just now')."""
        js_path = _REPO_ROOT / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        assert "just now" in content or "ago" in content, (
            "training-log.js must format sync times as relative (e.g. '2h ago', 'just now')"
        )

    def test_training_log_js_shows_never_for_null(self):
        """training-log.js displays 'Never' when synced_at is null."""
        js_path = _REPO_ROOT / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        assert "Never" in content, (
            "training-log.js must display 'Never' when synced_at is null"
        )


# ── AC: sync all button triggers both syncs ───────────────────────────────────

class TestACSync409Handling:
    """AC: 409 response is treated as 'already running', not an error."""

    def test_strava_sync_returns_409_when_already_running(self, authed_client):
        """POST /api/strava/sync returns 202 or 409 (both acceptable)."""
        res = authed_client.post("/api/strava/sync")
        assert res.status_code in (202, 409), (
            f"/api/strava/sync returned {res.status_code}: {res.text}"
        )

    def test_stryd_sync_returns_409_when_not_connected(self, authed_client):
        """POST /api/stryd/sync returns 4xx (not connected) but never 5xx."""
        res = authed_client.post("/api/stryd/sync")
        assert res.status_code < 500, (
            f"/api/stryd/sync returned server error {res.status_code}: {res.text}"
        )


# ── AC: run-view source strip uses real sync times ────────────────────────────

class TestACRunViewSourceStrip:
    """AC: Run-view 'Source & sync' strip uses real API sync times, not workout start time."""

    def test_training_log_js_run_view_no_startHHMM_as_sync_time(self):
        """training-log.js run-view strip must not use startHHMM as 'last sync' time."""
        js_path = _REPO_ROOT / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        # The bug: line using startHHMM as last-sync in the source strip
        assert "last sync ' + startHHMM" not in content, (
            "training-log.js must not use startHHMM (workout start time) as 'last sync' label — "
            "use real sync timestamps from GET /api/sync/strava/latest and /api/sync/stryd/latest"
        )

    def test_training_log_js_run_view_has_rv_srcnote_with_sync_id(self):
        """training-log.js renders the Source & sync strip with a proper sync-time placeholder."""
        js_path = _REPO_ROOT / "frontend" / "js" / "training-log.js"
        content = js_path.read_text()
        assert "rv-srcnote" in content, (
            "training-log.js must still render an rv-srcnote element in Source & sync strip"
        )
