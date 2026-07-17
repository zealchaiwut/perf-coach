"""Tests for issue #1503: Deterministic race-time projection to coach plan.

Tests the race_projection() function from backend.services.coach_projection
against all AC criteria:

- AC1: Module docstring names Riegel exponent (1.06), weight-pace adjustment
  (~1.5 s/km per kg), and CTL→pace improvement coefficients
- AC2: race_projection() returns dict with current_predicted_sec,
  plan_predicted_sec, band_sec, basis keys
- AC3: No qualifying efforts → returns {"unavailable": True, "reason": "..."},
  no numeric keys
- AC4: Riegel exponent 1.06 used; weight-adjusted to effort weight
- AC5: plan_predicted_sec simulates CTL ramp through plan to race week
- AC6: band_sec widens with sparse data
- AC7: Riegel HM prediction within ±30 s of hand-calculated value
- AC8: Same efforts at two weights → pace shifts by documented constant
- AC9: No efforts → unavailable with non-empty reason
- AC10: December race + ramp plan → plan_predicted_sec < current_predicted_sec
- AC11: Code passes linting/type-checking
"""

import math
import py_compile
import pathlib
from datetime import date, timedelta

import pytest

from backend.services.coach_projection import (
    race_projection,
    WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG,
    CTL_PACE_IMPROVEMENT_SLOPE,
    BAND_BASE_SEC,
    BAND_MIN_SEC,
)
from backend.services.riegel import RIEGEL_EXPONENT, HALF_MARATHON_KM

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── Fixtures ──────────────────────────────────────────────────────────────

def _effort_5k_20min():
    """5 km in 20:00 at 70 kg."""
    return {"time_seconds": 1200.0, "distance_km": 5.0, "weight_kg": 70.0}


def _effort_10k_42min():
    """10 km in 42:00 at 70 kg."""
    return {"time_seconds": 2520.0, "distance_km": 10.0, "weight_kg": 70.0}


# ── AC11: Syntax/linting ──────────────────────────────────────────────────────

def test_ac11_py_compile_coach_projection():
    """AC11: coach_projection.py has no syntax errors."""
    path = REPO_ROOT / "backend" / "services" / "coach_projection.py"
    py_compile.compile(str(path), doraise=True)


# ── AC1: Module docstring ─────────────────────────────────────────────────────

def test_ac1_docstring_names_riegel_exponent():
    """AC1: Module docstring names Riegel exponent (1.06)."""
    import backend.services.coach_projection as mod
    doc = mod.__doc__ or ""
    assert "1.06" in doc or "RIEGEL_EXPONENT" in doc, (
        "Module docstring must name the Riegel exponent (1.06)"
    )


def test_ac1_docstring_names_weight_pace_adjustment():
    """AC1: Module docstring names weight-pace adjustment (~1.5 s/km per kg)."""
    import backend.services.coach_projection as mod
    doc = mod.__doc__ or ""
    assert "1.5" in doc or "WEIGHT_PACE" in doc, (
        "Module docstring must name weight-pace adjustment constant"
    )


def test_ac1_docstring_names_ctl_pace_coefficients():
    """AC1: Module docstring names CTL→pace improvement coefficients."""
    import backend.services.coach_projection as mod
    doc = mod.__doc__ or ""
    lower = doc.lower()
    assert (
        "ctl" in lower and (
            "slope" in lower or "coefficient" in lower or "0.07" in lower
        )
    ), "Module docstring must describe CTL→pace improvement coefficients"


# ── AC2: Return dict shape ────────────────────────────────────────────────────

def test_ac2_return_dict_has_four_keys():
    """AC2: Successful result has all four required keys."""
    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
    )
    assert "unavailable" not in result, "Success should not include unavailable key"
    for key in (
        "current_predicted_sec",
        "plan_predicted_sec",
        "band_sec",
        "basis",
    ):
        assert key in result, f"Missing required key: {key}"


def test_ac2_current_predicted_sec_is_positive_int():
    """AC2: current_predicted_sec is a positive integer."""
    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
    )
    assert isinstance(result["current_predicted_sec"], int)
    assert result["current_predicted_sec"] > 0


