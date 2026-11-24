"""Performance tab v3 — Status widget, chain multiply, chart y-fit, readiness 5."""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from backend.services import projection_view as pv
from backend.services.axis_breakdown import ALL_AXES
from backend.services.radar_payload import AXIS_LABELS, build_axes
from backend.services.score_format import display_score
from backend.services.riegel import riegel_project

JS = Path("frontend/js/v2-performance.js").read_text(encoding="utf-8")
HTML = Path("frontend/pages/v2-performance.html").read_text(encoding="utf-8")
CSS = Path("frontend/css/revamp.css").read_text(encoding="utf-8")

TODAY = date(2026, 11, 24)
GOAL = {"time_sec": 16200, "pace_seconds_per_km": 384, "state": "provisional", "editable": True}


def _est(blend_pace, distance, fitness, correction, **extra):
    final = int(round(float(blend_pace) * float(distance) * float(fitness) * float(correction))
    )
    out = {
        "unavailable": False,
        "est_sec": final,
        "band_sec": 300,
        "blend_pace": blend_pace,
        "base_endurance_pace": blend_pace + 8,
        "base_speed_pace": blend_pace - 12,
        "blend_weight": 0.38,
        "fitness_factor": fitness,
        "correction_factor": correction,
        "end_score": 56.2,
        "spd_score": 53.4,
        "final_seconds": final,
        "form_factor": 1.05,
        "correction": correction,
        "projected_ctl": 52.0,
        "ctl_now": 38.0,
    }
    out.update(extra)
    return out


def test_html_has_status_and_races_layout():
    assert 'id="v2-perf-status"' in HTML
    assert 'id="v2-perf-states"' in HTML
    assert 'id="v2-perf-races-row"' in HTML
    assert 'id="v2-perf-axis-details"' in HTML
    assert "v2-perf-score-cards" in HTML
    assert "rv-perf-status-row" in CSS
    assert "2.1fr" in CSS
    assert "4fr" in CSS


def test_js_has_no_toilet_and_selects_axis():
    assert "data-toilet" not in JS
    assert "selectAxis" in JS
    assert "rv-axis-pills" in JS
    assert 'role="tablist"' in JS
    assert "perf-coach:status-axis" in JS


def test_chain_headers_present():
    assert 'hdr("Base")' in JS or ">Base<" in JS or 'hdr("Base")' in JS
    assert "Race-day fitness" in JS
    assert "Model correction" in JS
    assert "rv-proj-stage-hdr" in JS
    assert "rv-proj-stage-hdr" in CSS
    assert "height: 14px" in CSS
    assert "justify-content: flex-start" in CSS
    assert "white-space: nowrap" in CSS


def test_chain_product_invariant_on_three_fixture_races():
    fixtures = [
        (356.0, 42.195, 0.977, 1.098, "Osaka"),
        (310.0, 21.0975, 0.990, 1.040, "Bangsaen21"),
        (400.0, 10.0, 1.000, 0.960, "KFC 10K"),
    ]
    for pace, dist, fit, corr, name in fixtures:
        est = _est(pace, dist, fit, corr)
        chain = pv.build_chain(est, None, {"correction": corr, "n": 3}, dist, GOAL, name)
        payload = {
            "chain": chain,
            "race": {"distance_km": dist, "name": name},
            "chart": {"available": False},
        }
        assert chain["final"]["est_sec"] == est["est_sec"]
        assert chain["fitness"]["factor"] == fit
        assert abs(
            pace * dist * fit * corr - chain["final"]["est_sec"]
        ) <= 1
        assert pv.check_invariants(payload, hero_est_sec=est["est_sec"]) == []


