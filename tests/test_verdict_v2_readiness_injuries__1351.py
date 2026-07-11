"""Tests for issue #1351: Verdict v2 — readiness trend and active injuries modulate back_off/hold/build.

Tests the training_verdict.py pure-function logic directly (no HTTP/UAT,
pure Python tests aligned with existing test_training_verdict__loadmetricfix2.py pattern).
"""
from datetime import date
import pytest
from backend.services.training_verdict import (
    READINESS_LOW_TODAY,
    READINESS_LOW_TREND,
    compute_verdict,
)

_TODAY = date(2026, 7, 9)


# --- Acceptance Criteria ---

# AC: training_verdict.py accepts new optional inputs: today's canonical readiness score,
# 7-day readiness trend, and active injury_log entries; existing call sites updated to pass them

def test_verdict_v2__accepts_readiness_today_parameter():
    # compute_verdict accepts readiness_today without error.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 0.0, "ctl": 40.0, "atl": 40.0},
        readiness_today=85.0,
        today=_TODAY
    )
    assert result["verdict"] in ("back_off", "hold", "build")


def test_verdict_v2__accepts_readiness_7d_mean_parameter():
    # compute_verdict accepts readiness_7d_mean without error.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 0.0, "ctl": 40.0, "atl": 40.0},
        readiness_7d_mean=75.0,
        today=_TODAY
    )
    assert result["verdict"] in ("back_off", "hold", "build")


def test_verdict_v2__accepts_injury_log_parameter():
    # compute_verdict accepts injury_log list without error.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 0.0, "ctl": 40.0, "atl": 40.0},
        injury_log=[],
        today=_TODAY
    )
    assert result["verdict"] in ("back_off", "hold", "build")


# AC: Deterministic downgrade rules (pure function, exact thresholds as constants):
# - active `injury` severity >= 2 or active `illness` -> verdict capped at `back_off`
# - active `niggle` or severity-1 injury -> verdict capped at `hold`
# - today readiness < 40, or 7-day readiness mean < 50 -> verdict downgraded one step
# - rules only ever downgrade, never upgrade; missing readiness/injury data -> load-only verdict unchanged

def test_verdict_v2__illness_caps_verdict_at_back_off():
    # Active illness -> verdict capped at back_off.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        injury_log=[{"kind": "illness", "severity": 1}],
        today=_TODAY
    )
    assert result["verdict"] == "back_off"
    assert any(m["rule"] == "illness_or_severe_injury" for m in result["modifiers"])


def test_verdict_v2__injury_severity_2_caps_at_back_off():
    # Active injury severity >= 2 -> verdict capped at back_off.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        injury_log=[{"kind": "injury", "severity": 2}],
        today=_TODAY
    )
    assert result["verdict"] == "back_off"
    assert any(m["rule"] == "illness_or_severe_injury" for m in result["modifiers"])


def test_verdict_v2__injury_severity_3_caps_at_back_off():
    # Active injury severity 3 -> verdict capped at back_off.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        injury_log=[{"kind": "injury", "severity": 3}],
        today=_TODAY
    )
    assert result["verdict"] == "back_off"


def test_verdict_v2__niggle_caps_at_hold():
    # Active niggle -> verdict capped at hold.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        injury_log=[{"kind": "niggle", "severity": 1}],
        today=_TODAY
    )
    assert result["verdict"] == "hold"
    assert any(m["rule"] == "niggle_or_minor_injury" for m in result["modifiers"])


def test_verdict_v2__injury_severity_1_caps_at_hold():
    # Active injury severity 1 -> verdict capped at hold.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        injury_log=[{"kind": "injury", "severity": 1}],
        today=_TODAY
    )
    assert result["verdict"] == "hold"
    assert any(m["rule"] == "niggle_or_minor_injury" for m in result["modifiers"])


def test_verdict_v2__low_readiness_today_downgrades_build_to_hold():
    # today readiness < 40 -> verdict downgraded one step (build -> hold).
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        readiness_today=35.0,  # Below READINESS_LOW_TODAY (40)
        today=_TODAY
    )
    assert result["verdict"] == "hold"
    assert any(m["rule"] == "low_readiness_today" for m in result["modifiers"])


def test_verdict_v2__low_readiness_today_downgrades_hold_to_back_off():
    # today readiness < 40 -> verdict downgraded one step (hold -> back_off).
    result = compute_verdict(
        {"acwr": 1.35, "tsb": -5.0, "ctl": 40.0, "atl": 50.0},  # Would be "hold" from load alone
        readiness_today=30.0,  # Below READINESS_LOW_TODAY (40)
        today=_TODAY
    )
    assert result["verdict"] == "back_off"


def test_verdict_v2__low_readiness_7d_mean_downgrades_build_to_hold():
    # 7-day readiness mean < 50 -> verdict downgraded one step (build -> hold).
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        readiness_7d_mean=45.0,  # Below READINESS_LOW_TREND (50)
        today=_TODAY
    )
    assert result["verdict"] == "hold"
    assert any(m["rule"] == "low_readiness_trend" for m in result["modifiers"])


def test_verdict_v2__low_readiness_7d_mean_downgrades_hold_to_back_off():
    # 7-day readiness mean < 50 -> verdict downgraded one step (hold -> back_off).
    result = compute_verdict(
        {"acwr": 1.35, "tsb": -5.0, "ctl": 40.0, "atl": 50.0},  # Would be "hold" from load alone
        readiness_7d_mean=48.0,  # Below READINESS_LOW_TREND (50)
        today=_TODAY
    )
    assert result["verdict"] == "back_off"


def test_verdict_v2__readiness_exactly_at_threshold_does_not_trigger():
    # Exactly at threshold does not trigger downgrade (strictly less-than).
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        readiness_today=40.0,  # Exactly at READINESS_LOW_TODAY
        today=_TODAY
    )
    assert result["verdict"] == "build"
    assert len(result["modifiers"]) == 0


