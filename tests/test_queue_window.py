"""Fast-poll window config (backend.services.queue_window) and the webapp's
GET /api/coach/export/queue-window status endpoint that reports it."""
from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.services.queue_window import (
    is_in_fast_window,
    parse_fast_windows,
    window_status,
)

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")


class _StubUser:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


@pytest.fixture
def stub_user():
    user = _StubUser()
    app.dependency_overrides[resolve_user] = lambda: user
    yield user
    app.dependency_overrides.pop(resolve_user, None)


@pytest.fixture
def client():
    return TestClient(app)


def test_parse_fast_windows_basic():
    assert parse_fast_windows("10:00-12:00,21:00-23:00") == [
        (datetime(2000, 1, 1, 10, 0).time(), datetime(2000, 1, 1, 12, 0).time()),
        (datetime(2000, 1, 1, 21, 0).time(), datetime(2000, 1, 1, 23, 0).time()),
    ]


def test_parse_fast_windows_empty_and_malformed():
    assert parse_fast_windows("") == []
    assert parse_fast_windows(None) == []
    # A malformed entry is dropped, not raised — a typo must not crash either
    # process; a well-formed sibling entry still parses.
    assert parse_fast_windows("nonsense,10:00-12:00") == [
        (datetime(2000, 1, 1, 10, 0).time(), datetime(2000, 1, 1, 12, 0).time())
    ]
    # start >= end is rejected (no overnight-wrap support).
    assert parse_fast_windows("23:00-01:00") == []


def test_is_in_fast_window_boundaries():
    windows = parse_fast_windows("10:00-12:00,21:00-23:00")
    in_ = lambda h, m: is_in_fast_window(datetime(2026, 1, 1, h, m, tzinfo=BANGKOK_TZ), windows)
    assert in_(10, 0) is True  # inclusive start
    assert in_(11, 59) is True
    assert in_(12, 0) is False  # exclusive end
    assert in_(9, 59) is False
    assert in_(21, 30) is True
    assert in_(23, 0) is False


def test_is_in_fast_window_no_windows_configured():
    assert is_in_fast_window(datetime(2026, 1, 1, 11, 0, tzinfo=BANGKOK_TZ), []) is False


def test_window_status_reflects_env(monkeypatch):
    monkeypatch.setenv("QUEUE_POLL_FAST_WINDOWS", "10:00-12:00,21:00-23:00")
    status = window_status()
    assert status["tz"] == "Asia/Bangkok"
    assert status["fast_windows"] == ["10:00-12:00", "21:00-23:00"]
    assert isinstance(status["in_window"], bool)


def test_get_queue_window_endpoint_requires_auth(client):
    app.dependency_overrides.pop(resolve_user, None)
    res = client.get("/api/coach/export/queue-window")
    assert res.status_code == 401


def test_get_queue_window_endpoint_shape(client, stub_user, monkeypatch):
    monkeypatch.setenv("QUEUE_POLL_FAST_WINDOWS", "10:00-12:00,21:00-23:00")
    res = client.get("/api/coach/export/queue-window")
    assert res.status_code == 200
    body = res.json()
    assert body["tz"] == "Asia/Bangkok"
    assert body["fast_windows"] == ["10:00-12:00", "21:00-23:00"]
    assert "in_window" in body
