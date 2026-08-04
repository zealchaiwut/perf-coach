"""Hermes coach block exposes Focus #1 nudge fields."""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_brief.py"


@pytest.fixture(scope="module")
def m():
    spec = importlib.util.spec_from_file_location("export_brief_nudge", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_assemble_coach_includes_nudge_fields(m):
    mock_goal = MagicMock()
    mock_goal.user_id = "user-1"
    mock_goal.race_distance = "half"
    mock_goal.target_time = 6300
    mock_goal.race_date = date(2026, 12, 14)

    fake_plan_state = {
        "levers": {
            "load": {"state": "locked", "unlock_date": date(2026, 7, 31)},
            "weight": {"logged_days": 4, "total_days": 14},
        },
        "timeline": [],
        "constraints": [],
        "lever_ranking": {},
    }
    fake_projection = {
        "full_compliance_time_seconds": 6300,
        "target_date": date(2026, 12, 14),
        "current_trend_time_seconds": 6720,
        "uncertainty_minutes": 3,
        "distance_label": "HM",
    }
    nudge = {
        "focus_id": "weight_measurement",
        "focus_label": "Weight measurement consistency",
        "next_action": "Easy 8k on 2026-07-18",
        "why": "Serves Focus #1: weight_measurement",
    }

    with patch.object(m, "_load_goal_for_user", return_value=mock_goal), \
         patch.object(m, "_build_plan_state_for_user", return_value=(fake_plan_state, fake_projection)), \
         patch.object(m, "_coach_nudge_for_user", return_value=nudge):
        result = m._assemble_coach("user-1", date(2026, 7, 17))

    assert result is not None
    assert result["focus_id"] == "weight_measurement"
    assert result["focus_label"] == "Weight measurement consistency"
    assert "Easy 8k" in (result["next_action"] or "")
    assert result["directive"]
    assert isinstance(result["levers"], list)
