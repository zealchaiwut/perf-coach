"""UAT Tests for issue #1503: Deterministic race-time projection module.

This file exercises the coach_projection.race_projection() function
via direct imports, verifying the AC criteria map to functional behavior
that can be verified without API endpoints.

Test mapping:
- AC1: Module docstring — checked in test_coach_projection.py
- AC2-4: Riegel formula + weight adjustment — test_return_dict_shape, test_weight_adjustment
- AC5-6: Plan prediction + band — test_plan_simulation_with_phases, test_band_behavior
- AC7-11: Acceptance criteria tests
"""

import math
from datetime import date


from backend.services.coach_projection import (
    race_projection,
    WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG,
)
from backend.services.riegel import RIEGEL_EXPONENT, HALF_MARATHON_KM


# ── Test fixtures ─────────────────────────────────────────────────────

def _effort_5k_20min():
    """A known 5 km effort in 20:00, recorded at 70 kg."""
    return {"time_seconds": 1200.0, "distance_km": 5.0, "weight_kg": 70.0}


def _effort_10k_42min():
    """A known 10 km effort in 42:00."""
    return {"time_seconds": 2520.0, "distance_km": 10.0, "weight_kg": 70.0}


# ── AC2: Return dict with all four keys ────────────────────────────────

class TestReturnShape:
    """Verify the return dict structure for AC2."""

    def test_success_has_four_keys(self):
        """AC2: successful result includes current_predicted_sec, plan_predicted_sec, band_sec, basis."""
        result = race_projection(
            [_effort_5k_20min()],
            race_distance_km=HALF_MARATHON_KM,
        )
        assert "unavailable" not in result
        for key in ("current_predicted_sec", "plan_predicted_sec", "band_sec", "basis"):
            assert key in result, f"Missing required key: {key}"

    def test_success_has_correct_types(self):
        """AC2: returned values are properly typed."""
        result = race_projection(
            [_effort_5k_20min()],
            race_distance_km=HALF_MARATHON_KM,
        )
        assert isinstance(result["current_predicted_sec"], int)
        assert isinstance(result["plan_predicted_sec"], int)
        assert isinstance(result["band_sec"], int)
        assert isinstance(result["basis"], str)
        assert result["current_predicted_sec"] > 0
        assert result["plan_predicted_sec"] > 0
        assert result["band_sec"] >= 0
        assert len(result["basis"]) > 0


# ── AC3: No efforts → unavailable ────────────────────────────────────

class TestUnavailableWhenNoEfforts:
    """Verify AC3 behavior when no qualifying efforts exist."""

    def test_empty_list_returns_unavailable(self):
        """AC3: empty efforts list → unavailable=True, reason non-empty."""
        result = race_projection([], race_distance_km=HALF_MARATHON_KM)
        assert result.get("unavailable") is True
        assert result.get("reason")
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0

    def test_unavailable_lacks_numeric_keys(self):
        """AC3: unavailable response does not contain numeric prediction keys."""
        result = race_projection([], race_distance_km=HALF_MARATHON_KM)
        assert "current_predicted_sec" not in result
        assert "plan_predicted_sec" not in result
        assert "band_sec" not in result

    def test_invalid_efforts_also_unavailable(self):
        """AC3: malformed efforts (zero/null values) → unavailable."""
        bad = [
            {"time_seconds": None, "distance_km": 5.0},
            {"time_seconds": 1200.0, "distance_km": 0},
        ]
        result = race_projection(bad, race_distance_km=HALF_MARATHON_KM)
        assert result.get("unavailable") is True


# ── AC4 & AC7: Riegel formula accuracy ────────────────────────────────

