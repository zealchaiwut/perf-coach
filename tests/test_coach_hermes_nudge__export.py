"""Hermes coach block exposes Focus #1 nudge fields.

Updated for issue #1509: _assemble_coach now lives in
backend.services.daily_brief and uses get_coach_payload_for_user.  The nudge
fields (focus_id, focus_label, next_action, why) are sourced from the nudge
sub-dict of the coach payload rather than from a separate _coach_nudge_for_user
helper (which no longer exists).
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid as _uuid_mod
from datetime import date
from unittest.mock import patch

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_brief.py"

_FAKE_UID = _uuid_mod.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="module")
def m():
    spec = importlib.util.spec_from_file_location("export_brief_nudge", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_assemble_coach_includes_nudge_fields(m):
    """_assemble_coach exposes nudge fields from the coach payload."""
    fake_payload = {
        "as_of": "2026-07-17",
        "source": "deterministic",
        "sections": {
            "now": "Hold TSS at 315/week until ACWR converges.",
            "dream": "plan → ~1:45 by mid-Dec · now ~1:52",
        },
        "text": "Hold TSS at 315/week until ACWR converges.",
        "nudge": {
            "focus_id": "weight_measurement",
            "focus_label": "Weight measurement consistency",
            "next_action": "Easy 8k on 2026-07-18",
            "why": "Serves Focus #1: weight_measurement",
        },
        "chosen_preset": None,
    }

    with patch("backend.services.weekly_coach_message.get_coach_payload_for_user",
               return_value=fake_payload):
        result = m._assemble_coach(_FAKE_UID, date(2026, 7, 17))

    assert result is not None
    assert result["focus_id"] == "weight_measurement"
    assert result["focus_label"] == "Weight measurement consistency"
    assert "Easy 8k" in (result["next_action"] or "")
    assert result["directive"]
    assert isinstance(result["levers"], list)
