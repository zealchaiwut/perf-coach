"""Tests for issue #216: GET /api/google/callback and refresh_token_if_needed."""
import base64
import json
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import responses as responses_lib
from fastapi.testclient import TestClient

from backend.main import app, _make_google_state_token
from backend.services.google import refresh_token_if_needed
from backend.utils.errors import ExternalServiceError

TEST_SECRET = "test-google-state-secret-216"
TEST_USER_ID = "00000000-0000-0000-0000-000000000216"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

client = TestClient(app)


def _make_state():
    return _make_google_state_token(TEST_USER_ID, TEST_SECRET)


def _make_id_token(sub="google-sub-1", email="user@example.com", email_verified=True) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload_bytes = json.dumps({"sub": sub, "email": email, "email_verified": email_verified}).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


def _fake_google_token_response(
    access_token="at-new",
    refresh_token="rt-new",
    expires_in=3600,
    include_refresh=True,
) -> dict:
    resp = {
        "access_token": access_token,
        "expires_in": expires_in,
        "token_type": "Bearer",
        "id_token": _make_id_token(),
    }
    if include_refresh:
        resp["refresh_token"] = refresh_token
    return resp


# ── 1. Successful callback → credentials row created ─────────────────────────

def test_callback_success_creates_credentials(monkeypatch):
    monkeypatch.setenv("GOOGLE_STATE_SECRET", TEST_SECRET)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")

    state = _make_state()
    google_resp = _fake_google_token_response()

    with patch("backend.main._exchange_google_code", return_value=google_resp) as mock_ex, \
         patch("backend.main._upsert_google_credentials") as mock_up:
        res = client.get("/api/google/callback", params={
            "code": "code-abc", "state": state, "scope": "openid email profile",
        })

    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "google_connected" in res.text
    assert "window.close()" in res.text
    mock_ex.assert_called_once_with("code-abc", "cid", "csecret", "http://localhost:9001/api/google/callback")
    mock_up.assert_called_once()
    call_kwargs = mock_up.call_args.kwargs
    assert call_kwargs["user_id"] == TEST_USER_ID
    assert call_kwargs["access_token"] == "at-new"
    assert call_kwargs["refresh_token"] == "rt-new"


# ── 2. Repeat callback → upsert, not duplicate ───────────────────────────────

def test_callback_repeat_upserts_not_duplicates(monkeypatch):
    monkeypatch.setenv("GOOGLE_STATE_SECRET", TEST_SECRET)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")

    upsert_calls = []

    with patch("backend.main._exchange_google_code", return_value=_fake_google_token_response()), \
         patch("backend.main._upsert_google_credentials", side_effect=lambda **kw: upsert_calls.append(kw)):

        state1 = _make_state()
        res1 = client.get("/api/google/callback", params={
            "code": "code-1", "state": state1, "scope": "openid email profile",
        })
        state2 = _make_state()
        res2 = client.get("/api/google/callback", params={
            "code": "code-2", "state": state2, "scope": "openid email profile",
        })

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert len(upsert_calls) == 2
    assert upsert_calls[0]["user_id"] == TEST_USER_ID
    assert upsert_calls[1]["user_id"] == TEST_USER_ID


# ── 3. Repeat callback without refresh_token → existing DB refresh_token kept ─

def test_callback_no_refresh_token_preserves_existing(monkeypatch):
    monkeypatch.setenv("GOOGLE_STATE_SECRET", TEST_SECRET)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")

    google_resp_no_rt = _fake_google_token_response(include_refresh=False)
    upsert_calls = []

    with patch("backend.main._exchange_google_code", return_value=google_resp_no_rt), \
         patch("backend.main._upsert_google_credentials", side_effect=lambda **kw: upsert_calls.append(kw)):
        state = _make_state()
        res = client.get("/api/google/callback", params={
            "code": "code-no-rt", "state": state, "scope": "openid email profile",
        })

    assert res.status_code == 200
    assert len(upsert_calls) == 1
    # refresh_token should be None when Google omits it — _upsert_google_credentials
    # handles preserving the existing DB value when it receives None.
    assert upsert_calls[0]["refresh_token"] is None


# ── 4. Invalid/expired state → 400 ───────────────────────────────────────────