def test_ac2_plan_predicted_sec_is_positive_int():
    """AC2: plan_predicted_sec is a positive integer."""
    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
    )
    assert isinstance(result["plan_predicted_sec"], int)
    assert result["plan_predicted_sec"] > 0


def test_ac2_band_sec_is_non_negative_int():
    """AC2: band_sec is a non-negative integer."""
    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
    )
    assert isinstance(result["band_sec"], int)
    assert result["band_sec"] >= 0


def test_ac2_basis_is_non_empty_string():
    """AC2: basis is a non-empty string."""
    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
    )
    assert isinstance(result["basis"], str)
    assert len(result["basis"]) > 0


# ── AC3 & AC9: No qualifying efforts → unavailable ─────────────────────────

def test_ac3_empty_efforts_returns_unavailable():
    """AC3/AC9: Empty efforts list → unavailable with reason."""
    result = race_projection([], race_distance_km=HALF_MARATHON_KM)
    assert result.get("unavailable") is True
    assert result.get("reason"), "reason must be non-empty string"
    assert isinstance(result["reason"], str)
    assert len(result["reason"]) > 0


def test_ac3_unavailable_lacks_numeric_keys():
    """AC3: unavailable result excludes numeric prediction keys."""
    result = race_projection([], race_distance_km=HALF_MARATHON_KM)
    assert "current_predicted_sec" not in result
    assert "plan_predicted_sec" not in result
    assert "band_sec" not in result


def test_ac3_malformed_efforts_return_unavailable():
    """AC3: Efforts with null/zero values are filtered out."""
    bad = [
        {"time_seconds": None, "distance_km": 5.0},
        {"time_seconds": 1200.0, "distance_km": 0},
        {"time_seconds": 0, "distance_km": 5.0},
        {},
    ]
    result = race_projection(bad, race_distance_km=HALF_MARATHON_KM)
    assert result.get("unavailable") is True
    assert result.get("reason")


# ── AC4 & AC7: Riegel formula accuracy ─────────────────────────────────────

def test_ac4_ac7_riegel_hm_prediction_within_30s():
    """AC7: 5 K in 20:00 → HM prediction within ±30 s of hand-calculated Riegel.

    Hand calculation:
    T_HM = 1200 * (21.0975 / 5.0) ** 1.06
         ≈ 1200 * 4.2195 ** 1.06
         ≈ 1200 * 4.408
         ≈ 5289.6 s (88:09.6)

    Allow ±30 s tolerance.
    """
    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
    )
    current = result["current_predicted_sec"]

    hand_calc = 1200 * math.pow(HALF_MARATHON_KM / 5.0, RIEGEL_EXPONENT)
    error = abs(current - hand_calc)

    assert error <= 30, (
        f"Riegel prediction {current}s differs from hand-calc {hand_calc:.1f}s "
        f"by {error:.1f}s (tolerance ±30s)"
    )


def test_ac4_weight_adjustment_applied():
    """AC4: Riegel calculation adjusted for current vs effort weight.

    Heavier now than at effort → slower predicted time.
    """
    result_same = race_projection(
        [_effort_5k_20min()],  # 70 kg effort
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=70.0,  # same weight
    )

    result_heavier = race_projection(
        [_effort_5k_20min()],  # 70 kg effort
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=75.0,  # 5 kg heavier now
    )

    assert result_heavier["current_predicted_sec"] > result_same["current_predicted_sec"], (
        "Heavier current weight should predict slower time"
    )


# ── AC8: Weight-adjustment model constant ──────────────────────────────────

def test_ac8_weight_adjustment_constant():
    """AC8: Pace shifts by ~1.5 s/km per kg body-mass difference.

    Compare same effort at two different current weights.
    Expected shift: 5 kg * 1.5 s/km/kg * 21.1 km ≈ 158 s.
    """
    result_70kg = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=70.0,
    )

    result_75kg = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=75.0,
    )

    diff = result_75kg["current_predicted_sec"] - result_70kg["current_predicted_sec"]
    expected = 5.0 * WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG * HALF_MARATHON_KM

    assert abs(diff - expected) < 10, (
        f"Weight shift 5 kg should produce ~{expected:.0f} s change, got {diff:.0f} s"
    )


# ── AC6: Band widens with sparse data ──────────────────────────────────────

