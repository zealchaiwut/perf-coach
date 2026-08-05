"""Tests for issue #1459: /api/plan/today empty-state must include session_type:null.

AC: The no-row response shape must include a top-level ``session_type: null`` key so
that a Hermes client reading ``response.session_type`` gets ``null`` rather than
``undefined``. The uniform ``sessions: []`` list is kept for backwards compat.

Expected empty-state shape:
    {
        "plan_date": "YYYY-MM-DD",
        "planned": false,
        "session_type": null,
        "sessions": []
    }
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.worker_app import app

_TEST_TOKEN = "test-worker-token-1459"


@pytest.fixture(autouse=True)
def _worker_token(monkeypatch):
    monkeypatch.setenv("WORKER_API_TOKEN", _TEST_TOKEN)


@pytest.fixture(autouse=True)
def _authorised_client(monkeypatch):
    import fastapi.testclient as _tc
    orig = _tc.TestClient.__init__

    def patched(self, *a, **kw):
        orig(self, *a, **kw)
        self.headers.update({"Authorization": f"Bearer {_TEST_TOKEN}"})

    monkeypatch.setattr(_tc.TestClient, "__init__", patched)


def _make_user(username: str = "alice") -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.name = username
    u.is_active = True
    return u


def test_empty_state_includes_session_type_null():
    """AC(#1459): No-row response must include top-level session_type:null."""
    user = _make_user("alice")
    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = []

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/plan/today?date=2026-07-13&user=alice")

    assert r.status_code == 200
    data = r.json()
    assert data["planned"] is False
    assert "session_type" in data, (
        "Empty-state response must include top-level 'session_type' key "
        "(AC #1459: Hermes reads session_type directly; undefined != null)"
    )
    assert data["session_type"] is None, (
        f"Empty-state session_type must be null, got {data['session_type']!r}"
    )


def test_empty_state_still_includes_sessions_list():
    """AC(#1459): Backward-compat — sessions:[] is retained alongside session_type:null."""
    user = _make_user("alice")
    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = []

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/plan/today?date=2026-07-13&user=alice")

    data = r.json()
    assert "sessions" in data, "sessions key must be present even in empty state"
    assert data["sessions"] == []


def test_planned_state_does_not_gain_spurious_top_level_session_type():
    """AC(#1459): When sessions exist, session_type stays inside each session item (not top-level)."""
    from datetime import date
    row = MagicMock()
    row.planned_date = date(2026, 7, 13)
    row.session_type = "run"
    row.name = "Easy run"
    row.structure = None
    row.notes = None
    row.status = "planned"

    user = _make_user("alice")
    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = [row]

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/plan/today?date=2026-07-13&user=alice")

    data = r.json()
    assert data["planned"] is True
    assert "sessions" in data
    assert data["sessions"][0]["session_type"] == "run"


def test_worker_md_empty_state_example_includes_session_type_null():
    """AC(#1459): docs/worker.md empty-state JSON example must include session_type:null."""
    from pathlib import Path

    doc = Path("docs/worker.md").read_text()
    plan_section_start = doc.find("### `GET /api/plan/today`")
    plan_section_end = doc.find("### `GET /api/weight/recent`")
    assert plan_section_start != -1, "plan/today section missing from worker.md"
    plan_section = doc[plan_section_start:plan_section_end]

    empty_state_start = plan_section.find("no session planned")
    assert empty_state_start != -1, "Empty-state example block missing from worker.md plan section"
    empty_state_block = plan_section[empty_state_start:]

    assert '"session_type": null' in empty_state_block or '"session_type":null' in empty_state_block, (
        "docs/worker.md empty-state JSON example must contain '\"session_type\": null' "
        "(AC #1459: align docs with code)"
    )
