"""Radar centre-plot, legend flags, display_score, and why-table payload."""
from copy import deepcopy
from pathlib import Path
import json
import re

from backend.services import focus_ranking as fr
from backend.services import radar_payload as rp
from backend.services import radar_svg as rs
from backend.services.score_format import display_score

FIX = json.loads(Path("tests/fixtures/radar_payload__1853.json").read_text())
JS = Path("frontend/js/v2-performance.js").read_text()
RADAR_JS = Path("frontend/js/lib/perf-radar.js").read_text()


def test_display_score_half_rounds_up():
    assert display_score(52.5) == 53
    assert display_score(52.4) == 52
    assert display_score(None) is None
    assert display_score(0) == 0


def test_score_display_matches_fmt_score_after_1dp():
    axes = rp.build_axes(
        {"endurance": {"score": 52.48}, "speed": {"score": 52.48}},
        {},
        {},
    )
    by = {a["axis"]: a for a in axes}
    assert by["speed"]["score"] == 52.5
    assert by["speed"]["score_display"] == 53
    assert rp.fmt_score(by["speed"]["score"]) == "53"


def test_fmt_score_uses_display_score():
    assert rp.fmt_score(52.5) == "53"
    assert rp.fmt_score(None) in ("–", "—", "-")


def test_polygon_includes_center_for_never_measured():
    pts = rs._polygon(FIX["axes"], "score")
    assert len(pts) == len(FIX["axes"])
    for i, a in enumerate(FIX["axes"]):
        if a["never_measured"]:
            assert pts[i] == (rs.CX, rs.CY)
        else:
            assert pts[i] != (rs.CX, rs.CY)


def test_past_polygon_uses_score_when_present_else_center():
    pts = rs._polygon(FIX["axes"], "score_28d_ago")
    for i, a in enumerate(FIX["axes"]):
        if a.get("score_28d_ago") is None:
            assert pts[i] == (rs.CX, rs.CY)
        else:
            assert pts[i] != (rs.CX, rs.CY)


def test_legend_flags_follow_payload():
    flags = rp.legend_flags(FIX["axes"])
    assert flags == {"past": True, "stale": True, "focus": True}
    none = deepcopy(FIX["axes"])
    for a in none:
        a["score_28d_ago"] = None
        a["stale"] = False
        a["focus"] = False
    assert rp.legend_flags(none) == {"past": False, "stale": False, "focus": False}
    none[0]["score_28d_ago"] = 40.0
    assert rp.legend_flags(none)["past"] is False  # need at least two
    none[1]["score_28d_ago"] = 42.0
    assert rp.legend_flags(none)["past"] is True


def test_summary_mentions_grey_outline_only_when_past_is_drawn():
    with_past = rp.summary_sentence(FIX["axes"], past=True)
    without = rp.summary_sentence(FIX["axes"], past=False)
    assert "Grey outline is four weeks ago." in with_past
    assert "Grey outline" not in without
    assert "Dashed outline" not in with_past


def test_score_52_5_is_53_on_radar_why_and_focus():
    axes = [
        {"axis": "economy", "score": 40.0, "stale": False, "never_measured": False},
        {"axis": "speed", "score": 52.5, "stale": False, "never_measured": False},
        {"axis": "endurance", "score": 80.0, "stale": False, "never_measured": False},
    ]
    ranked = fr.rank_axes(axes, 42.2)
    assert ranked["focus"]["axis"] == "economy"
    assert ranked["focus"]["score_display"] == 40
    speed = next(w for w in ranked["why_not"] if w["axis"] == "speed")
    assert speed["score_display"] == 53
    assert speed["reason"] == "Smaller weighted gap"
    assert "Speed" not in speed["reason"]
    assert "53" not in speed["reason"]

    radar_axes = rp.build_axes(
        {"endurance": {"score": 80.0}, "speed": {"score": 52.5}},
        {"economy": {"score": 40.0}},
        {},
        focus_axis="economy",
    )
    by = {a["axis"]: a for a in radar_axes}
    assert by["speed"]["score_display"] == 53
    svg = rs.render_radar_svg({"axes": radar_axes, "summary": "", "not_yet_measured": []})
    speed_status = re.search(
        r'data-axis="speed"[^>]*>Speed</text>\s*<text class="perf-radar-status"[^>]*>([^<]+)</text>',
        svg,
    )
    assert speed_status is not None
    assert speed_status.group(1).startswith("53")


def test_why_not_reasons_have_no_label_score_prefix():
    out = fr.rank_axes(
        [
            {"axis": "economy", "score": 40, "stale": False, "never_measured": False},
            {"axis": "mobility", "score": None, "stale": False, "never_measured": True},
            {"axis": "durability", "score": 50, "stale": True, "never_measured": False},
        ],
        42.2,
    )
    by = {w["axis"]: w for w in out["why_not"]}
    assert by["mobility"]["reason"] == "Not measured · log a test"
    assert by["mobility"]["status"] == "never_measured"
    assert by["durability"]["reason"] == "Not ranked · anchor stale"
    assert by["durability"]["status"] == "stale"
    for w in out["why_not"]:
        assert not w["reason"].startswith(w["label"])


def test_frontend_uses_score_display_and_why_table():
    assert "Math.round(focus.score)" not in JS
    assert "Math.round(w.score)" not in JS
    assert "scoreText" in JS
    assert "rv-why-table" in JS
    assert '<th scope="col">' in JS
    assert "Stale · needs a test effort" not in RADAR_JS
    assert "payload.legend" in RADAR_JS
    assert "perf-radar-past" in RADAR_JS
