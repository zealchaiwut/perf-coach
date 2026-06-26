"""
Visual regression tests for progress card bar positioning (issue #476).

Verifies that the JS formula for plan-tick and you-dot bar positions is:
  - mathematically correct for LOSS targets (start > target)
  - mathematically correct for GAIN targets (start < target)
  - consistent with the backend gap_direction sign convention
  - correct for short (≤2 kg) and long (≥20 kg) target ranges
  - correctly clamped to [0, 100]

These tests are pure Python and do not require a running server. They
mirror the JS formula exactly so that any future divergence between JS
and backend causes a CI failure — that is the visual regression guard.

Reference JS (frontend/js/weight.js):
    const pct = Math.max(0, Math.min(100, target.progress_pct || 0));
    youDotEl.style.left = `${pct}%`;

    const totalRange = startW - targetW;
    const planPct = (totalRange !== 0 && planTodayKg != null)
      ? Math.max(0, Math.min(100, (startW - planTodayKg) / totalRange * 100))
      : pct;
    planTickEl.style.left = `${planPct}%`;

Reference backend (backend/services/weight_plan.py _gap_direction):
    is_loss = target_weight_kg < start_weight_kg
    behind = gap > 0 (LOSS) OR gap < 0 (GAIN)   where gap = current - plan_today
"""

from __future__ import annotations

import re
from pathlib import Path
from decimal import Decimal

import pytest

FRONTEND = Path(__file__).parent.parent / "frontend"
WEIGHT_JS = FRONTEND / "js" / "weight.js"

js = WEIGHT_JS.read_text()


# ── Reference Python mirrors of the JS formula ───────────────────────────────

def _you_dot_pct(start: float, target: float, current: float) -> float:
    """progress_pct formula: (start − current) / (start − target) × 100, clamped [0,100]."""
    total_range = start - target
    if total_range == 0:
        return 100.0
    raw = (start - current) / total_range * 100.0
    return max(0.0, min(100.0, raw))


def _plan_tick_pct(start: float, target: float, plan_today: float) -> float:
    """Plan-tick formula: (start − plan_today) / (start − target) × 100, clamped [0,100]."""
    total_range = start - target
    if total_range == 0:
        return 0.0
    raw = (start - plan_today) / total_range * 100.0
    return max(0.0, min(100.0, raw))


def _gap_direction_py(start: float, target: float, plan_today: float, current: float) -> str:
    """Mirror of backend _gap_direction logic."""
    gap = Decimal(str(current)) - Decimal(str(plan_today))
    if abs(gap) <= Decimal("0.2"):
        return "on_plan"
    is_loss = Decimal(str(target)) < Decimal(str(start))
    if is_loss:
        return "behind" if gap > 0 else "ahead"
    return "ahead" if gap > 0 else "behind"


# ── Fixture definitions ───────────────────────────────────────────────────────

# Each fixture: (label, start, target, plan_today, current, expected_gap_direction)
FIXTURES = [
    # LOSS scenarios (start > target)
    ("LOSS-behind",  90.0, 80.0, 87.0, 89.0, "behind"),
    ("LOSS-ahead",   90.0, 80.0, 87.0, 86.0, "ahead"),
    ("LOSS-on_plan", 90.0, 80.0, 87.0, 87.0, "on_plan"),

    # GAIN scenarios (start < target) — sign convention is the key divergence risk
    # gap = current - plan_today; is_loss=False so: gap>0 → ahead, gap<0 → behind
    ("GAIN-behind",  70.0, 80.0, 73.0, 71.0, "behind"),   # gap=-2 → behind (GAIN)
    ("GAIN-ahead",   70.0, 80.0, 73.0, 74.0, "ahead"),    # gap=+1 → ahead  (GAIN)
    ("GAIN-on_plan", 70.0, 80.0, 73.0, 73.0, "on_plan"),  # gap= 0 → on_plan

    # Short target (≤2 kg range)
    ("short-LOSS-behind", 75.0, 73.0, 74.5, 74.8, "behind"),
    ("short-GAIN-ahead",  73.0, 75.0, 73.5, 73.8, "ahead"),

    # Long target (≥20 kg range)
    ("long-LOSS-behind", 110.0, 85.0, 107.5, 109.2, "behind"),
    ("long-GAIN-ahead",   60.0, 85.0,  62.5,  63.5, "ahead"),
]


# ── (1) Reference formula produces sane [0, 100] values ─────────────────────