class TestRiegelAccuracy:
    """Verify AC4 (Riegel with exponent 1.06) and AC7 (within ±30 s)."""

    def test_riegel_5k_hm_within_30s(self):
        """AC7: 5 K in 20:00 → HM prediction matches hand-calculated Riegel ±30 s."""
        hand_calc = 1200.0 * math.pow(HALF_MARATHON_KM / 5.0, RIEGEL_EXPONENT)
        result = race_projection(
            [_effort_5k_20min()],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=70.0,  # same as effort → no adjustment
        )
        assert abs(result["current_predicted_sec"] - round(hand_calc)) <= 30, (
            f"Expected ≈{round(hand_calc)} s, got {result['current_predicted_sec']} s"
        )

    def test_riegel_10k_hm_within_30s(self):
        """AC7: 10 K in 42:00 → HM prediction within ±30 s."""
        hand_calc = 2520.0 * math.pow(HALF_MARATHON_KM / 10.0, RIEGEL_EXPONENT)
        result = race_projection(
            [_effort_10k_42min()],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=70.0,
        )
        assert abs(result["current_predicted_sec"] - round(hand_calc)) <= 30

    def test_riegel_exponent_is_1_06(self):
        """AC4: Riegel exponent must be 1.06 (not 1.0 or other value)."""
        assert RIEGEL_EXPONENT == 1.06, f"Expected exponent 1.06, got {RIEGEL_EXPONENT}"


# ── AC4 & AC8: Weight adjustment ──────────────────────────────────────

class TestWeightAdjustment:
    """Verify AC4 (weight-adjusted Riegel) and AC8 (constant shift)."""

    def test_weight_adjustment_shifts_by_documented_constant(self):
        """AC8: weight change of 5 kg → time change of 5 × 1.5 s/km × distance."""
        effort = _effort_5k_20min()

        r_baseline = race_projection(
            [effort],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=70.0,
        )
        r_heavier = race_projection(
            [effort],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=75.0,
        )

        delta = r_heavier["current_predicted_sec"] - r_baseline["current_predicted_sec"]
        expected_delta = 5.0 * WEIGHT_PACE_ADJ_SEC_PER_KM_PER_KG * HALF_MARATHON_KM

        assert abs(delta - expected_delta) <= 1, (
            f"Expected Δ≈{expected_delta:.0f} s, got {delta} s"
        )

    def test_lighter_athlete_is_faster(self):
        """AC4: lighter athlete (same effort) → faster predicted time."""
        effort = {"time_seconds": 1200.0, "distance_km": 5.0, "weight_kg": 75.0}

        r_heavy = race_projection(
            [effort],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=75.0,
        )
        r_light = race_projection(
            [effort],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=70.0,
        )

        assert r_light["current_predicted_sec"] < r_heavy["current_predicted_sec"]


# ── AC6: Confidence band widens with sparse data ───────────────────────

class TestConfidenceBand:
    """Verify AC6: band_sec widens when data is sparse."""

    def test_band_wider_for_sparse_data(self):
        """AC6: 1 effort → wider band than 5 efforts."""
        effort = _effort_5k_20min()
        r1 = race_projection([effort], race_distance_km=HALF_MARATHON_KM)
        r5 = race_projection([effort] * 5, race_distance_km=HALF_MARATHON_KM)
        assert r1["band_sec"] > r5["band_sec"], (
            f"Single-effort band ({r1['band_sec']}s) should exceed "
            f"five-effort band ({r5['band_sec']}s)"
        )

    def test_band_monotonic_with_more_efforts(self):
        """AC6: band_sec is monotonically non-increasing with more efforts."""
        effort = _effort_5k_20min()
        bands = []
        for n_efforts in [1, 3, 5, 10]:
            r = race_projection([effort] * n_efforts, race_distance_km=HALF_MARATHON_KM)
            bands.append((n_efforts, r["band_sec"]))

        for i in range(1, len(bands)):
            assert bands[i][1] <= bands[i - 1][1], (
                f"band_sec should decrease: {bands[i-1]} → {bands[i]}"
            )


# ── AC5 & AC10: Plan prediction with CTL simulation ────────────────────

