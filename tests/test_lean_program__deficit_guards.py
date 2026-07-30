"""Phase 2 — structural deficit, guardrails and auto-pause (spec §7, §12).

Three things are pinned here, in order of how badly they'd hurt if they broke:

1. **The floors hold.** No generated day drops below the EA floor, estimated
   BMR, or the carb floor, and a deficit over the hard max is rejected.
2. **The guards pause, and the copy says eat more.** Each trigger fires
   independently; no message ever says "try harder".
3. **`cut_review` answers from weight data alone.** The whole point of a
   structural deficit is that there is no food log — a review that demands one
   returns `check_logging` forever and the program has no feedback loop.
"""
from __future__ import annotations

import datetime

import pytest

from backend.services import cut_review, deficit_guard, fuel
from backend.services.body_composition import (
    LEAN_MASS_FALL_WEEKS,
    ROLLING_WEEKS,
    compute_composition_trend,
    derive_lean_mass_kg,
)
from backend.services.cut_review import (
    DEFICIT_MODE_MANAGED,
    DEFICIT_MODE_STRUCTURAL,
    compute_cut_recommendation,
)
from backend.services.deficit_guard import evaluate

TODAY = datetime.date(2026, 7, 30)


# ═════════════════════════════════════════════════════════════════════════════
# Always-on floors (spec §4)
# ═════════════════════════════════════════════════════════════════════════════

_SETTINGS = {
    "base_kcal": 2400,
    "deficit_kcal": 400,
    "lean_mass_kg": 62.0,
    "ea_floor": 30.0,
    "weight_kg": 80.0,
    "protein_g_per_kg": 2.0,
    "fat_g": 70,
}


def test_budget_never_falls_below_the_ea_floor():
    budget = fuel.compute_budget(dict(_SETTINGS, deficit_kcal=750), burn=0.0)
    assert budget["budget"] >= budget["ea_floor_kcal"]


def test_budget_never_falls_below_estimated_bmr():
    """The EA floor guards fuelling; BMR guards staying alive. Whichever binds
    higher wins, and neither is the athlete's to override."""
    lean_only = dict(_SETTINGS, ea_floor=5.0, deficit_kcal=750)
    budget = fuel.compute_budget(lean_only, burn=0.0)
    assert budget["bmr_estimate_kcal"] is not None
    assert budget["budget"] >= budget["bmr_estimate_kcal"]


def test_the_higher_floor_is_reported_as_binding():
    tight = fuel.compute_budget(dict(_SETTINGS, ea_floor=5.0, deficit_kcal=750), burn=0.0)
    assert tight["floor_binding"] == "bmr"


def test_no_floor_reported_when_the_deficit_fits():
    relaxed = fuel.compute_budget(dict(_SETTINGS, deficit_kcal=100), burn=600.0)
    assert relaxed["deficit_reduced"] is False
    assert relaxed["floor_binding"] is None


@pytest.mark.parametrize("burn", [0.0, 300.0, 900.0])
def test_every_day_type_clears_both_floors(burn):
    """Spec §12: every generated day clears the EA floor and BMR."""
    budget = fuel.compute_budget(dict(_SETTINGS, deficit_kcal=500), burn=burn)
    assert budget["budget"] >= budget["ea_floor_kcal"]
    assert budget["budget"] >= budget["bmr_estimate_kcal"]


def test_deficit_above_the_hard_max_is_rejected_by_the_schema():
    """750 is the rejection bound; the check constraint is the enforcement."""
    assert fuel.DEFICIT_KCAL_MAX == 750
    from backend.models import FuelSettings

    constraint = next(
        c for c in FuelSettings.__table__.constraints
        if getattr(c, "name", "") == "ck_fuel_settings_deficit_kcal"
    )
    assert "750" in str(constraint.sqltext)


def test_recommended_max_is_below_the_hard_max():
    """500 is what a recommendation may propose; 750 is where the door slams."""
    assert fuel.DEFICIT_KCAL_RECOMMENDED_MAX == 500
    assert fuel.DEFICIT_KCAL_RECOMMENDED_MAX < fuel.DEFICIT_KCAL_MAX


def test_carb_floor_scales_with_bodyweight():
    assert fuel.carb_floor_g_quality_day(80.0) == 320
    assert fuel.carb_floor_g_quality_day(60.0) == 240