def test_verdict_v2__readiness_above_threshold_does_not_trigger():
    # Above threshold does not trigger downgrade.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        readiness_today=85.0,  # Above READINESS_LOW_TODAY
        today=_TODAY
    )
    assert result["verdict"] == "build"
    assert len(result["modifiers"]) == 0


# AC: Verdict payload gains `modifiers: []` listing which rule fired with its input value

def test_verdict_v2__modifiers_field_exists():
    # Verdict payload has modifiers field.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 0.0, "ctl": 40.0, "atl": 40.0},
        today=_TODAY
    )
    assert "modifiers" in result
    assert isinstance(result["modifiers"], list)


def test_verdict_v2__modifiers_empty_when_no_rules_fire():
    # modifiers is empty when none fired.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # "build" from load alone
        readiness_today=85.0,  # Good readiness
        readiness_7d_mean=75.0,  # Good 7-day trend
        injury_log=[],  # No active injuries
        today=_TODAY
    )
    assert result["verdict"] == "build"
    assert result["modifiers"] == []


def test_verdict_v2__modifier_includes_rule_name_and_value():
    # Each modifier has rule and value keys.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},
        readiness_today=35.0,
        today=_TODAY
    )
    assert len(result["modifiers"]) > 0
    for mod in result["modifiers"]:
        assert "rule" in mod
        assert "value" in mod


# AC: rules only ever downgrade, never upgrade; missing readiness/injury data -> load-only verdict unchanged

def test_verdict_v2__rules_do_not_upgrade_build_to_higher():
    # A "build" verdict cannot be upgraded by anything.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # "build" from load alone
        readiness_today=100.0,  # Perfect readiness
        readiness_7d_mean=100.0,  # Perfect 7-day trend
        injury_log=[],  # No injuries
        today=_TODAY
    )
    assert result["verdict"] == "build"


def test_verdict_v2__missing_readiness_today_leaves_verdict_unchanged():
    # When readiness_today is None, load-only verdict is unchanged.
    result = compute_verdict(
        {"acwr": 1.35, "tsb": -5.0, "ctl": 40.0, "atl": 50.0},  # "hold" from load alone
        readiness_today=None,  # Missing
        today=_TODAY
    )
    assert result["verdict"] == "hold"


def test_verdict_v2__missing_readiness_7d_mean_leaves_verdict_unchanged():
    # When readiness_7d_mean is None, load-only verdict is unchanged.
    result = compute_verdict(
        {"acwr": 1.35, "tsb": -5.0, "ctl": 40.0, "atl": 50.0},  # "hold" from load alone
        readiness_7d_mean=None,  # Missing
        today=_TODAY
    )
    assert result["verdict"] == "hold"


def test_verdict_v2__missing_injury_log_leaves_verdict_unchanged():
    # When injury_log is None, load-only verdict is unchanged.
    result = compute_verdict(
        {"acwr": 1.35, "tsb": -5.0, "ctl": 40.0, "atl": 50.0},  # "hold" from load alone
        injury_log=None,  # Missing
        today=_TODAY
    )
    assert result["verdict"] == "hold"


def test_verdict_v2__empty_injury_log_leaves_verdict_unchanged():
    # When injury_log is empty, load-only verdict is unchanged.
    result = compute_verdict(
        {"acwr": 1.35, "tsb": -5.0, "ctl": 40.0, "atl": 50.0},  # "hold" from load alone
        injury_log=[],  # Empty
        today=_TODAY
    )
    assert result["verdict"] == "hold"


# AC: multiple rules stacking — worst wins

def test_verdict_v2__multiple_injuries_most_restrictive_wins():
    # Multiple injuries: the most restrictive verdict wins.
    # niggle (caps at hold) + illness (caps at back_off) -> back_off wins.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        injury_log=[
            {"kind": "niggle", "severity": 1},  # caps at hold
            {"kind": "illness", "severity": 1},  # caps at back_off
        ],
        today=_TODAY
    )
    assert result["verdict"] == "back_off"
    assert len(result["modifiers"]) >= 2  # Both rules fired


def test_verdict_v2__readiness_and_injury_most_restrictive_wins():
    # low_readiness_today downgrades build->hold, illness caps at back_off, back_off wins.
    result = compute_verdict(
        {"acwr": 1.0, "tsb": 10.0, "ctl": 40.0, "atl": 40.0},  # Would be "build" from load alone
        readiness_today=35.0,  # Downgrades to hold
        injury_log=[{"kind": "illness", "severity": 1}],  # Caps at back_off
        today=_TODAY
    )
    assert result["verdict"] == "back_off"
    assert len(result["modifiers"]) >= 2


def test_verdict_v2__back_off_verdict_cannot_be_downgraded_further():
    # A verdict already at "back_off" (from load) stays "back_off" even with wellness downgrades.
    result = compute_verdict(
        {"acwr": 1.60, "tsb": -16.8, "ctl": 32.0, "atl": 48.8},  # "back_off" from load
        readiness_today=35.0,  # Would downgrade
        injury_log=[{"kind": "illness", "severity": 1}],  # Would cap at back_off
        today=_TODAY
    )
    assert result["verdict"] == "back_off"


# UAT-level tests

def test_verdict_v2__weekly_summary_passes_readiness_and_injuries():
    # Test via the weekly_summary fact-assembly integration (if available in tests).
    pytest.skip("manual — requires end-to-end HTTP test with live user data; see UAT steps")


def test_verdict_v2__weekly_narration_includes_modifier_reason():
    # Test via the weekly_summary narration build (if available in tests).
    pytest.skip("manual — requires LLM generation; see UAT steps")
