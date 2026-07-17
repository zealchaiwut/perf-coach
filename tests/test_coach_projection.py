"""Tests for issue #1503: Deterministic race-time projection in coach_projection.py.

AC coverage:
- AC1: Module docstring names all model constants (Riegel exp, weight adj, CTL→pace)
- AC2: race_projection() returns dict with current_predicted_sec, plan_predicted_sec, band_sec, basis
- AC3: No qualifying efforts → {"unavailable": True, "reason": <str>}, no numeric keys
- AC4: Riegel exponent 1.06 used; weight-adjusted vs effort weight
- AC5: plan_predicted_sec simulates CTL ramp to race week
- AC6: band_sec widens when data is sparse (fewer qualifying efforts)
- AC7: Known-effort fixture → HM prediction within ±30 s of hand-calculated Riegel value
- AC8: Same efforts at two weights → pace shifts by WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG constant
- AC9: No-efforts fixture → unavailable with non-empty reason
- AC10: December race + ramp plan → plan_predicted_sec < current_predicted_sec
- AC11: py_compile passes on coach_projection.py
"""

import math
import py_compile
import pathlib
from datetime import date


from backend.services.coach_projection import (
    race_projection,
    WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG,
)
from backend.services.riegel import RIEGEL_EXPONENT, HALF_MARATHON_KM

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_EFFORT_5K_20MIN = {"time_seconds": 1200.0, "distance_km": 5.0, "weight_kg": 70.0}
_RACE_DIST = HALF_MARATHON_KM  # 21.0975 km


# ── AC11: py_compile ──────────────────────────────────────────────────────────

def test_py_compile_coach_projection():
    """AC11: coach_projection.py must have no syntax errors."""
    path = REPO_ROOT / "backend" / "services" / "coach_projection.py"
    py_compile.compile(str(path), doraise=True)


# ── AC1: Module docstring mentions all model constants ────────────────────────

def test_module_docstring_names_riegel_exponent():
    """AC1: Module docstring must name the Riegel exponent value (1.06)."""
    import backend.services.coach_projection as mod
    docstring = mod.__doc__ or ""
    assert "1.06" in docstring or "RIEGEL_EXPONENT" in docstring, (
        "Module docstring must mention the Riegel exponent (1.06)"
    )


def test_module_docstring_names_weight_adjustment():
    """AC1: Module docstring must name the weight-pace adjustment (~1.5 s/km per kg)."""
    import backend.services.coach_projection as mod
    docstring = mod.__doc__ or ""
    assert "1.5" in docstring or "WEIGHT_PACE" in docstring, (
        "Module docstring must mention the weight-pace adjustment constant"
    )


def test_module_docstring_names_ctl_pace_coefficients():
    """AC1: Module docstring must name the CTL→pace improvement mapping coefficients."""
    import backend.services.coach_projection as mod
    docstring = mod.__doc__ or ""
    lower = docstring.lower()
    assert "ctl" in lower and (
        "slope" in lower or "coefficient" in lower or "0.07" in lower
    ), "Module docstring must describe CTL→pace improvement coefficients"


# ── AC2: Return shape ─────────────────────────────────────────────────────────

def test_return_shape_all_four_keys():
    """AC2: Successful result must include all four keys."""
    result = race_projection(
        [_EFFORT_5K_20MIN],
        race_distance_km=_RACE_DIST,
    )
    assert "unavailable" not in result
    for key in ("current_predicted_sec", "plan_predicted_sec", "band_sec", "basis"):
        assert key in result, f"Missing key: {key}"


def test_current_predicted_sec_is_positive_int():
    """AC2: current_predicted_sec is a positive integer."""
    result = race_projection([_EFFORT_5K_20MIN], race_distance_km=_RACE_DIST)
    assert isinstance(result["current_predicted_sec"], int)
    assert result["current_predicted_sec"] > 0


def test_plan_predicted_sec_is_positive_int():
    """AC2: plan_predicted_sec is a positive integer."""
    result = race_projection([_EFFORT_5K_20MIN], race_distance_km=_RACE_DIST)
    assert isinstance(result["plan_predicted_sec"], int)
    assert result["plan_predicted_sec"] > 0


def test_band_sec_is_non_negative_int():
    """AC2: band_sec is a non-negative integer."""
    result = race_projection([_EFFORT_5K_20MIN], race_distance_km=_RACE_DIST)
    assert isinstance(result["band_sec"], int)
    assert result["band_sec"] >= 0


def test_basis_is_non_empty_string():
    """AC2: basis is a non-empty string."""
    result = race_projection([_EFFORT_5K_20MIN], race_distance_km=_RACE_DIST)
    assert isinstance(result["basis"], str)
    assert len(result["basis"]) > 0


