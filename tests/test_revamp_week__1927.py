"""Issue #1927 — GET /api/plan/revamp-week with selectable sections."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services import revamp_week as rw
from backend.utils import query_log

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)
WS = date(2026, 11, 16)
ROOT = Path(__file__).resolve().parents[1]
PLAN_JS = (ROOT / "frontend" / "js" / "v2-training-plan.js").read_text(encoding="utf-8")
BOARD_JS = (ROOT / "frontend" / "js" / "v2-plan-week-board.js").read_text(encoding="utf-8")


@pytest.fixture
def client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(resolve_user, None)
        query_log.disable()


def test_unknown_section_422(client):
    res = client.get("/api/plan/revamp-week?sections=board,nope")
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "nope" in detail["unknown"]
    assert "board" in detail["allowed"]


def test_warnings_skipped_without_a_race_or_recent_race():
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    q.first.return_value = None
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = []
    with (
        patch.object(rw, "plan_context", return_value=None),
        patch("backend.services.plan_warnings.revamp_warnings_payload") as wp,
        patch.object(rw, "week_board", return_value={"days": []}),
        patch.object(rw, "generic_week_load", return_value={"mode": "generic"}),
        patch.object(rw, "empty_generic_road", return_value={"mode": "generic", "columns": []}),
        patch.object(rw, "peek_focus_label", return_value=None),
    ):
        out = rw.build_revamp_week(session, UID, week_start=WS, today=TODAY, sections=["warnings"])
    wp.assert_not_called()
    assert out["warnings"]["layout_error"] is None
    assert out["warnings"]["clashes"] == []


def test_peek_focus_label_does_not_compute_radar():
    cached = {"axes": [{"axis": "economy", "label": "Economy", "focus": True}]}
    session = MagicMock()
    with (
        patch("backend.services.derived_cache.derived_signature", return_value="sig"),
        patch("backend.services.summary_cache_store.summary_cache_get", return_value=cached),
        patch("backend.services.radar_payload.build_radar") as build,
        patch("backend.services.derived_cache.get_or_compute") as goc,
    ):
        label = rw.peek_focus_label(session, UID, TODAY)
    assert label == "Economy"
    build.assert_not_called()
    goc.assert_not_called()


def test_section_parity_with_old_builders():
    session = MagicMock()
    board = {"week_start": WS.isoformat(), "days": []}
    load = {"week_start": WS.isoformat(), "target_tss": 100, "logged_tss": 10, "planned_tss": 20}
    road = {"race_name": "A", "columns": [{"week_start": WS.isoformat()}]}
    warnings = {"layout_error": None, "clashes": [], "race_week_note": rw.RACE_WEEK_NOTE}
    ctx = {"chronic_baseline": 200.0, "race": object(), "block_start": WS, "settings": {}}
    with (
        patch.object(rw, "plan_context", return_value=ctx),
        patch.object(rw, "week_board", return_value=board),
        patch.object(rw, "revamp_week_load", return_value=load),
        patch.object(rw, "road_to_chart", return_value=road),
        patch("backend.services.plan_warnings.revamp_warnings_payload", return_value=warnings),
        patch.object(rw, "peek_focus_label", return_value="Durability"),
        patch.object(rw, "rail_section", return_value={"next_up": [], "coach_imported": False, "focus_label": "Durability"}),
        patch.object(rw, "upcoming_races_section", return_value=[{"name": "A", "race_date": "2026-12-01", "priority": "A"}]),
    ):
        out = rw.build_revamp_week(session, UID, week_start=WS, today=TODAY)
    assert out["board"] == board
    assert out["week_load"] == load
    assert out["road"] == road
    assert out["warnings"] == warnings
    assert out["rail"]["focus_label"] == "Durability"
    assert out["upcoming_races"][0]["priority"] == "A"


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


def test_full_call_query_count_bounded(client, caplog):
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    inner = MagicMock()
    q = inner.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = []
    q.first.return_value = None
    Sess = _counting_session(sql_engine, inner)
    payload = {
        "week_start": WS.isoformat(),
        "board": {"days": []},
        "week_load": {"target_tss": 1},
        "road": {"columns": []},
        "warnings": rw.EMPTY_WARNINGS,
        "rail": {"next_up": [], "coach_imported": False, "focus_label": None},
        "upcoming_races": [],
    }
    with (
        caplog.at_level(logging.INFO, logger="backend.query_log"),
        patch("backend.main.Session", Sess),
        patch("backend.services.revamp_week.build_revamp_week", side_effect=_fire_select(sql_engine, payload)),
    ):
        res = client.get("/api/plan/revamp-week")
    assert res.status_code == 200, res.text
    records = [
        r
        for r in caplog.records
        if r.name == "backend.query_log" and getattr(r, "path", None) == "/api/plan/revamp-week"
    ]
    assert records, caplog.text
    assert records[-1].query_count <= 15
    assert records[-1].write_count == 0


def test_plan_page_calls_revamp_week_not_old_gets():
    hay = PLAN_JS + "\n" + BOARD_JS
    assert "/api/plan/revamp-week?" in hay
    assert "board,week_load" in hay
    for path in (
        "/api/plan/revamp-week-board",
        "/api/plan/revamp-week-load",
        "/api/plan/revamp-road-chart",
        "/api/plan/revamp-warnings'",
        "/api/plan/week-bundle",
        "/api/performance/focus",
        "/api/races'",
    ):
        assert path not in hay
    assert "fmtNextUpDate" in PLAN_JS
    assert "Tue" in PLAN_JS  # weekday short names used for next-up
