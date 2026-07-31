"""Unit tests for plateau and diet-break detection in weekly cut review (issue #1356).

AC coverage:
- Window boundary: 20 days does NOT trigger plateau; 21 days DOES
- Adherence gate: <70% at/under budget does NOT trigger; >=70% DOES
- Precedence: insufficient_data > slow_down > plateau > the rest
"""
from backend.services.cut_review import (
    compute_cut_recommendation,
    PLATEAU_MIN_DAYS,
    MIN_WEIGH_INS_14D,
)
from backend.services.body_modifier import RATE_ZERO_CROSSING, EA_LOW_THRESHOLD


# ── Fixture helper ────────────────────────────────────────────────────────────

def _params(**overrides):
    """Complete kwargs for compute_cut_recommendation — on_track by default."""
    defaults = dict(
        weigh_in_count_14d=8,
        has_active_plan=True,
        actual_rate_kg_per_week=-0.5,
        plan_rate_kg_per_week=-0.5,
        weekly_pct_bw_rate=-0.60,
        ea_proxy=0.80,
        logging_adherence_pct=85.0,
        avg_intake_vs_budget_kcal=-30.0,
        consecutive_weeks_behind=0,
        pct_logged_days_at_or_under_budget=80.0,
        current_deficit_kcal=400,
        plateau_days=0,
        pct_at_or_under_budget_21d=80.0,
    )
    defaults.update(overrides)
    return defaults


def _plateau_params(**overrides):
    """Params that produce a plateau recommendation (all conditions met)."""
    base = _params(
        actual_rate_kg_per_week=-0.05,
        plan_rate_kg_per_week=-0.5,
        weekly_pct_bw_rate=-0.05,
        ea_proxy=0.80,
        plateau_days=PLATEAU_MIN_DAYS,
        pct_at_or_under_budget_21d=75.0,
    )
    base.update(overrides)
    return base


# ── AC: Window boundary (20 vs 21 days) ──────────────────────────────────────

def test_plateau_not_triggered_at_20_days():
    """plateau_days=20 (< PLATEAU_MIN_DAYS=21) does NOT trigger plateau."""
    result = compute_cut_recommendation(**_plateau_params(plateau_days=20))
    assert result["recommendation"] != "plateau"


def test_plateau_triggered_at_21_days():
    """plateau_days=21 (= PLATEAU_MIN_DAYS) triggers plateau."""
    result = compute_cut_recommendation(**_plateau_params(plateau_days=21))
    assert result["recommendation"] == "plateau"


def test_plateau_triggered_above_21_days():
    """plateau_days=30 (> PLATEAU_MIN_DAYS) also triggers plateau."""
    result = compute_cut_recommendation(**_plateau_params(plateau_days=30))
    assert result["recommendation"] == "plateau"


# ── AC: Adherence gate (>= 70% of logged days at/under budget) ───────────────

def test_plateau_not_triggered_when_adherence_below_70_pct():
    """pct_at_or_under_budget_21d < 70% does NOT trigger plateau."""
    result = compute_cut_recommendation(
        **_plateau_params(pct_at_or_under_budget_21d=69.9)
    )
    assert result["recommendation"] != "plateau"


def test_plateau_triggered_at_exactly_70_pct_adherence():
    """pct_at_or_under_budget_21d exactly 70% triggers plateau (inclusive)."""
    result = compute_cut_recommendation(
        **_plateau_params(pct_at_or_under_budget_21d=70.0)
    )
    assert result["recommendation"] == "plateau"


def test_plateau_triggered_above_70_pct_adherence():
    """pct_at_or_under_budget_21d=85% triggers plateau."""
    result = compute_cut_recommendation(
        **_plateau_params(pct_at_or_under_budget_21d=85.0)
    )
    assert result["recommendation"] == "plateau"


# ── AC: plateau_days count in payload ────────────────────────────────────────

def test_plateau_payload_includes_plateau_days():
    """When plateau fires, the result dict contains the correct plateau_days."""
    result = compute_cut_recommendation(**_plateau_params(plateau_days=28))
    assert result["recommendation"] == "plateau"
    assert result["plateau_days"] == 28


