"""Tests for issue #285: Settings Integrations — configured endpoints and Strava sync."""
import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import create_session_cookie, COOKIE_NAME
from backend.main import app, resolve_user

_USER_ID = "00000000-0000-0000-0000-000000000285"
_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _mock_user(user_id=_USER_ID):
    u = MagicMock()
    u.id = user_id
    return u


def _make_client():
    """TestClient with a valid session cookie and resolve_user overridden."""
    mock_user = _mock_user()

    async def _fake_resolve_user():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve_user
    token = create_session_cookie(_USER_ID, time.time())
    client = TestClient(app, cookies={COOKIE_NAME: token})
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


# ── GET /api/strava/configured ────────────────────────────────────────────────

def test_strava_configured_all_vars_set():
    client, _ = _make_client()
    try:
        env = {
            "STRAVA_CLIENT_ID": "123",
            "STRAVA_CLIENT_SECRET": "secret",
            "STRAVA_STATE_SECRET": "state-secret",
        }
        with patch.dict("os.environ", env, clear=False):
            res = client.get("/api/strava/configured")
        assert res.status_code == 200
        assert res.json() == {"configured": True}
    finally:
        _teardown()


def test_strava_configured_no_vars():
    client, _ = _make_client()
    try:
        with patch("os.getenv", return_value=None):
            res = client.get("/api/strava/configured")
        assert res.status_code == 200
        assert res.json() == {"configured": False}
    finally:
        _teardown()


# ── GET /api/stryd/configured ─────────────────────────────────────────────────

def test_stryd_configured_key_set():
    client, _ = _make_client()
    try:
        with patch.dict("os.environ", {"STRYD_FERNET_KEY": "somekey"}, clear=False):
            res = client.get("/api/stryd/configured")
        assert res.status_code == 200
        assert res.json() == {"configured": True}
    finally:
        _teardown()


def test_stryd_configured_key_missing():
    client, _ = _make_client()
    try:
        with patch("os.getenv", return_value=None):
            res = client.get("/api/stryd/configured")
        assert res.status_code == 200
        assert res.json() == {"configured": False}
    finally:
        _teardown()


# ── POST /api/strava/sync ─────────────────────────────────────────────────────

def _fake_activity(activity_id, name="Morning Run"):
    return {
        "id": activity_id,
        "name": name,
        "type": "Run",
        "start_date": "2024-05-30T07:00:00Z",
        "distance": 10000.0,
        "moving_time": 3600,
        "average_heartrate": 145,
        "max_heartrate": 170,
        "total_elevation_gain": 50.0,
        "average_watts": None,
        "max_watts": None,
        "device_name": "Garmin",
        "external_id": "ext-123",
    }


def test_strava_sync_not_connected_returns_400():
    client, _ = _make_client()
    try:
        with patch("backend.main.refresh_token_if_needed", return_value=None):
            res = client.post("/api/strava/sync")
        assert res.status_code == 400
        assert "not connected" in res.json()["detail"].lower()
    finally:
        _teardown()


def test_strava_sync_no_activities_returns_zero():
    client, _ = _make_client()
    try:
        empty_resp = _urlopen_response([])
        with patch("backend.main.refresh_token_if_needed", return_value="token-abc"), \
             patch("urllib.request.urlopen", return_value=empty_resp):
            res = client.post("/api/strava/sync")
        assert res.status_code == 200
        assert res.json() == {"synced": 0}
    finally:
        _teardown()


def test_strava_sync_upserts_activities_and_returns_count():
    client, _ = _make_client()
    try:
        activities = [_fake_activity(1001), _fake_activity(1002, "Afternoon Run")]
        call_count = [0]

        def _urlopen_side_effect(req):
            call_count[0] += 1
            if call_count[0] == 1:
                return _urlopen_response(activities)
            return _urlopen_response([])

        mock_s = MagicMock()
        mock_s.__enter__ = MagicMock(return_value=mock_s)
        mock_s.__exit__ = MagicMock(return_value=False)

        with patch("backend.main.refresh_token_if_needed", return_value="token-abc"), \
             patch("urllib.request.urlopen", side_effect=_urlopen_side_effect), \
             patch("backend.main.Session", return_value=mock_s):
            res = client.post("/api/strava/sync")

        assert res.status_code == 200
        assert res.json()["synced"] == 2
    finally:
        _teardown()


def test_strava_sync_strava_api_error_returns_502():
    import urllib.error
    client, _ = _make_client()
    try:
        http_err = urllib.error.HTTPError(
            "https://www.strava.com/api/v3/athlete/activities",
            401,
            "Unauthorized",
            {},  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
        with patch("backend.main.refresh_token_if_needed", return_value="token-abc"), \
             patch("urllib.request.urlopen", side_effect=http_err):
            res = client.post("/api/strava/sync")
        assert res.status_code == 502
    finally:
        _teardown()


def test_strava_sync_single_page_returns_correct_count():
    """Fewer than per_page results → single page fetch, no second request."""
    client, _ = _make_client()
    try:
        activities = [_fake_activity(i) for i in range(5)]
        call_count = [0]

        def _urlopen_side_effect(req):
            call_count[0] += 1
            return _urlopen_response(activities)

        mock_s = MagicMock()
        mock_s.__enter__ = MagicMock(return_value=mock_s)
        mock_s.__exit__ = MagicMock(return_value=False)

        with patch("backend.main.refresh_token_if_needed", return_value="tok"), \
             patch("urllib.request.urlopen", side_effect=_urlopen_side_effect), \
             patch("backend.main.Session", return_value=mock_s):
            res = client.post("/api/strava/sync")

        assert res.status_code == 200
        assert res.json()["synced"] == 5
        assert call_count[0] == 1
    finally:
        _teardown()
