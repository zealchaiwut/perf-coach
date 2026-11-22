"""P5-1 Home: today hero, race plan panel, alert strip."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.services import revamp_home as rh

TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
UID = uuid.uuid4()


def _providers(last_at: str | None = None, *, connected=True, error=None):
    base = {"connected": connected, "last_success_at": last_at, "last_error": error}
    return {"strava": dict(base), "stryd": {"connected": False}}


# ── Hero states (fixtures) ───────────────────────────────────────────────────


def test_hero_rest_from_board_fixture():
    board = {
        "days": [
            {
                "date": TODAY.isoformat(),
                "rest_placeholder": True,
                "items": [],
            }
        ]
    }
    session = MagicMock()
    out = rh.build_today_hero(session, UID, TODAY, board=board)
    assert out["state"] == "rest"
    assert out["session"] is None


def test_hero_empty_from_board_fixture():
    board = {
        "days": [
            {
                "date": TODAY.isoformat(),
                "rest_placeholder": False,
                "items": [],
            }
        ]
    }
    out = rh.build_today_hero(MagicMock(), UID, TODAY, board=board)
    assert out["state"] == "empty"


def test_hero_planned_support_mark_done():
    ps_id = str(uuid.uuid4())
    board = {
        "days": [
            {
                "date": TODAY.isoformat(),
                "items": [
                    {
                        "id": ps_id,
                        "name": "Mobility",
                        "status": "planned",
                        "plan_source": "support",
                        "kind": "mobility",
                        "notes": None,
                    }
                ],
            }
        ]
    }
    row = SimpleNamespace(
        id=uuid.UUID(ps_id),
        user_id=UID,
        session_type="mobility",
        structure={"duration_minutes": 30, "effort": 3},
    )
    session = MagicMock()
    session.get.return_value = row
    with patch.object(rh, "planned_tss_estimate", return_value=14.0):
        out = rh.build_today_hero(session, UID, TODAY, board=board)
    assert out["state"] == "planned"
    assert out["session"]["mark_done_allowed"] is True


def test_hero_done_and_run_no_mark_done():
    ps_id = str(uuid.uuid4())
    board = {
        "days": [
            {
                "date": TODAY.isoformat(),
                "items": [
                    {
                        "id": ps_id,
                        "name": "Primer",
                        "status": "done",
                        "plan_source": "coach",
                        "kind": "run",
                    }
                ],
            }
        ]
    }
    row = SimpleNamespace(id=uuid.UUID(ps_id), user_id=UID, session_type="run", structure={})
    session = MagicMock()
    session.get.return_value = row
    with patch.object(rh, "planned_tss_estimate", return_value=28.0):
        out = rh.build_today_hero(session, UID, TODAY, board=board)
    assert out["state"] == "done"
    assert out["session"]["mark_done_allowed"] is False
    assert "Strava" in (out["session"]["run_auto_complete_note"] or "")


def test_race_plan_pace_cap():
    race = SimpleNamespace(
        id=uuid.uuid4(),
        name="Bangsaen",
        race_date=TODAY + timedelta(days=3),
        distance_km=42.195,
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    with patch.object(rh, "estimate_race_finish", return_value={"est_sec": 14893}):
        panel = rh.race_plan_panel(session, UID, race, TODAY)
    assert panel["target_pace_seconds_per_km"] == round(14893 / 42.195)
    assert panel["first_10k_cap_seconds_per_km"] == panel["target_pace_seconds_per_km"] + 10
    assert panel["fuel_timing"] == rh.FUEL_DEFAULT


def test_race_week_flag_in_payload():
    race = SimpleNamespace(
        id=uuid.uuid4(),
        name="Race",
        race_date=TODAY + timedelta(days=5),
        distance_km=42.195,
        priority="A",
        status="planned",
    )
    session = MagicMock()
    session.get.return_value = SimpleNamespace(name="Zeal")
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    with patch.object(rh, "week_board", return_value={"days": [{"date": TODAY.isoformat(), "items": []}]}), \
            patch.object(rh, "next_a_race", return_value=race), \
            patch.object(rh, "build_providers", return_value=_providers(NOW.isoformat())), \
            patch.object(rh, "chronic_weekly_tss", return_value=100.0), \
            patch.object(rh, "newest_due", return_value=None), \
            patch.object(rh, "checkin_state", return_value={"state": "done"}), \
            patch.object(rh, "estimate_race_finish", return_value={"est_sec": 15000}), \
            patch.object(rh, "estimate_historical_pace_and_tss", return_value={}), \
            patch.object(rh, "estimate_planned_session_metrics", return_value={"estimated_tss": 0}), \
            patch.object(rh, "build_this_week", return_value={"days": []}), \
            patch.object(rh, "build_next_race_card", return_value={"available": False}), \
            patch.object(rh, "build_focus_teaser", return_value={}), \
            patch.object(rh, "build_recent_sessions", return_value=[]), \
            patch.object(rh, "build_coach_card", return_value={}), \
            patch.object(rh, "fetch_coach_block", return_value={"checkin": {}}):
        session.query.return_value.filter.return_value.filter.return_value.all.return_value = []
        out = rh.home_payload(session, UID, today=TODAY)
    assert out["show_race_plan"] is True
    assert out["race_plan"]["race_name"] == "Race"


# ── Alert boundaries ───────────────────────────────────────────────────────────


def test_sync_alert_fires_over_48h():
    old = (NOW - timedelta(hours=49)).isoformat()
    alert = rh.sync_alert(_providers(old), now=NOW)
    assert alert and alert["rule_id"] == "sync_stale"


def test_sync_alert_hidden_at_exactly_48h():
    edge = (NOW - timedelta(hours=48)).isoformat()
    assert rh.sync_alert_boundary(_providers(edge), now=NOW) is None


def test_sync_alert_on_error():
    p = _providers(NOW.isoformat(), error="boom")
    alert = rh.sync_alert(p, now=NOW)
    assert alert and alert["rule_id"] == "sync_error"


def test_ceiling_alert_only_when_over():
    assert rh.build_alerts(
        provider_rows=_providers(NOW.isoformat()),
        review_due=None,
        checkin={"state": "done"},
        ceiling_hit=None,
        now=NOW,
    ) == []


def test_checkin_and_review_alerts():
    due = SimpleNamespace(id=uuid.uuid4(), raw_text="review: Did the long run happen?")
    alerts = rh.build_alerts(
        provider_rows=_providers(NOW.isoformat()),
        review_due=due,
        checkin={"state": "due", "link": "/coach"},
        ceiling_hit={"rule_id": "week_planned_ceiling", "message": "too high", "href": "/v2/training/plan"},
        now=NOW,
    )
    rules = {a["rule_id"] for a in alerts}
    assert rules == {"weekly_checkin", "review_due", "week_planned_ceiling"}


def test_format_pace():
    assert rh.format_pace_seconds_per_km(353) == "5:53 /km"