class TestPlanPrediction:
    """Verify AC5 (plan simulation) and AC10 (plan < current for ramp)."""

    _TODAY = date(2026, 7, 17)
    _RACE_DATE = date(2026, 12, 12)
    _PLAN_PHASES = [
        {"name": "hold", "start_date": _TODAY, "end_date": date(2026, 7, 23)},
        {"name": "ramp", "start_date": date(2026, 7, 24), "end_date": date(2026, 10, 9)},
        {"name": "peak block", "start_date": date(2026, 10, 10), "end_date": date(2026, 11, 6)},
        {"name": "taper", "start_date": date(2026, 11, 7), "end_date": _RACE_DATE},
    ]

    def test_plan_less_than_current_with_december_goal(self):
        """AC10: December goal + ramp plan → plan_predicted_sec < current_predicted_sec."""
        result = race_projection(
            [_effort_5k_20min()],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=75.0,
            current_ctl=60.0,
            current_atl=70.0,
            plan_phases=self._PLAN_PHASES,
            race_date=self._RACE_DATE,
            target_weight_kg=70.0,
            _today=self._TODAY,
        )
        assert "unavailable" not in result
        assert result["plan_predicted_sec"] < result["current_predicted_sec"], (
            f"Plan ({result['plan_predicted_sec']}s) should be faster than "
            f"current ({result['current_predicted_sec']}s)"
        )

    def test_plan_equals_current_without_phases(self):
        """AC5: without plan_phases, plan_predicted_sec equals current_predicted_sec."""
        result = race_projection(
            [_effort_5k_20min()],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=70.0,
            _today=self._TODAY,
        )
        assert result["plan_predicted_sec"] == result["current_predicted_sec"]

    def test_plan_faster_with_ctl_gain_alone(self):
        """AC5: CTL improvement alone (no weight change) → plan is faster."""
        result = race_projection(
            [_effort_5k_20min()],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=70.0,
            current_ctl=60.0,
            current_atl=70.0,
            plan_phases=self._PLAN_PHASES,
            race_date=self._RACE_DATE,
            target_weight_kg=70.0,  # no weight change
            _today=self._TODAY,
        )
        assert "unavailable" not in result
        assert result["plan_predicted_sec"] < result["current_predicted_sec"]


# ── AC2: basis mentions inputs ────────────────────────────────────────

class TestBasisString:
    """Verify AC2: basis string documents inputs used."""

    def test_basis_mentions_riegel_or_efforts(self):
        """AC2: basis should reference Riegel method or effort count."""
        result = race_projection(
            [_effort_5k_20min()],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=70.0,
        )
        basis_lower = result["basis"].lower()
        assert "riegel" in basis_lower or "effort" in basis_lower, (
            f"basis should mention Riegel or effort: {result['basis']!r}"
        )

    def test_basis_includes_ctl_when_plan_simulated(self):
        """AC2: basis mentions CTL when plan simulation runs."""
        _TODAY = date(2026, 7, 17)
        _RACE_DATE = date(2026, 12, 12)
        _PLAN_PHASES = [
            {"name": "hold", "start_date": _TODAY, "end_date": date(2026, 7, 23)},
            {"name": "ramp", "start_date": date(2026, 7, 24), "end_date": date(2026, 10, 9)},
            {"name": "peak block", "start_date": date(2026, 10, 10), "end_date": date(2026, 11, 6)},
            {"name": "taper", "start_date": date(2026, 11, 7), "end_date": _RACE_DATE},
        ]
        result = race_projection(
            [_effort_5k_20min()],
            race_distance_km=HALF_MARATHON_KM,
            current_weight_kg=75.0,
            current_ctl=60.0,
            current_atl=70.0,
            plan_phases=_PLAN_PHASES,
            race_date=_RACE_DATE,
            target_weight_kg=70.0,
            _today=_TODAY,
        )
        basis_lower = result["basis"].lower()
        assert "ctl" in basis_lower, f"basis should mention CTL: {result['basis']!r}"
