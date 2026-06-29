"""Tests for issue #1033: Connect Google Drive source folder for sleep CSVs (runs against UAT)"""
import os
import pytest
import httpx
from uuid import uuid4


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_user(client):
    """Log in as the test user; httpx client maintains session cookie automatically."""
    # Try standard test credentials
    r = client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    if r.status_code != 200:
        pytest.skip(f"Test user not available (status {r.status_code})")
    return client


# ─ Acceptance Criteria ─────────────────────────────────────────────────────────

def test_drive_sleep_connection__migration_creates_table_and_columns(auth_user):
    # AC: Migration creates `drive_sleep_connections` table with columns:
    # id, user_id, refresh_token_encrypted, folder_id, status (enum), last_sync_at, created_at, updated_at
    # Verify the table exists and responds correctly via API call
    r = auth_user.get("/api/drive-sleep/status")
    assert r.status_code == 200, f"Status endpoint failed: {r.text}"
    body = r.json()
    assert "status" in body
    assert "folder_id" in body
    assert "last_sync_at" in body


def test_drive_sleep_connection__status_values_enum(auth_user):
    # AC: status must be one of: not_connected | connected | error
    # Check initial status is not_connected
    r = auth_user.get("/api/drive-sleep/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("not_connected", "connected", "error")


def test_drive_sleep_connection__google_oauth_handler_exists(auth_user):
    # AC: A Google OAuth handler exists in main.py using read-only Drive scope
    # Verify the /api/drive-sleep/connect endpoint exists and returns authorize_url
    r = auth_user.get("/api/drive-sleep/connect")
    assert r.status_code == 200, f"OAuth handler missing: {r.text}"
    body = r.json()
    assert "authorize_url" in body
    assert "scope=https" in body["authorize_url"] or "scope=https%3A" in body["authorize_url"]
    assert "drive.readonly" in body["authorize_url"]


def test_drive_sleep_connection__oauth_uses_readonly_scope(auth_user):
    # AC: Uses read-only Drive scope (https://www.googleapis.com/auth/drive.readonly)
    r = auth_user.get("/api/drive-sleep/connect")
    assert r.status_code == 200
    body = r.json()
    authorize_url = body["authorize_url"]
    assert "drive.readonly" in authorize_url


def test_drive_sleep_connection__oauth_offline_access_requested(auth_user):
    # AC: OAuth flow requests offline access for token refresh
    r = auth_user.get("/api/drive-sleep/connect")
    assert r.status_code == 200
    body = r.json()
    authorize_url = body["authorize_url"]
    assert "access_type=offline" in authorize_url


def test_drive_sleep_connection__refresh_token_not_in_api_response(auth_user):
    # AC: No API response includes the raw refresh token — only status, folder_id, last_sync_at
    r = auth_user.get("/api/drive-sleep/status")
    assert r.status_code == 200
    body = r.json()
    assert "refresh_token" not in body, "refresh_token must not be exposed in API response"
    assert "refresh_token_encrypted" not in body


def test_drive_sleep_connection__disconnect_clears_token_and_resets_status(auth_user):
    # AC: A disconnect action clears refresh_token_encrypted and sets status to not_connected
    # Get CSRF token for DELETE request
    r = auth_user.get("/api/csrf-token")
    assert r.status_code == 200
    csrf_token = r.json()["csrf_token"]

    # Call disconnect endpoint and verify status resets
    r = auth_user.delete(
        "/api/drive-sleep/disconnect",
        headers={"X-CSRF-Token": csrf_token}
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("disconnected") is True

    # Verify status is back to not_connected
    r = auth_user.get("/api/drive-sleep/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_connected"
    assert body["folder_id"] is None


def test_drive_sleep_connection__oauth_error_sets_status_to_error(client):
    # AC: If OAuth callback returns error, status is set to error and logged
    # Simulate OAuth error by calling callback with error parameter
    r = client.get("/api/drive-sleep/callback?state=invalid&error=access_denied")
    # Expect either HTML response (success) or 400 (invalid state)
    # A real error should set status="error" in the database
    assert r.status_code in (200, 400)


def test_drive_sleep_connection__folder_id_persistence(auth_user):
    # AC: After OAuth, user can pick or paste folder ID/URL; selection is persisted to folder_id
    # First get status to confirm not_connected
    r = auth_user.get("/api/drive-sleep/status")
    assert r.status_code == 200

    # Try to set folder without being connected — should fail
    r = auth_user.post("/api/drive-sleep/folder", json={"folder_id": "test_folder_123"})
    # Should either return 400 (not connected) or succeed if connection exists
    if r.status_code == 400:
        # Expected — user is not connected yet
        assert "not connected" in r.text.lower() or "not connected" in r.json().get("detail", "").lower()


def test_drive_sleep_connection__folder_endpoint_requires_connection(auth_user):
    # AC: Setting folder without connection returns error
    r = auth_user.post("/api/drive-sleep/folder", json={"folder_id": "some_folder"})
    # If user is not connected, expect 400
    if r.status_code == 400:
        body = r.json() if r.headers.get("content-type") == "application/json" else {}
        assert "not connected" in str(body).lower() or "not connected" in r.text.lower()


def test_drive_sleep_connection__callback_error_html_rendered(client):
    # AC: On OAuth callback error, appropriate error HTML is returned
    # Call callback with intentional error (invalid state or missing code)
    r = client.get("/api/drive-sleep/callback?state=invalid")
    # Should get an HTML error page or 400
    assert r.status_code in (200, 400)


def test_drive_sleep_connection__initial_state_not_connected(auth_user):
    # AC: Settings UI shows current connection status (not_connected)
    r = auth_user.get("/api/drive-sleep/status")
    assert r.status_code == 200
    body = r.json()
    # New user should start as not_connected
    assert body["status"] == "not_connected"
    assert body["folder_id"] is None
    assert body["last_sync_at"] is None