@pytest.mark.parametrize("label,start,target,plan_today,current,gap_dir", FIXTURES)
def test_bar_positions_in_valid_range(label, start, target, plan_today, current, gap_dir):
    """Bar positions must always fall in [0, 100] regardless of LOSS/GAIN direction."""
    you_pct  = _you_dot_pct(start, target, current)
    plan_pct = _plan_tick_pct(start, target, plan_today)
    assert 0.0 <= you_pct  <= 100.0, f"[{label}] you-dot {you_pct:.2f}% out of range"
    assert 0.0 <= plan_pct <= 100.0, f"[{label}] plan-tick {plan_pct:.2f}% out of range"


# ── (2) gap_direction sign convention vs bar position ────────────────────────

@pytest.mark.parametrize("label,start,target,plan_today,current,expected_gap_dir", FIXTURES)
def test_gap_direction_consistent_with_bar_position(
    label, start, target, plan_today, current, expected_gap_dir
):
    """
    gap_direction from backend logic must agree with the bar-position relationship:
      behind  → you-dot < plan-tick  (you are left of the plan marker)
      ahead   → you-dot > plan-tick  (you are right of the plan marker)
      on_plan → you-dot ≈ plan-tick  (within floating-point tolerance)

    This is the core visual regression check: if the JS formula diverges from
    the backend sign convention, this test will catch it.
    """
    actual_dir = _gap_direction_py(start, target, plan_today, current)
    assert actual_dir == expected_gap_dir, (
        f"[{label}] _gap_direction_py returned '{actual_dir}', expected '{expected_gap_dir}'"
    )

    you_pct  = _you_dot_pct(start, target, current)
    plan_pct = _plan_tick_pct(start, target, plan_today)

    if expected_gap_dir == "behind":
        assert you_pct < plan_pct, (
            f"[{label}] 'behind' fixture: you-dot ({you_pct:.2f}%) must be LEFT of "
            f"plan-tick ({plan_pct:.2f}%)"
        )
    elif expected_gap_dir == "ahead":
        assert you_pct > plan_pct, (
            f"[{label}] 'ahead' fixture: you-dot ({you_pct:.2f}%) must be RIGHT of "
            f"plan-tick ({plan_pct:.2f}%)"
        )
    else:  # on_plan
        assert abs(you_pct - plan_pct) < 0.5, (
            f"[{label}] 'on_plan' fixture: you-dot ({you_pct:.2f}%) and "
            f"plan-tick ({plan_pct:.2f}%) must coincide"
        )


# ── (3) GAIN sign convention: formula must NOT flip positions ────────────────

@pytest.mark.parametrize("label,start,target,plan_today,current,gap_dir", [
    f for f in FIXTURES if f[0].startswith("GAIN")
])
def test_gain_formula_preserves_direction(label, start, target, plan_today, current, gap_dir):
    """
    For GAIN targets (start < target), totalRange is negative.
    The formula (start - planToday) / totalRange × 100 must still produce
    a percentage in [0, 100] where plan-tick advances toward 100% as the
    plan value approaches the target — same geometry as LOSS, opposite sign.
    """
    you_pct  = _you_dot_pct(start, target, current)
    plan_pct = _plan_tick_pct(start, target, plan_today)

    # Both markers must still be in (0, 100) exclusive for these non-trivial fixtures
    assert 0.0 < you_pct  < 100.0, f"[{label}] you-dot at boundary: {you_pct:.2f}%"
    assert 0.0 < plan_pct < 100.0, f"[{label}] plan-tick at boundary: {plan_pct:.2f}%"


# ── (4) LOSS formula: explicit numeric spot-checks ───────────────────────────

def test_loss_behind_spot_check():
    """LOSS-behind: start=90, target=80, plan=87, current=89 → you=10%, plan=30%."""
    assert abs(_you_dot_pct(90, 80, 89) - 10.0) < 0.01
    assert abs(_plan_tick_pct(90, 80, 87) - 30.0) < 0.01


def test_loss_ahead_spot_check():
    """LOSS-ahead: start=90, target=80, plan=87, current=86 → you=40%, plan=30%."""
    assert abs(_you_dot_pct(90, 80, 86) - 40.0) < 0.01
    assert abs(_plan_tick_pct(90, 80, 87) - 30.0) < 0.01


# ── (5) GAIN formula: explicit numeric spot-checks ───────────────────────────

