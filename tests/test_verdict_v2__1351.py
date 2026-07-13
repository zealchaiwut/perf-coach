"""Tests for verdict v2 — readiness trend and active injuries modulate
back_off / hold / build (issue #1351).

Pure-function tests: no DB, no LLM.
Each AC item has at least one test anchored to it.
"""
from __future__ import annotations

from datetime import date

from backend.services.training_verdict import (
    READINESS_LOW_TODAY,
    READINESS_LOW_TREND,
    compute_verdict,
)

_TODAY = date(2026, 7, 11)
_SNAP_BUILD = {"acwr": 1.0, "tsb": 5.0, "ctl": 40.0, "atl": 38.0}
_SNAP_HOLD = {"acwr": 1.35, "tsb": -5.0, "ctl": 40.0, "atl": 50.0}
_SNAP_BACK_OFF = {"acwr": 1.60, "tsb": -16.8, "ctl": 32.0, "atl": 48.8}


# ── AC: payload shape ────────────────────────────────────────────────────────

def test_modifiers_present_in_payload():
    result = compute_verdict(_SNAP_BUILD, today=_TODAY)
    assert "modifiers" in result
    assert result["modifiers"] == []


def test_no_data_passthrough():
    """Missing readiness and no injuries -> load-only verdict unchanged."""
    result = compute_verdict(_SNAP_BUILD, today=_TODAY)
    assert result["verdict"] == "build"
    assert result["modifiers"] == []


def test_none_injury_log_passthrough():
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, injury_log=None)
    assert result["verdict"] == "build"
    assert result["modifiers"] == []


def test_none_readiness_passthrough():
    result = compute_verdict(
        _SNAP_BUILD, today=_TODAY,
        readiness_today=None, readiness_7d_mean=None,
    )
    assert result["verdict"] == "build"
    assert result["modifiers"] == []


def test_modifier_keys_are_rule_and_value():
    injuries = [{"kind": "illness", "severity": 1}]
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, injury_log=injuries)
    for m in result["modifiers"]:
        assert "rule" in m
        assert "value" in m


# ── AC: injury rules ─────────────────────────────────────────────────────────

def test_illness_caps_at_back_off():
    """Active illness -> verdict capped at back_off regardless of load signal."""
    injuries = [{"kind": "illness", "severity": 1}]
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, injury_log=injuries)
    assert result["verdict"] == "back_off"
    assert any(m["rule"] == "illness_or_severe_injury" for m in result["modifiers"])


def test_injury_severity_2_caps_at_back_off():
    """Injury severity >= 2 -> verdict capped at back_off."""
    injuries = [{"kind": "injury", "severity": 2}]
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, injury_log=injuries)
    assert result["verdict"] == "back_off"


def test_injury_severity_3_caps_at_back_off():
    injuries = [{"kind": "injury", "severity": 3}]
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, injury_log=injuries)
    assert result["verdict"] == "back_off"


def test_niggle_caps_at_hold():
    """Active niggle -> verdict capped at hold."""
    injuries = [{"kind": "niggle", "severity": 1}]
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, injury_log=injuries)
    assert result["verdict"] == "hold"
    assert any(m["rule"] == "niggle_or_minor_injury" for m in result["modifiers"])


def test_injury_severity_1_caps_at_hold():
    """Injury severity 1 -> verdict capped at hold."""
    injuries = [{"kind": "injury", "severity": 1}]
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, injury_log=injuries)
    assert result["verdict"] == "hold"


def test_niggle_does_not_downgrade_back_off():
    """Niggle caps at hold — cannot upgrade back_off. Rules only downgrade."""
    injuries = [{"kind": "niggle", "severity": 1}]
    result = compute_verdict(_SNAP_BACK_OFF, today=_TODAY, injury_log=injuries)
    assert result["verdict"] == "back_off"


def test_niggle_does_not_downgrade_hold():
    """Niggle caps at hold — hold stays hold, not back_off."""
    injuries = [{"kind": "niggle", "severity": 1}]
    result = compute_verdict(_SNAP_HOLD, today=_TODAY, injury_log=injuries)
    assert result["verdict"] == "hold"


def test_empty_injury_log_passthrough():
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, injury_log=[])
    assert result["verdict"] == "build"
    assert result["modifiers"] == []


