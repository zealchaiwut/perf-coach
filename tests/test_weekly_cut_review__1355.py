"""Unit tests for weekly cut review recommendation (issue #1355).

AC coverage:
- every branch of the recommendation enum (7 branches)
- threshold boundary conditions
- guardrail (slow_down) precedence over increase_deficit when behind plan
- increase_deficit clamped at DEFICIT_KCAL_MAX (750)
"""
import pytest

from backend.services.cut_review import (
    compute_cut_recommendation,
    ON_TRACK_TOLERANCE_KG,
    EASE_OFF_THRESHOLD_KG,
    MIN_ADHERENCE_PCT,
    MIN_WEIGH_INS_14D,
    DEFICIT_STEP_KCAL,
    RECALIBRATE_WEEKS_THRESHOLD,
)
from backend.services.body_modifier import RATE_ZERO_CROSSING, EA_LOW_THRESHOLD
from backend.services.fuel import DEFICIT_KCAL_MAX


# ── Fixture helper ────────────────────────────────────────────────────────────

def _params(**overrides):
    """Return a complete kwargs dict for compute_cut_recommendation with defaults
    that produce on_track (close to plan, no issues)."""
    defaults = dict(
        weigh_in_count_14d=8,
        has_active_plan=True,
        actual_rate_kg_per_week=-0.5,    # losing 0.5 kg/wk (negative = losing)
        plan_rate_kg_per_week=-0.5,       # plan is -0.5 kg/wk
        weekly_pct_bw_rate=-0.60,         # -0.60 %BW/wk (losing 0.60%) — below RATE_ZERO_CROSSING
        ea_proxy=0.80,
        logging_adherence_pct=85.0,
        avg_intake_vs_budget_kcal=-30.0,   # eating ~30 kcal under budget
        consecutive_weeks_behind=0,
        pct_logged_days_at_or_under_budget=80.0,
        current_deficit_kcal=400,
    )
    defaults.update(overrides)
    return defaults


# ── AC-1: insufficient_data ────────────────────────────────────────────────────

def test_insufficient_data_fewer_than_4_weigh_ins():
    """Fewer than MIN_WEIGH_INS_14D weigh-ins → insufficient_data."""
    result = compute_cut_recommendation(**_params(weigh_in_count_14d=MIN_WEIGH_INS_14D - 1))
    assert result["recommendation"] == "insufficient_data"


def test_insufficient_data_no_active_plan():
    """No active plan → insufficient_data regardless of weigh-in count."""
    result = compute_cut_recommendation(**_params(has_active_plan=False))
    assert result["recommendation"] == "insufficient_data"


def test_insufficient_data_exactly_4_weigh_ins_is_sufficient():
    """Exactly MIN_WEIGH_INS_14D weigh-ins with active plan → not insufficient_data."""
    result = compute_cut_recommendation(**_params(weigh_in_count_14d=MIN_WEIGH_INS_14D))
    assert result["recommendation"] != "insufficient_data"


# ── AC-2: slow_down ───────────────────────────────────────────────────────────

def test_slow_down_loss_rate_exceeds_zero_crossing():
    """Loss rate above RATE_ZERO_CROSSING → slow_down (body_modifier penalty zone)."""
    # RATE_ZERO_CROSSING = 0.625; use 0.70 to be clearly above it
    pct_rate = -(RATE_ZERO_CROSSING + 0.10)  # e.g. -0.725 → losing 0.725%/wk
    result = compute_cut_recommendation(**_params(weekly_pct_bw_rate=pct_rate))
    assert result["recommendation"] == "slow_down"


def test_slow_down_ea_proxy_below_threshold():
    """EA proxy below EA_LOW_THRESHOLD → slow_down regardless of loss rate."""
    low_ea = EA_LOW_THRESHOLD - 0.05
    result = compute_cut_recommendation(**_params(
        weekly_pct_bw_rate=-0.30,  # low loss rate — would normally be on_track
        ea_proxy=low_ea,
    ))
    assert result["recommendation"] == "slow_down"