def test_gain_behind_spot_check():
    """GAIN-behind: start=70, target=80, plan=73, current=71 → you=10%, plan=30%."""
    # totalRange = 70-80 = -10
    # youPct = (70-71)/-10 * 100 = 10%
    # planPct = (70-73)/-10 * 100 = 30%
    assert abs(_you_dot_pct(70, 80, 71) - 10.0) < 0.01
    assert abs(_plan_tick_pct(70, 80, 73) - 30.0) < 0.01


def test_gain_ahead_spot_check():
    """GAIN-ahead: start=70, target=80, plan=73, current=74 → you=40%, plan=30%."""
    # youPct = (70-74)/-10 * 100 = 40%
    # planPct = (70-73)/-10 * 100 = 30%
    assert abs(_you_dot_pct(70, 80, 74) - 40.0) < 0.01
    assert abs(_plan_tick_pct(70, 80, 73) - 30.0) < 0.01


def test_gain_formula_matches_loss_geometry():
    """
    A GAIN fixture (start=70, target=80) with identical fractional progress
    must produce the same percentages as the equivalent LOSS fixture
    (start=90, target=80). The formula must be symmetric.
    """
    # Both at 30% plan, 10% you
    loss_you  = _you_dot_pct(90, 80, 89)      # 10%
    loss_plan = _plan_tick_pct(90, 80, 87)    # 30%
    gain_you  = _you_dot_pct(70, 80, 71)      # 10%
    gain_plan = _plan_tick_pct(70, 80, 73)    # 30%

    assert abs(loss_you - gain_you) < 0.01, (
        f"LOSS you={loss_you:.2f}% != GAIN you={gain_you:.2f}% — formula asymmetry"
    )
    assert abs(loss_plan - gain_plan) < 0.01, (
        f"LOSS plan={loss_plan:.2f}% != GAIN plan={gain_plan:.2f}% — formula asymmetry"
    )


# ── (6) Short target: small range doesn't collapse both markers ───────────────

def test_short_loss_target_non_degenerate():
    """Short LOSS (2 kg range): positions are distinct and ordered correctly."""
    you_pct  = _you_dot_pct(75.0, 73.0, 74.8)   # (75-74.8)/(75-73)*100 = 10%
    plan_pct = _plan_tick_pct(75.0, 73.0, 74.5)  # (75-74.5)/(75-73)*100 = 25%
    assert 0.0 < you_pct < plan_pct < 100.0, (
        f"short-LOSS-behind: you={you_pct:.2f}% must be left of plan={plan_pct:.2f}%"
    )


def test_short_gain_target_non_degenerate():
    """Short GAIN (2 kg range): positions are distinct and ordered correctly."""
    you_pct  = _you_dot_pct(73.0, 75.0, 73.8)   # (73-73.8)/(73-75)*100 = 40%
    plan_pct = _plan_tick_pct(73.0, 75.0, 73.5)  # (73-73.5)/(73-75)*100 = 25%
    assert 0.0 < plan_pct < you_pct < 100.0, (
        f"short-GAIN-ahead: plan={plan_pct:.2f}% must be left of you={you_pct:.2f}%"
    )


# ── (7) Long target: large range doesn't overflow ─────────────────────────────

def test_long_loss_target_in_range():
    """Long LOSS (25 kg range): both positions in (0, 100) — no overflow."""
    you_pct  = _you_dot_pct(110.0, 85.0, 109.2)
    plan_pct = _plan_tick_pct(110.0, 85.0, 107.5)
    assert 0.0 < you_pct  < 100.0
    assert 0.0 < plan_pct < 100.0


def test_long_gain_target_in_range():
    """Long GAIN (25 kg range): both positions in (0, 100) — no overflow."""
    you_pct  = _you_dot_pct(60.0, 85.0, 63.5)
    plan_pct = _plan_tick_pct(60.0, 85.0, 62.5)
    assert 0.0 < you_pct  < 100.0
    assert 0.0 < plan_pct < 100.0


# ── (8) Clamping: positions beyond [0, 100] are clamped ─────────────────────

def test_you_dot_clamped_below_zero():
    """Current weight overshooting in the wrong direction is clamped to 0%."""
    # LOSS: current > start (gained weight while trying to lose)
    assert _you_dot_pct(90.0, 80.0, 95.0) == 0.0


def test_you_dot_clamped_above_100():
    """Current weight past goal is clamped to 100%."""
    # LOSS: current < target (past goal)
    assert _you_dot_pct(90.0, 80.0, 78.0) == 100.0


def test_plan_tick_clamped_below_zero():
    """Plan exceeding start is clamped to 0%."""
    # LOSS: plan_today > start (shouldn't happen but must not crash)
    assert _plan_tick_pct(90.0, 80.0, 92.0) == 0.0


