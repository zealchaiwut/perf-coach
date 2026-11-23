"""Issue #1924 — Plan GETs must not write load-plan snapshots."""
from __future__ import annotations

import inspect
import logging
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession

from backend.auth import resolve_user
from backend.main import (
    app,
    get_plan_revamp_road_chart,
    get_plan_revamp_warnings,
    get_plan_revamp_week_board,
    get_plan_revamp_week_load,
)
from backend.models import User
from backend.services import revamp_load_plan as rlp
from backend.services.revamp_load_plan import REVAMP_PLAN_DEFAULTS
from backend.utils import query_log

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)
# Compact 8-week block: 2 build + 1 peak + 1 taper + race + 1 recover + 2 rebuild.
COMPACT = {
    **REVAMP_PLAN_DEFAULTS,
    "build_weeks": 2,
    "peak_hold_weeks": 1,
    "taper_factors": [0.75],
    "recover_weeks": 1,
    "rebuild_weeks": 2,
}
BLOCK_START = date(2026, 11, 9)
RACE_DATE = date(2026, 12, 28)
GET_PATHS = [
    "/api/plan/revamp-road-chart",
    "/api/plan/revamp-week-load",
    "/api/plan/revamp-warnings",
    "/api/plan/revamp-week-board",
]


def _ctx():
    return {
        "race": SimpleNamespace(id=uuid.uuid4(), race_date=RACE_DATE, name="A"),
        "block_start": BLOCK_START,
        "settings": COMPACT,
        "chronic_baseline": 100.0,
        "row": None,
    }


def _session_no_row():
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    q.first.return_value = None
    q.delete.return_value = 0
    q.all.return_value = []
    return session


def test_finding_get_handlers_never_commit():
    """Finding: GET handlers never commit, so flushed snapshots would roll back."""
    for fn in (
        get_plan_revamp_road_chart,
        get_plan_revamp_week_load,
        get_plan_revamp_warnings,
        get_plan_revamp_week_board,
    ):
        src = inspect.getsource(fn)
        assert "commit(" not in src, fn.__name__


def test_read_path_live_derives_when_snapshot_missing():
    session = _session_no_row()
    with patch.object(rlp, "ensure_snapshots") as ens:
        out = rlp.week_target_and_phase(
            UID,
            date(2026, 11, 16),
            session=session,
            today=TODAY,
            ctx=_ctx(),
            chronic_baseline=100.0,
            settings=COMPACT,
        )
    ens.assert_not_called()
    session.add.assert_not_called()
    session.flush.assert_not_called()
    assert out is not None
    assert out["phase"] == "build"
    assert out["target_tss"] == pytest.approx(100.0 * 1.05**2, rel=1e-3)


def test_started_week_keeps_snapshot_after_settings_would_change():
    snap = SimpleNamespace(target_tss=111.0, phase="build", peak_tss=200.0)
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    q.first.return_value = snap
    live = rlp._live_week_target(
        block_start=BLOCK_START,
        race_date=RACE_DATE,
        week_start=date(2026, 11, 16),
        chronic_baseline=100.0,
        settings=COMPACT,
    )
    assert live["target_tss"] != 111.0
    out = rlp.week_target_and_phase(
        UID,
        date(2026, 11, 16),
        session=session,
        today=TODAY,
        ctx=_ctx(),
        chronic_baseline=100.0,
        settings=COMPACT,
    )
    assert out["target_tss"] == 111.0
    assert out["phase"] == "build"


def test_future_week_rederives_without_snapshot():
    session = _session_no_row()
    future = date(2026, 11, 30)
    with patch.object(rlp, "ensure_snapshots") as ens:
        out = rlp.week_target_and_phase(
            UID,
            future,
            session=session,
            today=TODAY,
            ctx=_ctx(),
            chronic_baseline=100.0,
            settings=COMPACT,
        )
    ens.assert_not_called()
    session.query.assert_not_called()
    assert out is not None
    assert out["phase"] == "taper"