def test_callback_invalid_state_returns_400(monkeypatch):
    monkeypatch.setenv("GOOGLE_STATE_SECRET", TEST_SECRET)

    res = client.get("/api/google/callback", params={
        "code": "irrelevant", "state": "bad.state", "scope": "",
    })

    assert res.status_code == 400
    assert "Authorization state expired or invalid" in res.json()["detail"]


def test_callback_expired_state_returns_400(monkeypatch):
    monkeypatch.setenv("GOOGLE_STATE_SECRET", TEST_SECRET)

    # Build an already-expired state by patching time
    with patch("backend.main.time") as mock_time:
        mock_time.time.return_value = time.time() - 700  # 700s ago > 600s max_age
        state = _make_google_state_token(TEST_USER_ID, TEST_SECRET)

    res = client.get("/api/google/callback", params={
        "code": "irrelevant", "state": state, "scope": "",
    })

    assert res.status_code == 400
    assert "Authorization state expired or invalid" in res.json()["detail"]


# ── 5. Google 4xx during token exchange → 502 ────────────────────────────────

def test_callback_google_4xx_returns_502(monkeypatch):
    monkeypatch.setenv("GOOGLE_STATE_SECRET", TEST_SECRET)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")

    state = _make_state()
    http_err = urllib.error.HTTPError(
        url=_GOOGLE_TOKEN_URL,
        code=400,
        msg="Bad Request",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )

    with patch("backend.main._exchange_google_code", side_effect=Exception("502 from _exchange")), \
         patch("backend.main._exchange_google_code") as mock_ex:
        mock_ex.side_effect = None
        mock_ex.return_value = None

    # Use the real _exchange_google_code path with a mocked urllib that raises HTTPError
    with patch("backend.main._urllib_request.urlopen", side_effect=http_err):
        res = client.get("/api/google/callback", params={
            "code": "bad-code", "state": state, "scope": "",
        })

    assert res.status_code == 502
    assert "Google token exchange failed" in res.json()["detail"]


# ── 6. refresh_token_if_needed calls Google when token expired/near-expiry ────

@responses_lib.activate
def test_refresh_token_if_needed_refreshes_expired():
    now = datetime.now(tz=timezone.utc)
    expired_at = now - timedelta(minutes=1)

    mock_cred = MagicMock()
    mock_cred.expires_at = expired_at
    mock_cred.refresh_token = "old-rt"
    mock_cred.access_token = "old-at"

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_cred

    responses_lib.add(
        responses_lib.POST,
        _GOOGLE_TOKEN_URL,
        json={"access_token": "refreshed-at", "expires_in": 3600},
        status=200,
    )

    with patch("backend.services.google.Session", return_value=mock_session):
        result = refresh_token_if_needed(TEST_USER_ID)

    assert result == "refreshed-at"
    assert mock_cred.access_token == "refreshed-at"
    mock_session.commit.assert_called_once()
    assert len(responses_lib.calls) == 1


# ── 7. refresh_token_if_needed skips Google when token still fresh ────────────

@responses_lib.activate
def test_refresh_token_if_needed_skips_when_fresh():
    now = datetime.now(tz=timezone.utc)
    fresh_at = now + timedelta(minutes=10)

    mock_cred = MagicMock()
    mock_cred.expires_at = fresh_at
    mock_cred.access_token = "still-valid-at"

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_cred

    with patch("backend.services.google.Session", return_value=mock_session):
        result = refresh_token_if_needed(TEST_USER_ID)

    assert result == "still-valid-at"
    assert len(responses_lib.calls) == 0
    mock_session.commit.assert_not_called()


# ── 8. refresh_token_if_needed raises when refresh_token is NULL ──────────────

def test_refresh_token_if_needed_raises_when_no_refresh_token():
    now = datetime.now(tz=timezone.utc)
    expired_at = now - timedelta(minutes=1)

    mock_cred = MagicMock()
    mock_cred.expires_at = expired_at
    mock_cred.refresh_token = None

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_cred

    with patch("backend.services.google.Session", return_value=mock_session):
        with pytest.raises(ExternalServiceError, match="refresh token is missing"):
            refresh_token_if_needed(TEST_USER_ID)
