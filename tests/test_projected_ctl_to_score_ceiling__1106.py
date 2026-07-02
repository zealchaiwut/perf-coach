"""Tests for projected_ctl_to_score_ceiling (issue #1106).

AC coverage:
  AC1 — function accepts projected CTL and economy kwarg, returns endurance and speed ceilings
  AC2 — ceilings rise monotonically as CTL increases (three-value test)
  AC3 — economy parameter is a no-op stub (same output regardless of economy value)
  AC4 — no ceiling exceeds SCORE_CEILING_MAX; all ceilings are non-negative
  AC5 — py_compile passes (structural, no explicit assertion needed here)
  AC6 — existing tests are unchanged (structural, not enforced here)
"""

import pytest
from backend.services.score_ceiling import (
    projected_ctl_to_score_ceiling,
    SCORE_CEILING_MAX,
)


# ── AC1: signature and return shape ──────────────────────────────────────────

def test_returns_endurance_and_speed_ceilings():
    result = projected_ctl_to_score_ceiling(ctl=40)
    assert "endurance_ceiling" in result
    assert "speed_ceiling" in result


def test_accepts_economy_kwarg():
    # Must not raise; economy is accepted as a kwarg
    result = projected_ctl_to_score_ceiling(ctl=40, economy=0.85)
    assert "endurance_ceiling" in result
    assert "speed_ceiling" in result


# ── AC2: monotonic rise with CTL ─────────────────────────────────────────────

@pytest.mark.parametrize("ctl_low,ctl_high", [
    (20, 40),
    (40, 70),
    (70, 100),
])
def test_ceilings_rise_monotonically(ctl_low, ctl_high):
    low = projected_ctl_to_score_ceiling(ctl=ctl_low)
    high = projected_ctl_to_score_ceiling(ctl=ctl_high)
    assert high["endurance_ceiling"] >= low["endurance_ceiling"], (
        f"Endurance ceiling did not rise: CTL={ctl_low} → {low['endurance_ceiling']}, "
        f"CTL={ctl_high} → {high['endurance_ceiling']}"
    )
    assert high["speed_ceiling"] >= low["speed_ceiling"], (
        f"Speed ceiling did not rise: CTL={ctl_low} → {low['speed_ceiling']}, "
        f"CTL={ctl_high} → {high['speed_ceiling']}"
    )


def test_three_ctl_values_all_monotonic():
    """AC2 explicit check with at least three CTL values."""
    r40 = projected_ctl_to_score_ceiling(ctl=40)
    r70 = projected_ctl_to_score_ceiling(ctl=70)
    r100 = projected_ctl_to_score_ceiling(ctl=100)
    assert r70["endurance_ceiling"] >= r40["endurance_ceiling"]
    assert r100["endurance_ceiling"] >= r70["endurance_ceiling"]
    assert r70["speed_ceiling"] >= r40["speed_ceiling"]
    assert r100["speed_ceiling"] >= r70["speed_ceiling"]


# ── AC3: economy is a no-op stub ─────────────────────────────────────────────

def test_economy_is_noop_stub():
    without_economy = projected_ctl_to_score_ceiling(ctl=40)
    with_economy = projected_ctl_to_score_ceiling(ctl=40, economy=0.85)
    assert with_economy["endurance_ceiling"] == without_economy["endurance_ceiling"]
    assert with_economy["speed_ceiling"] == without_economy["speed_ceiling"]


def test_economy_none_default_same_as_explicit_none():
    r1 = projected_ctl_to_score_ceiling(ctl=60)
    r2 = projected_ctl_to_score_ceiling(ctl=60, economy=None)
    assert r1 == r2


# ── AC4: bounds — max not exceeded, non-negative ─────────────────────────────

@pytest.mark.parametrize("ctl", [0, 10, 40, 70, 100, 150, 200, 999])
def test_ceilings_within_bounds(ctl):
    result = projected_ctl_to_score_ceiling(ctl=ctl)
    assert result["endurance_ceiling"] >= 0, f"Endurance ceiling negative at CTL={ctl}"
    assert result["speed_ceiling"] >= 0, f"Speed ceiling negative at CTL={ctl}"
    assert result["endurance_ceiling"] <= SCORE_CEILING_MAX, (
        f"Endurance ceiling {result['endurance_ceiling']} exceeds max {SCORE_CEILING_MAX} at CTL={ctl}"
    )
    assert result["speed_ceiling"] <= SCORE_CEILING_MAX, (
        f"Speed ceiling {result['speed_ceiling']} exceeds max {SCORE_CEILING_MAX} at CTL={ctl}"
    )


def test_zero_ctl_non_negative():
    result = projected_ctl_to_score_ceiling(ctl=0)
    assert result["endurance_ceiling"] >= 0
    assert result["speed_ceiling"] >= 0


def test_high_ctl_caps_at_max():
    result = projected_ctl_to_score_ceiling(ctl=999)
    assert result["endurance_ceiling"] <= SCORE_CEILING_MAX
    assert result["speed_ceiling"] <= SCORE_CEILING_MAX


# ── UAT step 1: CTL=40, both positive, within max ────────────────────────────

def test_uat_step1_ctl_40_positive_and_within_max():
    result = projected_ctl_to_score_ceiling(ctl=40)
    assert result["endurance_ceiling"] > 0
    assert result["speed_ceiling"] > 0
    assert result["endurance_ceiling"] <= SCORE_CEILING_MAX
    assert result["speed_ceiling"] <= SCORE_CEILING_MAX


# ── UAT step 3: CTL=100, no exception, within max ────────────────────────────

def test_uat_step3_ctl_100_no_exception():
    result = projected_ctl_to_score_ceiling(ctl=100)
    assert result["endurance_ceiling"] <= SCORE_CEILING_MAX
    assert result["speed_ceiling"] <= SCORE_CEILING_MAX