def test_ac6_band_widens_with_sparse_data():
    """AC6: Confidence band wider for fewer qualifying efforts."""
    result_one = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
    )

    result_multi = race_projection(
        [_effort_5k_20min(), _effort_10k_42min()],
        race_distance_km=HALF_MARATHON_KM,
    )

    assert result_one["band_sec"] > result_multi["band_sec"], (
        "Band should be wider with fewer efforts"
    )


def test_ac6_band_scaled_by_distance():
    """AC6: Confidence band scales with race distance."""
    result_5k = race_projection(
        [_effort_5k_20min()],
        race_distance_km=5.0,
    )

    result_hm = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
    )

    ratio = result_hm["band_sec"] / result_5k["band_sec"]
    distance_ratio = HALF_MARATHON_KM / 5.0

    assert abs(ratio - distance_ratio) < 0.2, (
        f"Band scaling ({ratio:.2f}x) should match distance ratio ({distance_ratio:.2f}x)"
    )


def test_ac6_band_respects_minimum():
    """AC6: Confidence band has a floor (BAND_MIN_SEC)."""
    result = race_projection(
        [e for e in [_effort_5k_20min()] * 100],  # many efforts
        race_distance_km=5.0,  # short distance
    )

    assert result["band_sec"] >= BAND_MIN_SEC, (
        f"Band {result['band_sec']}s should not go below minimum {BAND_MIN_SEC}s"
    )


# ── AC5 & AC10: Plan simulation with CTL ramp ──────────────────────────────

def test_ac5_plan_simulation_with_phases():
    """AC5: plan_predicted_sec simulates CTL ramp to race week.

    December race with ramp plan should show improvement.
    """
    today = date(2026, 8, 1)
    race_date = date(2026, 12, 15)

    phases = [
        {
            "name": "hold",
            "start_date": date(2026, 8, 1),
            "end_date": date(2026, 8, 31),
        },
        {
            "name": "ramp",
            "start_date": date(2026, 9, 1),
            "end_date": date(2026, 11, 15),
        },
        {
            "name": "peak block",
            "start_date": date(2026, 11, 16),
            "end_date": date(2026, 12, 1),
        },
        {
            "name": "taper",
            "start_date": date(2026, 12, 2),
            "end_date": race_date,
        },
    ]

    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=70.0,
        plan_phases=phases,
        current_ctl=50.0,
        current_atl=30.0,
        race_date=race_date,
        target_weight_kg=68.0,
        _today=today,
    )

    assert result["plan_predicted_sec"] < result["current_predicted_sec"], (
        "Plan prediction should be faster (lower time) than current"
    )
    assert result["plan_predicted_sec"] > 0
    assert isinstance(result["plan_predicted_sec"], int)


def test_ac10_december_race_shows_improvement():
    """AC10: December goal + ramp plan → plan_predicted_sec < current_predicted_sec."""
    today = date(2026, 8, 1)
    race_date = date(2026, 12, 15)

    phases = [
        {
            "name": "hold",
            "start_date": date(2026, 8, 1),
            "end_date": date(2026, 8, 31),
        },
        {
            "name": "ramp",
            "start_date": date(2026, 9, 1),
            "end_date": date(2026, 11, 15),
        },
        {
            "name": "peak block",
            "start_date": date(2026, 11, 16),
            "end_date": date(2026, 12, 1),
        },
        {
            "name": "taper",
            "start_date": date(2026, 12, 2),
            "end_date": race_date,
        },
    ]

    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=72.0,
        plan_phases=phases,
        current_ctl=50.0,
        current_atl=30.0,
        race_date=race_date,
        target_weight_kg=68.0,
        _today=today,
    )

    assert result["plan_predicted_sec"] < result["current_predicted_sec"], (
        "December goal with ramp and weight loss should show improvement"
    )


def test_plan_prediction_without_phases_equals_current():
    """When no plan phases provided, plan_predicted_sec == current_predicted_sec."""
    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=70.0,
    )

    assert result["plan_predicted_sec"] == result["current_predicted_sec"], (
        "Without plan phases, plan prediction should equal current prediction"
    )


# ── Multiple efforts and best-of logic ─────────────────────────────────────