def test_chain_uses_estimate_intermediates_not_foreign_basis():
    est = _est(356, 42.195, 0.977, 1.098)
    basis = {
        "endurance_score": 41.0,
        "endurance_pace_seconds_per_km": 387,
        "speed_score": 45.0,
        "speed_pace_seconds_per_km": 363,
        "speed_weight": 0.5,
        "blended_pace_seconds_per_km": 999,
    }
    chain = pv.build_chain(est, basis, {"correction": 1.2, "n": 1}, 42.195, GOAL, "Osaka")
    assert chain["blended"]["pace_seconds_per_km"] == 356
    assert chain["correction"]["factor"] == 1.098


def test_chart_y_range_ignores_outlier_result():
    race = SimpleNamespace(name="Osaka", race_date=date(2027, 2, 28), distance_km=42.195)
    est = {"unavailable": False, "est_sec": 16133, "band_sec": 790}
    ch = pv.build_chart(
        start=date(2026, 9, 1),
        today=TODAY,
        race=race,
        est=est,
        goal_sec=16200,
        history=[(date(2026, 9, 1), 16500), (TODAY, 16133)],
        recalibrations=[{
            "date": date(2026, 11, 15), "race_id": "r1", "name": "Bangsaen42", "role": "a_race",
            "converted_sec": 19772, "actual_sec": 19772, "distance_km": 42.2,
            "distance_label": "42.2K", "date_label": "15 Nov",
        }],
        ticks=[],
        pending=[],
    )
    assert ch["y_max_sec"] < 19000
    bang = ch["recalibrations"][0]
    assert bang["clipped"] is True
    assert bang["clip_side"] == "slow"
    assert bang["plot_sec"] == ch["y_max_sec"]


def test_tag_nudge_is_one_lane():
    marks = [
        {"x": 0.50, "name": "A"},
        {"x": 0.52, "name": "B"},
        {"x": 0.90, "name": "C"},
    ]
    pv._assign_tag_lanes(marks)
    assert all(m["tag_lane"] == 0 for m in marks)
    assert marks[0]["tag_dx"] != 0 or marks[1]["tag_dx"] != 0


def test_riegel_project_used_for_converted_actual():
    converted = riegel_project(19772, 42.195, 42.195)
    assert converted == 19772
    half = riegel_project(5400, 10.0, 42.195)
    assert half is not None and half > 5400


def test_radar_and_breakdown_share_display_score():
    overall = {
        "endurance": {"score": 55.5, "delta_28d": 15, "stale": False},
        "speed": {"score": 53.4, "delta_28d": 2, "stale": False},
    }
    axis_blocks = {
        "economy": {"score": 42.2, "delta_28d": 0, "stale": False},
        "strength": {"score": 25.0, "delta_28d": None, "stale": False},
        "mobility": {"score": None, "never_measured": True, "stale": False},
        "power_to_weight": {"score": 74.4, "delta_28d": None, "stale": True},
        "durability": {"score": None, "never_measured": True, "stale": False},
    }
    past = {k: None for k in AXIS_LABELS}
    axes = build_axes(overall, axis_blocks, past, "economy")
    by = {a["axis"]: a for a in axes}
    for name in ALL_AXES:
        a = by[name]
        raw = a["score"]
        assert a["score_display"] == display_score(raw)


def test_score_history_axis_accepted():
    src = Path("backend/main.py").read_text(encoding="utf-8")
    assert "axis: Optional[str]" in src
    assert "score_history_for_axis" in src
    assert "build_axis_breakdown" in src


def test_readiness_five_items_in_js():
    assert "five things" in JS
    assert "of " in JS and " done" in JS
    assert 'id="v2-perf-readiness"' in HTML
    assert "race_name" in Path("backend/services/a_race_readiness_checklist.py").read_text(encoding="utf-8")


def test_estimate_cache_key_bumped_for_intermediates():
    src = Path("backend/services/race_finish_estimate.py").read_text(encoding="utf-8")
    assert "derived:race_estimate:v2:" in src
    assert 'DERIVED_PROJECTION = "derived:projection:v4"' in Path(
        "backend/services/derived_cache.py"
    ).read_text(encoding="utf-8")
