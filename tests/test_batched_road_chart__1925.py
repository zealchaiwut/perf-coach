"""Issue #1925 — batched weekly_rollups for the Plan road chart."""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services import revamp_load_plan as rlp
from backend.services.revamp_load_plan import REVAMP_PLAN_DEFAULTS
from backend.utils import query_log

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)
CURRENT_WS = date(2026, 11, 23)
BLOCK_START = date(2026, 8, 10)  # 16 Mondays through 2026-11-23
RACE_DATE = date(2026, 11, 23)


def _weeks(n=16):
    return [BLOCK_START + timedelta(weeks=i) for i in range(n)]


def _rollup(ws: date, *, tss=40.0, planned=10.0, target=100.0, phase="build"):
    return {
        "week_start": ws.isoformat(),
        "tss_total": tss,
        "planned_tss_training": planned,
        "race_planned_tss": 0,
        "race_items": [],
        "target_tss": target,
        "phase": phase,
    }


def _ctx(n=16):
    weeks = _weeks(n)
    return {
        "race": SimpleNamespace(id=uuid.uuid4(), race_date=weeks[-1], name="A"),
        "block_start": weeks[0],
        "settings": {**REVAMP_PLAN_DEFAULTS},
        "chronic_baseline": 200.0,
        "row": None,
    }


def test_road_to_chart_calls_weekly_rollups_once():
    weeks = _weeks(16)
    rolls = [_rollup(w, phase="build" if i < 8 else "peak_hold") for i, w in enumerate(weeks)]
    session = MagicMock()
    with (
        patch.object(rlp, "week_starts_in_block", return_value=weeks),
        patch("backend.services.weekly_rollup.weekly_rollup") as single,
        patch("backend.services.weekly_rollup.weekly_rollups", return_value=rolls) as batched,
        patch("backend.services.revamp_plan_settings.plan_context", return_value=_ctx()),
    ):
        out = rlp.road_to_chart(UID, session=session, today=TODAY)
    batched.assert_called_once()
    single.assert_not_called()
    assert out is not None
    assert len(out["columns"]) == 16


