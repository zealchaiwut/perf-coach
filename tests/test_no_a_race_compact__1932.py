"""Issue #1932 — no A-race: empty road section, compact load card."""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.services import revamp_load_plan as rlp
from backend.services import revamp_week as rw

UID = uuid.uuid4()
TODAY = date(2026, 11, 23)
WS = date(2026, 11, 17)
ROOT = Path(__file__).resolve().parents[1]
PLAN_JS = (ROOT / "frontend" / "js" / "v2-training-plan.js").read_text(encoding="utf-8")


def test_no_a_race_road_is_empty_generic_without_rollups():
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    q.first.return_value = None
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = []
    with (
        patch.object(rw, "plan_context", return_value=None),
        patch.object(rw, "generic_week_load", return_value={"mode": "generic", "logged_tss": 10, "planned_tss": 20, "target_tss": 100}),
        patch("backend.services.weekly_rollup.weekly_rollups") as rolls,
        patch.object(rlp, "generic_road_chart") as chart,
    ):
        out = rw.build_revamp_week(session, UID, week_start=WS, today=TODAY, sections=["road"])
    rolls.assert_not_called()
    chart.assert_not_called()
    assert out["road"]["mode"] == "generic"
    assert out["road"]["columns"] == []


def test_a_race_still_builds_block_chart():
    session = MagicMock()
    ctx = {"chronic_baseline": 200.0, "race": object(), "block_start": WS, "settings": {}}
    road = {"race_name": "A", "columns": [{"week_start": WS.isoformat()}]}
    with (
        patch.object(rw, "plan_context", return_value=ctx),
        patch.object(rw, "road_to_chart", return_value=road) as rtc,
        patch.object(rw, "empty_generic_road") as empty,
    ):
        out = rw.build_revamp_week(session, UID, week_start=WS, today=TODAY, sections=["road"])
    rtc.assert_called_once()
    empty.assert_not_called()
    assert out["road"] == road


def test_generic_road_chart_keeps_span_weeks():
    import inspect
    sig = inspect.signature(rlp.generic_road_chart)
    assert "span_weeks" in sig.parameters
    assert sig.parameters["span_weeks"].default == 14


def test_frontend_compact_card_and_add_race_link():
    assert "function renderCompactNoRace" in PLAN_JS
    assert "TSS · vs your 28-day average" in PLAN_JS
    assert 'href="/v2/settings/plan"' in PLAN_JS
    assert "Add an A race" in PLAN_JS
    assert "mode === 'generic'" in PLAN_JS
