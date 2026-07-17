"""Coach projection uses Performance race-day estimate — never CTL-ratio invent."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.services.coach_facts import (
    _dream_block,
    _estimate_for_a_race,
    _focus_for_session,
)
from backend.services.coach_narrative import compose_coach_narrative, parse_sections_from_text


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


def test_compose_uses_performance_estimate_not_six_hour_fiction():
    facts = {
        "load": {"state": "available", "acwr": 0.36, "unlock_date": "2026-07-17"},
        "weight": {"phase": "measurement", "logged_days": 7, "window_days": 14, "gap_kg": 6},
        "timeline": [
            {
                "date": "2026-07-17",
                "end_date": "2026-09-05",
                "phase": "ramp",
                "directive": "Ramp 5%/week",
            }
        ],
        "lever_ranking": {},
        "projection": {
            "goal_label": "4:15",
            "full_compliance_label": "4:15",
            "current_trend_label": "2:30:00",
            "current_trend_sec": 9000,
            "uncertainty_min": 5,
            "source": "performance_time_curve",
            "unavailable": False,
            "target_date": "2026-11-15",
            "distance_label": "marathon",
        },
        "focus_ranked": [
            {
                "id": "weight_measurement",
                "rank": 1,
                "label": "Weight measurement",
                "rationale": "Build weigh-in consistency",
                "tracking": {"current": 7, "target": 12, "unit": "weigh_ins_14d"},
            },
            {
                "id": "long_run",
                "rank": 2,
                "label": "Long run",
                "rationale": "One easy long run with fuel practice",
                "tracking": {},
            },
        ],
        "focus_noise": ["intervals", "plyo"],
        "dream": {
            "a_race": {
                "name": "Bangsaen42",
                "date": "2026-11-15",
                "goal_time_label": "4:15",
            },
            "scenarios": [
                {
                    "id": "weight_cut",
                    "cut_kg": 6.0,
                    "finish_label": "4:00",
                }
            ],
            "sell_line_facts": {},
        },
        "reflection": {
            "sessions_planned": 4,
            "sessions_completed": 4,
            "adherence_pct": 100,
            "benchmarks": [],
            "next_session": {
                "name": "Long run",
                "date": "2026-07-18",
                "why_focus": "Serves Focus #2: long_run",
            },
        },
        "goal": {"name": "Bangsaen42", "target_time_label": "4:15", "race_date": "2026-11-15"},
    }
    text = compose_coach_narrative(facts)
    secs = parse_sections_from_text(text)
    assert "2:30:00" in secs["dream"]
    assert "6:00" not in text
    assert "Focus #2" in secs["focus"]
    assert "Two things this week" in secs["focus"]