def test_road_chart_parity_with_per_week_columns():
    weeks = _weeks(16)
    b_race = {"name": "B", "tss": 50}
    rolls = []
    for i, w in enumerate(weeks):
        rolls.append(
            _rollup(
                w,
                tss=30.0 + i,
                planned=12.0,
                target=100.0 + i,
                phase=["build", "peak_hold", "taper", "race_week"][min(i // 4, 3)],
            )
        )
        if i == 10:
            rolls[-1]["race_items"] = [b_race]
            rolls[-1]["race_planned_tss"] = 50
    expected = [
        rlp._chart_column(
            ws=w,
            current_ws=CURRENT_WS,
            rollup=r,
            target=r["target_tss"],
            phase=r["phase"],
        )
        for w, r in zip(weeks, rolls)
    ]
    session = MagicMock()
    with (
        patch.object(rlp, "week_starts_in_block", return_value=weeks),
        patch("backend.services.weekly_rollup.weekly_rollups", return_value=rolls),
        patch("backend.services.revamp_plan_settings.plan_context", return_value=_ctx()),
    ):
        out = rlp.road_to_chart(UID, session=session, today=TODAY)
    assert out["columns"] == expected
    assert any(c["race_items"] for c in out["columns"])


def test_generic_road_chart_batches_and_keeps_span_weeks():
    ws = CURRENT_WS
    weeks = [ws - timedelta(weeks=i) for i in range(13, -1, -1)]
    rolls = [_rollup(w, target=200.0) for w in weeks]
    session = MagicMock()
    with (
        patch.object(rlp, "chronic_weekly_tss", return_value=200.0),
        patch("backend.services.weekly_rollup.weekly_rollup") as single,
        patch("backend.services.weekly_rollup.weekly_rollups", return_value=rolls) as batched,
    ):
        out = rlp.generic_road_chart(UID, session=session, today=TODAY, span_weeks=14)
    batched.assert_called_once()
    single.assert_not_called()
    ctx = batched.call_args.kwargs.get("plan_ctx") or {}
    assert ctx.get("chronic_baseline") == 200.0
    assert ctx.get("race") is None
    assert out["mode"] == "generic"
    assert len(out["columns"]) == 14


def test_weekly_rollups_chronic_only_skips_snapshot_and_plan_lookup():
    from backend.services.weekly_rollup import weekly_rollups

    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.all.return_value = []
    q.first.return_value = None
    with (
        patch("backend.services.training_load.estimate_historical_pace_and_tss", return_value={}),
        patch("backend.services.revamp_load_plan.chronic_weekly_tss") as chronic,
        patch("backend.services.revamp_plan_settings.get_row") as get_row,
        patch("backend.services.revamp_load_plan.week_target_and_phase") as target,
    ):
        weekly_rollups(
            UID,
            date(2026, 11, 9),
            date(2026, 11, 23),
            session=session,
            today=TODAY,
            plan_ctx={"chronic_baseline": 200.0},
        )
    chronic.assert_not_called()
    get_row.assert_not_called()
    target.assert_not_called()
    models = [c.args[0].__name__ for c in session.query.call_args_list]
    assert "LoadPlanWeekSnapshot" not in models


def test_week_target_prefetched_miss_skips_snapshot_query():
    session = MagicMock()
    ctx = {
        "race": SimpleNamespace(id=uuid.uuid4(), race_date=date(2026, 12, 28), name="A"),
        "block_start": date(2026, 11, 9),
        "settings": {
            **REVAMP_PLAN_DEFAULTS,
            "build_weeks": 2,
            "peak_hold_weeks": 1,
            "taper_factors": [0.75],
            "recover_weeks": 1,
            "rebuild_weeks": 2,
        },
        "chronic_baseline": 100.0,
        "row": None,
    }
    out = rlp.week_target_and_phase(
        UID,
        date(2026, 11, 16),
        session=session,
        today=TODAY,
        ctx=ctx,
        chronic_baseline=100.0,
        settings=ctx["settings"],
        snapshot=None,
    )
    session.query.assert_not_called()
    assert out is not None
    assert out["phase"] == "build"


def test_warnings_and_week_load_reuse_ctx():
    from backend.services import plan_warnings as pw

    ctx = _ctx()
    session = MagicMock()
    with patch.object(pw._rps, "plan_context") as pc:
        pw.layout_error(session, UID, today=TODAY, ctx=ctx)
    pc.assert_not_called()

    with (
        patch("backend.services.revamp_plan_settings.plan_context") as pc2,
        patch.object(rlp, "week_target_and_phase", return_value={"target_tss": 100, "phase": "build", "peak_tss": 120}),
        patch("backend.services.weekly_rollup.weekly_rollup", return_value={"tss_total": 0, "planned_tss_training": 0, "race_items": []}),
    ):
        rlp.revamp_week_load(UID, CURRENT_WS, session=session, today=TODAY, ctx=ctx)
    pc2.assert_not_called()


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


def _fire_select(sql_engine, payload):
    def _fn(*_a, **_k):
        with SASession(sql_engine) as s:
            s.execute(text("SELECT 1"))
        return payload

    return _fn


def test_road_chart_query_count_bounded(client, caplog):
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    inner = MagicMock()
    q = inner.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.all.return_value = []
    q.first.return_value = None
    Sess = _counting_session(sql_engine, inner)
    weeks = _weeks(16)
    rolls = [_rollup(w) for w in weeks]
    ctx = _ctx()

    with (
        caplog.at_level(logging.INFO, logger="backend.query_log"),
        patch("backend.main.Session", Sess),
        patch("backend.services.revamp_plan_settings.plan_context", side_effect=_fire_select(sql_engine, ctx)),
        patch.object(rlp, "week_starts_in_block", return_value=weeks),
        patch("backend.services.weekly_rollup.weekly_rollups", side_effect=_fire_select(sql_engine, rolls)),
    ):
        res = client.get("/api/plan/revamp-road-chart")

    assert res.status_code == 200, res.text
    assert len(res.json()["columns"]) == 16
    records = [
        r
        for r in caplog.records
        if r.name == "backend.query_log" and getattr(r, "path", None) == "/api/plan/revamp-road-chart"
    ]
    assert records, caplog.text
    assert records[-1].query_count <= 12
    assert records[-1].write_count == 0
