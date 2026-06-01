"""Tests for load_context on GET /api/training-log (issue #262).

Acceptance criteria:
  (a) load_context present when user has >= 7 days of training data
  (b) load_context is null when user has < 7 days of training data
  (c) interpretation string matches defined thresholds
"""

import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app

_client = TestClient(app)
_USER_ID = str(uuid.uuid4())

_DOCS_FILE = Path(__file__).parent.parent / "docs" / "training-load.md"
_REQUIRED_SECTIONS = [
    "## Purpose",
    "## The Math",
    "## Interpreting Values",
    "## Limitations",
    "## Data Sources",
    "## Endpoints",
    "## References",
]


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
# (a) load_context present with >= 7 days
# ---------------------------------------------------------------------------


def test_load_context_present_with_enough_data():
    snap = _make_snap(ctl=55.0, atl=60.0, tsb=-5.0)
    mock_sess = _make_session_mock(total_workout_days=10, today_snap=snap)

    with patch("backend.main.Session", return_value=mock_sess):
        res = _client.get(f"/api/training-log?user_id={_USER_ID}")

    assert res.status_code == 200
    body = res.json()
    assert "load_context" in body
    lc = body["load_context"]
    assert lc is not None
    assert isinstance(lc["ctl"], float)
    assert isinstance(lc["atl"], float)
    assert isinstance(lc["tsb"], float)
    assert isinstance(lc["interpretation"], str) and lc["interpretation"]
    assert lc["as_of"] == date.today().isoformat()


# ---------------------------------------------------------------------------
# (b) load_context null with < 7 days
# ---------------------------------------------------------------------------


def test_load_context_null_with_insufficient_data():
    mock_sess = _make_session_mock(total_workout_days=6, today_snap=None)

    with patch("backend.main.Session", return_value=mock_sess):
        res = _client.get(f"/api/training-log?user_id={_USER_ID}")

    assert res.status_code == 200
    body = res.json()
    assert "load_context" in body
    assert body["load_context"] is None


# ---------------------------------------------------------------------------
# (c) interpretation matches thresholds: Fresh / Neutral / Productive / Overreached
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tsb, expected_prefix",
    [
        (10.0, "Fresh"),
        (-2.0, "Neutral"),
        (-10.0, "Productive"),
        (-20.0, "Overreached"),
    ],
)
def test_interpretation_matches_threshold(tsb: float, expected_prefix: str):
    snap = _make_snap(ctl=45.0, atl=45.0 - tsb, tsb=tsb)
    mock_sess = _make_session_mock(total_workout_days=30, today_snap=snap)

    with patch("backend.main.Session", return_value=mock_sess):
        res = _client.get(f"/api/training-log?user_id={_USER_ID}")

    assert res.status_code == 200
    lc = res.json()["load_context"]
    assert lc is not None
    assert lc["interpretation"].startswith(expected_prefix)


# ---------------------------------------------------------------------------
# docs/training-load.md — all 7 sections present + Banister/Coggan refs
# ---------------------------------------------------------------------------


def test_training_load_docs_exist():
    assert _DOCS_FILE.exists(), "docs/training-load.md missing"


def test_training_load_docs_has_all_required_sections():
    text = _DOCS_FILE.read_text()
    for section in _REQUIRED_SECTIONS:
        assert section in text, f"Missing section: {section}"


def test_training_load_docs_references_banister_and_coggan():
    text = _DOCS_FILE.read_text()
    assert "Banister" in text
    assert "Coggan" in text


# ---------------------------------------------------------------------------
# existing weeks field is not broken (non-breaking change)
# ---------------------------------------------------------------------------


def test_weeks_field_unchanged():
    mock_sess = _make_session_mock(total_workout_days=2)

    with patch("backend.main.Session", return_value=mock_sess):
        res = _client.get(f"/api/training-log?user_id={_USER_ID}")

    assert res.status_code == 200
    body = res.json()
    assert "weeks" in body
    assert isinstance(body["weeks"], list)
