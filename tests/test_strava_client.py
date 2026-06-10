"""Tests for issue #374: Strava API client with pagination and rate-limit handling."""
import json
import logging
import urllib.error
import uuid
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from backend.utils.errors import RateLimited

USER_ID = str(uuid.uuid4())
FAKE_TOKEN = "fake-access-token-abc"
_GOOD_HEADERS = {"X-RateLimit-Usage": "10,100", "X-RateLimit-Limit": "600,30000"}


def _mock_resp(body, headers=None):
    """Return a context-manager mock suitable for urllib.request.urlopen."""
    if isinstance(body, (list, dict)):
        body = json.dumps(body).encode()
    headers = headers or {}
    ctx = MagicMock()
    ctx.__enter__ = lambda s: s
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.read = MagicMock(return_value=body)
    ctx.getheader = lambda key, default=None: headers.get(key, default)
    return ctx


def _http_err(code, headers=None):
    headers = headers or {}

    class FakeMsg:
        def get(self, key, default=None):
            return headers.get(key, default)

    return urllib.error.HTTPError(
        url="https://www.strava.com/api/v3/...",
        code=code,
        msg=str(code),
        hdrs=FakeMsg(),
        fp=BytesIO(b""),
    )


# ── (a) yields all activities across multiple pages ───────────────────────────

def test_get_athlete_activities_yields_all_pages():
    """AC (a): yields all activities across multiple pages."""
    from backend.services.strava_client import get_athlete_activities

    page1 = [{"id": i} for i in range(30)]
    page2 = [{"id": i + 30} for i in range(20)]  # partial → stop after this

    resps = [_mock_resp(page1, _GOOD_HEADERS), _mock_resp(page2, _GOOD_HEADERS)]

    with patch("backend.services.strava_client.refresh_token_if_needed", return_value=FAKE_TOKEN), \
         patch("backend.services.strava_client._urlopen", side_effect=resps):
        results = list(get_athlete_activities(USER_ID, after_epoch=None, before_epoch=None))

    assert len(results) == 50
    assert results[0]["id"] == 0
    assert results[30]["id"] == 30


# ── (b) pagination stops on partial page ──────────────────────────────────────

def test_pagination_stops_on_partial_page():
    """AC (b): stops fetching when a page smaller than page_size is returned."""
    from backend.services.strava_client import get_athlete_activities

    partial = [{"id": i} for i in range(5)]
    urlopen_mock = MagicMock(side_effect=[_mock_resp(partial, _GOOD_HEADERS)])

    with patch("backend.services.strava_client.refresh_token_if_needed", return_value=FAKE_TOKEN), \
         patch("backend.services.strava_client._urlopen", urlopen_mock):
        results = list(get_athlete_activities(USER_ID, after_epoch=None, before_epoch=None))

    assert len(results) == 5
    assert urlopen_mock.call_count == 1


# ── (c) HTTP 429 raises RateLimited ───────────────────────────────────────────

def test_http_429_raises_rate_limited():
    """AC (c): HTTP 429 raises RateLimited with retry_after from Retry-After header."""
    from backend.services.strava_client import get_athlete_activities

    with patch("backend.services.strava_client.refresh_token_if_needed", return_value=FAKE_TOKEN), \
         patch("backend.services.strava_client._urlopen", side_effect=_http_err(429, {"Retry-After": "60"})):
        with pytest.raises(RateLimited) as exc_info:
            list(get_athlete_activities(USER_ID, after_epoch=None, before_epoch=None))

    assert exc_info.value.details.get("retry_after") is not None


# ── (d) HTTP 500 retries 3 times then raises ──────────────────────────────────

def test_http_500_retries_3_times_then_raises():
    """AC (d): HTTP 500 retries up to 3 times (4 total attempts) then raises."""
    from backend.services.strava_client import get_athlete_activities

    call_count = {"n": 0}

    def failing_urlopen(req):
        call_count["n"] += 1
        raise _http_err(500)

    with patch("backend.services.strava_client.refresh_token_if_needed", return_value=FAKE_TOKEN), \
         patch("backend.services.strava_client._urlopen", side_effect=failing_urlopen), \
         patch("time.sleep"):
        with pytest.raises(urllib.error.HTTPError):
            list(get_athlete_activities(USER_ID, after_epoch=None, before_epoch=None))

    assert call_count["n"] == 4  # 1 initial + 3 retries


# ── (e) refresh_token_if_needed called before first request ──────────────────

def test_refresh_token_called_before_first_request():
    """AC (e): refresh_token_if_needed is called before the first API request."""
    from backend.services.strava_client import get_athlete_activities

    call_order = []

    def mock_refresh(user_id):
        call_order.append("refresh")
        return FAKE_TOKEN

    def mock_urlopen(req):
        call_order.append("request")
        return _mock_resp([], _GOOD_HEADERS)

    with patch("backend.services.strava_client.refresh_token_if_needed", side_effect=mock_refresh), \
         patch("backend.services.strava_client._urlopen", side_effect=mock_urlopen):
        list(get_athlete_activities(USER_ID, after_epoch=None, before_epoch=None))

    assert "refresh" in call_order
    assert "request" in call_order
    assert call_order.index("refresh") < call_order.index("request")


# ── (f) rate-limit header warning when usage > 80% ───────────────────────────

def test_rate_limit_warning_logged_above_80_percent(caplog):
    """AC (f): WARNING logged when X-RateLimit-Usage > 80% of X-RateLimit-Limit."""
    from backend.services.strava_client import get_athlete_activities

    # 500/600 = 83.3% → triggers warning
    over_headers = {"X-RateLimit-Usage": "500,10000", "X-RateLimit-Limit": "600,30000"}

    with patch("backend.services.strava_client.refresh_token_if_needed", return_value=FAKE_TOKEN), \
         patch("backend.services.strava_client._urlopen", return_value=_mock_resp([], over_headers)):
        with caplog.at_level(logging.WARNING, logger="backend.services.strava_client"):
            list(get_athlete_activities(USER_ID, after_epoch=None, before_epoch=None))

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        "rate" in r.getMessage().lower() or "limit" in r.getMessage().lower()
        for r in warnings
    )