def test_plateau_payload_describes_both_actions():
    """Plateau action text mentions calibration and diet break."""
    result = compute_cut_recommendation(**_plateau_params())
    action = result["action"].lower()
    assert "calibrat" in action or "recalibrat" in action
    assert "diet break" in action or "deficit to 0" in action


# ── AC: Precedence ordering ───────────────────────────────────────────────────

def test_insufficient_data_beats_plateau():
    """insufficient_data has priority over plateau (weigh-in count too low)."""
    result = compute_cut_recommendation(
        **_plateau_params(weigh_in_count_14d=MIN_WEIGH_INS_14D - 1)
    )
    assert result["recommendation"] == "insufficient_data"


def test_no_plan_does_not_block_plateau_in_structural_mode():
    """REVERSED by #1600.

    This asserted that a missing WeightPlan yields insufficient_data even with a
    21-day stall. That gate was the bug: no UI creates a WeightPlan, and the one
    route that does requires a `goal_weight_kg` — the target-weight concept the
    lean program exists to eliminate. So a structural-deficit athlete could
    plateau for three weeks and be told only to "set an active plan".

    Structural mode diagnoses from the weight trend alone, which is its premise.
    """
    result = compute_cut_recommendation(**_plateau_params(has_active_plan=False))
    assert result["recommendation"] == "plateau"


def test_no_plan_still_blocks_in_managed_mode():
    """Managed mode keeps the original contract — a daily-budget cut genuinely
    has a plan behind it."""
    result = compute_cut_recommendation(
        **_plateau_params(has_active_plan=False, deficit_mode="managed")
    )
    assert result["recommendation"] == "insufficient_data"


def test_slow_down_beats_plateau():
    """slow_down (guardrail) has priority over plateau."""
    result = compute_cut_recommendation(**_plateau_params(
        weekly_pct_bw_rate=-(RATE_ZERO_CROSSING + 0.10),
        ea_proxy=0.80,
    ))
    assert result["recommendation"] == "slow_down"


def test_slow_down_beats_plateau_with_low_ea():
    """EA proxy below threshold triggers slow_down, which beats plateau."""
    result = compute_cut_recommendation(**_plateau_params(
        weekly_pct_bw_rate=-0.05,
        ea_proxy=EA_LOW_THRESHOLD - 0.05,
    ))
    assert result["recommendation"] == "slow_down"


def test_plateau_beats_on_track():
    """When all plateau conditions are met, result is plateau, not on_track."""
    result = compute_cut_recommendation(**_plateau_params())
    assert result["recommendation"] == "plateau"


def test_on_track_when_no_plateau_days():
    """plateau_days=0 leaves normal on_track recommendation unaffected."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.5,
        plan_rate_kg_per_week=-0.5,
        plateau_days=0,
    ))
    assert result["recommendation"] == "on_track"


# ── AC: Weeks covered by slow_down or insufficient_data are unaffected ────────

def test_plateau_does_not_affect_slow_down_case():
    """slow_down still fires when plateau conditions are also met."""
    result = compute_cut_recommendation(**_plateau_params(
        weekly_pct_bw_rate=-(RATE_ZERO_CROSSING + 0.10),
        plateau_days=30,
        pct_at_or_under_budget_21d=90.0,
    ))
    assert result["recommendation"] == "slow_down"


def test_plateau_does_not_affect_insufficient_data_case():
    """insufficient_data still fires when plateau conditions are also met."""
    result = compute_cut_recommendation(**_plateau_params(
        plateau_days=30,
        weigh_in_count_14d=0,
    ))
    assert result["recommendation"] == "insufficient_data"


# ── Response structure ────────────────────────────────────────────────────────

def test_non_plateau_result_has_no_plateau_days():
    """Non-plateau recommendations return plateau_days=None."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.5,
        plan_rate_kg_per_week=-0.5,
    ))
    assert result["recommendation"] == "on_track"
    assert result.get("plateau_days") is None
