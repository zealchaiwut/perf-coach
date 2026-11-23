"""Issue #1939 — GET /api/performance/page with selectable sections."""
from __future__ import annotations

import logging
import uuid
from contextlib import ExitStack, contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services import performance_page as pp
from backend.utils import query_log

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)

OLD_PATHS = [
    "/api/performance/hero",
    "/api/performance/radar",
    "/api/performance/score-cards",
    "/api/performance/a-race-readiness",
    "/api/performance/projection",
    "/api/performance/races",
    "/api/performance/focus",
    "/api/performance/coach-block",
    "/api/performance/mobility-tests",
    "/api/performance/anchor-lifts",
]


def _passthrough_goc(_s, _u, _k, _a, compute):
    return compute()


@pytest.fixture
def client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(resolve_user, None)
        query_log.disable()


def test_unknown_section_422(client):
    res = client.get("/api/performance/page?sections=hero,nope")
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "nope" in detail["unknown"]
    assert "hero" in detail["allowed"]
    assert "radar" in detail["allowed"]


def test_invalid_size_422(client):
    res = client.get("/api/performance/page?size=huge")
    assert res.status_code == 422


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


def _page_patches(sql_engine, *, hero=None, radar=None, cards=None, checklist=None,
                  projection=None, races=None, coach=None, mobility=None, anchors=None,
                  focus=None):
    hero = hero if hero is not None else {"race": None, "after_race": {}}
    radar = radar if radar is not None else {"axes": [], "summary": {}, "legend": {}}
    cards = cards if cards is not None else {"state": "scored", "cards": []}
    checklist = checklist if checklist is not None else {
        "race_id": None, "available": False, "reason": "no_a_race",
        "summary": {"done": 0, "total": 6, "count_label": "0 / 6"}, "items": [],
    }
    projection = projection if projection is not None else {"tiles": {}, "chain": None}
    races = races if races is not None else {"needs_result": [], "upcoming": [], "completed": []}
    coach = coach if coach is not None else {"checkin": {}, "history": []}
    mobility = mobility if mobility is not None else {"never_measured": True}
    anchors = anchors if anchors is not None else []
    focus = focus if focus is not None else {"focus": None, "why_not": []}
    return (
        patch("backend.services.derived_cache.get_or_compute", side_effect=_passthrough_goc),
        patch("backend.services.derived_cache.get_data_version", return_value=1),
        patch("backend.services.radar_cache.get_or_compute", side_effect=_passthrough_goc),
        patch("backend.services.radar_cache.get_radar_payload", side_effect=_fire_select(sql_engine, radar)),
        patch("backend.services.radar_payload.apply_focus_ranker"),
        patch("backend.services.radar_svg.render_radar_svg", return_value="<svg/>"),
        patch("backend.routers.performance_axes._a_race_distance_km", return_value=None),
        patch("backend.services.perf_a_race.next_a_race", return_value=None),
        patch("backend.services.race_hero.build_hero", side_effect=_fire_select(sql_engine, hero)),
        patch("backend.services.a_race_readiness_checklist.build_checklist",
              side_effect=_fire_select(sql_engine, checklist)),
        patch("backend.services.score_cards.build_cards", side_effect=_fire_select(sql_engine, cards)),
        patch("backend.services.projection_view.build_projection",
              side_effect=_fire_select(sql_engine, projection)),
        patch("backend.services.race_list.build_race_list", side_effect=_fire_select(sql_engine, races)),
        patch("backend.services.coach_block.fetch_coach_block", side_effect=_fire_select(sql_engine, coach)),
        patch("backend.services.axis_strength.get_anchor_lifts", side_effect=_fire_select(sql_engine, anchors)),
        patch("backend.services.axis_mobility.get_mobility", side_effect=_fire_select(sql_engine, mobility)),
        patch("backend.services.axis_mobility.mobility_test_dict", return_value={}),
        patch("backend.services.focus_ranking.rank_axes", side_effect=lambda *_a, **_k: dict(focus)),
        patch("backend.services.focus_ranking.queued_items", return_value=[]),
        patch("backend.services.focus_ranking.earliest_queue_week", return_value=None),
        patch("backend.services.focus_ranking._phase_lookup", return_value=lambda _w: "build"),
    )


