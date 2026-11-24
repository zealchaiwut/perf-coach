"""Sprint 149 #1948 — unmeasured radar axes are gaps, not centre vertices."""
from copy import deepcopy

from backend.services import radar_payload as rp
from backend.services import radar_svg as rs
from tests.test_radar_component__1853 import PAYLOAD


def _axes(missing):
    axes = deepcopy(PAYLOAD["axes"])
    for a in axes:
        if a["axis"] in missing:
            a["never_measured"] = True
            a["score"] = None
            a["status"] = ""
            a["focus"] = False
            label, href = rp.axis_action(a["axis"])
            a["action_label"] = label
            a["action_href"] = href
        else:
            if a.get("score") is None:
                a["score"] = 50.0
            a["never_measured"] = False
            a["action_label"] = None
            a["action_href"] = None
    return axes


def _payload(missing):
    axes = _axes(missing)
    flags = rp.legend_flags(axes)
    return {"axes": axes, "legend": flags, "summary": "t", "not_yet_measured": [a["label"] for a in axes if a["never_measured"]]}


def test_zero_one_two_five_unmeasured_edges():
    for missing in ([], ["mobility"], ["mobility", "durability"],
                    ["speed", "economy", "strength", "mobility", "durability"]):
        axes = _axes(missing)
        svg = rs.render_radar_svg(_payload(missing))
        edges = rs.now_edges(axes)
        for e in edges:
            needle = f'data-adjacent="{"1" if e["adjacent"] else "0"}"'
            assert needle in svg
            if e["adjacent"]:
                assert f'stroke="{rs.COLOR_BLUE}"' in svg
            else:
                assert 'stroke-dasharray="5 5"' in svg
        centre = f"{rs._fmt(rs.CX)},{rs._fmt(rs.CY)}"
        now = svg.split('class="perf-radar-now"')
        if len(now) > 1:
            assert centre not in now[1].split(">")[0]


def test_fewer_than_three_measured_has_no_fill():
    svg = rs.render_radar_svg(_payload(["speed", "economy", "strength", "mobility", "power_to_weight"]))
    assert 'class="perf-radar-now"' not in svg  # no fill polygon
    assert "perf-radar-now-edge" in svg
    assert rs.measured_indices(_axes(["speed", "economy", "strength", "mobility", "power_to_weight"])) == [0, 6]


def test_no_centre_vertex_for_unmeasured():
    svg = rs.render_radar_svg(_payload(["mobility"]))
    assert f'cx="{rs._fmt(rs.CX)}" cy="{rs._fmt(rs.CY)}"' not in svg.replace("perf-radar-spoke", "")
    poly = [p for p in svg.split("<") if 'class="perf-radar-now"' in p]
    assert poly and f"{rs._fmt(rs.CX)},{rs._fmt(rs.CY)}" not in poly[0]


def test_legend_flags_include_not_measured():
    flags = rp.legend_flags(_axes(["mobility"]))
    assert flags["not_measured"] is True and flags["stale"] is True and flags["focus"] is True
    none = rp.legend_flags(_axes([]))
    # fixture still has stale endurance + focus economy
    assert none["not_measured"] is False


def test_action_copy_lives_in_payload():
    axes = rp.build_axes(
        {"endurance": {"score": 50.0}, "speed": {"score": None}},
        {},
        {},
    )
    by = {a["axis"]: a for a in axes}
    assert by["mobility"]["action_label"] == "Log a test"
    assert by["mobility"]["action_href"] == "#v2-mobility-log"
    assert by["durability"]["action_label"].startswith("Needs a 90-min")
    assert by["speed"]["action_label"] == "Not measured yet"
    assert by["speed"]["action_href"] is None
    assert by["endurance"]["action_label"] is None
