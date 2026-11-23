"""Issue #1943 — Log list D dark week bar + tss_delta_prev."""
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.services.weekly_rollup import _attach_tss_delta_prev, weekly_rollups

REPO = Path(__file__).resolve().parents[1]
LOG_JS = (REPO / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")
CSS = (REPO / "frontend" / "css" / "revamp.css").read_text(encoding="utf-8")


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


def test_tss_delta_prev_first_week_null_adjacent_subtracts():
    weeks = [
        {"week_start": "2026-11-02", "tss_total": 100.0, "tss_delta_prev": None},
        {"week_start": "2026-11-09", "tss_total": 244.0, "tss_delta_prev": None},
        {"week_start": "2026-11-16", "tss_total": 477.0, "tss_delta_prev": None},
    ]
    out = _attach_tss_delta_prev(weeks)
    assert out[0]["tss_delta_prev"] is None
    assert out[1]["tss_delta_prev"] == 144.0
    assert out[2]["tss_delta_prev"] == 233.0


def test_weekly_rollups_sets_delta_on_empty_adjacent_weeks():
    inst = MagicMock()
    inst.query.return_value.filter.return_value = inst.query.return_value
    inst.query.return_value.order_by.return_value = inst.query.return_value
    inst.query.return_value.all.return_value = []
    inst.query.return_value.first.return_value = None
    inst.get.return_value = None
    with (
        patch("backend.services.revamp_load_plan.chronic_weekly_tss", return_value=300.0),
        patch("backend.services.revamp_plan_settings.resolve_a_race", return_value=None),
        patch("backend.services.training_load.estimate_historical_pace_and_tss", return_value={}),
        patch("backend.services.weekly_rollup._estimate_planned_tss_remaining", return_value=0.0),
        patch("backend.services.race_day_tss.race_week_payload", return_value=[]),
    ):
        rows = weekly_rollups(
            "00000000-0000-0000-0000-000000000001",
            date(2026, 11, 2),
            date(2026, 11, 16),
            session=inst,
            today=date(2026, 11, 16),
        )
    assert len(rows) == 3
    assert rows[0]["tss_delta_prev"] is None
    assert rows[1]["tss_delta_prev"] == 0.0
    assert rows[2]["tss_delta_prev"] == 0.0
    assert all(r["target_tss"] == 300.0 for r in rows)


def test_week_bar_markup_covers_under_on_over_empty_no_target():
    bar = _fn(LOG_JS, "weekBarHtml")
    paint = _fn(LOG_JS, "paintList")
    assert "rv-log-wkbar" in bar
    assert "#e4ff52" in CSS
    assert "#0b1530" in CSS
    assert "rv-log-wkbar--empty" in bar
    assert "rv-log-wkbar-big--over" in bar
    assert "rv-log-wkbar-fill--over" in bar
    assert "hasTarget" in bar
    assert "emptyCurrent" in bar
    assert "max(tnum / 0.87, tss)" in bar
    assert "Open in Plan" in bar
    assert "/v2/training/plan" in bar
    assert "tss_delta_prev" in bar
    assert "vs prev" in bar
    assert "rv-log-wkbar-delta--down" in bar
    assert "race_planned_tss" in bar
    assert "race " in bar
    assert "headerPlannedTss" in bar
    assert "planned " in bar
    assert "This week" in bar
    assert "Last week" in bar
    assert "weekBarHtml" in paint
    assert "plannedEmptyCard" not in paint
    assert "rv-week-target" not in paint
    assert "rv-week-body" in paint


def test_week_bar_css_tokens_and_phone_stack():
    assert "background: #0b1530" in CSS
    assert "background: #33405e" in CSS
    assert "color: #ffb27a" in CSS
    assert "width: 220px" in CSS
    assert "height: 8px" in CSS
    assert "rgba(255, 255, 255, 0.16)" in CSS
    assert "@media (max-width: 600px)" in CSS
    assert "rv-log-wkbar-meter" in CSS
    assert "rv-log-wkbar-delta--down" in CSS
    assert "width: 100%" in CSS
    assert "border: 1px solid #e6ebf5" in CSS
