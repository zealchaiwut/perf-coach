"""Hermes coach block exposes Focus #1 nudge fields.

Note (#1663): After de8019f1 consolidated _build_brief into backend.services.daily_brief,
_assemble_coach now gets all data from get_coach_payload_for_user (weekly_coach_message).
Patching _load_goal_for_user / _build_plan_state_for_user / _coach_nudge_for_user on the
export_brief module no longer intercepts anything. Tests are repointed to mock
get_coach_payload_for_user with a payload that includes a nudge block.
"""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import date
from unittest.mock import patch

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_brief.py"

_UID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="module")
def m():
    spec = importlib.util.spec_from_file_location("export_brief_nudge", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_assemble_coach_includes_nudge_fields(m):
    """_assemble_coach propagates nudge fields (focus_id, focus_label, next_action, why)."""
    fake_payload = {
        "as_of": "2026-07-17",
        "source": "weekly_coach",
        "sections": {
            "now": "Hold TSS steady.",
            "dream": "plan → ~1:45 by mid-Dec · now ~1:52",
        },
        "nudge": {
            "focus_id": "weight_measurement",
            "focus_label": "Weight measurement consistency",
            "next_action": "Easy 8k on 2026-07-18",
            "why": "Serves Focus #1: weight_measurement",
        },
        "text": "Hold TSS steady.",
        "chosen_preset": None,
    }

    with patch(
        "backend.services.weekly_coach_message.get_coach_payload_for_user",
        return_value=fake_payload,
    ):
        result = m._assemble_coach(_UID, date(2026, 7, 17))

    assert result is not None
    assert result["focus_id"] == "weight_measurement"
    assert result["focus_label"] == "Weight measurement consistency"
    assert "Easy 8k" in (result["next_action"] or "")
    assert result["directive"]
    assert isinstance(result["levers"], list)