def test_carb_floor_is_independent_of_the_deficit():
    """It is a substrate floor, not an energy floor — the EA floor already
    guards total energy and still lets carbohydrate go too low."""
    import inspect

    source = inspect.getsource(fuel.carb_floor_g_quality_day)
    assert "deficit" not in source


@pytest.mark.parametrize("bad", [None, 0, -5, "heavy"])
def test_carb_floor_and_bmr_return_none_for_unusable_input(bad):
    assert fuel.carb_floor_g_quality_day(bad) is None
    assert fuel.bmr_estimate_kcal(bad) is None


def test_loss_rate_cap_matches_the_spec():
    assert fuel.MAX_LOSS_RATE_PCT_BW_PER_WEEK == 0.5
    assert fuel.TARGET_LOSS_RATE_PCT_BW_PER_WEEK == 0.35


# ═════════════════════════════════════════════════════════════════════════════
# Auto-pause triggers (spec §4, §12)
# ═════════════════════════════════════════════════════════════════════════════

def test_no_signals_means_no_pause():
    assert evaluate()["active"] is False


def test_injury_pauses():
    result = evaluate(has_open_injury_or_illness=True)
    assert result["active"] is True
    assert result["reason"] == "injury_or_illness"


def test_falling_ctl_pauses():
    result = evaluate(ctl_change_14d=-4.0)
    assert result["reason"] == "ctl_falling"


def test_ctl_noise_does_not_pause():
    assert evaluate(ctl_change_14d=-0.4)["active"] is False


def test_rising_ctl_does_not_pause():
    assert evaluate(ctl_change_14d=+3.0)["active"] is False


@pytest.mark.parametrize("field", ["endurance_declining_weeks", "speed_declining_weeks"])
def test_two_weeks_of_score_decline_pauses(field):
    assert evaluate(**{field: 2})["reason"] == "scores_declining"


@pytest.mark.parametrize("field", ["endurance_declining_weeks", "speed_declining_weeks"])
def test_one_week_of_score_decline_does_not_pause(field):
    assert evaluate(**{field: 1})["active"] is False


def test_rising_rhr_pauses():
    result = evaluate(rhr_recent=56.0, rhr_baseline=52.0)
    assert result["reason"] == "recovery_degrading"


def test_shorter_sleep_pauses():
    result = evaluate(sleep_recent_hours=6.0, sleep_baseline_hours=7.2)
    assert result["reason"] == "recovery_degrading"


def test_small_recovery_wobble_does_not_pause():
    assert evaluate(
        rhr_recent=53.0, rhr_baseline=52.0,
        sleep_recent_hours=7.0, sleep_baseline_hours=7.2,
    )["active"] is False


def test_three_weeks_of_lean_mass_decline_pauses():
    """Spec §12 — the body-fat scale's actual job."""
    assert evaluate(lean_mass_falling_weeks=LEAN_MASS_FALL_WEEKS)["reason"] == "lean_mass_falling"


def test_two_weeks_of_lean_mass_decline_does_not_pause():
    assert evaluate(lean_mass_falling_weeks=LEAN_MASS_FALL_WEEKS - 1)["active"] is False


def test_missing_inputs_never_pause():
    """An absent signal is not a bad signal. A guard that fired on missing data
    would pause the cut permanently for anyone without a sleep tracker."""
    assert evaluate(
        ctl_change_14d=None, rhr_recent=None, rhr_baseline=None,
        sleep_recent_hours=None, sleep_baseline_hours=None,
    )["active"] is False


def test_all_firing_reasons_are_reported():
    result = evaluate(has_open_injury_or_illness=True, lean_mass_falling_weeks=3)
    assert set(result["reasons"]) == {"injury_or_illness", "lean_mass_falling"}


def test_injury_outranks_other_reasons_in_the_summary():
    """A niggle must not be reported as a sleep problem."""
    result = evaluate(
        has_open_injury_or_illness=True,
        rhr_recent=60.0, rhr_baseline=52.0,
        lean_mass_falling_weeks=3,
    )
    assert result["reason"] == "injury_or_illness"


def test_an_active_pause_zeroes_the_deficit():
    """A warning next to an unchanged deficit is a warning that gets scrolled
    past. The deficit actually goes to zero."""
    assert evaluate(has_open_injury_or_illness=True)["effective_deficit_multiplier"] == 0.0
    assert evaluate()["effective_deficit_multiplier"] == 1.0


