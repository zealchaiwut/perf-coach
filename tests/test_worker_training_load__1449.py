"""Tests for issue #1449: Worker read API — GET /api/training/load.

AC coverage:
- AC1: endpoint GET /api/training/load?date=YYYY-MM-DD&user=<username> in worker_app.py
- AC2: user resolution — explicit ?user=, WORKER_READ_API_USER env, one-active fallback, 400
- AC3: CTL/ATL/TSB/ACWR from training_load_snapshots; fallback to latest ≤ date; 404 if none
- AC4: verdict from verdict_history, no recompute; null if no row for date
- AC5: response shape: date, snapshot_date, ctl, atl, tsb, acwr, verdict, verdict_date
- AC6: no auth required
- AC7: endpoint ONLY in worker_app, not in backend/main.py
- AC8: tests for default date, explicit date, fallback snapshot, null verdict, user-resolution 400
"""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.worker_app import app


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_snapshot(
    *,
    snapshot_date: date = date(2026, 7, 10),
    ctl: float = 42.5,
    atl: float = 48.0,
    tsb: float = -5.5,
    acwr: float | None = 1.13,
) -> MagicMock:
    row = MagicMock()
    row.snapshot_date = snapshot_date
    row.ctl = ctl
    row.atl = atl
    row.tsb = tsb
    row.acwr = acwr
    return row


def _make_verdict(
    *,
    verdict_date: date = date(2026, 7, 10),
    verdict: str = "build",
) -> MagicMock:
    row = MagicMock()
    row.verdict_date = verdict_date
    row.verdict = verdict
    return row


def _make_user(username: str = "testuser") -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.name = username
    u.is_active = True
    return u


# ── AC7: endpoint in worker_app only ─────────────────────────────────────────

def test_endpoint_registered_in_worker_app():
    """AC7: Route /api/training/load is registered on the worker FastAPI app."""
    routes = {r.path for r in app.routes}
    assert "/api/training/load" in routes, (
        "GET /api/training/load not registered on the worker app"
    )


def test_endpoint_not_in_main():
    """AC7: Route not added to backend/main.py."""
    import backend.main as main_mod
    routes = {getattr(r, "path", None) for r in main_mod.app.routes}
    assert "/api/training/load" not in routes, (
        "GET /api/training/load must NOT be in the main app (deploys to Render)"
    )


# ── AC6: no auth required ─────────────────────────────────────────────────────

def test_no_auth_required():
    """AC6: Endpoint has no authentication dependency — plain GET succeeds without credentials."""
    user = _make_user()
    snap = _make_snapshot()

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)

        q_snap = mock_db.query.return_value.filter.return_value.order_by.return_value.first
        q_snap.return_value = snap
        mock_db.query.return_value.filter.return_value.first.return_value = None  # verdict

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/training/load?date=2026-07-10&user=testuser")

    assert r.status_code in (200, 404)


# ── AC5 + AC8: explicit date, correct response shape ─────────────────────────

def test_explicit_date_returns_correct_shape():
    """AC5/AC8: Explicit date=2026-07-10 returns snapshot fields + verdict in correct shape."""
    user = _make_user()
    snap = _make_snapshot(snapshot_date=date(2026, 7, 10), ctl=42.5, atl=48.0, tsb=-5.5, acwr=1.13)
    verdict = _make_verdict(verdict_date=date(2026, 7, 10), verdict="build")

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)

        def query_side_effect(model):
            from backend.models import TrainingLoadSnapshot
            if model is TrainingLoadSnapshot:
                q = MagicMock()
                q.filter.return_value.order_by.return_value.first.return_value = snap
                return q
            else:  # VerdictHistory
                q = MagicMock()
                q.filter.return_value.first.return_value = verdict
                return q

        mock_db.query.side_effect = query_side_effect

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/training/load?date=2026-07-10&user=testuser")

    assert r.status_code == 200
    data = r.json()
    assert data["date"] == "2026-07-10"
    assert data["snapshot_date"] == "2026-07-10"
    assert data["ctl"] == pytest.approx(42.5)
    assert data["atl"] == pytest.approx(48.0)
    assert data["tsb"] == pytest.approx(-5.5)
    assert data["acwr"] == pytest.approx(1.13)
    assert data["verdict"] == "build"
    assert data["verdict_date"] == "2026-07-10"


# ── AC3: fallback to latest snapshot ≤ date ──────────────────────────────────

