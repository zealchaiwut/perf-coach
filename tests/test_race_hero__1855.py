"""P4-8 (#1855) — A-race hero and the after-the-race card."""
import ast
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.services import race_hero as rh

TODAY = date(2026, 11, 8)
UID = uuid.uuid4()


def race(**kw):
    base = dict(
        id=uuid.uuid4(), name="Bangsaen42", race_date=TODAY + timedelta(days=7), distance_km=42.195,
        priority="A", race_type="race", goal_time_seconds=16200, goal_pace_seconds_per_km=384,
    )
    base.update(kw)
    return SimpleNamespace(**base)


EST = {"unavailable": False, "est_sec": 14893, "band_sec": 540, "uncertainty_min": 9, "source": "race_prediction"}
SCORES = {"race_specific": {"endurance": {"score": 38.4}, "speed": {"score": 52.7}}}


def hero(est=EST, r=None, session=None, pace=(353, None)):
    r = r or race()
    session = session or MagicMock()
    session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    empty_checklist = {
        "summary": {"done": 0, "total": 6, "count_label": "0 / 6"},
        "items": [],
    }
    with patch.object(rh, "next_a_race", return_value=r), \
            patch.object(rh, "estimate_race_finish", return_value=est) as e, \
            patch.object(rh, "get_race_scores", return_value=SCORES) as g, \
            patch.object(rh, "compute_goal_pace", return_value=pace) as p, \
            patch("backend.services.a_race_readiness_checklist.build_checklist",
                  return_value=empty_checklist):
        return rh.build_hero(session, UID, TODAY), e, g, p


def test_values_come_from_the_patched_readers_untouched():
    out, e, g, p = hero()
    assert e.called and g.called and p.called
    assert out["estimate"]["est_sec"] == 14893
    assert out["estimate"]["pace_seconds_per_km"] == 353  # from compute_goal_pace, not local division
    assert out["estimate"]["uncertainty_min"] == 9        # printed from the projection, not recomputed
    assert out["race_specific"]["endurance"] == 38.4 and out["race_specific"]["speed"] == 52.7
    assert out["goal"] == {"time_sec": 16200, "pace_seconds_per_km": 384}
    assert out["race"]["days_to_race"] == 7 and out["race"]["name"] == "Bangsaen42"
    assert out["race_specific"]["explanation"] == rh.RACE_SPECIFIC_EXPLANATION


def test_range_endpoints_are_estimate_minus_and_plus_band_exactly():
    out, *_ = hero()
    est, band = EST["est_sec"], EST["band_sec"]
    assert out["estimate"]["range_low_sec"] == est - band == 14353
    assert out["estimate"]["range_high_sec"] == est + band == 15433


def test_gap_is_goal_minus_slow_end_and_estimate():
    out, *_ = hero()
    gap = out["gap"]
    assert gap["goal_minus_estimate_sec"] == 16200 - 14893 == 1307
    assert gap["goal_minus_slow_end_sec"] == 16200 - (14893 + 540) == 767
    assert gap["reading"] == rh.READING_SLOW_END_BEATS


def test_gap_readings():
    assert rh.gap_block(16200, 15900, 600)["reading"] == rh.READING_ESTIMATE_BEATS
    assert rh.gap_block(16200, 16500, 300)["reading"] == rh.READING_BEHIND
    assert rh.gap_block(None, 16500, 300)["reading"] == rh.READING_NO_GOAL
    assert rh.gap_block(16200, None, None)["reading"] == rh.READING_NO_ESTIMATE
    assert rh.gap_block(16200, 16500, None)["goal_minus_slow_end_sec"] == 16200 - 16500


def test_only_subtraction_and_addition_in_the_hero_module():
    """No local recomputation beyond the gap: no multiply/divide/modulo/power anywhere."""
    tree = ast.parse(Path("backend/services/race_hero.py").read_text())
    bad = [
        type(n.op).__name__ for n in ast.walk(tree)
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow))
    ]
    assert bad == []
    assert not any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "round" for n in ast.walk(tree))


def test_unavailable_estimate_degrades_without_hiding_hero():
    out, *_ = hero(est={"unavailable": True, "reason": "no training-load history"})
    assert out["estimate"] == {"available": False, "reason": "no training-load history"}
    assert out["race"]["name"] == "Bangsaen42" and out["gap"]["reading"] == rh.READING_NO_ESTIMATE
    assert out["estimate"].get("range_low_sec") is None


def test_goal_pace_falls_back_to_the_reader_when_unset():
    out, *_ = hero(r=race(goal_pace_seconds_per_km=None), pace=(384, None))
    assert out["goal"]["pace_seconds_per_km"] == 384


def test_no_a_race_still_returns_after_the_race_card():
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    with patch.object(rh, "next_a_race", return_value=None):
        out = rh.build_hero(session, UID, TODAY)
    assert out["race"] is None and out["estimate"] is None
    assert out["after_race"]["copy"] == rh.AFTER_RACE_COPY


def test_after_race_card_shows_next_checkpoint_with_projection_estimate():
    cp = SimpleNamespace(label="Half checkpoint", target_date=TODAY + timedelta(days=30),
                         target_distance_km=21.0975)
    session = MagicMock()
    ckpt_est = {"unavailable": False, "est_sec": 6000, "band_sec": 200, "uncertainty_min": 3, "source": "x"}
    with patch.object(rh, "next_checkpoint", return_value=cp), \
            patch.object(rh, "estimate_race_finish", return_value=ckpt_est) as e, \
            patch.object(rh, "compute_goal_pace", return_value=(284, None)):
        block = rh.build_after_race(session, UID, race(), TODAY)
    nc = block["next_checkpoint"]
    assert nc["label"] == "Half checkpoint" and nc["estimate"]["est_sec"] == 6000
    pseudo = e.call_args[0][1]
    assert pseudo.distance_km == 21.0975 and pseudo.race_date == cp.target_date and pseudo.id is None
    assert "replaces" in block["copy"] and "anchors" in block["copy"]


def test_checkpoint_without_distance_has_no_estimate():
    cp = SimpleNamespace(label="Tune-up", target_date=TODAY + timedelta(days=5), target_distance_km=None)
    with patch.object(rh, "next_checkpoint", return_value=cp):
        block = rh.build_after_race(MagicMock(), UID, race(), TODAY)
    assert block["next_checkpoint"]["estimate"]["available"] is False


def test_endpoint_requires_session():
    from backend.main import app
    assert TestClient(app).get("/api/performance/hero").status_code == 401


def test_endpoint_returns_builder_payload():
    from backend.main import app
    from backend.auth import resolve_user
    from backend.models import User

    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        with patch("backend.services.race_hero.build_hero", return_value={"race": None, "after_race": {}}):
            r = TestClient(app).get("/api/performance/hero")
        assert r.status_code == 200 and r.json()["race"] is None
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_page_wiring():
    html = Path("frontend/pages/v2-performance.html").read_text()
    js = Path("frontend/js/v2-performance.js").read_text()
    assert "v2-perf-hero" in html and "v2-perf-after-race" in html
    assert "/api/performance/hero" in js and "Change race" in js
    assert "Race-specific" in js
