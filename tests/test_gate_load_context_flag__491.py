"""Tests for issue #491: Gate load_context computation behind query flag.

Acceptance Criteria:
  AC1 - plain list (no flag) → load_context absent from response
  AC2 - ?include_load_context=true → load_context present with ctl/atl/tsb
  AC3 - EWMA current_load not called on plain list (no DB history scan)
  AC4 - consumers that pass flag receive data as before
"""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app, resolve_user

_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000491")


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_client():
    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve
    return TestClient(app), mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _make_session_mock(total_workout_days: int, today_snap=None):
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    def _side_effect(model_or_col):
        m = MagicMock()
        from backend.models import Workout as _W, TrainingLoadSnapshot as _TLS

        if model_or_col is _W.workout_date:
            m.filter.return_value.distinct.return_value.count.return_value = total_workout_days
            return m
        if model_or_col is _TLS:
            m.filter.return_value.first.return_value = today_snap
            return m
        m.filter.return_value.filter.return_value = m.filter.return_value
        m.filter.return_value.order_by.return_value.all.return_value = []
        m.filter.return_value.all.return_value = []
        m.filter.return_value.first.return_value = None
        return m

    mock_session.query.side_effect = _side_effect
    return mock_session


def _make_snap(ctl: float, atl: float, tsb: float) -> MagicMock:
    snap = MagicMock()
    snap.ctl = ctl
    snap.atl = atl
    snap.tsb = tsb
    snap.snapshot_date = date.today()
    return snap


# ---------------------------------------------------------------------------
# AC1: plain list → load_context absent
# ---------------------------------------------------------------------------


def test_plain_list_has_no_load_context_field():
    """AC1: without ?include_load_context=true, response must NOT contain load_context."""
    client, _ = _make_client()
    mock_sess = _make_session_mock(total_workout_days=20)
    fake_load = {"date": date.today(), "ctl": 50.0, "atl": 48.0, "tsb": 2.0}
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch("backend.main.current_load", return_value=fake_load),
        ):
            res = client.get("/api/training-log")
        assert res.status_code == 200
        body = res.json()
        assert "load_context" not in body, (
            "load_context must be absent on plain list load"
        )
    finally:
        _teardown()


def test_plain_list_load_context_absent_regardless_of_data_volume():
    """AC1: load_context absent even when user has many workout days (>=7)."""
    client, _ = _make_client()
    snap = _make_snap(ctl=70.0, atl=65.0, tsb=5.0)
    mock_sess = _make_session_mock(total_workout_days=30, today_snap=snap)
    fake_load = {"date": date.today(), "ctl": 70.0, "atl": 65.0, "tsb": 5.0}
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch("backend.main.current_load", return_value=fake_load),
        ):
            res = client.get("/api/training-log")
        assert res.status_code == 200
        assert "load_context" not in res.json()
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# AC2: ?include_load_context=true → load_context present
# ---------------------------------------------------------------------------


def test_flag_true_returns_load_context_with_snapshot():
    """AC2: ?include_load_context=true includes load_context with ctl/atl/tsb."""
    client, _ = _make_client()
    snap = _make_snap(ctl=55.0, atl=60.0, tsb=-5.0)
    mock_sess = _make_session_mock(total_workout_days=10, today_snap=snap)
    try:
        with patch("backend.main.Session", return_value=mock_sess):
            res = client.get("/api/training-log?include_load_context=true")
        assert res.status_code == 200
        body = res.json()
        assert "load_context" in body
        lc = body["load_context"]
        assert lc is not None
        assert lc["ctl"] == 55.0
        assert lc["atl"] == 60.0
        assert lc["tsb"] == -5.0
        assert "interpretation" in lc
        assert lc["as_of"] == date.today().isoformat()
    finally:
        _teardown()


def test_flag_true_returns_null_load_context_with_insufficient_data():
    """AC2: flag present but < 7 days of data → load_context: null."""
    client, _ = _make_client()
    mock_sess = _make_session_mock(total_workout_days=3)
    try:
        with patch("backend.main.Session", return_value=mock_sess):
            res = client.get("/api/training-log?include_load_context=true")
        assert res.status_code == 200
        body = res.json()
        assert "load_context" in body
        assert body["load_context"] is None
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# AC3: EWMA current_load NOT called on plain list
# ---------------------------------------------------------------------------


def test_current_load_not_called_on_plain_list():
    """AC3: current_load (EWMA fallback) is never invoked on a plain list load."""
    client, _ = _make_client()
    mock_sess = _make_session_mock(total_workout_days=20, today_snap=None)
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch("backend.main.current_load") as mock_cl,
        ):
            res = client.get("/api/training-log")
        assert res.status_code == 200
        mock_cl.assert_not_called()
    finally:
        _teardown()




# ---------------------------------------------------------------------------
# AC4: consumers with flag get data as before (fallback to current_load)
# ---------------------------------------------------------------------------


def test_flag_true_falls_back_to_current_load_when_no_snapshot():
    """AC4: with flag and no snapshot, on-demand current_load is called."""
    client, _ = _make_client()
    mock_sess = _make_session_mock(total_workout_days=10, today_snap=None)
    fake_load = {"date": date.today(), "ctl": 42.0, "atl": 38.0, "tsb": 4.0}
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch("backend.main.current_load", return_value=fake_load) as mock_cl,
        ):
            res = client.get("/api/training-log?include_load_context=true")
        assert res.status_code == 200
        lc = res.json()["load_context"]
        assert lc is not None
        assert lc["ctl"] == 42.0
        assert lc["tsb"] == 4.0
        mock_cl.assert_called_once()
    finally:
        _teardown()


def test_weeks_field_always_present_with_or_without_flag():
    """AC4: existing shape of 'weeks' is unaffected by the new flag."""
    client, _ = _make_client()
    mock_sess = _make_session_mock(total_workout_days=5)
    fake_load = {"date": date.today(), "ctl": 10.0, "atl": 10.0, "tsb": 0.0}
    try:
        with (
            patch("backend.main.Session", return_value=mock_sess),
            patch("backend.main.current_load", return_value=fake_load),
        ):
            res_plain = client.get("/api/training-log")
            res_flagged = client.get("/api/training-log?include_load_context=true")
        assert res_plain.status_code == 200
        assert res_flagged.status_code == 200
        assert "weeks" in res_plain.json()
        assert "weeks" in res_flagged.json()
        assert isinstance(res_plain.json()["weeks"], list)
        assert isinstance(res_flagged.json()["weeks"], list)
    finally:
        _teardown()