def test_apply_settings_writes_snapshots():
    from backend.services import revamp_plan_settings as rps

    session = MagicMock()
    ctx = _ctx()
    row = SimpleNamespace(
        a_race_id=None, block_start=None, phase={}, peak_tss=None, max_consecutive_days=None,
    )
    with (
        patch.object(rps, "validate_draft"),
        patch.object(rps, "merged_phase_settings", return_value=COMPACT),
        patch("backend.services.plan_warnings.settings_save_allowed", return_value=True),
        patch.object(rps, "preview_settings_change", return_value={"allowed": True}),
        patch.object(rps, "plan_context", return_value=ctx),
        patch.object(rps, "get_row", return_value=row),
        patch.object(rps, "settings_payload", return_value={}),
        patch.object(rps, "ensure_snapshots") as ens,
    ):
        rps.apply_settings(session, UID, {"build_weeks": 2}, today=TODAY)
    ens.assert_called_once()


def test_worker_registers_load_plan_snapshots_job():
    from pathlib import Path

    src = Path("backend/worker_app.py").read_text()
    assert '"load_plan_snapshots": _h_load_plan_snapshots' in src
    assert "load_plan_snapshots:" in src


def test_weekly_rollups_does_not_ensure_snapshots():
    src = inspect.getsource(__import__("backend.services.weekly_rollup", fromlist=["weekly_rollups"]).weekly_rollups)
    assert "ensure_snapshots" not in src


@pytest.fixture
def client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(resolve_user, None)
        query_log.disable()


def _sqlite_engine():
    return create_engine("sqlite://")


def _counting_session(sql_engine, inner):
    class Sess:
        def __init__(self, bind=None, **kwargs):
            self._sa = SASession(bind=sql_engine)
            self._sa.execute(text("SELECT 1"))

        def __enter__(self):
            return inner

        def __exit__(self, *exc):
            self.close()
            return False

        def close(self):
            self._sa.close()

        def __getattr__(self, name):
            return getattr(inner, name)

    return Sess


def _mock_orm():
    inner = MagicMock()
    q = inner.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.distinct.return_value = q
    q.group_by.return_value = q
    q.all.return_value = []
    q.first.return_value = None
    q.count.return_value = 0
    inner.__enter__.return_value = inner
    inner.__exit__.return_value = False
    return inner


def _fire_select(sql_engine, payload):
    def _fn(*_a, **_k):
        with SASession(sql_engine) as s:
            s.execute(text("SELECT 1"))
        return payload

    return _fn


@pytest.mark.parametrize("path", GET_PATHS)
def test_get_plan_endpoints_write_count_zero(client, caplog, path):
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    inner = _mock_orm()
    Sess = _counting_session(sql_engine, inner)
    board = {"week_start": "2026-11-16", "days": []}
    load = {"week_start": "2026-11-16", "logged_tss": 0, "planned_tss": 0, "target_tss": 0}
    road = {"mode": "generic", "columns": []}
    warnings = {"layout_error": None, "clashes": []}

    with (
        caplog.at_level(logging.INFO, logger="backend.query_log"),
        patch("backend.main.Session", Sess),
        patch("backend.services.revamp_week_board.week_board", side_effect=_fire_select(sql_engine, board)),
        patch("backend.services.revamp_load_plan.revamp_week_load", side_effect=_fire_select(sql_engine, load)),
        patch("backend.services.revamp_load_plan.generic_week_load", side_effect=_fire_select(sql_engine, load)),
        patch("backend.services.revamp_load_plan.road_to_chart", side_effect=_fire_select(sql_engine, None)),
        patch("backend.services.revamp_load_plan.generic_road_chart", side_effect=_fire_select(sql_engine, road)),
        patch("backend.services.plan_warnings.revamp_warnings_payload", side_effect=_fire_select(sql_engine, warnings)),
        patch("backend.services.revamp_load_plan.ensure_snapshots") as ens,
    ):
        res = client.get(path)

    assert res.status_code == 200, res.text
    ens.assert_not_called()
    records = [
        r
        for r in caplog.records
        if r.name == "backend.query_log" and getattr(r, "path", None) == path
    ]
    assert records, caplog.text
    assert records[-1].write_count == 0
