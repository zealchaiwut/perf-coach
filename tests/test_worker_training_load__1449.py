"""Tests for issue #1449: Worker read API — GET /api/training/load.

AC coverage:
- AC1: endpoint GET /api/training/load?date=YYYY-MM-DD&user=<username> in worker_app.py
- AC2: user resolution — explicit ?user=, WORKER_READ_API_USER env, one-active fallback, 400
- AC3: CTL/ATL/TSB/ACWR via training_load.current_load — the SAME function the
       webapp calls. SUPERSEDED by issue #1601: this route used to run its own
       "latest snapshot <= date" query with no formula_version or calibration
       check, so Hermes and the dashboard could report different fitness for the
       same day. The "fallback to latest <= date" and "404 if none" behaviours
       were that bug, not a contract, and are gone with it.
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


def _load_from(snap):
    """Stand in for training_load.current_load using a snapshot fixture.

    The route delegates to current_load now (issue #1601), so these tests patch
    that instead of the raw Session query the route used to run. Patched at its
    source — backend.services.training_load — because worker_app imports it
    inside the handler, so it is never a module attribute of worker_app.
    """
    def _fn(user_id, as_of=None):
        return {
            "date": snap.snapshot_date,
            "ctl": snap.ctl,
            "atl": snap.atl,
            "tsb": snap.tsb,
            "acwr": snap.acwr,
        }
    return _fn


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
         patch("backend.services.training_load.current_load", side_effect=_load_from(snap)), \
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
         patch("backend.services.training_load.current_load", side_effect=_load_from(snap)), \
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


# ── AC3 (superseded by #1601) ────────────────────────────────────────────────
#
# Two behaviours used to be asserted here and are deliberately gone:
#
#   test_fallback_to_latest_snapshot_when_no_row_for_date
#       The route took the newest snapshot at-or-before the requested date and
#       returned it, whatever formula version or calibration produced it. That
#       IS the bug in #1601 — it is how Hermes came to report a stale number
#       while the dashboard showed the correct one for the same day.
#
#   test_404_when_no_snapshots_at_all
#       current_load recomputes when no usable snapshot exists rather than
#       giving up, so there is no "no snapshots" state left to 404 on. A brand
#       new athlete now reads as zero fitness, which is true, instead of an
#       error. NOTE: this is a real contract change for Hermes — it must no
#       longer treat 404 as "no data yet".


def test_route_reports_the_requested_date_not_a_stale_snapshot_date():
    """The replacement for the old fallback test.

    current_load answers FOR the requested date — reading a fresh snapshot when
    one exists, recomputing when it does not. So snapshot_date tracks the date
    the numbers describe rather than whatever old row happened to be nearest.
    """
    user = _make_user()
    snap = _make_snapshot(snapshot_date=date(2026, 7, 10), ctl=40.0, atl=45.0, tsb=-5.0)

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.services.training_load.current_load", side_effect=_load_from(snap)), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/training/load?date=2026-07-10&user=testuser")

    assert r.status_code == 200
    assert r.json()["snapshot_date"] == "2026-07-10"


def test_numbers_come_from_current_load_not_a_raw_row():
    """The parity guarantee, asserted at the route: whatever current_load says
    is what Hermes reports. Any divergence would mean the delegation is only
    partial."""
    user = _make_user()
    snap = _make_snapshot(ctl=51.234, atl=44.567, tsb=6.667, acwr=0.987)

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.services.training_load.current_load", side_effect=_load_from(snap)), \
         patch("backend.worker_app.Session") as MockSession:
        mock_db = MagicMock()
        MockSession.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockSession.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        client = TestClient(app, raise_server_exceptions=True)
        r = client.get("/api/training/load?date=2026-07-10&user=testuser")

    data = r.json()
    # Rounded to the webapp's precision: 1 dp for ctl/atl/tsb, 2 for acwr.
    assert data["ctl"] == pytest.approx(51.2)
    assert data["atl"] == pytest.approx(44.6)
    assert data["tsb"] == pytest.approx(6.7)
    assert data["acwr"] == pytest.approx(0.99)


def test_null_verdict_when_no_verdict_row():
    """AC4/AC8: No verdict row for the date → verdict: null, verdict_date: null."""
    user = _make_user()
    snap = _make_snapshot(snapshot_date=date(2026, 7, 10))

    with patch("backend.worker_app._resolve_read_user", return_value=user), \
         patch("backend.services.training_load.current_load", side_effect=_load_from(snap)), \
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
         patch("backend.services.training_load.current_load", side_effect=_load_from(snap)), \
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
         patch("backend.services.training_load.current_load", side_effect=_load_from(snap)), \
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
