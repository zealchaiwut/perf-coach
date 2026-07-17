"""Phase 4 Reflection facts smoke (next-session CTA + benchmarks)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from backend.services.coach_facts import _reflection_block


def test_reflection_uses_recent_wrap_and_focus_benchmarks():
    focus = [
        {
            "id": "weight_measurement",
            "label": "Weight measurement",
            "rationale": "Log weigh-ins",
            "tracking": {"current": 4, "target": 12, "unit": "weigh_ins_14d"},
        }
    ]
    wrap = {
        "sessions_planned": 5,
        "sessions_completed": 3,
        "adherence": 0.6,
        "highlights_md": "Solid long run",
    }
    with patch(
        "backend.services.daily_brief._assemble_recent_wrap",
        return_value=wrap,
    ), patch("sqlalchemy.orm.Session") as sess:
        # next_session query: empty
        cm = sess.return_value
        cm.__enter__.return_value.execute.return_value.fetchone.return_value = None
        cm.__exit__.return_value = False
        ref = _reflection_block("uid", date(2026, 7, 17), focus)

    assert ref["sessions_planned"] == 5
    assert ref["sessions_completed"] == 3
    assert ref["adherence_pct"] == 60
    assert ref["benchmarks"]
    assert ref["benchmarks"][0]["id"] == "weight_measurement"
    assert ref["benchmarks"][0]["met"] is False
    assert "4/12" in (ref["benchmarks"][0]["detail"] or "")


def test_reflection_next_session_cites_matching_focus_rank():
    focus = [
        {"id": "weight_measurement", "rank": 1, "label": "Weigh-ins", "tracking": None},
        {"id": "long_run", "rank": 2, "label": "Long run", "tracking": None},
    ]
    wrap = {"sessions_planned": 2, "sessions_completed": 2, "adherence": 1.0}
    row = ("ps-1", date(2026, 7, 18), "Long run 18k", "long")
    with patch(
        "backend.services.daily_brief._assemble_recent_wrap",
        return_value=wrap,
    ), patch("sqlalchemy.orm.Session") as sess:
        cm = sess.return_value
        cm.__enter__.return_value.execute.return_value.fetchone.return_value = row
        cm.__exit__.return_value = False
        ref = _reflection_block("uid", date(2026, 7, 17), focus)

    assert ref["next_session"] is not None
    assert "Focus #2" in (ref["next_session"]["why_focus"] or "")
    assert "long_run" in (ref["next_session"]["why_focus"] or "")


def test_reflection_next_session_cites_focus():
    focus = [{"id": "hold_load", "rank": 1, "label": "Hold load", "tracking": None}]
    wrap = {"sessions_planned": 2, "sessions_completed": 2, "adherence": 1.0}
    row = ("ps-1", date(2026, 7, 18), "Tempo 6k", "tempo")
    with patch(
        "backend.services.daily_brief._assemble_recent_wrap",
        return_value=wrap,
    ), patch("sqlalchemy.orm.Session") as sess:
        cm = sess.return_value
        cm.__enter__.return_value.execute.return_value.fetchone.return_value = row
        cm.__exit__.return_value = False
        ref = _reflection_block("uid", date(2026, 7, 17), focus)

    assert ref["next_session"] is not None
    assert ref["next_session"]["name"] == "Tempo 6k"
    assert "hold_load" in (ref["next_session"]["why_focus"] or "")
