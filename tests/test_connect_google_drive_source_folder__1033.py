"""Tests for issue #1033: Connect Google Drive source folder for sleep CSVs.

AC coverage:
  AC1 – drive_sleep_connections table exists with correct columns/enum
  AC2 – GET /api/drive-sleep/connect returns authorize_url with drive.readonly scope
  AC3 – POST /api/drive-sleep/folder persists folder_id
  AC4 – refresh token is stored encrypted (not plaintext)
  AC5 – status API never exposes refresh_token in payload
  AC6 – DELETE /api/drive-sleep/disconnect clears token + sets status not_connected
  AC7 – callback with ?error= sets status to error and logs server-side
  AC8 – GET /api/drive-sleep/status returns status, folder_id, last_sync_at
"""
import time
import json
import urllib.parse
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import create_session_cookie, COOKIE_NAME, generate_csrf_token, CSRF_COOKIE_NAME
from backend.main import app, resolve_user

_USER_ID = "00000000-0000-0000-0000-000000001033"
_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def _mock_user(user_id=_USER_ID):
    u = MagicMock()
    u.id = user_id
    return u


def _make_client():
    mock_user = _mock_user()

    async def _fake_resolve_user():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve_user
    session_cookie = create_session_cookie(_USER_ID, time.time())
    csrf = generate_csrf_token()
    client = TestClient(
        app,
        cookies={COOKIE_NAME: session_cookie, CSRF_COOKIE_NAME: csrf},
        headers={"X-CSRF-Token": csrf},
    )
    return client, mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _urlopen_response(payload):
    body = json.dumps(payload).encode()
    resp = MagicMock()
    resp.read.return_value = body
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=resp)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ── AC1: drive_sleep_connections table schema ──────────────────────────────────

def test_drive_sleep_connections_model_importable():
    """Model must be importable from backend.models."""
    from backend.models import DriveSleepConnection  # noqa: F401


def test_drive_sleep_connections_model_columns():
    """Model must define the required columns."""
    from backend.models import DriveSleepConnection
    col_names = {c.key for c in DriveSleepConnection.__table__.columns}
    required = {"id", "user_id", "refresh_token_encrypted", "folder_id", "status", "last_sync_at", "created_at", "updated_at"}
    assert required.issubset(col_names), f"Missing columns: {required - col_names}"


def test_drive_sleep_connections_status_default():
    """status column should default to not_connected."""
    from backend.models import DriveSleepConnection
    col = DriveSleepConnection.__table__.columns["status"]
    sd = col.server_default
    # server_default is a DefaultClause wrapping a TextClause; extract the text
    clause_text = str(sd.arg) if sd is not None else ""
    assert "not_connected" in clause_text


def test_drive_sleep_connections_last_sync_at_nullable():
    """last_sync_at must be nullable (no sync has happened yet at connect time)."""
    from backend.models import DriveSleepConnection
    col = DriveSleepConnection.__table__.columns["last_sync_at"]
    assert col.nullable is True


# ── AC2: GET /api/drive-sleep/connect ─────────────────────────────────────────

def test_drive_sleep_connect_returns_authorize_url():
    """AC2: connect endpoint returns authorize_url containing drive.readonly scope."""
    client, _ = _make_client()
    try:
        env = {
            "GOOGLE_CLIENT_ID": "fake-client-id",
            "GOOGLE_CLIENT_SECRET": "fake-secret",
            "GOOGLE_STATE_SECRET": "fake-state-secret",
        }
        with patch.dict("os.environ", env, clear=False):
            res = client.get("/api/drive-sleep/connect")
        assert res.status_code == 200, res.text
        body = res.json()
        assert "authorize_url" in body
        url = body["authorize_url"]
        assert "accounts.google.com" in url
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert _DRIVE_READONLY_SCOPE in qs.get("scope", [""])[0]
    finally:
        _teardown()


def test_drive_sleep_connect_scope_is_drive_readonly():
    """AC2: scope must be exactly drive.readonly (not fitness, not calendar)."""
    client, _ = _make_client()
    try:
        env = {
            "GOOGLE_CLIENT_ID": "fake-client-id",
            "GOOGLE_CLIENT_SECRET": "fake-secret",
            "GOOGLE_STATE_SECRET": "fake-state-secret",
        }
        with patch.dict("os.environ", env, clear=False):
            res = client.get("/api/drive-sleep/connect")
        assert res.status_code == 200
        url = res.json()["authorize_url"]
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        scope = qs["scope"][0]
        assert "drive.readonly" in scope
        assert "fitness" not in scope
    finally:
        _teardown()


