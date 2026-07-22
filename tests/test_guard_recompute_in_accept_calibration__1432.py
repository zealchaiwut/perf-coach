"""Tests for issue #1432: Guard recompute_user_snapshots in accept_calibration.

Acceptance criteria verified:
- AC1: If recompute_user_snapshots raises, accept_calibration returns 200 (not 500).
- AC2: On recompute failure the response includes snapshots_recomputed=0 and the
       saved ctl_days/atl_days constants (prefs commit was already successful).
- AC3: On recompute success the response is unchanged (snapshots_recomputed = real count).
"""
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

_USER_ID = str(uuid.uuid4())


def _make_authed_client(user_id_str):
    from fastapi.testclient import TestClient
    from backend.main import app, resolve_user
    from backend.auth import create_session_cookie, COOKIE_NAME, CSRF_COOKIE_NAME, generate_csrf_token

    uid = uuid.UUID(user_id_str)
    mock_user = MagicMock()
    mock_user.id = uid

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    csrf_token = generate_csrf_token()
    session_token = create_session_cookie(user_id_str, time.time())
    client = TestClient(
        app,
        cookies={COOKIE_NAME: session_token, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return client, mock_user


def _mock_session(race_id_str, user_id, ctl_days=35, atl_days=5):
    """Return a mock SQLAlchemy session that resolves the race and prefs."""
    race_uuid = uuid.UUID(race_id_str)

    mock_race = MagicMock()
    mock_race.user_id = user_id

    mock_prefs = MagicMock()
    mock_prefs.ctl_days = ctl_days
    mock_prefs.atl_days = atl_days

    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)
    mock_sess.get.return_value = mock_race
    mock_sess.query.return_value.filter.return_value.first.return_value = mock_prefs

    return mock_sess


# ---------------------------------------------------------------------------
# AC1 — recompute error must not produce a 500
# ---------------------------------------------------------------------------

def test_accept_calibration_returns_200_when_recompute_raises():
    """AC1: A recompute failure must not propagate as a 500 to the caller."""
    from backend.main import app, resolve_user

    race_id = str(uuid.uuid4())
    user_id = uuid.UUID(_USER_ID)
    mock_sess = _mock_session(race_id, user_id)

    client, _ = _make_authed_client(_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch(
                "backend.main.recompute_user_snapshots",
                side_effect=Exception("DB hiccup mid-range"),
            ),
        ):
            resp = client.post(
                f"/api/races/{race_id}/calibrate/accept",
                json={"ctl_days": 35, "atl_days": 5},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert resp.status_code == 200, (
        f"Expected 200 even when recompute raises, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# AC2 — degraded response shape on recompute failure
# ---------------------------------------------------------------------------

def test_accept_calibration_returns_zero_snapshots_recomputed_on_failure():
    """AC2: snapshots_recomputed=0 when recompute raises."""
    from backend.main import app, resolve_user

    race_id = str(uuid.uuid4())
    user_id = uuid.UUID(_USER_ID)
    mock_sess = _mock_session(race_id, user_id, ctl_days=35, atl_days=5)

    client, _ = _make_authed_client(_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch(
                "backend.main.recompute_user_snapshots",
                side_effect=RuntimeError("snapshot write failed"),
            ),
        ):
            resp = client.post(
                f"/api/races/{race_id}/calibrate/accept",
                json={"ctl_days": 35, "atl_days": 5},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("snapshots_recomputed") == 0, (
        f"Expected snapshots_recomputed=0 on recompute error, got {body}"
    )


def test_accept_calibration_returns_saved_constants_on_recompute_failure():
    """AC2: Response includes the saved ctl_days/atl_days even when recompute fails."""
    from backend.main import app, resolve_user

    race_id = str(uuid.uuid4())
    user_id = uuid.UUID(_USER_ID)
    mock_sess = _mock_session(race_id, user_id, ctl_days=28, atl_days=4)

    client, _ = _make_authed_client(_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch(
                "backend.main.recompute_user_snapshots",
                side_effect=Exception("connection reset"),
            ),
        ):
            resp = client.post(
                f"/api/races/{race_id}/calibrate/accept",
                json={"ctl_days": 28, "atl_days": 4},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ctl_days") == 28, f"ctl_days missing/wrong in degraded response: {body}"
    assert body.get("atl_days") == 4, f"atl_days missing/wrong in degraded response: {body}"


# ---------------------------------------------------------------------------
# AC3 — success path unchanged
# ---------------------------------------------------------------------------

def test_accept_calibration_success_path_unchanged():
    """AC3: When recompute succeeds the response is unchanged (snapshots_recomputed = real count)."""
    from backend.main import app, resolve_user

    race_id = str(uuid.uuid4())
    user_id = uuid.UUID(_USER_ID)
    mock_sess = _mock_session(race_id, user_id, ctl_days=42, atl_days=7)

    client, _ = _make_authed_client(_USER_ID)
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch("backend.main.recompute_user_snapshots", return_value=180),
        ):
            resp = client.post(
                f"/api/races/{race_id}/calibrate/accept",
                json={"ctl_days": 42, "atl_days": 7},
            )
    finally:
        app.dependency_overrides.pop(resolve_user, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("snapshots_recomputed") == 180
    assert body.get("ctl_days") == 42
    assert body.get("atl_days") == 7
