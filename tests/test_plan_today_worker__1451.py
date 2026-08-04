"""Tests for issue #1451: Worker read API — GET /api/plan/today endpoint.

AC coverage:
- AC1: GET /api/plan/today?date=YYYY-MM-DD&user=<username> via _resolve_read_user;
       date defaults to today (Asia/Bangkok)
- AC2: Reads from planned_sessions (planned_date, session_type, name, structure, notes, status)
- AC3: Response for a planned session with target extracted from structure JSONB
- AC4: Rest row → planned:true session_type:rest; no row → planned:false, sessions:[], HTTP 200
- AC5: Multiple sessions on one date returned under sessions:[]
- AC6: Endpoint in worker_app.py only
- AC7: Tests for planned run, rest row, no row (planned:false 200), multi-session day
"""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.worker_app import app


# ── Auth plumbing (#1601) ─────────────────────────────────────────────────────
# The Hermes API now requires a bearer token on reads as well as writes. These
# tests cover route BEHAVIOUR, so they present a valid token; the auth contract
# itself lives in tests/test_worker_read_auth__1601.py.

_TEST_TOKEN = "test-worker-token"


@pytest.fixture(autouse=True)
def _worker_token(monkeypatch):
    monkeypatch.setenv("WORKER_API_TOKEN", _TEST_TOKEN)


@pytest.fixture(autouse=True)
def _authorised_client(monkeypatch):
    """Attach the token to every TestClient this module builds."""
    import fastapi.testclient as _tc
    orig = _tc.TestClient.__init__

    def patched(self, *a, **kw):
        orig(self, *a, **kw)
        self.headers.update({"Authorization": f"Bearer {_TEST_TOKEN}"})

    monkeypatch.setattr(_tc.TestClient, "__init__", patched)



# ── helpers ───────────────────────────────────────────────────────────────────

def _make_session(
    *,
    session_type: str = "run",
    planned_date: date | None = None,
    name: str | None = "Easy run",
    structure: dict | None = None,
    notes: str | None = None,
    status: str = "planned",
) -> MagicMock:
    row = MagicMock()
    row.planned_date = planned_date or date(2026, 7, 13)
    row.session_type = session_type
    row.name = name
    row.structure = structure
    row.notes = notes
    row.status = status
    return row


def _make_user(username: str = "testuser") -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.name = username
    u.is_active = True
    return u


# ── AC6: endpoint exists only in worker app ───────────────────────────────────

def test_endpoint_registered_in_worker_app():
    """AC6: Route /api/plan/today is registered on the worker FastAPI app."""
    routes = {r.path for r in app.routes}
    assert "/api/plan/today" in routes, (
        "GET /api/plan/today not registered on the worker app"
    )


def test_endpoint_not_in_main():
    """AC6: Route not added to backend/main.py."""
    import backend.main as main_mod
    routes = {r.path for r in main_mod.app.routes}
    assert "/api/plan/today" not in routes, (
        "GET /api/plan/today must NOT be in the main app"
    )


# ── AC4: No row for the date → planned:false, HTTP 200 ───────────────────────

def test_no_session_returns_planned_false_200():
    """AC4/AC7: No row for the date → HTTP 200 with planned:false, sessions:[]."""
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
    assert data["plan_date"] == "2026-07-13"
    assert data["sessions"] == []


# ── AC3 + AC7: Planned run day ────────────────────────────────────────────────

def test_planned_run_session_returns_correct_shape():
    """AC3/AC7: Planned run day → planned:true with session details and target."""
    structure = {
        "blocks": [
            {"intensity": "easy", "distance_km": 8.0, "duration_min": 50}
        ]
    }
    session = _make_session(
        session_type="run",
        name="Easy aerobic run",
        structure=structure,
        notes="Keep HR in zone 2",
        status="planned",
    )
    user = _make_user("alice")

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = [session]

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/plan/today?date=2026-07-13&user=alice")

    assert r.status_code == 200
    data = r.json()
    assert data["planned"] is True
    assert data["plan_date"] == "2026-07-13"
    assert len(data["sessions"]) == 1

    s = data["sessions"][0]
    assert s["session_type"] == "run"
    assert s["name"] == "Easy aerobic run"
    assert s["note"] == "Keep HR in zone 2"
    assert s["status"] == "planned"
    assert s["target"]["distance_km"] == 8.0
    assert s["target"]["duration_min"] == 50
    assert s["target"]["intensity"] == "easy"


def test_planned_run_top_level_structure():
    """AC3: target fields also extracted when at top level of structure (not inside blocks)."""
    structure = {"distance_km": 10.0, "duration_min": 60, "intensity": "tempo"}
    session = _make_session(session_type="run", structure=structure)
    user = _make_user("alice")

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = [session]

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/plan/today?date=2026-07-13")

    assert r.status_code == 200
    s = r.json()["sessions"][0]
    assert s["target"]["distance_km"] == 10.0
    assert s["target"]["duration_min"] == 60
    assert s["target"]["intensity"] == "tempo"


def test_target_nulls_when_structure_absent():
    """AC3: target fields are null when structure is None."""
    session = _make_session(session_type="run", structure=None)
    user = _make_user("alice")

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = [session]

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/plan/today?date=2026-07-13")

    assert r.status_code == 200
    s = r.json()["sessions"][0]
    assert s["target"]["distance_km"] is None
    assert s["target"]["duration_min"] is None
    assert s["target"]["intensity"] is None


# ── AC4 + AC7: Rest row ───────────────────────────────────────────────────────

def test_rest_row_returns_planned_true_session_type_rest():
    """AC4/AC7: session_type='rest' row → planned:true, session_type:'rest'."""
    session = _make_session(session_type="rest", name=None, structure=None, notes=None)
    user = _make_user("alice")

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = [session]

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/plan/today?date=2026-07-13")

    assert r.status_code == 200
    data = r.json()
    assert data["planned"] is True
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["session_type"] == "rest"


# ── AC5 + AC7: Multi-session day ─────────────────────────────────────────────

def test_multiple_sessions_returned_as_list():
    """AC5/AC7: Multiple sessions on one date returned under sessions:[]."""
    s1 = _make_session(session_type="run", name="Morning run", structure={"distance_km": 5.0})
    s2 = _make_session(session_type="strength", name="Gym session", structure=None)
    user = _make_user("alice")

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = [s1, s2]

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/plan/today?date=2026-07-13")

    assert r.status_code == 200
    data = r.json()
    assert data["planned"] is True
    assert data["plan_date"] == "2026-07-13"
    assert len(data["sessions"]) == 2
    types = {s["session_type"] for s in data["sessions"]}
    assert types == {"run", "strength"}


# ── AC1: date defaults to today (Asia/Bangkok) ────────────────────────────────

def test_date_defaults_to_today_bangkok():
    """AC1: When ?date= is omitted, defaults to today in Asia/Bangkok."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    user = _make_user("alice")
    today_bkk = datetime.now(ZoneInfo("Asia/Bangkok")).date()

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = []

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/plan/today?user=alice")

    assert r.status_code == 200
    assert r.json()["plan_date"] == today_bkk.isoformat()