def test_slow_down_at_zero_crossing_boundary_not_triggered():
    """Loss rate exactly at RATE_ZERO_CROSSING (not above) → not slow_down."""
    # body_modifier_guardrail uses > RATE_ZERO_CROSSING, so exactly at is not warn
    pct_rate = -RATE_ZERO_CROSSING
    result = compute_cut_recommendation(**_params(
        weekly_pct_bw_rate=pct_rate,
        actual_rate_kg_per_week=-0.5,
        plan_rate_kg_per_week=-0.5,
    ))
    assert result["recommendation"] != "slow_down"


def test_slow_down_beats_increase_deficit_when_losing_too_fast_but_behind_plan():
    """Guardrail (slow_down) wins even if the user appears to be behind plan
    because the AC says slow_down has higher priority than increase_deficit."""
    pct_rate = -(RATE_ZERO_CROSSING + 0.15)  # exceeds penalty zone
    result = compute_cut_recommendation(**_params(
        weekly_pct_bw_rate=pct_rate,
        actual_rate_kg_per_week=-0.3,   # behind plan
        plan_rate_kg_per_week=-0.5,
        logging_adherence_pct=90.0,
        avg_intake_vs_budget_kcal=-20.0,
    ))
    assert result["recommendation"] == "slow_down"


# ── AC-3: on_track ─────────────────────────────────────────────────────────────

def test_on_track_exact_match():
    """Actual equals plan → on_track."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.50,
        plan_rate_kg_per_week=-0.50,
    ))
    assert result["recommendation"] == "on_track"


def test_on_track_within_tolerance():
    """Actual within ON_TRACK_TOLERANCE_KG of plan → on_track."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.41,       # 0.09 behind plan
        plan_rate_kg_per_week=-0.50,
    ))
    assert result["recommendation"] == "on_track"


def test_on_track_at_tolerance_boundary():
    """Actual exactly ON_TRACK_TOLERANCE_KG behind plan → on_track (boundary inclusive)."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-(0.50 - ON_TRACK_TOLERANCE_KG),  # -0.40
        plan_rate_kg_per_week=-0.50,
    ))
    assert result["recommendation"] == "on_track"


def test_beyond_tolerance_not_on_track():
    """Actual > ON_TRACK_TOLERANCE_KG behind plan → not on_track."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.35,  # 0.15 behind plan
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=90.0,
        avg_intake_vs_budget_kcal=-20.0,
    ))
    assert result["recommendation"] != "on_track"


# ── AC-4: check_logging ───────────────────────────────────────────────────────

def test_check_logging_behind_plan_low_adherence():
    """Behind plan AND adherence < MIN_ADHERENCE_PCT → check_logging."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.30,     # behind plan
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=MIN_ADHERENCE_PCT - 1.0,
    ))
    assert result["recommendation"] == "check_logging"


def test_check_logging_requires_being_behind_plan():
    """Low adherence alone when on_track doesn't produce check_logging."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.50,
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=50.0,
    ))
    assert result["recommendation"] == "on_track"


def test_check_logging_boundary_adherence_exactly_at_threshold_not_triggered():
    """Adherence exactly at MIN_ADHERENCE_PCT (70%) → not check_logging (threshold is <, not <=)."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.30,
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=MIN_ADHERENCE_PCT,
        avg_intake_vs_budget_kcal=-30.0,
    ))
    assert result["recommendation"] != "check_logging"


# ── AC-5: recalibrate_maintenance ─────────────────────────────────────────────

def test_recalibrate_maintenance_three_weeks_behind_at_budget():
    """Behind for RECALIBRATE_WEEKS_THRESHOLD consecutive weeks + eating at budget → recalibrate."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.30,
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=80.0,
        consecutive_weeks_behind=RECALIBRATE_WEEKS_THRESHOLD,
        pct_logged_days_at_or_under_budget=75.0,
        avg_intake_vs_budget_kcal=-30.0,
    ))
    assert result["recommendation"] == "recalibrate_maintenance"


def test_recalibrate_maintenance_requires_at_budget():
    """If intake >> budget on logged days, recalibrate is not the right call."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.30,
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=80.0,
        consecutive_weeks_behind=RECALIBRATE_WEEKS_THRESHOLD,
        pct_logged_days_at_or_under_budget=40.0,  # < 70% at budget
        avg_intake_vs_budget_kcal=-30.0,
    ))
    assert result["recommendation"] != "recalibrate_maintenance"


def test_recalibrate_maintenance_requires_enough_weeks():
    """Only 2 consecutive weeks behind → not recalibrate, try increase_deficit instead."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.30,
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=80.0,
        consecutive_weeks_behind=RECALIBRATE_WEEKS_THRESHOLD - 1,
        pct_logged_days_at_or_under_budget=80.0,
        avg_intake_vs_budget_kcal=-30.0,
    ))
    assert result["recommendation"] != "recalibrate_maintenance"


