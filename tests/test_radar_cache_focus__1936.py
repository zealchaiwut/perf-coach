"""Issue #1936 — radar GET hits derived:radar; focus is applied after the cache read."""
from __future__ import annotations

import copy
import json
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app
from backend.models import User
from backend.services import radar_cache as rc
from backend.services import radar_payload as rp
from backend.services import radar_svg as rs

FIX = Path("tests/fixtures")
PAYLOAD = json.loads((FIX / "radar_payload__1853.json").read_text())
AS_OF = date(2026, 11, 20)
UID = uuid.uuid4()


def _unfocused(payload: dict) -> dict:
    out = copy.deepcopy(payload)
    for a in out["axes"]:
        a["focus"] = False
        a["status"] = rp.axis_status(a)
    out["legend"] = rp.legend_flags(out["axes"])
    out["summary"] = rp.summary_sentence(out["axes"], past=out["legend"]["past"])
    return out


def _mem_cache():
    store: dict = {}

    def fake_get(user_id, key, sig):
        return store.get((str(user_id), key, sig))

    def fake_put(user_id, key, sig, payload):
        store[(str(user_id), key, sig)] = payload

    return store, fake_get, fake_put


def test_apply_focus_ranker_matches_fixture_and_svg():
    unfocused = _unfocused(PAYLOAD)
    out = rp.apply_focus_ranker(copy.deepcopy(unfocused), lambda _axes: "economy")
    assert out == PAYLOAD
    assert rs.render_radar_svg(out, "large") == (FIX / "radar_large__1853.svg").read_text()
    assert rs.render_radar_svg(out, "small") == (FIX / "radar_small__1853.svg").read_text()


def test_apply_focus_ranker_matches_inline_build_radar():
    unfocused = _unfocused(PAYLOAD)
    session = MagicMock()
    ranker = lambda _axes: "economy"
    with (
        patch.object(rp, "build_axes", side_effect=[
            copy.deepcopy(unfocused["axes"]),
            copy.deepcopy(PAYLOAD["axes"]),
        ]),
        patch("backend.services.score_reader.get_scores", return_value={"overall": {}}),
        patch("backend.services.score_reader.get_axis_scores", return_value={"axes": {}}),
        patch("backend.services.axis_snapshot.snapshot_row_on_or_before", return_value=None),
    ):
        inline = rp.build_radar(session, UID, AS_OF, focus_ranker=ranker)
    applied = rp.apply_focus_ranker(copy.deepcopy(unfocused), ranker)
    assert [a["axis"] for a in applied["axes"] if a["focus"]] == ["economy"]
    assert [a["axis"] for a in inline["axes"] if a["focus"]] == ["economy"]
    assert rs.render_radar_svg(applied, "large") == rs.render_radar_svg(inline, "large")
    assert rs.render_radar_svg(applied, "small") == rs.render_radar_svg(inline, "small")


def test_two_calls_one_build_radar_and_cache_stays_unflagged():
    store, fake_get, fake_put = _mem_cache()
    unfocused = _unfocused(PAYLOAD)
    build = MagicMock(return_value=copy.deepcopy(unfocused))
    ranker = lambda _axes: "economy"
    session = MagicMock()
    with (
        patch("backend.services.derived_cache.get_data_version", return_value=1),
        patch("backend.services.derived_cache.summary_cache_get", side_effect=fake_get),
        patch("backend.services.derived_cache.summary_cache_put", side_effect=fake_put),
        patch("backend.services.radar_payload.build_radar", build),
    ):
        a = rc.get_radar_payload(session, UID, AS_OF, focus_ranker=ranker)
        b = rc.get_radar_payload(session, UID, AS_OF, focus_ranker=ranker)
        c = rc.get_radar_payload(session, UID, AS_OF)
    assert build.call_count == 1
    assert [x["axis"] for x in a["axes"] if x["focus"]] == ["economy"]
    assert [x["axis"] for x in b["axes"] if x["focus"]] == ["economy"]
    assert not any(x["focus"] for x in c["axes"])
    cached = store[(str(UID), rc.DERIVED_RADAR_KEY, "dv:1|2026-11-20")]
    assert not any(x["focus"] for x in cached["axes"])
    c["axes"][0]["focus"] = True
    assert not any(x["focus"] for x in cached["axes"])


def test_data_version_bump_recomputes():
    _store, fake_get, fake_put = _mem_cache()
    unfocused = _unfocused(PAYLOAD)
    version = [1]
    build = MagicMock(return_value=copy.deepcopy(unfocused))
    session = MagicMock()
    with (
        patch("backend.services.derived_cache.get_data_version", side_effect=lambda *_a, **_k: version[0]),
        patch("backend.services.derived_cache.summary_cache_get", side_effect=fake_get),
        patch("backend.services.derived_cache.summary_cache_put", side_effect=fake_put),
        patch("backend.services.radar_payload.build_radar", build),
    ):
        rc.get_radar_payload(session, UID, AS_OF, focus_ranker=lambda _a: "economy")
        version[0] = 2
        rc.get_radar_payload(session, UID, AS_OF, focus_ranker=lambda _a: "economy")
    assert build.call_count == 2


def test_radar_then_focus_endpoints_share_one_build():
    store, fake_get, fake_put = _mem_cache()
    unfocused = _unfocused(PAYLOAD)
    build = MagicMock(return_value=copy.deepcopy(unfocused))
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        with (
            patch("backend.services.derived_cache.get_data_version", return_value=1),
            patch("backend.services.derived_cache.summary_cache_get", side_effect=fake_get),
            patch("backend.services.derived_cache.summary_cache_put", side_effect=fake_put),
            patch("backend.services.radar_payload.build_radar", build),
            patch("backend.routers.performance_axes._a_race_distance_km", return_value=None),
            patch("backend.services.focus_ranking.rank_axes", return_value={"focus": {"axis": "economy"}}),
            patch("backend.services.focus_ranking.queued_items", return_value=[]),
            patch("backend.services.focus_ranking.earliest_queue_week", return_value=None),
            patch("backend.services.focus_ranking._phase_lookup", return_value=lambda _w: "build"),
            patch("backend.services.radar_svg.render_radar_svg", return_value="<svg/>"),
        ):
            client = TestClient(app)
            radar = client.get("/api/performance/radar")
            focus = client.get("/api/performance/focus")
    finally:
        app.dependency_overrides.pop(resolve_user, None)
    assert radar.status_code == 200, radar.text
    assert focus.status_code == 200, focus.text
    assert build.call_count == 1
    assert [a["axis"] for a in radar.json()["axes"] if a["focus"]] == ["economy"]
