"""Phase 3 Dream block: A-race preference + weight-cut heuristic."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.services.coach_facts import _dream_block


def _empty_race_session():
    """Session context manager whose Race queries return nothing."""
    mock_db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value.order_by.return_value.first.return_value = None
    mock_q.filter.return_value.order_by.return_value.all.return_value = []
    mock_db.query.return_value = mock_q
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = False
    return cm


def test_dream_weight_cut_scenario_when_gap_material():
    projection = {
        "full_compliance_label": "1:50",
        "full_compliance_sec": 6600,
        "current_trend_label": "1:55",
        "current_trend_sec": 6900,
        "uncertainty_min": 4,
    }
    weight = {"gap_kg": 6.0}
    with patch("sqlalchemy.orm.Session", return_value=_empty_race_session()):
        dream = _dream_block("uid", date(2026, 7, 17), projection, weight)
    ids = [s["id"] for s in dream["scenarios"]]
    assert "plan_compliance" in ids
    assert "weight_cut" in ids
    cut = next(s for s in dream["scenarios"] if s["id"] == "weight_cut")
    assert cut["cut_kg"] == 6.0
    assert "0.8pct" in (cut.get("method") or "")
    assert cut["finish_label"] is not None


def test_dream_skips_weight_cut_when_gap_small():
    projection = {"full_compliance_sec": 6600, "full_compliance_label": "1:50"}
    weight = {"gap_kg": 1.0}
    with patch("sqlalchemy.orm.Session", return_value=_empty_race_session()):
        dream = _dream_block("uid", date(2026, 7, 17), projection, weight)
    assert not any(s["id"] == "weight_cut" for s in dream["scenarios"])


def test_dream_prefers_a_race_and_checkpoints():
    mock_race = MagicMock()
    mock_race.id = "race-1"
    mock_race.name = "Bangkok HM"
    mock_race.race_date = date(2026, 12, 14)
    mock_race.distance_km = 21.1
    mock_race.goal_time_seconds = 6300
    mock_race.priority = "A"

    mock_cp = MagicMock()
    mock_cp.label = "Mid-Sep"
    mock_cp.target_date = date(2026, 9, 15)
    mock_cp.target_duration_seconds = 6900
    mock_cp.met = False
    mock_cp.met_override = False

    mock_db = MagicMock()

    def query_side(model):
        name = getattr(model, "__name__", str(model))
        q = MagicMock()
        if "Checkpoint" in name:
            q.filter.return_value.order_by.return_value.all.return_value = [mock_cp]
        else:
            q.filter.return_value.order_by.return_value.first.return_value = mock_race
        return q

    mock_db.query.side_effect = query_side
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = False

    with patch("sqlalchemy.orm.Session", return_value=cm):
        dream = _dream_block(
            "uid",
            date(2026, 7, 17),
            {"full_compliance_label": "1:45"},
            {"gap_kg": 0},
        )

    assert dream["a_race"] is not None
    assert dream["a_race"]["name"] == "Bangkok HM"
    assert dream["a_race"]["goal_time_label"] == "1:45"
    assert len(dream["checkpoints"]) == 1
    assert dream["sell_line_facts"].get("next_checkpoint_label") == "Mid-Sep"
    assert dream["sell_line_facts"].get("next_checkpoint_target") == "1:55"
