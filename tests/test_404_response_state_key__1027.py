"""Tests for issue #1027: 404 from performance endpoint must include top-level state key.

Acceptance Criteria:
  AC1: uid not in DB → HTTP 404 with state="error" in body
  AC2: 404 produced by _build_performance_response(state="error", ...) not bare HTTPException
  AC3: 404 body has same top-level keys as success response (state, generated_at, reason)
       and does NOT contain a bare "detail" key alone
  AC4: Success paths (valid athlete) are unaffected → 200 with non-error state
  AC5: No other code path in get_athlete_performance raises bare HTTPException
"""

import uuid
import unittest.mock as mock

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user
from backend.models import User

_REQUIRED_KEYS = {"state", "endurance", "speed", "generated_at"}


def _make_user():
    u = User(name="test-perf-1027-" + uuid.uuid4().hex[:8])
    u.id = uuid.uuid4()
    return u


# ---------------------------------------------------------------------------
# AC1, AC2, AC3: athlete not found in DB → 404 with canonical shape
# ---------------------------------------------------------------------------

def test_athlete_not_found_in_db_returns_404_with_state_key():
    """AC1: session.get(User, uid) returns None → HTTP 404 with state='error'."""
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with mock.patch("backend.main.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session.__enter__ = mock.Mock(return_value=mock_session)
            mock_session.__exit__ = mock.Mock(return_value=False)
            mock_session.get.return_value = None
            mock_session_cls.return_value = mock_session

            res = client.get(f"/api/athletes/{user.id}/performance")

        assert res.status_code == 404, (
            f"Expected 404 for missing athlete, got {res.status_code}: {res.text}"
        )
        data = res.json()
        assert "state" in data, (
            f"AC1 FAIL: 404 body missing 'state' key; got: {data}"
        )
        assert data["state"] == "error", (
            f"AC1 FAIL: expected state='error', got: {data.get('state')!r}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_athlete_not_found_404_body_has_generated_at():
    """AC3: 404 body must contain generated_at (canonical shape)."""
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with mock.patch("backend.main.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session.__enter__ = mock.Mock(return_value=mock_session)
            mock_session.__exit__ = mock.Mock(return_value=False)
            mock_session.get.return_value = None
            mock_session_cls.return_value = mock_session

            res = client.get(f"/api/athletes/{user.id}/performance")

        assert res.status_code == 404
        data = res.json()
        assert "generated_at" in data, (
            f"AC3 FAIL: 404 body missing 'generated_at'; got keys: {list(data.keys())}"
        )
        assert isinstance(data["generated_at"], str) and data["generated_at"], (
            "generated_at must be a non-empty string"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_athlete_not_found_404_body_has_reason():
    """AC3: 404 body must contain reason='athlete not found'."""
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with mock.patch("backend.main.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session.__enter__ = mock.Mock(return_value=mock_session)
            mock_session.__exit__ = mock.Mock(return_value=False)
            mock_session.get.return_value = None
            mock_session_cls.return_value = mock_session

            res = client.get(f"/api/athletes/{user.id}/performance")

        assert res.status_code == 404
        data = res.json()
        assert "reason" in data, (
            f"AC3 FAIL: 404 body missing 'reason'; got keys: {list(data.keys())}"
        )
        assert data["reason"] == "athlete not found", (
            f"AC3 FAIL: expected reason='athlete not found', got: {data.get('reason')!r}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_athlete_not_found_404_body_has_no_bare_detail_key():
    """AC3: 404 body must NOT be the old {'detail': ...} bare HTTPException shape."""
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with mock.patch("backend.main.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session.__enter__ = mock.Mock(return_value=mock_session)
            mock_session.__exit__ = mock.Mock(return_value=False)
            mock_session.get.return_value = None
            mock_session_cls.return_value = mock_session

            res = client.get(f"/api/athletes/{user.id}/performance")

        assert res.status_code == 404
        data = res.json()
        keys = set(data.keys())
        assert keys != {"detail"}, (
            f"AC3 FAIL: 404 body is still the bare HTTPException shape {{detail: ...}}; got: {data}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_athlete_not_found_404_body_has_all_canonical_keys():
    """AC2, AC3: 404 body has the same top-level keys as a canonical performance response."""
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with mock.patch("backend.main.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session.__enter__ = mock.Mock(return_value=mock_session)
            mock_session.__exit__ = mock.Mock(return_value=False)
            mock_session.get.return_value = None
            mock_session_cls.return_value = mock_session

            res = client.get(f"/api/athletes/{user.id}/performance")

        assert res.status_code == 404
        data = res.json()
        missing = _REQUIRED_KEYS - set(data.keys())
        assert not missing, (
            f"AC2/AC3 FAIL: 404 body missing canonical keys: {missing}; got: {data}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ---------------------------------------------------------------------------
# AC5: foreign UUID and malformed UUID also return canonical 404 (not bare HTTPException)
# ---------------------------------------------------------------------------

def test_foreign_uuid_returns_404_with_state_key():
    """AC5: athlete_id != user.id → 404 must include state key, not bare HTTPException."""
    user = _make_user()
    foreign_id = uuid.uuid4()
    assert foreign_id != user.id

    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        res = client.get(f"/api/athletes/{foreign_id}/performance")
        assert res.status_code == 404
        data = res.json()
        assert "state" in data, (
            f"AC5 FAIL: foreign-UUID 404 missing 'state'; got: {data}"
        )
        assert data["state"] == "error", (
            f"AC5 FAIL: expected state='error', got: {data.get('state')!r}"
        )
        assert set(data.keys()) != {"detail"}, (
            "AC5 FAIL: foreign-UUID 404 is still bare HTTPException shape"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_malformed_uuid_returns_404_with_state_key():
    """AC5: non-UUID athlete_id → 404 must include state key, not bare HTTPException."""
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user
    try:
        client = TestClient(app, raise_server_exceptions=False)
        res = client.get("/api/athletes/not-a-valid-uuid/performance")
        assert res.status_code == 404
        data = res.json()
        assert "state" in data, (
            f"AC5 FAIL: malformed-UUID 404 missing 'state'; got: {data}"
        )
        assert data["state"] == "error", (
            f"AC5 FAIL: expected state='error', got: {data.get('state')!r}"
        )
        assert set(data.keys()) != {"detail"}, (
            "AC5 FAIL: malformed-UUID 404 is still bare HTTPException shape"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ---------------------------------------------------------------------------
# AC4: success path is unaffected
# ---------------------------------------------------------------------------

def test_build_performance_response_state_error_shape():
    """AC2: _build_performance_response(state='error', reason='athlete not found')
    produces the expected canonical dict — the function the endpoint must use.
    """
    from backend.main import _build_performance_response
    resp = _build_performance_response(
        state="error",
        endurance=None,
        speed=None,
        generated_at="2026-01-01T00:00:00+00:00",
        reason="athlete not found",
    )
    assert resp["state"] == "error"
    assert resp["reason"] == "athlete not found"
    assert resp["endurance"] is None
    assert resp["speed"] is None
    assert "generated_at" in resp
    assert set(resp.keys()) != {"detail"}


def test_success_path_returns_200_and_non_error_state():
    """AC4: valid athlete with mocked DB → 200 with state != 'error'."""
    user = _make_user()
    app.dependency_overrides[resolve_user] = lambda: user

    try:
        client = TestClient(app, raise_server_exceptions=False)

        # Mock the full session: athlete found, no prefs, no workouts
        with mock.patch("backend.main.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session.__enter__ = mock.Mock(return_value=mock_session)
            mock_session.__exit__ = mock.Mock(return_value=False)

            # athlete exists
            mock_session.get.return_value = user

            # prefs query → None (no prefs row)
            mock_query = mock.MagicMock()
            mock_query.filter.return_value = mock_query
            mock_query.first.return_value = None
            mock_query.order_by.return_value = mock_query
            mock_query.all.return_value = []
            mock_session.query.return_value = mock_query
            mock_session_cls.return_value = mock_session

            # Also patch _performance_signature and _summary_cache_get/_get_athlete_duration_curve
            with mock.patch("backend.main._performance_signature", return_value="sig"), \
                 mock.patch("backend.main._summary_cache_get", return_value=None), \
                 mock.patch("backend.main._get_athlete_duration_curve", return_value={}), \
                 mock.patch("backend.main._latest_race_perf", return_value=None):
                res = client.get(f"/api/athletes/{user.id}/performance")

        assert res.status_code == 200, (
            f"AC4 FAIL: expected 200 for valid athlete, got {res.status_code}: {res.text}"
        )
        data = res.json()
        assert data.get("state") != "error", (
            f"AC4 FAIL: success path should not return state='error'; got: {data.get('state')!r}"
        )
        assert "state" in data, "AC4 FAIL: state key missing from success response"
    finally:
        app.dependency_overrides.pop(resolve_user, None)