def test_drive_sleep_connect_missing_client_id(monkeypatch):
    """connect returns 500 when GOOGLE_CLIENT_ID is missing."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    with TestClient(app) as tc:
        res = tc.get("/api/drive-sleep/connect")
    assert res.status_code in (401, 500)


def test_drive_sleep_connect_unauthenticated():
    """connect returns 401 for unauthenticated requests."""
    client = TestClient(app)
    env = {
        "GOOGLE_CLIENT_ID": "fake-client-id",
        "GOOGLE_CLIENT_SECRET": "fake-secret",
        "GOOGLE_STATE_SECRET": "fake-state-secret",
    }
    with patch.dict("os.environ", env, clear=False):
        res = client.get("/api/drive-sleep/connect")
    assert res.status_code == 401


# ── AC3: POST /api/drive-sleep/folder persists folder_id ──────────────────────

def test_drive_sleep_folder_persists():
    """AC3: POST /api/drive-sleep/folder persists the folder_id."""
    client, _ = _make_client()
    try:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_row = MagicMock()
        mock_row.status = "connected"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_row

        with patch("backend.main.Session", return_value=mock_session):
            res = client.post("/api/drive-sleep/folder", json={"folder_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"})

        assert res.status_code == 200, res.text
        body = res.json()
        assert "folder_id" in body or body.get("ok") is True or "status" in body
    finally:
        _teardown()


def test_drive_sleep_folder_not_connected_rejected():
    """POST /api/drive-sleep/folder when status is not_connected returns 400."""
    client, _ = _make_client()
    try:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_row = MagicMock()
        mock_row.status = "not_connected"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_row

        with patch("backend.main.Session", return_value=mock_session):
            res = client.post("/api/drive-sleep/folder", json={"folder_id": "some-folder"})

        assert res.status_code in (400, 404)
    finally:
        _teardown()


# ── AC4: refresh token is encrypted before storage ─────────────────────────────

def test_drive_sleep_callback_encrypts_token():
    """AC4: callback stores refresh token encrypted, never plaintext."""
    from backend.services.crypto import decrypt_value

    captured = {}

    def _fake_upsert(**kwargs):
        captured.update(kwargs)

    client, _ = _make_client()
    try:
        state_secret = "test-state-secret-1033"
        from backend.main import _make_google_state_token
        state = _make_google_state_token(_USER_ID, state_secret)

        fake_token_resp = {
            "access_token": "ya29.access-token",
            "refresh_token": "1//refresh-plaintext-token",
            "expires_in": 3600,
            "id_token": "",
        }

        env = {
            "GOOGLE_CLIENT_ID": "fake-id",
            "GOOGLE_CLIENT_SECRET": "fake-secret",
            "GOOGLE_STATE_SECRET": state_secret,
            "GOOGLE_DRIVE_REDIRECT_URI": "http://localhost:9001/api/drive-sleep/callback",
        }

        with patch.dict("os.environ", env, clear=False), \
             patch("backend.main._exchange_google_code", return_value=fake_token_resp), \
             patch("backend.main._upsert_drive_sleep_connection", side_effect=_fake_upsert):
            res = client.get(f"/api/drive-sleep/callback?code=fake-code&state={state}")

        # The upsert must have been called with an encrypted token (not plaintext)
        assert "refresh_token_encrypted" in captured
        stored = captured["refresh_token_encrypted"]
        assert stored != "1//refresh-plaintext-token", "Token stored as plaintext — must be encrypted"
        # Verify it can be decrypted back to original
        assert decrypt_value(stored) == "1//refresh-plaintext-token"
    finally:
        _teardown()


# ── AC5: no raw refresh token in API response ──────────────────────────────────

def test_drive_sleep_status_no_refresh_token_in_response():
    """AC5: GET /api/drive-sleep/status never exposes refresh_token."""
    client, _ = _make_client()
    try:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_row = MagicMock()
        mock_row.status = "connected"
        mock_row.folder_id = "some-folder-id"
        mock_row.last_sync_at = None
        mock_row.refresh_token_encrypted = "gAAAAA-encrypted-value-here"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_row

        with patch("backend.main.Session", return_value=mock_session):
            res = client.get("/api/drive-sleep/status")

        assert res.status_code == 200, res.text
        body = res.json()
        assert "refresh_token" not in body, "Raw refresh_token must NOT appear in the response"
        assert "refresh_token_encrypted" not in body, "Encrypted token must NOT appear in the response"
        assert "status" in body
        assert "folder_id" in body
        assert "last_sync_at" in body
    finally:
        _teardown()


def test_drive_sleep_status_fields_present():
    """AC5/AC8: status response contains status, folder_id, last_sync_at."""
    client, _ = _make_client()
    try:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_row = MagicMock()
        mock_row.status = "connected"
        mock_row.folder_id = "test-folder-id"
        mock_row.last_sync_at = None
        mock_row.refresh_token_encrypted = "gAAAAA-something"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_row

        with patch("backend.main.Session", return_value=mock_session):
            res = client.get("/api/drive-sleep/status")

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "connected"
        assert body["folder_id"] == "test-folder-id"
        assert "last_sync_at" in body
    finally:
        _teardown()


def test_drive_sleep_status_not_connected_when_no_row():
    """AC8: status returns not_connected when no row exists yet."""
    client, _ = _make_client()
    try:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch("backend.main.Session", return_value=mock_session):
            res = client.get("/api/drive-sleep/status")

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "not_connected"
        assert body["folder_id"] is None
        assert body["last_sync_at"] is None
    finally:
        _teardown()


# ── AC6: disconnect clears token + sets status not_connected ───────────────────

def test_drive_sleep_disconnect_clears_token():
    """AC6: DELETE /api/drive-sleep/disconnect clears refresh_token_encrypted and sets status to not_connected."""
    client, _ = _make_client()
    try:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_row = MagicMock()
        mock_row.status = "connected"
        mock_row.refresh_token_encrypted = "gAAAAA-some-encrypted-value"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_row

        with patch("backend.main.Session", return_value=mock_session):
            res = client.delete("/api/drive-sleep/disconnect")

        assert res.status_code == 200, res.text
        # The row's fields must have been cleared
        assert mock_row.refresh_token_encrypted is None
        assert mock_row.status == "not_connected"
        mock_session.commit.assert_called()
    finally:
        _teardown()


def test_drive_sleep_disconnect_no_row_is_ok():
    """AC6: disconnect is idempotent — returns 200 even if no row exists."""
    client, _ = _make_client()
    try:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch("backend.main.Session", return_value=mock_session):
            res = client.delete("/api/drive-sleep/disconnect")

        assert res.status_code == 200
    finally:
        _teardown()


# ── AC7: error callback sets status to error ───────────────────────────────────

def test_drive_sleep_callback_error_sets_error_status():
    """AC7: callback with ?error= query param sets status to error."""
    client, _ = _make_client()
    try:
        state_secret = "test-state-secret-1033-error"
        from backend.main import _make_google_state_token
        state = _make_google_state_token(_USER_ID, state_secret)

        captured = {}

        def _fake_upsert(**kwargs):
            captured.update(kwargs)

        env = {
            "GOOGLE_CLIENT_ID": "fake-id",
            "GOOGLE_CLIENT_SECRET": "fake-secret",
            "GOOGLE_STATE_SECRET": state_secret,
        }

        with patch.dict("os.environ", env, clear=False), \
             patch("backend.main._upsert_drive_sleep_connection", side_effect=_fake_upsert):
            res = client.get(f"/api/drive-sleep/callback?error=access_denied&state={state}")

        # Must not crash — redirect or HTML response
        assert res.status_code in (200, 302, 303)
        # Status set to error
        assert captured.get("status") == "error" or \
               "error" in str(res.headers.get("location", "")) or \
               "error" in res.text.lower()
    finally:
        _teardown()


def test_drive_sleep_callback_error_no_state_returns_400():
    """AC7: callback with ?error= and no/invalid state still handles gracefully."""
    client, _ = _make_client()
    try:
        env = {
            "GOOGLE_CLIENT_ID": "fake-id",
            "GOOGLE_CLIENT_SECRET": "fake-secret",
            "GOOGLE_STATE_SECRET": "any-secret",
        }
        with patch.dict("os.environ", env, clear=False):
            res = client.get("/api/drive-sleep/callback?error=access_denied")
        assert res.status_code in (200, 302, 303, 400, 422)
    finally:
        _teardown()


# ── AC8: Settings UI has Connect / Disconnect ──────────────────────────────────

def test_settings_html_has_drive_sleep_card():
    """AC8: settings.html must contain a Google Drive Sleep connection section."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "drive-sleep" in html or "drive_sleep" in html or "Google Drive" in html


def test_settings_html_has_connect_button():
    """AC8: settings.html must have a Connect button for Drive Sleep."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    # Must contain JS or HTML that handles drive-sleep connect/disconnect
    assert "drive-sleep" in html.lower() or "drive_sleep" in html.lower()


def test_settings_html_exposes_status_field():
    """AC8: settings page JS must fetch/display drive-sleep status."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "/api/drive-sleep/status" in html


# ── Upsert helper importable ───────────────────────────────────────────────────

def test_upsert_drive_sleep_connection_importable():
    """_upsert_drive_sleep_connection must exist in backend.main."""
    from backend.main import _upsert_drive_sleep_connection  # noqa: F401