# ── AC3 / AC9: No qualifying efforts → unavailable ───────────────────────────

def test_empty_efforts_returns_unavailable():
    """AC3/AC9: Empty efforts list → unavailable with non-empty reason."""
    result = race_projection([], race_distance_km=_RACE_DIST)
    assert result.get("unavailable") is True, "Should set unavailable=True"
    assert result.get("reason"), "reason must be a non-empty string"


def test_no_efforts_excludes_numeric_keys():
    """AC3: unavailable result must not contain numeric prediction keys."""
    result = race_projection([], race_distance_km=_RACE_DIST)
    assert "current_predicted_sec" not in result
    assert "plan_predicted_sec" not in result
    assert "band_sec" not in result


def test_invalid_efforts_also_return_unavailable():
    """AC3: Efforts with null/zero values are not qualifying → unavailable."""
    bad_efforts = [
        {"time_seconds": None, "distance_km": 5.0},
        {"time_seconds": 1200.0, "distance_km": 0},
        {},
    ]
    result = race_projection(bad_efforts, race_distance_km=_RACE_DIST)
    assert result.get("unavailable") is True
    assert result.get("reason")
    assert "current_predicted_sec" not in result


# ── AC4 / AC7: Riegel formula accuracy ───────────────────────────────────────

def test_riegel_hm_prediction_within_30s_of_hand_calc():
    """AC7: 5 K in 20:00 → HM prediction within ±30 s of hand-calculated Riegel."""
    hand_calc = 1200.0 * math.pow(_RACE_DIST / 5.0, RIEGEL_EXPONENT)
    result = race_projection(
        [{"time_seconds": 1200.0, "distance_km": 5.0, "weight_kg": 70.0}],
        race_distance_km=_RACE_DIST,
        current_weight_kg=70.0,  # same as effort → no weight adjustment
    )
    assert "unavailable" not in result
    assert abs(result["current_predicted_sec"] - round(hand_calc)) <= 30, (
        f"Expected ≈{round(hand_calc)} s, got {result['current_predicted_sec']} s"
    )


def test_riegel_10k_effort_within_30s():
    """AC7: 10 K in 42:00 → HM prediction within ±30 s of Riegel formula."""
    t1, d1 = 2520.0, 10.0
    hand_calc = t1 * math.pow(_RACE_DIST / d1, RIEGEL_EXPONENT)
    result = race_projection(
        [{"time_seconds": t1, "distance_km": d1, "weight_kg": 70.0}],
        race_distance_km=_RACE_DIST,
        current_weight_kg=70.0,
    )
    assert abs(result["current_predicted_sec"] - round(hand_calc)) <= 30


def test_no_weight_adjustment_when_weight_missing():
    """AC4: If effort has no weight_kg, result equals plain Riegel (no adjustment)."""
    effort_no_weight = {"time_seconds": 1200.0, "distance_km": 5.0}  # no weight_kg
    hand_calc = 1200.0 * math.pow(_RACE_DIST / 5.0, RIEGEL_EXPONENT)
    result = race_projection(
        [effort_no_weight],
        race_distance_km=_RACE_DIST,
        current_weight_kg=75.0,
    )
    assert abs(result["current_predicted_sec"] - round(hand_calc)) <= 1


# ── AC4 / AC8: Weight adjustment ─────────────────────────────────────────────

def test_weight_adjustment_shifts_time_by_documented_constant():
    """AC8: +5 kg current weight → time increases by 5 × 1.5 s/km × distance."""
    effort = {"time_seconds": 1200.0, "distance_km": 5.0, "weight_kg": 70.0}

    r_base = race_projection(
        [effort],
        race_distance_km=_RACE_DIST,
        current_weight_kg=70.0,
    )
    r_heavy = race_projection(
        [effort],
        race_distance_km=_RACE_DIST,
        current_weight_kg=75.0,
    )

    delta_actual = r_heavy["current_predicted_sec"] - r_base["current_predicted_sec"]
    delta_expected = 5.0 * WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG * _RACE_DIST
    assert abs(delta_actual - delta_expected) <= 1, (
        f"Expected Δ≈{delta_expected:.0f} s, got {delta_actual} s"
    )


def test_lighter_current_weight_gives_faster_prediction():
    """AC4: If athlete is lighter now than at effort time, prediction is faster."""
    effort = {"time_seconds": 1200.0, "distance_km": 5.0, "weight_kg": 75.0}

    r_heavy = race_projection(
        [effort],
        race_distance_km=_RACE_DIST,
        current_weight_kg=75.0,
    )
    r_light = race_projection(
        [effort],
        race_distance_km=_RACE_DIST,
        current_weight_kg=70.0,
    )
    assert r_light["current_predicted_sec"] < r_heavy["current_predicted_sec"]