# ── AC-6: increase_deficit ────────────────────────────────────────────────────

def test_increase_deficit_behind_plan_good_adherence_at_budget():
    """Behind plan, adherence OK, eating at budget → increase_deficit."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.30,
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=80.0,
        avg_intake_vs_budget_kcal=-50.0,   # within AT_BUDGET_TOLERANCE_KCAL
        consecutive_weeks_behind=1,
        pct_logged_days_at_or_under_budget=80.0,
        current_deficit_kcal=400,
    ))
    assert result["recommendation"] == "increase_deficit"
    assert result["suggested_deficit_delta_kcal"] == DEFICIT_STEP_KCAL


def test_increase_deficit_clamped_at_750():
    """Never suggest a deficit above DEFICIT_KCAL_MAX (750 kcal)."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.30,
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=80.0,
        avg_intake_vs_budget_kcal=-30.0,
        consecutive_weeks_behind=1,
        pct_logged_days_at_or_under_budget=80.0,
        current_deficit_kcal=DEFICIT_KCAL_MAX,  # already at max
    ))
    # Can't go higher — increase_deficit should not be recommended
    assert result["recommendation"] != "increase_deficit"


def test_increase_deficit_not_suggested_when_significantly_under_budget():
    """If avg intake is far below budget (user already undereating), don't push more."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.30,
        plan_rate_kg_per_week=-0.50,
        logging_adherence_pct=80.0,
        avg_intake_vs_budget_kcal=-300.0,  # eating 300 kcal under budget
        consecutive_weeks_behind=1,
        pct_logged_days_at_or_under_budget=90.0,
    ))
    assert result["recommendation"] != "increase_deficit"


# ── AC-7: ease_off ────────────────────────────────────────────────────────────

def test_ease_off_ahead_of_plan_by_more_than_threshold():
    """Ahead by > EASE_OFF_THRESHOLD_KG → ease_off."""
    ahead_by = EASE_OFF_THRESHOLD_KG + 0.05  # 0.20 kg/wk ahead
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-(0.50 + ahead_by),  # losing faster than plan
        plan_rate_kg_per_week=-0.50,
        weekly_pct_bw_rate=-0.60,  # still below slow_down threshold
    ))
    assert result["recommendation"] == "ease_off"
    assert result["suggested_deficit_delta_kcal"] == -DEFICIT_STEP_KCAL


def test_ease_off_not_triggered_when_just_under_threshold():
    """Ahead by clearly less than EASE_OFF_THRESHOLD_KG (0.14 < 0.15) → NOT ease_off."""
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-0.64,  # 0.14 ahead of -0.50 plan (< 0.15 threshold)
        plan_rate_kg_per_week=-0.50,
        weekly_pct_bw_rate=-0.60,
    ))
    assert result["recommendation"] != "ease_off"


# ── Guardrail precedence ──────────────────────────────────────────────────────

def test_slow_down_beats_ease_off_when_loss_rate_excessive():
    """slow_down wins over ease_off: guardrail fires first even when ahead of plan."""
    pct_rate = -(RATE_ZERO_CROSSING + 0.10)  # above penalty zone
    ahead_by = EASE_OFF_THRESHOLD_KG + 0.05
    result = compute_cut_recommendation(**_params(
        actual_rate_kg_per_week=-(0.50 + ahead_by),
        plan_rate_kg_per_week=-0.50,
        weekly_pct_bw_rate=pct_rate,
    ))
    assert result["recommendation"] == "slow_down"


# ── Response structure ────────────────────────────────────────────────────────

def test_result_always_contains_required_keys():
    """All response dicts have recommendation, action, suggested_deficit_delta_kcal."""
    result = compute_cut_recommendation(**_params())
    assert "recommendation" in result
    assert "action" in result
    assert "suggested_deficit_delta_kcal" in result


def test_insufficient_data_action_is_non_empty():
    result = compute_cut_recommendation(**_params(has_active_plan=False))
    assert result["action"] and len(result["action"]) > 0