# ── Copy contract (spec §12) ─────────────────────────────────────────────────

@pytest.mark.parametrize("reason", sorted(deficit_guard.PAUSE_COPY))
def test_every_pause_message_says_eat_more(reason):
    assert "eat more" in deficit_guard.PAUSE_COPY[reason].lower()


@pytest.mark.parametrize("reason", sorted(deficit_guard.PAUSE_COPY))
@pytest.mark.parametrize("banned", ["try harder", "tighten up", "discipline", "willpower", "failed"])
def test_no_pause_message_blames_the_athlete(reason, banned):
    assert banned not in deficit_guard.PAUSE_COPY[reason].lower()


def test_the_copy_contract_is_enforced_at_import():
    with pytest.raises(ValueError, match="eat more"):
        deficit_guard.assert_eat_more_copy("Deficit paused — try harder tomorrow.")
    with pytest.raises(ValueError, match="try harder"):
        deficit_guard.assert_eat_more_copy("Eat more, and try harder.")


def test_every_trigger_has_copy():
    """A trigger without a message would pause the deficit silently."""
    triggers = {
        "injury_or_illness", "ctl_falling", "scores_declining",
        "recovery_degrading", "lean_mass_falling",
    }
    assert set(deficit_guard.PAUSE_COPY) == triggers


# ═════════════════════════════════════════════════════════════════════════════
# Body composition (spec §7, §12)
# ═════════════════════════════════════════════════════════════════════════════

def _reading(weeks_ago: int, weight: float, bf: float) -> dict:
    return {
        "date": TODAY - datetime.timedelta(weeks=weeks_ago),
        "weight_kg": weight,
        "body_fat_pct": bf,
    }


def test_lean_mass_is_derived_not_stored():
    assert derive_lean_mass_kg(80.0, 20.0) == 64.0
    assert derive_lean_mass_kg(80.0, None) is None
    assert derive_lean_mass_kg(None, 20.0) is None


@pytest.mark.parametrize("bf", [0, 100, -5, 120])
def test_impossible_body_fat_yields_no_lean_mass(bf):
    assert derive_lean_mass_kg(80.0, bf) is None


def test_trend_needs_four_readings_before_it_means_anything():
    """Bioimpedance is ±5 points; three readings cannot show a direction."""
    result = compute_composition_trend(
        [_reading(i, 80.0, 20.0) for i in range(3)], TODAY
    )
    assert result["readable"] is False
    assert str(ROLLING_WEEKS) in result["readable_note"]


def test_four_readings_are_readable():
    result = compute_composition_trend(
        [_reading(i, 80.0, 20.0) for i in range(4)], TODAY
    )
    assert result["readable"] is True
    assert result["lean_mass_kg_trend"] == pytest.approx(64.0, abs=0.05)


def test_falling_lean_mass_is_counted_in_weeks():
    readings = [
        _reading(3, 80.0, 18.0),
        _reading(2, 79.0, 18.5),
        _reading(1, 78.0, 19.0),
        _reading(0, 77.0, 19.5),
    ]
    result = compute_composition_trend(readings, TODAY)
    assert result["lean_mass_falling_weeks"] == 3


def test_a_wobble_does_not_count_as_falling():
    """The guard catches a sustained decline, not one bad reading."""
    readings = [
        _reading(3, 80.0, 18.0),
        _reading(2, 80.0, 18.0),
        _reading(1, 80.0, 18.05),
        _reading(0, 80.0, 18.0),
    ]
    assert compute_composition_trend(readings, TODAY)["lean_mass_falling_weeks"] == 0


def test_weigh_ins_without_a_scale_reading_are_ignored():
    readings = [
        {"date": TODAY, "weight_kg": 80.0, "body_fat_pct": None},
        _reading(1, 80.0, 20.0),
    ]
    assert compute_composition_trend(readings, TODAY)["readings_count"] == 1


def test_no_readings_is_not_an_error():
    result = compute_composition_trend([], TODAY)
    assert result["readable"] is False
    assert result["readings"] == []
    assert result["lean_mass_falling_weeks"] == 0


def test_composition_output_carries_no_target():
    """Spec §12/§13: trend series only. A body-composition target is out of
    scope by design — it is the framing that produces failed attempt six."""
    result = compute_composition_trend([_reading(i, 80.0, 20.0) for i in range(5)], TODAY)
    forbidden = {"target", "goal", "target_kg", "goal_line", "on_track", "target_body_fat_pct"}
    assert forbidden.isdisjoint(result.keys())


