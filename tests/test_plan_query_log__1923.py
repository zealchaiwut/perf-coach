"""Issue #1923 — query_count / write_count / duration_ms on Plan endpoints."""
from __future__ import annotations

import logging
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.utils import query_log

UID = uuid.uuid4()

PLAN_PATHS = [
    ("/api/plan/revamp-week", "/api/plan/revamp-week"),
    ("/api/plan/revamp-road-chart", "/api/plan/revamp-road-chart"),
    ("/api/plan/week-bundle", "/api/plan/week-bundle"),
    ("/api/performance/focus", "/api/performance/focus"),
]


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


@pytest.fixture
def client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(resolve_user, None)
        query_log.disable()


def _fire_select(sql_engine, payload):
    def _fn(*_a, **_k):
        with SASession(sql_engine) as s:
            s.execute(text("SELECT 1"))
        return payload

    return _fn


def test_write_count_increments_on_insert():
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    with SASession(sql_engine) as s:
        s.execute(text("CREATE TABLE t (id INTEGER)"))
        s.commit()
    cap = []

    class _H(logging.Handler):
        def emit(self, record):
            cap.append(record)

    h = _H()
    log = logging.getLogger("backend.query_log")
    log.addHandler(h)
    log.setLevel(logging.INFO)
    try:
        with query_log.request_span("/api/plan/revamp-week", UID):
            with SASession(sql_engine) as s:
                s.execute(text("INSERT INTO t (id) VALUES (1)"))
                s.execute(text("SELECT id FROM t"))
                s.commit()
    finally:
        log.removeHandler(h)
        query_log.disable()
    rec = cap[-1]
    assert rec.query_count >= 2
    assert rec.write_count == 1
    assert rec.user_id == str(UID)


@pytest.mark.parametrize("path,expected", PLAN_PATHS)
def test_plan_endpoints_emit_query_and_write_count(client, caplog, path, expected):
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    inner = _mock_orm()
    Sess = _counting_session(sql_engine, inner)
    empty = {}
    board = {"week_start": "2026-11-17", "days": []}
    load = {"week_start": "2026-11-17", "logged_tss": 0, "planned_tss": 0, "target_tss": 0}
    road = {"mode": "generic", "columns": []}
    warnings = {"warnings": []}
    sessions = {"from": "2026-11-17", "to": "2026-11-23", "days": []}
    radar = {"axes": []}
    focus = {
        "focus": None, "why_not": [], "distance_class": "marathon",
        "weights": {}, "focus_rationale": None,
    }

    with (
        caplog.at_level(logging.INFO, logger="backend.query_log"),
        patch("backend.main.Session", Sess),
        patch("backend.routers.performance_axes.Session", Sess),
        patch("backend.services.revamp_week_board.week_board", side_effect=_fire_select(sql_engine, board)),
        patch("backend.services.revamp_load_plan.revamp_week_load", side_effect=_fire_select(sql_engine, load)),
        patch("backend.services.revamp_load_plan.generic_week_load", side_effect=_fire_select(sql_engine, load)),
        patch("backend.services.revamp_load_plan.road_to_chart", side_effect=_fire_select(sql_engine, None)),
        patch("backend.services.revamp_load_plan.generic_road_chart", side_effect=_fire_select(sql_engine, road)),
        patch("backend.services.plan_warnings.revamp_warnings_payload", side_effect=_fire_select(sql_engine, warnings)),
        patch("backend.services.revamp_week.build_revamp_week", side_effect=_fire_select(sql_engine, {"week_start": "2026-11-17", "board": board})),
        patch("backend.main.get_planned_sessions", side_effect=_fire_select(sql_engine, sessions)),
        patch("backend.main.get_plan_week_load", side_effect=_fire_select(sql_engine, load)),
        patch("backend.services.radar_cache.get_radar_payload", side_effect=_fire_select(sql_engine, radar)),
        patch("backend.services.focus_ranking.rank_axes", return_value=dict(focus)),
        patch("backend.services.focus_ranking.queued_items", return_value=[]),
        patch("backend.services.focus_ranking.earliest_queue_week", return_value=None),
        patch("backend.services.focus_ranking._phase_lookup", return_value=lambda _w: "build"),
        patch("backend.routers.performance_axes._a_race_distance_km", return_value=None),
    ):
        res = client.get(path)

    assert res.status_code == 200, res.text
    records = [
        r
        for r in caplog.records
        if r.name == "backend.query_log" and getattr(r, "path", None) == expected
    ]
    assert records, caplog.text
    rec = records[-1]
    assert isinstance(rec.query_count, int) and rec.query_count > 0
    assert isinstance(rec.write_count, int) and rec.write_count >= 0
    assert isinstance(rec.duration_ms, (int, float))
    assert rec.user_id == str(UID)
