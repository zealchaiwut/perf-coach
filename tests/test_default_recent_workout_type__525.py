"""Tests for issue #525 follow-up (#1278): remove conditional pytest.skip calls.

The two tests in this file verify GET /api/workouts/recent-type using an
in-process TestClient with resolve_user overridden, so they always reach the
200 path and the assertions always run — no conditional skips needed.

Acceptance criteria (issue #1278):
  AC — The two conditional pytest.skip calls (lines 32 and 46) are replaced
       with a properly authenticated in-process TestClient so the 200-path
       assertions run unconditionally.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app


class _StubUser:
    def __init__(self, user_id=None):
        self.id = user_id or uuid.uuid4()
        self.name = "test-user-525"
        self.is_admin = False
        self.is_active = True


@pytest.fixture
def authed_client():
    """TestClient with resolve_user stubbed so /api/workouts/recent-type returns 200."""
    stub = _StubUser()
    app.dependency_overrides[resolve_user] = lambda: stub
    with TestClient(app, raise_server_exceptions=True) as c:
        c._stub_user = stub
        yield c
    app.dependency_overrides.pop(resolve_user, None)


def test_endpoint_returns_null_when_no_history(authed_client):
    """AC: endpoint returns {"workout_type": null} for a user with no workout history."""
    mock_session = MagicMock()
    mock_query = mock_session.__enter__.return_value.query.return_value
    mock_query.filter.return_value.order_by.return_value.first.return_value = None

    with patch("backend.main.Session", return_value=mock_session):
        r = authed_client.get("/api/workouts/recent-type")

    assert r.status_code == 200, r.text
    data = r.json()
    assert "workout_type" in data
    assert data["workout_type"] is None


def test_endpoint_returns_most_recent_type(authed_client):
    """AC: endpoint returns {"workout_type": <type>} with the workout_type key present."""
    mock_session = MagicMock()
    mock_query = mock_session.__enter__.return_value.query.return_value
    mock_query.filter.return_value.order_by.return_value.first.return_value = ("run",)

    with patch("backend.main.Session", return_value=mock_session):
        r = authed_client.get("/api/workouts/recent-type")

    assert r.status_code == 200, r.text
    data = r.json()
    assert "workout_type" in data
    assert isinstance(data["workout_type"], str)
    assert data["workout_type"] == "run"


def test_anonymous_request_gets_401():
    """The endpoint rejects unauthenticated requests (no skip needed — always runs)."""
    with TestClient(app, raise_server_exceptions=True) as c:
        r = c.get("/api/workouts/recent-type")
    assert r.status_code == 401
