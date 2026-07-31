"""Tests for load_context field added to GET /api/training-log (issue #246)."""

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app

_client = TestClient(app)
_USER_ID = str(uuid.uuid4())
_UID = uuid.UUID(_USER_ID)


def _make_session_mock(total_workout_days: int, today_snap=None):
    """Session mock for /api/training-log.

    Handles:
    - Workout date-range query → empty list
    - Workout distinct count → total_workout_days
    - TrainingLoadSnapshot today query → today_snap
    """
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    def _query_side_effect(model_or_col):
        m = MagicMock()
        from backend.models import Workout as _W, TrainingLoadSnapshot as _TLS

        if model_or_col is _W.workout_date:
            # distinct().count() chain for total_workout_days
            m.filter.return_value.distinct.return_value.count.return_value = total_workout_days
            return m
        if model_or_col is _TLS:
            m.filter.return_value.first.return_value = today_snap
            return m
        # Workout model query (date-range workouts) and DailyMetric
        m.filter.return_value.filter.return_value = m.filter.return_value
        m.filter.return_value.order_by.return_value.all.return_value = []
        m.filter.return_value.all.return_value = []
        m.filter.return_value.first.return_value = None
        return m

    mock_session.query.side_effect = _query_side_effect
    return mock_session


def _make_snap(ctl: float, atl: float, tsb: float) -> MagicMock:
    snap = MagicMock()
    snap.ctl = ctl
    snap.atl = atl
    snap.tsb = tsb
    snap.snapshot_date = date.today()
    return snap


# ---------------------------------------------------------------------------
# (a) load_context present with ≥ 7 days of data
# ---------------------------------------------------------------------------


def test_training_log_load_context_present_with_enough_data(as_user):
    as_user(_UID)
    snap = _make_snap(ctl=55.0, atl=60.0, tsb=-5.0)
    mock_sess = _make_session_mock(total_workout_days=10, today_snap=snap)

    with patch("backend.main.Session", return_value=mock_sess):
        res = _client.get(f"/api/training-log")

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


# ---------------------------------------------------------------------------
# (b) load_context is null with < 7 days of data
# ---------------------------------------------------------------------------


def test_training_log_load_context_null_with_insufficient_data(as_user):
    as_user(_UID)
    mock_sess = _make_session_mock(total_workout_days=3, today_snap=None)

    with patch("backend.main.Session", return_value=mock_sess):
        res = _client.get(f"/api/training-log")

    assert res.status_code == 200
    body = res.json()
    assert "load_context" in body
    assert body["load_context"] is None


# ---------------------------------------------------------------------------
# (c) interpretation value matches threshold logic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ctl, atl, tsb, expected_label",
    [
        (50.0, 44.0, 6.0, "Fresh"),
        (50.0, 52.0, -2.0, "Neutral"),
        (50.0, 60.0, -10.0, "Productive (high load)"),
        (50.0, 70.0, -20.0, "Overreached (high risk)"),
        (70.0, 65.0, 5.0, "Fresh, well-trained"),
        (20.0, 22.0, -2.0, "Neutral, undertrained"),
    ],
)
def test_training_log_interpretation_matches_threshold(ctl, atl, tsb, expected_label):
    snap = _make_snap(ctl=ctl, atl=atl, tsb=tsb)
    mock_sess = _make_session_mock(total_workout_days=30, today_snap=snap)

    with patch("backend.main.Session", return_value=mock_sess):
        res = _client.get(f"/api/training-log")

    assert res.status_code == 200
    lc = res.json()["load_context"]
    assert lc is not None
    assert lc["interpretation"] == expected_label


# ---------------------------------------------------------------------------
# (d) existing `weeks` field shape is unchanged
# ---------------------------------------------------------------------------


def test_training_log_weeks_field_still_present(as_user):
    as_user(_UID)
    mock_sess = _make_session_mock(total_workout_days=3)

    with patch("backend.main.Session", return_value=mock_sess):
        res = _client.get(f"/api/training-log")

    assert res.status_code == 200
    body = res.json()
    assert "weeks" in body
    assert isinstance(body["weeks"], list)


# ---------------------------------------------------------------------------
# (e) snapshot missing → falls back to on-demand current_load
# ---------------------------------------------------------------------------


def test_training_log_falls_back_to_on_demand_when_no_snapshot(as_user):
    as_user(_UID)
    mock_sess = _make_session_mock(total_workout_days=10, today_snap=None)
    fake_load = {"date": date.today(), "ctl": 42.0, "atl": 38.0, "tsb": 4.0}

    with (
        patch("backend.main.Session", return_value=mock_sess),
        patch("backend.main.current_load", return_value=fake_load) as mock_cl,
    ):
        res = _client.get(f"/api/training-log")

    assert res.status_code == 200
    lc = res.json()["load_context"]
    assert lc is not None
    assert lc["ctl"] == 42.0
    assert lc["tsb"] == 4.0
    mock_cl.assert_called_once()
