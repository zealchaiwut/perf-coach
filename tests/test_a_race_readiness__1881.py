"""P6-7 (#1881) — A-race readiness checklist."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.services import a_race_readiness_checklist as arc
from backend.services import race_hero as rh

TODAY = date(2026, 11, 8)
UID = uuid.uuid4()
RACE_DATE = TODAY + timedelta(days=28)


def a_race(**kw):
    base = dict(
        id=uuid.uuid4(),
        name="Osaka",
        race_date=RACE_DATE,
        distance_km=42.195,
        goal_time_seconds=16200,
        goal_pace_seconds_per_km=384,
        priority="A",
        role="a_race",
        race_type="race",
        status="planned",
        notes=None,
        toilet_plan_done=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def run_on(d, *, dur=12600, dist=42.0, gel=None, fluid=None, race_shoe=False):
    return SimpleNamespace(
        workout_date=d,
        duration_seconds=dur,
        distance_km=dist,
        workout_type="run",
        run_subtype="longrun",
        gel_count=gel,
        fluid_level=fluid,
        manual_overrides={"race_shoe": True} if race_shoe else None,
        shoe_id=None,
    )


V2_PERF = (Path("frontend/pages/v2-performance.html")).read_text(encoding="utf-8")
V2_JS = (Path("frontend/js/v2-performance.js")).read_text(encoding="utf-8")


def test_fuel_run_requires_gels_and_fluid():
    ok = run_on(TODAY, dur=5400, gel=3, fluid="ok")
    assert arc._fuel_run_ok(ok)
    short = run_on(TODAY, dur=3000, gel=1, fluid="ok")
    assert not arc._fuel_run_ok(short)
    bad = run_on(TODAY, dur=5400, gel=0, fluid="ok")
    assert not arc._fuel_run_ok(bad)


def test_long_runs_item_counts_in_window():
    session = MagicMock()
    mid = RACE_DATE - timedelta(weeks=5)
    rows = [run_on(mid, dur=12600), run_on(mid + timedelta(days=2), dur=12600)]
    with patch.object(arc, "_run_workouts", return_value=rows):
        item = arc.item_long_runs(session, UID, RACE_DATE)
    assert item["state"] == "done" and item["count_label"] == "2 / 2"
    assert item["detail"] == "2 of 2 long runs done"
    assert "workouts.duration_seconds" in item["source"]


def test_toilet_plan_manual_only():
    done = arc.item_toilet_plan(a_race(notes="Portaloo by village", toilet_plan_done=True))
    assert done["state"] == "done" and done["manual"]
    assert done["detail"] == "Write your race-morning plan"
    assert done["note"] == "Portaloo by village"
    todo = arc.item_toilet_plan(a_race())
    assert todo["state"] == "not_started"


def test_build_checklist_no_a_race():
    session = MagicMock()
    with patch.object(arc, "next_a_race", return_value=None):
        out = arc.build_checklist(session, UID, TODAY)
    assert out["available"] is False
    assert out["summary"]["count_label"] == "0 / 6"


def test_hero_includes_readiness_summary():
    race = a_race()
    session = MagicMock()
    checklist = {"done": 3, "total": 6, "count_label": "3 / 6"}
    session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None
    with patch.object(rh, "next_a_race", return_value=race), \
            patch.object(rh, "estimate_race_finish", return_value={"unavailable": True}), \
            patch.object(rh, "get_race_scores", return_value={}), \
            patch("backend.services.a_race_readiness_checklist.build_checklist", return_value={"summary": checklist}):
        out = rh.build_hero(session, UID, TODAY)
    assert out["readiness_checklist"]["count_label"] == "3 / 6"


def test_v2_performance_has_readiness_mount_points():
    assert "v2-perf-readiness" in V2_PERF
    assert 'data-hero="readiness"' in V2_JS
    assert "applyReadiness" in V2_JS
    assert 'href="/v2/settings#thresholds"' in V2_JS and "Update CP" in V2_JS
    assert "it.source" not in V2_JS
    assert "it.detail" in V2_JS
    assert "host.hidden = true" in V2_JS
    assert "workouts.duration_seconds" not in V2_JS
    assert "cp_staleness" not in V2_JS
    assert "P6-14" not in V2_JS


@pytest.fixture
def client():
    from backend.main import app

    return TestClient(app)


def test_a_race_readiness_endpoint_requires_auth(client):
    assert client.get("/api/performance/a-race-readiness").status_code == 401