@contextmanager
def _patched_page(sql_engine, **kwargs):
    with ExitStack() as stack:
        for cm in _page_patches(sql_engine, **kwargs):
            stack.enter_context(cm)
        yield


def test_section_parity_with_old_endpoints_no_a_race(client):
    sql_engine = _sqlite_engine()
    inner = _mock_orm()
    Sess = _counting_session(sql_engine, inner)
    hero = {"race": None, "goal": None, "after_race": {"copy": "x"}}
    radar = {"axes": [{"axis": "speed", "score": 40}], "summary": {"n": 1}, "legend": {}}
    cards = {"state": "scored", "cards": [{"axis": "endurance"}]}
    checklist = {"available": False, "reason": "no_a_race", "items": []}
    projection = {"tiles": {}, "race": None}
    races = {"upcoming": [], "needs_result": [], "completed": []}
    coach = {"checkin": {"state": "due"}, "history": []}
    mobility_axis = {"never_measured": True, "score": None}
    anchors = [{"key": "sldl", "label": "SLDL", "target_factor": 0.6}]
    focus = {"focus": None, "why_not": []}
    with patch("backend.routers.performance_axes.Session", Sess), _patched_page(
        sql_engine, hero=hero, radar=radar, cards=cards, checklist=checklist,
        projection=projection, races=races, coach=coach, mobility=mobility_axis,
        anchors=anchors, focus=focus,
    ):
        old = {path: client.get(path).json() for path in OLD_PATHS}
        page = client.get("/api/performance/page").json()

    assert page["hero"] == old["/api/performance/hero"] == hero
    radar_out = dict(page["radar"])
    focus_out = radar_out.pop("focus")
    assert radar_out == old["/api/performance/radar"]
    assert focus_out == old["/api/performance/focus"]
    assert page["score_cards"] == old["/api/performance/score-cards"] == cards
    assert page["readiness"] == old["/api/performance/a-race-readiness"] == checklist
    assert page["projection"] == old["/api/performance/projection"] == projection
    assert page["races"] == old["/api/performance/races"] == races
    assert page["coach"] == old["/api/performance/coach-block"] == coach
    assert page["mobility"] == old["/api/performance/mobility-tests"]
    assert page["anchors"] == old["/api/performance/anchor-lifts"]
    assert page["anchors"]["anchors"] == anchors


def test_section_parity_with_a_race(client):
    sql_engine = _sqlite_engine()
    inner = _mock_orm()
    Sess = _counting_session(sql_engine, inner)
    hero = {"race": {"id": "r1", "name": "BKK"}, "after_race": {}}
    radar = {"axes": [{"axis": "endurance", "score": 70}], "summary": {}, "legend": {}}
    focus = {"focus": {"axis": "speed", "label": "Speed"}, "why_not": []}
    with patch("backend.routers.performance_axes.Session", Sess), _patched_page(
        sql_engine, hero=hero, radar=radar, focus=focus,
    ):
        old_hero = client.get("/api/performance/hero").json()
        old_radar = client.get("/api/performance/radar").json()
        old_focus = client.get("/api/performance/focus").json()
        page = client.get("/api/performance/page?sections=hero,radar").json()
    assert page["hero"] == old_hero == hero
    radar_out = dict(page["radar"])
    assert radar_out.pop("focus") == old_focus
    assert radar_out == old_radar


def test_failing_section_returns_error_key_http_200(client, caplog):
    sql_engine = _sqlite_engine()
    inner = _mock_orm()
    Sess = _counting_session(sql_engine, inner)
    with caplog.at_level(logging.ERROR), patch("backend.routers.performance_axes.Session", Sess), \
            _patched_page(sql_engine), \
            patch("backend.services.race_hero.build_hero", side_effect=RuntimeError("boom")):
        res = client.get("/api/performance/page?sections=hero,anchors")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["hero"] == {"error": "failed"}
    assert body["anchors"]["anchors"] == []
    assert "performance page section hero failed" in caplog.text