# ── AC6: Band widens with sparse data ────────────────────────────────────────

def test_band_wider_with_one_effort_than_five():
    """AC6: band_sec is larger for 1 effort than for 5 efforts (same effort repeated)."""
    effort = {"time_seconds": 1200.0, "distance_km": 5.0}
    r1 = race_projection([effort], race_distance_km=_RACE_DIST)
    r5 = race_projection([effort] * 5, race_distance_km=_RACE_DIST)
    assert r1["band_sec"] > r5["band_sec"], (
        f"Single-effort band {r1['band_sec']}s should be wider than "
        f"five-effort band {r5['band_sec']}s"
    )


def test_band_decreases_monotonically_with_more_efforts():
    """AC6: band_sec decreases (or stays equal) as more efforts are provided."""
    effort = {"time_seconds": 1200.0, "distance_km": 5.0}
    prev = None
    for n in (1, 3, 9):
        r = race_projection([effort] * n, race_distance_km=_RACE_DIST)
        if prev is not None:
            assert r["band_sec"] <= prev, (
                f"band_sec should not increase with {n} efforts vs fewer"
            )
        prev = r["band_sec"]


# ── AC5 / AC10: Plan prediction (integration) ────────────────────────────────

_TODAY = date(2026, 7, 17)
_RACE_DATE = date(2026, 12, 12)

_PLAN_PHASES = [
    {"name": "hold",        "start_date": _TODAY,                 "end_date": date(2026, 7, 23)},
    {"name": "ramp",        "start_date": date(2026, 7, 24),      "end_date": date(2026, 10, 9)},
    {"name": "peak block",  "start_date": date(2026, 10, 10),     "end_date": date(2026, 11, 6)},
    {"name": "taper",       "start_date": date(2026, 11, 7),      "end_date": _RACE_DATE},
]


def test_plan_predicted_less_than_current_for_december_race():
    """AC10: December goal + ramp plan → plan_predicted_sec < current_predicted_sec."""
    result = race_projection(
        [_EFFORT_5K_20MIN],
        race_distance_km=_RACE_DIST,
        current_weight_kg=75.0,
        current_ctl=60.0,
        current_atl=70.0,
        plan_phases=_PLAN_PHASES,
        race_date=_RACE_DATE,
        target_weight_kg=70.0,
        _today=_TODAY,
    )
    assert "unavailable" not in result
    assert result["plan_predicted_sec"] < result["current_predicted_sec"], (
        f"plan_predicted_sec ({result['plan_predicted_sec']}) should be less than "
        f"current_predicted_sec ({result['current_predicted_sec']})"
    )


def test_plan_predicted_equals_current_when_no_phases():
    """AC5: Without plan_phases, plan_predicted_sec equals current_predicted_sec."""
    result = race_projection(
        [_EFFORT_5K_20MIN],
        race_distance_km=_RACE_DIST,
        current_weight_kg=70.0,
        _today=_TODAY,
    )
    assert result["plan_predicted_sec"] == result["current_predicted_sec"]


def test_plan_predicted_less_than_current_with_ctl_gain_only():
    """AC5: CTL improvement alone (no weight change) → plan is faster than current."""
    result = race_projection(
        [_EFFORT_5K_20MIN],
        race_distance_km=_RACE_DIST,
        current_weight_kg=70.0,
        current_ctl=60.0,
        current_atl=70.0,
        plan_phases=_PLAN_PHASES,
        race_date=_RACE_DATE,
        target_weight_kg=70.0,  # same weight → no weight contribution
        _today=_TODAY,
    )
    assert "unavailable" not in result
    assert result["plan_predicted_sec"] < result["current_predicted_sec"]


# ── AC2: basis mentions inputs used ──────────────────────────────────────────

def test_basis_mentions_efforts_and_riegel():
    """AC2: basis string should reference the effort count and Riegel method."""
    result = race_projection(
        [_EFFORT_5K_20MIN],
        race_distance_km=_RACE_DIST,
        current_weight_kg=70.0,
    )
    basis = result["basis"].lower()
    assert "riegel" in basis or "effort" in basis, (
        f"basis should mention Riegel or effort count: {result['basis']!r}"
    )


def test_basis_includes_ctl_when_plan_simulated():
    """AC2: basis string should include CTL info when plan simulation ran."""
    result = race_projection(
        [_EFFORT_5K_20MIN],
        race_distance_km=_RACE_DIST,
        current_weight_kg=75.0,
        current_ctl=60.0,
        current_atl=70.0,
        plan_phases=_PLAN_PHASES,
        race_date=_RACE_DATE,
        target_weight_kg=70.0,
        _today=_TODAY,
    )
    basis = result["basis"].lower()
    assert "ctl" in basis, f"basis should mention CTL when plan simulated: {result['basis']!r}"
