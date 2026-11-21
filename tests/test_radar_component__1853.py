"""P4-6 (#1853) — radar payload + inline-SVG component."""
import json
import re
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.services import radar_payload as rp
from backend.services import radar_svg as rs
from backend.services.axis_spec import PERFORMANCE_AXES

FIX = Path("tests/fixtures")
PAYLOAD = json.loads((FIX / "radar_payload__1853.json").read_text())


def test_fixture_snapshot_large_and_small():
    assert rs.render_radar_svg(PAYLOAD, "large") == (FIX / "radar_large__1853.svg").read_text()
    assert rs.render_radar_svg(PAYLOAD, "small") == (FIX / "radar_small__1853.svg").read_text()


def test_axis_order_fixed():
    assert [a["axis"] for a in PAYLOAD["axes"]] == list(PERFORMANCE_AXES)
    svg = rs.render_radar_svg(PAYLOAD)
    labels = re.findall(r'class="perf-radar-label" data-axis="(\w+)"', svg)
    assert labels == list(PERFORMANCE_AXES)


def test_never_measured_omitted_from_polygon_and_listed_below():
    svg = rs.render_radar_svg(PAYLOAD)
    now = re.search(r'<polygon class="perf-radar-now" points="([^"]+)"', svg).group(1).split()
    assert len(now) == 6  # seven axes, mobility never measured -> closes over six
    assert 'data-axis="mobility" cx' not in svg  # no point drawn
    assert "Not yet measured: Mobility" in svg


def test_stale_points_hollow_dashed_and_focus_amber():
    svg = rs.render_radar_svg(PAYLOAD)
    stale = re.search(r'<circle class="perf-radar-point perf-radar-point--stale" data-axis="endurance"[^>]*>', svg).group(0)
    assert 'fill="#ffffff"' in stale and 'stroke-dasharray="3 2"' in stale
    focus = re.search(r'<circle class="perf-radar-point perf-radar-point--focus" data-axis="economy"[^>]*>', svg).group(0)
    assert 'fill="#b45309"' in focus
    assert svg.count("perf-radar-point--focus") == 1
    assert re.search(r'data-axis="economy"[^>]*fill="#7a3a10"[^>]*>Economy', svg)


def test_rings_and_dashed_28_day_outline():
    svg = rs.render_radar_svg(PAYLOAD)
    for ring in (25, 50, 75):
        assert f'data-ring="{ring}"' in svg
    past = re.search(r'<polygon class="perf-radar-past"[^>]*>', svg).group(0)
    assert 'stroke-dasharray="6 5"' in past


def test_labels_carry_score_and_status():
    svg = rs.render_radar_svg(PAYLOAD)
    assert ">41</tspan>" in svg and ">stale</text>" in svg
    assert ">focus</text>" in svg
    # speed: 45 vs 42 => +3
    assert ">+3</text>" in svg
    assert ">+3</text>" in rs.render_radar_svg(PAYLOAD, "small")


def test_accessible_summary_lists_every_axis_and_value():
    summary = PAYLOAD["summary"]
    for a in PAYLOAD["axes"]:
        assert a["label"] in summary
        if not a["never_measured"]:
            assert f"{a['label']} {int(round(a['score']))}" in summary
    svg = rs.render_radar_svg(PAYLOAD)
    assert 'role="img"' in svg and "<title" in svg and "<desc" in svg
    assert "Endurance 41 (stale)" in svg and "Economy 44 (focus)" in svg


def test_same_numbers_at_both_sizes():
    nums = lambda s: re.findall(r'font-weight="600"[^>]*>(\d+)</tspan>', s)
    assert nums(rs.render_radar_svg(PAYLOAD, "large")) == nums(rs.render_radar_svg(PAYLOAD, "small")) != []


def test_status_precedence_and_delta_format():
    base = {"never_measured": False, "stale": False, "focus": False, "delta_28d": 4.4}
    assert rp.axis_status(base) == "+4"
    assert rp.axis_status({**base, "delta_28d": -2.6}) == "\u22123"
    assert rp.axis_status({**base, "delta_28d": 0.2}) == "0"
    assert rp.axis_status({**base, "delta_28d": None}) == ""
    assert rp.axis_status({**base, "stale": True}) == "stale"
    assert rp.axis_status({**base, "stale": True, "test_due": True}) == "test due"
    assert rp.axis_status({**base, "stale": True, "focus": True}) == "focus"
    assert rp.axis_status({**base, "never_measured": True, "focus": True}) == ""


def test_build_axes_uses_snapshot_for_28_day_values():
    axes = rp.build_axes(
        {"endurance": {"score": 50.0}, "speed": {"score": None}},
        {"economy": {"score": 44, "stale": False}},
        {"endurance": 40.0, "economy": 50},
        focus_axis="speed",  # never-measured axes cannot be focus
    )
    by = {a["axis"]: a for a in axes}
    assert by["endurance"]["score_28d_ago"] == 40.0 and by["endurance"]["delta_28d"] == 10.0
    assert by["economy"]["delta_28d"] == -6.0
    assert by["speed"]["never_measured"] and not by["speed"]["focus"]
    assert by["durability"]["never_measured"]


def _client():
    from backend.main import app
    from backend.auth import resolve_user
    from backend.models import User

    app.dependency_overrides[resolve_user] = lambda: User(id=uuid.uuid4(), name="t")
    return app, resolve_user, TestClient(app)


def test_home_and_performance_get_identical_numbers_from_one_endpoint():
    app, dep, c = _client()
    payload = {k: v for k, v in PAYLOAD.items()}
    try:
        with patch("backend.services.radar_payload.build_radar", return_value=dict(payload)) as build:
            big = c.get("/api/performance/radar?size=large").json()
            small = c.get("/api/performance/radar?size=small").json()
        assert build.call_count == 2
        assert big["axes"] == small["axes"] == PAYLOAD["axes"]
        assert big["summary"] == small["summary"]
        assert big["svg"] != small["svg"] and 'data-size="large"' in big["svg"]
        assert c.get("/api/performance/radar?size=huge").status_code == 422
    finally:
        app.dependency_overrides.pop(dep, None)


def test_radar_endpoint_requires_session():
    from backend.main import app
    assert TestClient(app).get("/api/performance/radar").status_code == 401


def test_both_pages_mount_the_one_component():
    home = Path("frontend/pages/v2-home.html").read_text()
    perf = Path("frontend/pages/v2-performance.html").read_text()
    for html, size in ((home, "small"), (perf, "large")):
        assert "/js/lib/perf-radar.js" in html
        assert f'data-perf-radar data-size="{size}"' in html
    js = Path("frontend/js/lib/perf-radar.js").read_text()
    assert js.count("/api/performance/radar") == 1
    for other in ("v2-performance.js",):
        assert "performance/radar" not in Path("frontend/js", other).read_text()