def test_shared_inputs_resolved_once():
    session = _mock_orm()
    scores = {"state": "scored", "overall": {"endurance": {"score": 1}, "speed": {"score": 2}}}
    payload = {"endurance": {}, "speed": {}}
    radar = {"axes": [], "summary": {}, "legend": {}}
    with (
        patch("backend.services.perf_a_race.next_a_race", return_value=None) as race,
        patch("backend.services.score_reader.get_scores", return_value=scores) as get_scores,
        patch("backend.services.performance_scores.get_performance_payload", return_value=payload) as get_payload,
        patch("backend.services.radar_cache.get_radar_payload", return_value=radar) as get_radar,
        patch("backend.services.derived_cache.get_or_compute", side_effect=_passthrough_goc),
        patch("backend.services.radar_cache.get_or_compute", side_effect=_passthrough_goc),
        patch("backend.services.radar_svg.render_radar_svg", return_value="<svg/>"),
        patch("backend.services.radar_payload.apply_focus_ranker"),
        patch("backend.services.focus_ranking.rank_axes", return_value={"focus": None}),
        patch("backend.services.focus_ranking.queued_items", return_value=[]),
        patch("backend.services.focus_ranking.earliest_queue_week", return_value=None),
        patch("backend.services.focus_ranking._phase_lookup", return_value=lambda _w: "build"),
        patch("backend.services.race_hero.build_hero", return_value={"race": None}) as hero_fn,
        patch("backend.services.a_race_readiness_checklist.build_checklist", return_value={"items": []}),
        patch("backend.services.score_cards.build_cards", return_value={"cards": []}) as cards_fn,
        patch("backend.services.projection_view.build_projection", return_value={"tiles": {}}) as proj_fn,
        patch("backend.services.race_list.build_race_list", return_value={"upcoming": []}) as races_fn,
        patch("backend.services.coach_block.fetch_coach_block", return_value={}),
        patch("backend.services.axis_strength.get_anchor_lifts", return_value=[]),
        patch("backend.services.axis_mobility.get_mobility", return_value={}),
        patch("backend.services.axis_mobility.mobility_test_dict", return_value={}),
    ):
        out = pp.build_page(session, UID, TODAY)
    assert set(out) == set(pp.PAGE_SECTIONS)
    assert race.call_count == 1
    assert get_scores.call_count == 1
    assert get_payload.call_count == 1
    assert get_radar.call_count == 1
    assert hero_fn.call_args.kwargs["race"] is None
    assert cards_fn.call_args.kwargs["overall"] == scores
    assert cards_fn.call_args.kwargs["payload"] == payload
    assert proj_fn.call_args.kwargs["race"] is None
    assert proj_fn.call_args.kwargs["overall"] == scores["overall"]
    assert races_fn.call_args.kwargs["race"] is None


def test_old_endpoints_stay_registered(client):
    sql_engine = _sqlite_engine()
    inner = _mock_orm()
    Sess = _counting_session(sql_engine, inner)
    with patch("backend.routers.performance_axes.Session", Sess), _patched_page(sql_engine):
        for path in OLD_PATHS:
            assert client.get(path).status_code == 200, path


def test_full_call_query_count_below_sum_of_old_endpoints(client, caplog):
    sql_engine = _sqlite_engine()
    query_log.enable(engine=sql_engine)
    inner = _mock_orm()
    Sess = _counting_session(sql_engine, inner)
    old_total = 0
    with caplog.at_level(logging.INFO, logger="backend.query_log"), \
            patch("backend.routers.performance_axes.Session", Sess), \
            _patched_page(sql_engine):
        for path in OLD_PATHS:
            res = client.get(path)
            assert res.status_code == 200, res.text
        recs = [
            r for r in caplog.records
            if r.name == "backend.query_log" and getattr(r, "path", None) in OLD_PATHS
        ]
        old_total = sum(r.query_count for r in recs)
        caplog.clear()
        page = client.get("/api/performance/page")
        assert page.status_code == 200, page.text
    page_recs = [
        r for r in caplog.records
        if r.name == "backend.query_log" and getattr(r, "path", None) == "/api/performance/page"
    ]
    assert page_recs, caplog.text
    page_count = page_recs[-1].query_count
    assert page_recs[-1].write_count == 0
    assert page_count < old_total, (
        f"page query_count={page_count} should be below sum of 10 endpoints={old_total}"
    )
    # Recorded for the PR: page vs the 10-endpoint sum under the same mock harness.
    print(f"#1939 query_count page={page_count} old_sum={old_total}")