def test_multiple_efforts_uses_best_prediction():
    """race_projection uses the best (minimum) time prediction across efforts."""
    poor_5k = {"time_seconds": 1500.0, "distance_km": 5.0, "weight_kg": 70.0}
    good_10k = {"time_seconds": 2100.0, "distance_km": 10.0, "weight_kg": 70.0}

    result = race_projection(
        [poor_5k, good_10k],
        race_distance_km=HALF_MARATHON_KM,
    )

    riegel_poor = 1500.0 * math.pow(HALF_MARATHON_KM / 5.0, RIEGEL_EXPONENT)
    riegel_good = 2100.0 * math.pow(HALF_MARATHON_KM / 10.0, RIEGEL_EXPONENT)
    expected_best = min(riegel_poor, riegel_good)

    assert abs(result["current_predicted_sec"] - round(expected_best)) < 2, (
        "Should use best (lowest) prediction"
    )


# ── Basis string generation ────────────────────────────────────────────────

def test_basis_string_includes_effort_count():
    """basis string includes number of efforts used."""
    result = race_projection(
        [_effort_5k_20min(), _effort_10k_42min()],
        race_distance_km=HALF_MARATHON_KM,
    )

    assert "2 efforts" in result["basis"], (
        "basis should mention the effort count"
    )


def test_basis_string_includes_distance_range():
    """basis string includes distance range of efforts."""
    result = race_projection(
        [_effort_5k_20min(), _effort_10k_42min()],
        race_distance_km=HALF_MARATHON_KM,
    )

    assert "5.0" in result["basis"] and "10.0" in result["basis"], (
        "basis should include distance range"
    )


def test_basis_string_with_weight():
    """basis includes current weight if provided."""
    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=70.5,
    )

    assert "70.5" in result["basis"] or "weight" in result["basis"], (
        "basis should mention current weight"
    )


def test_basis_string_with_plan():
    """basis includes CTL progression if plan is provided."""
    today = date(2026, 8, 1)
    race_date = date(2026, 12, 15)
    phases = [
        {
            "name": "hold",
            "start_date": today,
            "end_date": date(2026, 8, 31),
        },
        {
            "name": "ramp",
            "start_date": date(2026, 9, 1),
            "end_date": race_date,
        },
    ]

    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=70.0,
        plan_phases=phases,
        current_ctl=50.0,
        current_atl=30.0,
        race_date=race_date,
        target_weight_kg=68.0,
        _today=today,
    )

    assert "ctl" in result["basis"].lower() or "plan" in result["basis"].lower(), (
        "basis should reference plan if provided"
    )


# ── Edge cases ─────────────────────────────────────────────────────────────

def test_effort_without_weight_field():
    """Efforts without weight_kg are still used; just not weight-adjusted."""
    effort_no_weight = {"time_seconds": 1200.0, "distance_km": 5.0}

    result = race_projection(
        [effort_no_weight],
        race_distance_km=HALF_MARATHON_KM,
        current_weight_kg=70.0,
    )

    assert "current_predicted_sec" in result
    assert result["current_predicted_sec"] > 0


def test_past_race_date_skips_plan():
    """If race_date <= today, plan prediction is skipped."""
    today = date(2026, 8, 1)
    past_race = date(2026, 7, 31)

    phases = [
        {
            "name": "hold",
            "start_date": date(2026, 7, 1),
            "end_date": today,
        },
    ]

    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=HALF_MARATHON_KM,
        plan_phases=phases,
        current_ctl=50.0,
        current_atl=30.0,
        race_date=past_race,
        _today=today,
    )

    assert result["plan_predicted_sec"] == result["current_predicted_sec"], (
        "Past race date should skip plan simulation"
    )


def test_very_long_distance_scales_correctly():
    """Band and predictions scale appropriately for ultra-distances."""
    ultramarathon = 50.0  # 50 km

    result = race_projection(
        [_effort_5k_20min()],
        race_distance_km=ultramarathon,
    )

    assert result["current_predicted_sec"] > 0
    assert result["band_sec"] > 0

    riegel = 1200 * math.pow(ultramarathon / 5.0, RIEGEL_EXPONENT)
    assert abs(result["current_predicted_sec"] - round(riegel)) < 50, (
        "Riegel should scale correctly for long distances"
    )