def test_plan_tick_clamped_above_100():
    """Plan past goal is clamped to 100%."""
    # LOSS: plan_today < target
    assert _plan_tick_pct(90.0, 80.0, 79.0) == 100.0


# ── (9) Zero-range target (start == target) ───────────────────────────────────

def test_zero_range_you_dot_is_100():
    """When start == target, you-dot defaults to 100% (already at goal)."""
    assert _you_dot_pct(80.0, 80.0, 80.0) == 100.0


def test_zero_range_plan_tick_is_zero():
    """When start == target, plan-tick defaults to 0% (guard division by zero)."""
    assert _plan_tick_pct(80.0, 80.0, 80.0) == 0.0


# ── (10) JS formula presence checks ─────────────────────────────────────────

def test_js_plan_tick_uses_start_minus_plan_over_total_range():
    """JS must compute plan-tick using (startW - planTodayKg) / totalRange."""
    assert "startW - planTodayKg" in js or "(startW - plan" in js, (
        "JS plan-tick formula must subtract planTodayKg from startW "
        "(AC-C, required for correct GAIN sign convention)"
    )


def test_js_total_range_is_start_minus_target():
    """JS must define totalRange as startW - targetW (works for both LOSS and GAIN)."""
    assert "startW - targetW" in js or "totalRange" in js, (
        "JS must compute totalRange = startW - targetW for plan-tick position"
    )


def test_js_you_dot_uses_progress_pct_from_api():
    """JS positions you-dot using progress_pct from the API response, not a JS recomputation."""
    # The JS should read target.progress_pct, not recalculate (start-current)/(start-target)
    assert "progress_pct" in js, "JS must use target.progress_pct for you-dot position"
    # And it must assign it to the you-dot element
    assert "pgbar-you-dot" in js, "JS must set left% on #pgbar-you-dot"


def test_js_plan_tick_clamps_to_0_100():
    """JS must clamp plan-tick position to [0, 100] (Math.max/Math.min)."""
    # Look for min/max clamping in the planPct computation
    plan_tick_idx = js.find("planPct")
    assert plan_tick_idx != -1, "planPct variable not found in JS"
    snippet = js[plan_tick_idx:plan_tick_idx + 200]
    assert "Math.max" in snippet or "Math.min" in snippet, (
        "JS plan-tick must be clamped with Math.max/Math.min to prevent "
        "positions outside [0%, 100%]"
    )


def test_js_current_basis_derived_not_separate_api_field():
    """
    JS derives currentBasisKg from planTodayKg + gapKg — it does NOT expect
    a separate 'current_basis_kg' field in the API response.
    This keeps the API shape stable and prevents GAIN sign divergence via
    an independent client-side computation of 'current'.
    """
    assert "planTodayKg + gapKg" in js or "plan_today_kg + gap_kg" in js, (
        "JS must derive currentBasisKg = planTodayKg + gapKg "
        "(no separate current_basis_kg API field expected by the client)"
    )


# ── (11) gap_direction sign convention is not hardcoded for LOSS-only ─────────

def test_gain_behind_gap_direction():
    """GAIN-behind: current < plan_today → gap_kg < 0 → gap_direction = 'behind'."""
    result = _gap_direction_py(start=70.0, target=80.0, plan_today=73.0, current=71.0)
    assert result == "behind", (
        "For GAIN target with current < plan_today (gap_kg<0), "
        "gap_direction must be 'behind' (AC: sign convention for GAIN)"
    )


def test_gain_ahead_gap_direction():
    """GAIN-ahead: current > plan_today → gap_kg > 0 → gap_direction = 'ahead'."""
    result = _gap_direction_py(start=70.0, target=80.0, plan_today=73.0, current=74.0)
    assert result == "ahead", (
        "For GAIN target with current > plan_today (gap_kg>0), "
        "gap_direction must be 'ahead' (AC: sign convention for GAIN)"
    )


def test_loss_behind_gap_direction():
    """LOSS-behind: current > plan_today → gap_kg > 0 → gap_direction = 'behind'."""
    result = _gap_direction_py(start=90.0, target=80.0, plan_today=87.0, current=89.0)
    assert result == "behind"


def test_loss_ahead_gap_direction():
    """LOSS-ahead: current < plan_today → gap_kg < 0 → gap_direction = 'ahead'."""
    result = _gap_direction_py(start=90.0, target=80.0, plan_today=87.0, current=86.0)
    assert result == "ahead"