def test_fallback_to_latest_snapshot_when_no_row_for_date():
    """AC3/AC8: No snapshot for requested date → latest ≤ date returned with its actual snapshot_date."""
    user = _make_user()
    # snapshot is 3 days old, but it's the most recent one before the requested date
    older_snap = _make_snapshot(snapshot_date=date(2026, 7, 7), ctl=40.0, atl=45.0, tsb=-5.0, acwr=1.05)

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)

        def query_side_effect(model):
            from backend.models import TrainingLoadSnapshot
            if model is TrainingLoadSnapshot:
                q = MagicMock()
                q.filter.return_value.order_by.return_value.first.return_value = older_snap
                return q
            else:
                q = MagicMock()
                q.filter.return_value.first.return_value = None
                return q

        mock_db.query.side_effect = query_side_effect

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/training/load?date=2026-07-10&user=testuser")

    assert r.status_code == 200
    data = r.json()
    assert data["date"] == "2026-07-10"       # requested date
    assert data["snapshot_date"] == "2026-07-07"  # actual snapshot date (older)
    assert data["ctl"] == pytest.approx(40.0)
    assert data["verdict"] is None
    assert data["verdict_date"] is None


# ── AC3: 404 if user has no snapshots at all ──────────────────────────────────

def test_404_when_no_snapshots_at_all():
    """AC3/AC8: User has zero snapshot rows → 404."""
    user = _make_user()

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)

        def query_side_effect(model):
            from backend.models import TrainingLoadSnapshot
            if model is TrainingLoadSnapshot:
                q = MagicMock()
                q.filter.return_value.order_by.return_value.first.return_value = None
                return q
            else:
                q = MagicMock()
                q.filter.return_value.first.return_value = None
                return q

        mock_db.query.side_effect = query_side_effect

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/training/load?date=2026-07-10&user=testuser")

    assert r.status_code == 404


# ── AC4: null verdict when no row for date ───────────────────────────────────

def test_null_verdict_when_no_verdict_row():
    """AC4/AC8: No verdict row for the date → verdict: null, verdict_date: null."""
    user = _make_user()
    snap = _make_snapshot(snapshot_date=date(2026, 7, 10))

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)

        def query_side_effect(model):
            from backend.models import TrainingLoadSnapshot
            if model is TrainingLoadSnapshot:
                q = MagicMock()
                q.filter.return_value.order_by.return_value.first.return_value = snap
                return q
            else:
                q = MagicMock()
                q.filter.return_value.first.return_value = None
                return q

        mock_db.query.side_effect = query_side_effect

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/training/load?date=2026-07-10&user=testuser")

    assert r.status_code == 200
    data = r.json()
    assert data["verdict"] is None
    assert data["verdict_date"] is None


# ── AC4: acwr nullable ────────────────────────────────────────────────────────

def test_acwr_can_be_null():
    """AC4: acwr field is nullable; response must include it as null if not set."""
    user = _make_user()
    snap = _make_snapshot(snapshot_date=date(2026, 7, 10), acwr=None)

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)

        def query_side_effect(model):
            from backend.models import TrainingLoadSnapshot
            if model is TrainingLoadSnapshot:
                q = MagicMock()
                q.filter.return_value.order_by.return_value.first.return_value = snap
                return q
            else:
                q = MagicMock()
                q.filter.return_value.first.return_value = None
                return q

        mock_db.query.side_effect = query_side_effect

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/training/load?date=2026-07-10&user=testuser")

    assert r.status_code == 200
    assert r.json()["acwr"] is None


# ── AC8: default date = today Bangkok ────────────────────────────────────────

def test_default_date_is_today_bangkok():
    """AC8: Omitting ?date= defaults to today in Asia/Bangkok."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    user = _make_user()
    today_bkk = datetime.now(ZoneInfo("Asia/Bangkok")).date()
    snap = _make_snapshot(snapshot_date=today_bkk)

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)

        def query_side_effect(model):
            from backend.models import TrainingLoadSnapshot
            if model is TrainingLoadSnapshot:
                q = MagicMock()
                q.filter.return_value.order_by.return_value.first.return_value = snap
                return q
            else:
                q = MagicMock()
                q.filter.return_value.first.return_value = None
                return q

        mock_db.query.side_effect = query_side_effect

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/training/load?user=testuser")

    assert r.status_code == 200
    assert r.json()["date"] == today_bkk.isoformat()


# ── AC2: user-resolution failure → 400 ───────────────────────────────────────

def test_user_resolution_failure_returns_400():
    """AC2/AC8: _resolve_read_user raises 400 when user cannot be resolved."""
    from fastapi import HTTPException

    with patch(
        "backend.worker_app._resolve_read_user",
        side_effect=HTTPException(status_code=400, detail="?user= required"),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/training/load")

    assert r.status_code == 400


# ── AC3: POST returns 405 ─────────────────────────────────────────────────────

def test_post_returns_405():
    """AC3 (UAT step 3): POST to the read-only endpoint returns 405."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/training/load")
    assert r.status_code == 405
