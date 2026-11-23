"""Issue #1919 — server search, paged All, This block from load plan."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User, Workout

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]
LOG_JS = (REPO / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)
OLD = date(2026, 10, 12)  # six weeks before TODAY


def _client():
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


def _workout():
    return SimpleNamespace(
        id=uuid.uuid4(),
        workout_date=OLD,
        workout_type="run",
        run_subtype=None,
        name="Long hill repeats",
        duration_seconds=3600,
        distance_km=16.0,
        avg_hr=None,
        elevation_m=None,
        tss=80,
        source="manual",
        tss_source="manual",
        strava_activity_url=None,
        stryd_activity_pk=None,
        strava_activity_pk=None,
        remarks="",
        feeling=None,
        speed_signal=None,
        speed_signal_basis=None,
        start_time=None,
        avg_power=None,
        created_at=None,
    )


def _session(workouts):
    sess = MagicMock()
    sess.__enter__.return_value = sess
    sess.__exit__.return_value = False

    def query(model, *cols):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.distinct.return_value = q
        q.group_by.return_value = q
        q.first.return_value = None
        q.count.return_value = 0
        q.__iter__.return_value = iter([])
        if model is Workout:
            q.all.return_value = workouts
        else:
            q.all.return_value = []
        return q

    sess.query.side_effect = query
    return sess


def test_search_finds_workout_outside_two_week_window():
    w = _workout()
    client = _client()
    try:
        with (
            patch("backend.main.Session", return_value=_session([w])),
            patch("backend.main._workout_list_tss", return_value=80),
            patch("backend.main._plan_match_map", return_value={}),
        ):
            r = client.get(
                "/api/training-log?from=2026-10-05&to=2026-11-23&search=hill"
            )
        assert r.status_code == 200, r.text
        titles = [
            e.get("title")
            for week in r.json().get("weeks", [])
            for e in week.get("entries", [])
        ]
        assert "Long hill repeats" in titles
        assert any(e.get("date") == "2026-10-12" for week in r.json()["weeks"] for e in week["entries"])
    finally:
        _teardown()


def _fn(src: str, name: str) -> str:
    needle = "function " + name + "("
    start = src.find(needle)
    assert start != -1, name
    brace = src.find("{", start)
    depth = 0
    i = brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    raise AssertionError("unclosed " + name)


def test_frontend_search_debounce_one_request():
    filters = _fn(LOG_JS, "renderFilters")
    assert "setTimeout(function () {" in filters
    assert ", 300)" in filters
    assert "runSearch()" in filters
    search = _fn(LOG_JS, "runSearch")
    assert search.count("fetch(") == 1
    assert "&search=" in search
    assert "No sessions match" in LOG_JS
    assert "state.searchWeeks = []" in search


def test_all_range_pages_by_month_not_three_years():
    assert "-365 * 3" not in LOG_JS
    assert "loadOlderAllMonth" in LOG_JS
    older = _fn(LOG_JS, "loadOlderAllMonth")
    assert "monthBounds" in older
    assert "/api/weekly-rollup?from=" in older
    assert "function applyRange" in LOG_JS


def test_this_block_uses_load_plan_block_start():
    assert "state.blockStart" in LOG_JS
    assert 'option value="block">This block' in LOG_JS
    assert "state.blockStart ? '<option value=\"block\">This block</option>'" in LOG_JS
    apply = _fn(LOG_JS, "applyRange")
    assert "state.blockStart" in apply
    chart = _fn(LOG_JS, "loadChart")
    assert "data.block_start" in chart
