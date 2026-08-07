"""Coach projection uses Performance race-day estimate — never CTL-ratio invent."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.services.coach_facts import (
    _dream_block,
    _estimate_for_a_race,
    _focus_for_session,
)

def test_focus_for_session_maps_long_run_not_always_first():
    focus = [
        {"id": "weight_measurement", "rank": 1, "label": "Weigh-ins"},
        {"id": "long_run", "rank": 2, "label": "Long run"},
    ]
    rank, fid = _focus_for_session(focus, "Long run 18k", "long")
    assert fid == "long_run"
    assert rank == 2


def test_estimate_for_a_race_uses_helper_not_ctl_sqrt():
    mock_race = MagicMock()
    mock_race.id = "r1"
    mock_race.goal_time_seconds = 15300
    mock_race.race_date = date(2026, 11, 15)
    mock_race.distance_km = 42.2
    mock_race.priority = "A"

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
        mock_race
    )

    fake_est = {
        "unavailable": False,
        "est_sec": 9000,
        "est_label": "2:30:00",
        "band_sec": 300,
        "uncertainty_min": 5,
        "source": "performance_time_curve",
        "reason": None,
    }
    with patch(
        "backend.services.race_finish_estimate.estimate_race_finish",
        return_value=fake_est,
    ) as est_fn:
        out = _estimate_for_a_race("uid", date(2026, 7, 17), mock_db)

    est_fn.assert_called_once()
    assert out["est_label"] == "2:30:00"
    assert out["est_sec"] == 9000
    assert out["source"] == "performance_time_curve"
    assert out["goal_time_sec"] == 15300
    assert "6:00" not in (out.get("est_label") or "")


def test_estimate_unavailable_omits_trend_times():
    mock_race = MagicMock()
    mock_race.id = "r1"
    mock_race.goal_time_seconds = 15300
    mock_race.race_date = date(2026, 11, 15)
    mock_race.distance_km = 42.2

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
        mock_race
    )

    with patch(
        "backend.services.race_finish_estimate.estimate_race_finish",
        return_value={
            "unavailable": True,
            "est_sec": None,
            "est_label": None,
            "band_sec": None,
            "uncertainty_min": None,
            "source": "none",
            "reason": "no curves",
        },
    ):
        out = _estimate_for_a_race("uid", date(2026, 7, 17), mock_db)

    assert out["unavailable"] is True
    assert out["est_sec"] is None
    assert out["est_label"] is None


def test_dream_current_trend_uses_performance_source_only():
    projection = {
        "full_compliance_label": "4:15",
        "full_compliance_sec": 15300,
        "current_trend_label": "2:30:00",
        "current_trend_sec": 9000,
        "uncertainty_min": 5,
        "source": "performance_time_curve",
        "unavailable": False,
    }
    mock_db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value.order_by.return_value.first.return_value = None
    mock_q.filter.return_value.order_by.return_value.all.return_value = []
    mock_db.query.return_value = mock_q
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = False

    with patch("sqlalchemy.orm.Session", return_value=cm):
        dream = _dream_block("uid", date(2026, 7, 17), projection, {"gap_kg": 0})

    trend = next(s for s in dream["scenarios"] if s["id"] == "current_trend")
    assert trend["finish_label"] == "2:30:00"
    assert trend["method"] == "performance_time_curve"
    assert "ctl" not in (trend["method"] or "").lower()


def test_dream_skips_trend_when_unavailable():
    projection = {
        "full_compliance_label": "4:15",
        "full_compliance_sec": 15300,
        "current_trend_label": None,
        "unavailable": True,
        "source": "none",
    }
    mock_db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value.order_by.return_value.first.return_value = None
    mock_db.query.return_value = mock_q
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = False

    with patch("sqlalchemy.orm.Session", return_value=cm):
        dream = _dream_block("uid", date(2026, 7, 17), projection, {"gap_kg": 0})

    assert not any(s["id"] == "current_trend" for s in dream["scenarios"])