def test_four_week_delta_compares_blocks_not_single_readings():
    """One bad reading should move a block mean, not flip a verdict."""
    readings = [_reading(i, 80.0, 22.0) for i in range(5, 9)] + [
        _reading(i, 78.0, 20.0) for i in range(0, 4)
    ]
    result = compute_composition_trend(readings, TODAY)
    assert result["lean_mass_4wk_delta"] is not None


# ═════════════════════════════════════════════════════════════════════════════
# cut_review re-gate (spec §7, §12)
# ═════════════════════════════════════════════════════════════════════════════

_BEHIND = dict(
    weigh_in_count_14d=12,
    has_active_plan=True,
    actual_rate_kg_per_week=-0.05,
    plan_rate_kg_per_week=-0.35,
    weekly_pct_bw_rate=-0.06,
    ea_proxy=1.0,
    logging_adherence_pct=0.0,          # never logs food — the whole point
    avg_intake_vs_budget_kcal=0.0,
    consecutive_weeks_behind=1,
    pct_logged_days_at_or_under_budget=0.0,
    current_deficit_kcal=300,
)


def test_structural_mode_gives_a_real_recommendation_with_zero_food_logs():
    """Spec §12 — the acceptance criterion for the re-gate."""
    result = compute_cut_recommendation(**_BEHIND)
    assert result["recommendation"] not in ("insufficient_data", "check_logging")


def test_managed_mode_still_asks_for_food_logs():
    """The old behaviour is intact for anyone who does log."""
    result = compute_cut_recommendation(**_BEHIND, deficit_mode=DEFICIT_MODE_MANAGED)
    assert result["recommendation"] == "check_logging"


def test_structural_check_logging_keys_on_weigh_ins_not_food():
    """When the trend is too sparse, ask for the one input the program wants."""
    sparse = dict(_BEHIND, weigh_in_count_14d=5)
    result = compute_cut_recommendation(**sparse)
    assert result["recommendation"] == "check_logging"
    assert "scale" in result["action"].lower()
    assert "food" not in result["action"].lower()


def test_too_few_weigh_ins_is_still_insufficient_data():
    result = compute_cut_recommendation(**dict(_BEHIND, weigh_in_count_14d=2))
    assert result["recommendation"] == "insufficient_data"


def test_structural_recalibrate_needs_no_intake_evidence():
    """Three weeks of the same swaps and still behind IS the evidence that the
    maintenance estimate is wrong."""
    result = compute_cut_recommendation(**dict(_BEHIND, consecutive_weeks_behind=3))
    assert result["recommendation"] == "recalibrate_maintenance"


def test_structural_plateau_needs_no_budget_adherence():
    result = compute_cut_recommendation(
        **dict(_BEHIND, plateau_days=25, pct_at_or_under_budget_21d=0.0)
    )
    assert result["recommendation"] == "plateau"
    assert "within budget" not in result["action"]
    assert "swaps" in result["action"]


def test_managed_plateau_still_requires_adherence():
    result = compute_cut_recommendation(
        **dict(_BEHIND, plateau_days=25, pct_at_or_under_budget_21d=0.0),
        deficit_mode=DEFICIT_MODE_MANAGED,
    )
    assert result["recommendation"] != "plateau"


def test_structural_mode_is_the_default():
    """D1: the deficit is structural. Nobody should have to pass a flag."""
    import inspect

    sig = inspect.signature(compute_cut_recommendation)
    assert sig.parameters["deficit_mode"].default == DEFICIT_MODE_STRUCTURAL


def test_the_slow_down_guardrail_still_outranks_everything():
    """Losing too fast is the one finding that must survive the re-gate."""
    result = compute_cut_recommendation(**dict(_BEHIND, weekly_pct_bw_rate=-1.2, ea_proxy=0.2))
    assert result["recommendation"] == "slow_down"


def test_on_track_still_reads_from_the_trend():
    result = compute_cut_recommendation(**dict(_BEHIND, actual_rate_kg_per_week=-0.35))
    assert result["recommendation"] == "on_track"


def test_increase_is_clamped_at_the_hard_max():
    result = compute_cut_recommendation(
        **dict(_BEHIND, current_deficit_kcal=cut_review.DEFICIT_KCAL_MAX)
    )
    assert result["recommendation"] != "increase_deficit"
