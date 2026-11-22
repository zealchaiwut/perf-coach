"""P5-2 Home lower columns: week, next race, focus teaser, recent, coach."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.services import revamp_home as rh

TODAY = date(2026, 11, 12)
UID = uuid.uuid4()


def test_this_week_uses_week_board_items():
    board = {
        "days": [
            {
                "date": TODAY.isoformat(),
                "label": "Thu",
                "items": [{"name": "Primer", "kind": "run", "status": "planned", "plan_source": "coach", "estimated_tss": 28.0}],
                "rest_placeholder": False,
            }
        ]
    }
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    with patch.object(rh, "revamp_week_load", return_value={"target_tss": 150, "logged_tss": 80, "planned_tss": 38, "phase": "taper"}), \
            patch.object(rh, "weekly_rollup", return_value={"partial": True}):
        out = rh.build_this_week(session, UID, TODAY, board)
    row = out["days"][0]
    assert row["is_today"] is True
    assert row["items"][0]["name"] == "Primer"
    assert out["load_bar"]["logged_tss"] == 80


def test_next_race_numbers_from_build_hero_reader():
    hero = {
        "race": {"name": "Bangsaen", "race_date": "2026-11-15", "days_to_race": 3},
        "goal": {"time_sec": 16200},
        "estimate": {"available": True, "est_sec": 14893, "range_low_sec": 14353, "range_high_sec": 15433},
    }
    session = MagicMock()
    with patch("backend.services.race_hero.build_hero", return_value=hero):
        card = rh.build_next_race_card(session, UID, TODAY)
    assert card["available"] is True
    assert card["goal_time_label"] == "4:30:00"
    assert card["estimate_time_label"] == "4:08:13"
    assert "14353" not in card["range_label"]  # short range, not raw seconds


def test_focus_teaser_uses_rank_axes_not_local_math():
    session = MagicMock()
    fake_axes = [{"axis": "economy", "score": 44, "stale": False}]
    with patch("backend.services.radar_payload.build_radar", return_value={"axes": fake_axes}) as br, \
            patch("backend.services.focus_ranking.rank_axes", return_value={"focus": {"axis": "economy", "score": 44}, "advice": {"economy": "Drills."}}) as rk, \
            patch.object(rh, "next_a_race", return_value=SimpleNamespace(distance_km=42.195)):
        out = rh.build_focus_teaser(session, UID, TODAY)
    assert br.called and rk.called
    assert out["axis"] == "economy"
    assert out["score"] == 44


def test_recent_sessions_use_session_tss_reader():
    w = SimpleNamespace(
        id=uuid.uuid4(),
        name="Easy Run",
        workout_type="run",
        run_subtype="",
        workout_date=TODAY,
        distance_km=5.4,
        duration_seconds=2400,
        created_at=None,
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [w]
    session.query.return_value.filter.return_value.first.return_value = None
    with patch("backend.services.plan_match_payload.plan_match_map", return_value={str(w.id): {"source": "coach"}}), \
            patch("backend.services.session_tss.session_tss", return_value={"tss": 38.0}) as st:
        rows = rh.build_recent_sessions(session, UID, TODAY)
    assert st.called
    assert rows[0]["tss"] == 38.0
    assert rows[0]["who"] == "COACH"


def test_home_payload_wires_p52_sections():
    session = MagicMock()
    session.get.return_value = SimpleNamespace(name="Zeal")
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    session.query.return_value.filter.return_value.filter.return_value.all.return_value = []
    with patch.object(rh, "week_board", return_value={"days": []}), \
            patch.object(rh, "build_today_hero", return_value={"state": "empty"}), \
            patch.object(rh, "next_a_race", return_value=None), \
            patch.object(rh, "build_providers", return_value={"strava": {"connected": False}}), \
            patch.object(rh, "newest_due", return_value=None), \
            patch.object(rh, "checkin_state", return_value={"state": "done"}), \
            patch.object(rh, "week_planned_over_ceiling", return_value=None), \
            patch.object(rh, "build_this_week", return_value={"days": []}) as wk, \
            patch.object(rh, "build_next_race_card", return_value={"available": False}) as nr, \
            patch.object(rh, "build_focus_teaser", return_value={}) as fc, \
            patch.object(rh, "build_recent_sessions", return_value=[]) as rs, \
            patch.object(rh, "build_coach_card", return_value={}) as cc:
        out = rh.home_payload(session, UID, today=TODAY)
    assert wk.called and nr.called and fc.called and rs.called and cc.called
    assert "this_week" in out and "recent_sessions" in out