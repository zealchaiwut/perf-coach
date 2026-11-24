"""P6-6 (#1880) — season road page and API."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.services import season_road as sr

TODAY = date(2026, 11, 8)
UID = uuid.uuid4()


def race(**kw):
    base = dict(
        id=uuid.uuid4(),
        name="Osaka",
        race_date=TODAY + timedelta(days=40),
        distance_km=42.195,
        goal_time_seconds=16200,
        goal_band_low_seconds=16000,
        goal_band_high_seconds=16400,
        goal_pace_seconds_per_km=384,
        priority="A",
        role="a_race",
        race_type="race",
        status="planned",
        actual_time_seconds=None,
        addon_workout_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_track_status_on_track_when_bands_overlap():
    r = race()
    est = {"est_sec": 15000, "band_sec": 600}
    assert sr.track_status(r, est, 2)["status"] == "on_track"


def test_track_status_building_vs_at_risk_by_readiness():
    r = race(goal_band_low_seconds=15000, goal_band_high_seconds=15100)
    est = {"est_sec": 16000, "band_sec": 100}
    assert sr.track_status(r, est, 2)["status"] == "building"
    assert sr.track_status(r, est, 5)["status"] == "at_risk"


def test_build_season_road_unavailable_without_a_race():
    session = MagicMock()
    with patch.object(sr, "next_a_race", return_value=None):
        out = sr.build_season_road(session, UID, TODAY)
    assert out["available"] is False


def test_build_season_road_includes_timeline_and_readiness():
    from backend.models import Race, Workout

    a = race()
    pb = race(
        id=uuid.uuid4(), name="Half", race_date=TODAY + timedelta(days=10),
        role="pb", priority="B", goal_time_seconds=7200,
    )
    session = MagicMock()
    race_q = MagicMock()
    race_q.filter.return_value.order_by.return_value.all.return_value = [a, pb]
    run_q = MagicMock()
    run_q.filter.return_value.all.return_value = []

    def query_side(model):
        if model is Race:
            return race_q
        if model is Workout:
            return run_q
        return MagicMock()

    session.query.side_effect = query_side
    session.get.return_value = None

    with patch.object(sr, "next_a_race", return_value=a), \
            patch("backend.services.race_hero.build_estimate_block", return_value={"available": True, "est_sec": 15800, "band_sec": 200}), \
            patch("backend.services.race_finish_estimate.estimate_race_finish", return_value={}), \
            patch("backend.services.projection_view.goal_state", return_value={"state": "provisional", "time_sec": 16200}), \
            patch("backend.services.a_race_readiness_checklist.build_checklist", return_value={"summary": {"done": 4, "total": 6, "count_label": "4 / 6"}}):
        out = sr.build_season_road(session, UID, TODAY)
    assert out["available"] is True
    assert out["hero"]["readiness"]["count_label"] == "4 of 6"
    assert out["timeline"]["target_a_race_id"] == str(a.id)
    assert "earlier_rows" in out
    assert len(out["rows"]) == 2
    assert out["rows"][0]["role"] in ("a_race", "pb")


def test_page_route_and_static_assets():
    from backend.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/v2/performance/season-road" in paths

    html = Path("frontend/pages/v2-season-road.html").read_text(encoding="utf-8")
    js = Path("frontend/js/v2-season-road.js").read_text(encoding="utf-8")
    css = Path("frontend/css/revamp.css").read_text(encoding="utf-8")
    assert "sr-root" in html and "v2-season-road.js" in html
    assert "/api/performance/season-road" in js
    assert "data-timeline-node" in js and "data-race-role" in js
    assert "sr-tiles" in css and "@media (max-width: 420px)" in css


def test_performance_links_to_season_road():
    js = Path("frontend/js/v2-performance.js").read_text(encoding="utf-8")
    assert 'href="/v2/performance/season-road"' in js