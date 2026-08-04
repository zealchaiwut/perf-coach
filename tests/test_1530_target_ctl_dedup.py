"""Tests for issue #1530 — _TARGET_CTL must not be duplicated.

weekly_coach_message must import _TARGET_CTL from coach_plan instead of
redeclaring it, so that a single source of truth governs both modules.
"""

import backend.services.coach_plan as coach_plan
import backend.services.weekly_coach_message as weekly_coach_message


def test_target_ctl_is_same_object():
    """AC1: weekly_coach_message._TARGET_CTL is the same object as
    coach_plan._TARGET_CTL — not a copy, a shared reference."""
    assert weekly_coach_message._TARGET_CTL is coach_plan._TARGET_CTL


def test_target_ctl_values_preserved():
    """AC2: All expected distance keys and target values are intact."""
    expected = {
        "5k": 50.0,
        "10k": 60.0,
        "half": 70.0,
        "marathon": 85.0,
    }
    assert coach_plan._TARGET_CTL == expected
