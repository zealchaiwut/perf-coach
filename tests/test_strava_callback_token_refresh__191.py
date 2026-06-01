"""Tests for issue #191: GET /api/strava/callback and refresh_token_if_needed."""
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, _make_strava_state_token
from backend.services.strava import refresh_token_if_needed

TEST_SECRET = "test-strava-state-secret-191"
TEST_USER_ID = "00000000-0000-0000-0000-000000000191"

client = TestClient(app)


def _make_state():
    return _make_strava_state_token(TEST_USER_ID, TEST_SECRET)


def _fake_strava_token_response(at="at-new", rt="rt-new", offset=21600, athlete_id=42):
    expires = int((datetime.now(tz=timezone.utc) + timedelta(seconds=offset)).timestamp())
    return {
        "access_token": at,
        "refresh_token": rt,
        "expires_at": expires,
        "athlete": {"id": athlete_id, "firstname": "Test"},
    }


# ── 1. Successful callback creates token row ──────────────────────────────────

def test_callback_success_creates_token(monkeypatch):
    monkeypatch.setenv("STRAVA_STATE_SECRET", TEST_SECRET)
    monkeypatch.setenv("STRAVA_CLIENT_ID", "cid")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "csecret")

    state = _make_state()
    strava_resp = _fake_strava_token_response()

    with patch("backend.main._exchange_strava_code", return_value=strava_resp) as mock_ex, \
         patch("backend.main._upsert_strava_token") as mock_up:
        res = client.get("/api/strava/callback", params={
            "code": "code-abc", "scope": "activity:read_all", "state": state,
        })

    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "strava_connected" in res.text
    assert "window.close()" in res.text
    mock_ex.assert_called_once_with("code-abc", "cid", "csecret")
    mock_up.assert_called_once()
    call_kwargs = mock_up.call_args
    assert call_kwargs.kwargs["user_id"] == TEST_USER_ID
    assert call_kwargs.kwargs["access_token"] == "at-new"


# ── 2. Repeat callback updates same row (no duplicate) ────────────────────────

def test_callback_repeat_upserts_not_duplicates(monkeypatch):
    monkeypatch.setenv("STRAVA_STATE_SECRET", TEST_SECRET)
    monkeypatch.setenv("STRAVA_CLIENT_ID", "cid")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "csecret")

    upsert_calls = []

    with patch("backend.main._exchange_strava_code", return_value=_fake_strava_token_response()), \
         patch("backend.main._upsert_strava_token", side_effect=lambda **kw: upsert_calls.append(kw)):

        state1 = _make_state()
        res1 = client.get("/api/strava/callback", params={
            "code": "code-1", "scope": "activity:read_all", "state": state1,
        })
        state2 = _make_state()
        res2 = client.get("/api/strava/callback", params={
            "code": "code-2", "scope": "activity:read_all", "state": state2,
        })

    assert res1.status_code == 200
    assert res2.status_code == 200
    # Both calls hit _upsert_strava_token which uses ON CONFLICT DO UPDATE —
    # DB-level uniqueness is enforced by the UPSERT, not by calling the function once.
    assert len(upsert_calls) == 2
    assert upsert_calls[0]["user_id"] == TEST_USER_ID
    assert upsert_calls[1]["user_id"] == TEST_USER_ID


# ── 3. Invalid state → 400 ────────────────────────────────────────────────────

def test_callback_invalid_state_returns_400(monkeypatch):
    monkeypatch.setenv("STRAVA_STATE_SECRET", TEST_SECRET)

    res = client.get("/api/strava/callback", params={
        "code": "irrelevant", "scope": "", "state": "bad.state",
    })

    assert res.status_code == 400
    assert "Authorization state expired or invalid" in res.json()["detail"]


# ── 4. Strava 4xx → 502 ───────────────────────────────────────────────────────

def test_callback_strava_4xx_returns_502(monkeypatch):
    monkeypatch.setenv("STRAVA_STATE_SECRET", TEST_SECRET)
    monkeypatch.setenv("STRAVA_CLIENT_ID", "cid")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "csecret")

    state = _make_state()

    import urllib.error
    http_err = urllib.error.HTTPError(
        url="https://www.strava.com/oauth/token",
        code=400,
        msg="Bad Request",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        res = client.get("/api/strava/callback", params={
            "code": "bad-code", "scope": "", "state": state,
        })

    assert res.status_code == 502
    assert "Strava token exchange failed" in res.json()["detail"]


# ── 5. refresh_token_if_needed refreshes expired token ───────────────────────

def test_refresh_token_if_needed_refreshes_expired():
    now = datetime.now(tz=timezone.utc)
    expired_at = now - timedelta(minutes=1)

    mock_token = MagicMock()
    mock_token.expires_at = expired_at
    mock_token.refresh_token = "old-rt"
    mock_token.access_token = "old-at"

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_token

    strava_resp = {
        "access_token": "refreshed-at",
        "refresh_token": "refreshed-rt",
        "expires_at": int((now + timedelta(hours=6)).timestamp()),
    }

    with patch("backend.services.strava.Session", return_value=mock_session), \
         patch("backend.services.strava._call_strava_refresh", return_value=strava_resp) as mock_refresh:
        result = refresh_token_if_needed(TEST_USER_ID)

    assert result == "refreshed-at"
    assert mock_token.access_token == "refreshed-at"
    assert mock_token.refresh_token == "refreshed-rt"
    mock_refresh.assert_called_once()
    mock_session.commit.assert_called_once()


# ── 6. refresh_token_if_needed skips refresh for fresh token ─────────────────

def test_refresh_token_if_needed_skips_when_fresh():
    now = datetime.now(tz=timezone.utc)
    fresh_at = now + timedelta(minutes=10)

    mock_token = MagicMock()
    mock_token.expires_at = fresh_at
    mock_token.access_token = "still-valid-at"

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_token

    with patch("backend.services.strava.Session", return_value=mock_session), \
         patch("backend.services.strava._call_strava_refresh") as mock_refresh:
        result = refresh_token_if_needed(TEST_USER_ID)

    assert result == "still-valid-at"
    mock_refresh.assert_not_called()
    mock_session.commit.assert_not_called()


# ── 7. refresh_token_if_needed returns None for user with no token row ─────────

def test_refresh_token_if_needed_returns_none_when_no_token_row():
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = None

    with patch("backend.services.strava.Session", return_value=mock_session), \
         patch("backend.services.strava._call_strava_refresh") as mock_refresh:
        result = refresh_token_if_needed("user-with-no-strava-token")

    assert result is None
    mock_refresh.assert_not_called()
    mock_session.commit.assert_not_called()
