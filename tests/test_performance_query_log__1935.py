"""Issue #1935 — query_count / write_count / duration_ms / rss_delta_kb on Performance GETs."""
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

PERF_PATHS = [
    "/api/performance/radar",
    "/api/performance/score-cards",
    "/api/performance/hero",
    "/api/performance/a-race-readiness",
    "/api/performance/projection",
    "/api/performance/races",
    "/api/performance/focus",
    "/api/performance/coach-block",
    "/api/performance/mobility-tests",
    "/api/performance/anchor-lifts",
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
    q.limit.return_value = q
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


def _fire_radar(sql_engine, payload):
    def _fn(*_a, **_k):
        query_log.note_radar_cache(hit=False)
        with SASession(sql_engine) as s:
            s.execute(text("SELECT 1"))
        return payload

    return _fn


@pytest.fixture
def client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(resolve_user, None)
        query_log.disable()


def test_rss_delta_kb_on_span(caplog):
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    try:
        with caplog.at_level(logging.INFO, logger="backend.query_log"):
            with query_log.request_span("/api/performance/radar", UID):
                with SASession(sql_engine) as s:
                    s.execute(text("SELECT 1"))
        recs = [r for r in caplog.records if r.name == "backend.query_log"]
        assert recs
        rec = recs[-1]
        assert isinstance(rec.rss_delta_kb, int) and rec.rss_delta_kb >= 0
        assert rec.query_count >= 1
        assert rec.write_count == 0
    finally:
        query_log.disable()


def test_radar_cache_hit_and_miss_on_span():
    query_log.enable()
    cap = []

    class _H(logging.Handler):
        def emit(self, record):
            cap.append(record)

    log = logging.getLogger("backend.query_log")
    h = _H()
    log.addHandler(h)
    log.setLevel(logging.INFO)
    try:
        with query_log.request_span("/api/performance/radar", UID):
            query_log.note_radar_cache(hit=False)
            query_log.note_radar_cache(hit=True)
        with query_log.request_span("/api/performance/focus", UID):
            query_log.note_radar_cache(hit=True)
    finally:
        log.removeHandler(h)
        query_log.disable()
    assert cap[0].radar_cache == "miss"
    assert cap[1].radar_cache == "hit"


@pytest.mark.parametrize("path", PERF_PATHS)
def test_performance_endpoints_emit_query_log(client, caplog, path):
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    inner = _mock_orm()
    Sess = _counting_session(sql_engine, inner)
    radar = {"axes": [], "summary": {}}
    empty = {}
    cards = {"endurance": {}, "speed": {}}

    with (
        caplog.at_level(logging.INFO, logger="backend.query_log"),
        patch("backend.routers.performance_axes.Session", Sess),
        patch(
            "backend.services.radar_payload.build_radar",
            side_effect=_fire_radar(sql_engine, radar),
        ),
        patch(
            "backend.services.derived_cache.get_or_compute",
            side_effect=_fire_radar(sql_engine, radar),
        ),
        patch("backend.services.radar_svg.render_radar_svg", return_value="<svg/>"),
        patch(
            "backend.routers.performance_axes._a_race_distance_km",
            return_value=None,
        ),
        patch(
            "backend.services.score_cards.build_cards",
            side_effect=_fire_select(sql_engine, cards),
        ),
        patch(
            "backend.services.race_hero.build_hero",
            side_effect=_fire_select(sql_engine, empty),
        ),
        patch(
            "backend.services.a_race_readiness_checklist.build_checklist",
            side_effect=_fire_select(sql_engine, empty),
        ),
        patch(
            "backend.services.projection_view.build_projection",
            side_effect=_fire_select(sql_engine, empty),
        ),
        patch(
            "backend.services.race_list.build_race_list",
            side_effect=_fire_select(sql_engine, empty),
        ),
        patch(
            "backend.services.coach_block.fetch_coach_block",
            side_effect=_fire_select(sql_engine, empty),
        ),
        patch(
            "backend.services.axis_strength.get_anchor_lifts",
            side_effect=_fire_select(sql_engine, []),
        ),
        patch(
            "backend.services.axis_mobility.get_mobility",
            side_effect=_fire_select(sql_engine, empty),
        ),
        patch("backend.services.focus_ranking.rank_axes", return_value={"focus": None}),
        patch("backend.services.focus_ranking.queued_items", return_value=[]),
        patch("backend.services.focus_ranking.earliest_queue_week", return_value=None),
        patch("backend.services.focus_ranking._phase_lookup", return_value=lambda _w: "build"),
    ):
        res = client.get(path)

    assert res.status_code == 200, res.text
    records = [
        r
        for r in caplog.records
        if r.name == "backend.query_log" and getattr(r, "path", None) == path
    ]
    assert records, caplog.text
    rec = records[-1]
    assert isinstance(rec.query_count, int) and rec.query_count > 0
    assert isinstance(rec.write_count, int) and rec.write_count >= 0
    assert isinstance(rec.duration_ms, (int, float))
    assert isinstance(rec.rss_delta_kb, int) and rec.rss_delta_kb >= 0
    if path in ("/api/performance/radar", "/api/performance/focus"):
        assert rec.radar_cache in ("hit", "miss")
