"""Tests for issue #197: Strava/Stryd status and disconnect endpoints."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

_USER_ID = "00000000-0000-0000-0000-000000000197"
_NOW = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
_FRESH_EXPIRES = _NOW + timedelta(hours=6)
_EXPIRED = _NOW - timedelta(hours=1)


def _mock_user(user_id=_USER_ID):
    u = MagicMock()
    u.id = user_id
    return u


def _mock_session_with_user(user=None):
    if user is None:
        user = _mock_user()
    s = MagicMock()
    s.__enter__ = MagicMock(return_value=s)
    s.__exit__ = MagicMock(return_value=False)
    s.query.return_value.order_by.return_value.first.return_value = user
    return s


def _strava_token_row(
    expires_at=None,
    scope="activity:read_all",
    athlete_data=None,
    athlete_id=12345,
):
    if expires_at is None:
        expires_at = _FRESH_EXPIRES
    if athlete_data is None:
        athlete_data = {"firstname": "Jane", "lastname": "Doe"}
    row = MagicMock()
    row.access_token = "access-abc"
    row.refresh_token = "refresh-abc"
    row.expires_at = expires_at
    row.scope = scope
    row.athlete_data = athlete_data
    # strava_status() reads token_row.athlete_id directly into the JSON
    # response; an unset MagicMock attribute isn't JSON-serializable, which
    # only started surfacing once these tests were authenticated far enough
    # to reach that code (#1606 — see the as_user fixture above).
    row.athlete_id = athlete_id
    return row


def _stryd_cred_row(
    session_expires_at=None,
    athlete_id=42,
    stryd_email="runner@example.com",
    session_token="tok-xyz",
):
    if session_expires_at is None:
        session_expires_at = _FRESH_EXPIRES
    row = MagicMock()
    row.athlete_id = athlete_id
    row.stryd_email = stryd_email
    row.session_token = session_token
    row.session_token_expires_at = session_expires_at
    return row


# ── GET /api/strava/status ────────────────────────────────────────────────────

def test_strava_status_not_connected_no_token_row(as_user):
    """No strava_tokens row → connected: false with null fields."""
    as_user(_USER_ID)
    mock_s = _mock_session_with_user()
    mock_s.query.return_value.filter.return_value.first.return_value = None

    with patch("backend.main.Session", return_value=mock_s):
        res = client.get("/api/strava/status")

    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is False
    assert body["athlete_name"] is None
    assert body["scope"] is None
    assert body["expires_at"] is None


def test_strava_status_connected_fresh_token(as_user):
    """Valid, non-expired token → connected: true with correct fields."""
    as_user(_USER_ID)
    token_row = _strava_token_row()
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = token_row

    with patch("backend.main.Session", return_value=mock_s), \
         patch("backend.main.refresh_token_if_needed", return_value="access-abc"):
        res = client.get("/api/strava/status")

    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["athlete_name"] == "Jane Doe"
    assert body["scope"] == "activity:read_all"
    assert body["expires_at"] is not None


def test_strava_status_expired_token_refresh_succeeds(as_user):
    """Expired token that can be refreshed → connected: true, expires_at updated."""
    as_user(_USER_ID)
    expired_row = _strava_token_row(expires_at=_EXPIRED)
    fresh_row = _strava_token_row(expires_at=_FRESH_EXPIRES)
    call_count = [0]

    def _session_factory(*args, **kwargs):
        s = MagicMock()
        s.__enter__ = MagicMock(return_value=s)
        s.__exit__ = MagicMock(return_value=False)
        call_count[0] += 1
        if call_count[0] == 1:
            s.query.return_value.filter.return_value.first.return_value = expired_row
        else:
            s.query.return_value.filter.return_value.first.return_value = fresh_row
        return s

    with patch("backend.main.Session", side_effect=_session_factory), \
         patch("backend.main.refresh_token_if_needed", return_value="new-access-token"):
        res = client.get("/api/strava/status")

    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["expires_at"] is not None


def test_strava_status_refresh_fails_returns_not_connected(as_user):
    """Token refresh failure → connected: false, HTTP 200, no 5xx."""
    as_user(_USER_ID)
    token_row = _strava_token_row(expires_at=_EXPIRED)
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = token_row

    with patch("backend.main.Session", return_value=mock_s), \
         patch("backend.main.refresh_token_if_needed", side_effect=Exception("token revoked")):
        res = client.get("/api/strava/status")

    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is False
    assert body["athlete_name"] is None


def test_strava_status_refresh_http_exception_returns_not_connected(as_user):
    """HTTPException from refresh → connected: false, no crash."""
    as_user(_USER_ID)
    token_row = _strava_token_row(expires_at=_EXPIRED)
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = token_row

    with patch("backend.main.Session", return_value=mock_s), \
         patch("backend.main.refresh_token_if_needed", side_effect=HTTPException(status_code=502, detail="bad")):
        res = client.get("/api/strava/status")

    assert res.status_code == 200
    assert res.json()["connected"] is False


# ── DELETE /api/strava/disconnect ─────────────────────────────────────────────

def test_strava_disconnect_with_row_deletes_and_returns_disconnected(as_user):
    """Valid token row present → row deleted, returns {disconnected: true}."""
    as_user(_USER_ID)
    token_row = _strava_token_row()
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = token_row

    with patch("backend.main.Session", return_value=mock_s), \
         patch("urllib.request.urlopen"):
        res = client.delete("/api/strava/disconnect")

    assert res.status_code == 200
    assert res.json() == {"disconnected": True}


def test_strava_disconnect_without_row_is_idempotent(as_user):
    """No token row → returns {disconnected: true} (idempotent)."""
    as_user(_USER_ID)
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = None

    with patch("backend.main.Session", return_value=mock_s):
        res = client.delete("/api/strava/disconnect")

    assert res.status_code == 200
    assert res.json() == {"disconnected": True}


def test_strava_disconnect_deauthorize_failure_silently_ignored(as_user):
    """Strava deauthorize call fails → still returns {disconnected: true}."""
    as_user(_USER_ID)
    import urllib.error
    token_row = _strava_token_row()
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = token_row

    http_err = urllib.error.HTTPError("https://www.strava.com/oauth/deauthorize", 401, "Unauthorized", {}, None)  # type: ignore[arg-type]

    with patch("backend.main.Session", return_value=mock_s), \
         patch("urllib.request.urlopen", side_effect=http_err):
        res = client.delete("/api/strava/disconnect")

    assert res.status_code == 200
    assert res.json() == {"disconnected": True}


# ── GET /api/stryd/status ─────────────────────────────────────────────────────

def test_stryd_status_not_connected_no_cred_row(as_user):
    """No stryd_credentials row → connected: false with null fields."""
    as_user(_USER_ID)
    mock_s = _mock_session_with_user()
    mock_s.query.return_value.filter.return_value.first.return_value = None

    with patch("backend.main.Session", return_value=mock_s):
        res = client.get("/api/stryd/status")

    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is False
    assert body["athlete_id"] is None
    assert body["stryd_email"] is None
    assert body["session_expires_at"] is None


def test_stryd_status_connected_fresh_session(as_user):
    """Valid credentials with fresh session → connected: true with correct fields."""
    as_user(_USER_ID)
    cred_row = _stryd_cred_row()
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = cred_row

    with patch("backend.main.Session", return_value=mock_s), \
         patch("backend.main.refresh_stryd_session_if_needed", return_value="tok-xyz"):
        res = client.get("/api/stryd/status")

    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["athlete_id"] == 42
    assert body["stryd_email"] == "runner@example.com"
    assert body["session_expires_at"] is not None


def test_stryd_status_expired_session_refresh_succeeds(as_user):
    """Expired session that re-auths successfully → connected: true."""
    as_user(_USER_ID)
    cred_row = _stryd_cred_row(session_expires_at=_EXPIRED)
    fresh_row = _stryd_cred_row(session_expires_at=_FRESH_EXPIRES)
    call_count = [0]

    def _session_factory(*args, **kwargs):
        s = MagicMock()
        s.__enter__ = MagicMock(return_value=s)
        s.__exit__ = MagicMock(return_value=False)
        call_count[0] += 1
        if call_count[0] == 1:
            s.query.return_value.filter.return_value.first.return_value = cred_row
        else:
            s.query.return_value.filter.return_value.first.return_value = fresh_row
        return s

    with patch("backend.main.Session", side_effect=_session_factory), \
         patch("backend.main.refresh_stryd_session_if_needed", return_value="new-tok"):
        res = client.get("/api/stryd/status")

    assert res.status_code == 200
    assert res.json()["connected"] is True


def test_stryd_status_refresh_fails_deletes_credentials_returns_not_connected(as_user):
    """Re-auth failure → credentials row deleted, connected: false, HTTP 200."""
    as_user(_USER_ID)
    cred_row = _stryd_cred_row(session_expires_at=_EXPIRED)
    delete_called = [False]

    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = cred_row

    def _delete(obj):
        delete_called[0] = True

    mock_s.delete.side_effect = _delete

    with patch("backend.main.Session", return_value=mock_s), \
         patch("backend.main.refresh_stryd_session_if_needed", side_effect=Exception("re-auth failed")):
        res = client.get("/api/stryd/status")

    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is False
    assert body["athlete_id"] is None
    assert delete_called[0] is True


# ── DELETE /api/stryd/disconnect ──────────────────────────────────────────────

def test_stryd_disconnect_with_row_deletes_and_returns_disconnected(as_user):
    """Valid credentials row present → row deleted, returns {disconnected: true}."""
    as_user(_USER_ID)
    cred_row = _stryd_cred_row()
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = cred_row

    with patch("backend.main.Session", return_value=mock_s):
        res = client.delete("/api/stryd/disconnect")

    assert res.status_code == 200
    assert res.json() == {"disconnected": True}


def test_stryd_disconnect_without_row_is_idempotent(as_user):
    """No credentials row → returns {disconnected: true} (idempotent)."""
    as_user(_USER_ID)
    mock_s = MagicMock()
    mock_s.__enter__ = MagicMock(return_value=mock_s)
    mock_s.__exit__ = MagicMock(return_value=False)
    mock_s.query.return_value.filter.return_value.first.return_value = None

    with patch("backend.main.Session", return_value=mock_s):
        res = client.delete("/api/stryd/disconnect")

    assert res.status_code == 200
    assert res.json() == {"disconnected": True}


# ── Docs files existence ──────────────────────────────────────────────────────

import os as _os


def test_strava_docs_file_exists():
    path = _os.path.join(_os.path.dirname(__file__), "..", "docs", "integrations", "strava.md")
    assert _os.path.isfile(path), "docs/integrations/strava.md missing"


def test_stryd_docs_file_exists():
    path = _os.path.join(_os.path.dirname(__file__), "..", "docs", "integrations", "stryd.md")
    assert _os.path.isfile(path), "docs/integrations/stryd.md missing"


def test_architecture_docs_file_exists():
    path = _os.path.join(_os.path.dirname(__file__), "..", "docs", "integrations", "architecture.md")
    assert _os.path.isfile(path), "docs/integrations/architecture.md missing"


def test_strava_docs_contains_required_sections():
    path = _os.path.join(_os.path.dirname(__file__), "..", "docs", "integrations", "strava.md")
    content = open(path).read()
    assert "STATE_SECRET" in content or "state_secret" in content.lower()
    assert "checklist" in content.lower() or "setup" in content.lower()


def test_stryd_docs_contains_fernet_section():
    path = _os.path.join(_os.path.dirname(__file__), "..", "docs", "integrations", "stryd.md")
    content = open(path).read()
    assert "Fernet" in content or "fernet" in content.lower()


def test_architecture_docs_contains_required_content():
    path = _os.path.join(_os.path.dirname(__file__), "..", "docs", "integrations", "architecture.md")
    content = open(path).read()
    assert "strava_activities" in content
    assert "stryd_activities" in content
    assert "workouts" in content
    assert "compute_best_values" in content or "priority" in content.lower()
    assert "5" in content and "minute" in content.lower()
    assert "source" in content