# ── AC: readiness rules ──────────────────────────────────────────────────────

def test_low_readiness_today_downgrades_build_to_hold():
    """Today readiness < 40 -> build downgraded one step (to hold)."""
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, readiness_today=READINESS_LOW_TODAY - 1)
    assert result["verdict"] == "hold"
    rules = [m["rule"] for m in result["modifiers"]]
    assert "low_readiness_today" in rules


def test_low_readiness_today_modifier_value_is_input_score():
    score = 33.5
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, readiness_today=score)
    mod = next((m for m in result["modifiers"] if m["rule"] == "low_readiness_today"), None)
    assert mod is not None
    assert mod["value"] == score


def test_low_readiness_today_downgrades_hold_to_back_off():
    """Today readiness < 40 -> hold downgraded one step (to back_off)."""
    result = compute_verdict(_SNAP_HOLD, today=_TODAY, readiness_today=READINESS_LOW_TODAY - 1)
    assert result["verdict"] == "back_off"


def test_low_readiness_today_does_not_change_back_off():
    """back_off cannot be downgraded further."""
    result = compute_verdict(_SNAP_BACK_OFF, today=_TODAY, readiness_today=READINESS_LOW_TODAY - 1)
    assert result["verdict"] == "back_off"


def test_readiness_exactly_at_threshold_does_not_trigger():
    """Exactly at READINESS_LOW_TODAY (40.0) must NOT trigger (strict less-than)."""
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, readiness_today=READINESS_LOW_TODAY)
    assert result["verdict"] == "build"
    assert result["modifiers"] == []


def test_low_readiness_trend_downgrades_build_to_hold():
    """7-day readiness mean < 50 -> build downgraded one step (to hold)."""
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, readiness_7d_mean=READINESS_LOW_TREND - 1)
    assert result["verdict"] == "hold"
    rules = [m["rule"] for m in result["modifiers"]]
    assert "low_readiness_trend" in rules


def test_readiness_trend_exactly_at_threshold_does_not_trigger():
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, readiness_7d_mean=READINESS_LOW_TREND)
    assert result["verdict"] == "build"
    assert result["modifiers"] == []


# ── AC: rule stacking (worst wins) ──────────────────────────────────────────

def test_worst_rule_wins_illness_over_niggle():
    """Both illness and niggle active: illness (back_off) wins over niggle (hold)."""
    injuries = [
        {"kind": "niggle", "severity": 1},
        {"kind": "illness", "severity": 2},
    ]
    result = compute_verdict(_SNAP_BUILD, today=_TODAY, injury_log=injuries)
    assert result["verdict"] == "back_off"
    assert len(result["modifiers"]) == 2


def test_injury_and_low_readiness_stack_to_worst():
    """Illness (back_off) + low readiness on a build base -> back_off; both modifiers fire."""
    injuries = [{"kind": "illness", "severity": 1}]
    result = compute_verdict(
        _SNAP_BUILD, today=_TODAY,
        readiness_today=READINESS_LOW_TODAY - 5,
        injury_log=injuries,
    )
    assert result["verdict"] == "back_off"
    assert len(result["modifiers"]) >= 2


def test_two_readiness_rules_both_fire():
    """Both low_readiness_today and low_readiness_trend fire simultaneously."""
    result = compute_verdict(
        _SNAP_BUILD, today=_TODAY,
        readiness_today=READINESS_LOW_TODAY - 5,
        readiness_7d_mean=READINESS_LOW_TREND - 5,
    )
    assert result["verdict"] == "hold"
    rules = [m["rule"] for m in result["modifiers"]]
    assert "low_readiness_today" in rules
    assert "low_readiness_trend" in rules


def test_readiness_downgrade_uses_load_only_verdict_as_base():
    """Readiness downgrades one step from the load-only verdict, not from
    the already-modified verdict — so double-readiness can't jump two steps."""
    result = compute_verdict(
        _SNAP_BUILD, today=_TODAY,
        readiness_today=READINESS_LOW_TODAY - 5,
        readiness_7d_mean=READINESS_LOW_TREND - 5,
    )
    # build -> one step = hold (not two steps to back_off)
    assert result["verdict"] == "hold"
