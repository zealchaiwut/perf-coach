"""Unit tests for compute_guardrail and monthly_summary service integration (issue #1057).

Acceptance criteria covered:
  AC1  - Function returns flat dict with exactly acwr, acwr_state, stressors_ramping,
         guardrail_state, guardrail_message
  AC2  - acwr is a numeric value reused from existing ACWR computation (no duplicate logic)
  AC3  - acwr_state is one of detraining, productive, high_risk
  AC4  - stressors_ramping is an integer count (0-3)
  AC5  - "rose sharply" uses a documented, configurable percentage threshold
  AC6  - guardrail_state is warn when stressors_ramping > 1 OR acwr_state == high_risk
  AC7  - guardrail_message is non-empty when warn, empty string when ok
  AC8  - Unit-tested: all stressors flat (ok), exactly one ramping (ok),
         two ramping (warn), ACWR high_risk alone (warn), both simultaneously (warn)
  AC9  - Function accessible to monthly summary service without circular dependencies
"""

from __future__ import annotations

import pytest

from backend.services.guardrail import compute_guardrail, STRESSOR_RAMP_THRESHOLD_PCT
from backend.services.acwr import compute_acwr, HIGH_BOUND, LOWER_BOUND


# ── Series builders ────────────────────────────────────────────────────────────

def _flat_series(weekly_total: float = 300.0, weeks: int = 4) -> list:
    """28-day series of equal weekly totals — yields a productive ACWR."""
    daily = weekly_total / 7
    return [daily] * (weeks * 7)


def _high_risk_series() -> list:
    """28-day series where the last 7 days spike well above chronic baseline."""
    chronic_weekly = 300.0
    # acute spike: HIGH_BOUND + 0.2 above chronic → ratio ≈ 1.7 (> 1.5)
    acute_weekly = chronic_weekly * (HIGH_BOUND + 0.2)
    prior = [chronic_weekly / 7] * 21
    spike = [acute_weekly / 7] * 7
    return prior + spike


def _detraining_series() -> list:
    """28-day series where acute load is well below chronic baseline."""
    chronic_weekly = 300.0
    # acute drops to LOWER_BOUND - 0.2 → ratio ≈ 0.6 (< 0.8)
    acute_weekly = chronic_weekly * (LOWER_BOUND - 0.2)
    prior = [chronic_weekly / 7] * 21
    low = [acute_weekly / 7] * 7
    return prior + low


# ── AC1 / return shape ─────────────────────────────────────────────────────────

class TestReturnShape:
    REQUIRED_KEYS = {"acwr", "acwr_state", "stressors_ramping", "guardrail_state", "guardrail_message"}

    def test_exactly_five_keys(self):
        """AC1: result has exactly the five required keys."""
        result = compute_guardrail(_flat_series())
        assert set(result.keys()) == self.REQUIRED_KEYS

    def test_returns_dict(self):
        """AC1: function returns a dict."""
        result = compute_guardrail(_flat_series())
        assert isinstance(result, dict)


# ── AC2 / acwr reuses existing computation ─────────────────────────────────────

class TestAcwrReuse:
    def test_acwr_matches_direct_compute_acwr(self):
        """AC2: acwr value equals ratio from compute_acwr on same series."""
        series = _flat_series()
        guardrail = compute_guardrail(series)
        direct = compute_acwr(series)
        assert guardrail["acwr"] == direct["ratio"]

    def test_acwr_is_numeric_for_valid_series(self):
        """AC2: acwr is a float (not None) for a valid 28-day series."""
        result = compute_guardrail(_flat_series())
        assert isinstance(result["acwr"], float)

    def test_acwr_is_none_for_short_series(self):
        """AC2: acwr is None when series is too short for ACWR baseline."""
        result = compute_guardrail([50.0] * 10)
        assert result["acwr"] is None


# ── AC3 / acwr_state values ────────────────────────────────────────────────────

class TestAcwrState:
    VALID_STATES = {"detraining", "productive", "high_risk"}

    def test_productive_state(self):
        """AC3: equal-load series yields acwr_state == productive."""
        result = compute_guardrail(_flat_series())
        assert result["acwr_state"] == "productive"

    def test_high_risk_state(self):
        """AC3: spike series yields acwr_state == high_risk."""
        result = compute_guardrail(_high_risk_series())
        assert result["acwr_state"] == "high_risk"

    def test_detraining_state(self):
        """AC3: low-acute series yields acwr_state == detraining."""
        result = compute_guardrail(_detraining_series())
        assert result["acwr_state"] == "detraining"

    def test_baseline_forming_maps_to_productive(self):
        """AC3: when ACWR is baseline_forming (< 28 days), acwr_state defaults to productive."""
        result = compute_guardrail([50.0] * 10)
        assert result["acwr_state"] == "productive"

    def test_acwr_state_is_always_one_of_three_values(self):
        """AC3: acwr_state is always one of the three defined states."""
        for series in [_flat_series(), _high_risk_series(), _detraining_series(), [50.0] * 10]:
            result = compute_guardrail(series)
            assert result["acwr_state"] in self.VALID_STATES


# ── AC4 / stressors_ramping ────────────────────────────────────────────────────

class TestStressorsRamping:
    def test_is_integer(self):
        """AC4: stressors_ramping is an int."""
        result = compute_guardrail(_flat_series())
        assert isinstance(result["stressors_ramping"], int)

    def test_is_in_range_zero_to_three(self):
        """AC4: stressors_ramping is between 0 and 3."""
        for series in [_flat_series(), _high_risk_series()]:
            result = compute_guardrail(series)
            assert 0 <= result["stressors_ramping"] <= 3

    def test_all_three_stressors_ramping(self):
        """AC4: all three stressors up sharply → stressors_ramping == 3."""
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=130.0,
            plyometric_volume_prev_week=5.0,
            plyometric_volume_curr_week=7.0,
            weight_loss_rate_prev_week=0.5,
            weight_loss_rate_curr_week=1.0,
        )
        assert result["stressors_ramping"] == 3


# ── AC5 / configurable threshold ──────────────────────────────────────────────

class TestRampThreshold:
    def test_module_constant_exists_and_is_positive(self):
        """AC5: STRESSOR_RAMP_THRESHOLD_PCT is a positive number."""
        assert isinstance(STRESSOR_RAMP_THRESHOLD_PCT, float)
        assert STRESSOR_RAMP_THRESHOLD_PCT > 0

    def test_below_threshold_does_not_count_as_ramping(self):
        """AC5: increase of exactly threshold_pct does NOT count (strict >)."""
        # 20% increase exactly should NOT trigger at default 20% threshold
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=120.0,  # exactly 20% — not strictly greater
        )
        assert result["stressors_ramping"] == 0

    def test_above_threshold_counts_as_ramping(self):
        """AC5: increase above threshold counts as a sharp ramp."""
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=121.0,  # 21% — above 20%
        )
        assert result["stressors_ramping"] == 1

    def test_custom_threshold_overrides_default(self):
        """AC5: caller-supplied ramp_threshold_pct overrides the default."""
        result_default = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=121.0,
            ramp_threshold_pct=30.0,  # stricter threshold — 21% shouldn't trigger
        )
        assert result_default["stressors_ramping"] == 0

        result_loose = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=115.0,
            ramp_threshold_pct=10.0,  # looser threshold — 15% should trigger
        )
        assert result_loose["stressors_ramping"] == 1


# ── AC6 + AC7 / guardrail_state and guardrail_message ─────────────────────────

class TestGuardrailState:
    def test_ok_when_no_stressors_and_productive_acwr(self):
        """AC6: all flat + productive ACWR → guardrail_state is ok."""
        result = compute_guardrail(_flat_series())
        assert result["guardrail_state"] == "ok"

    def test_guardrail_state_is_ok_or_warn(self):
        """AC6: guardrail_state is always one of ok or warn."""
        for series in [_flat_series(), _high_risk_series()]:
            result = compute_guardrail(series)
            assert result["guardrail_state"] in ("ok", "warn")


class TestGuardrailMessage:
    def test_message_empty_when_ok(self):
        """AC7: guardrail_message is empty string when guardrail_state is ok."""
        result = compute_guardrail(_flat_series())
        assert result["guardrail_state"] == "ok"
        assert result["guardrail_message"] == ""

    def test_message_non_empty_when_warn(self):
        """AC7: guardrail_message is a non-empty sentence when guardrail_state is warn."""
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=130.0,
            plyometric_volume_prev_week=5.0,
            plyometric_volume_curr_week=7.0,
        )
        assert result["guardrail_state"] == "warn"
        assert isinstance(result["guardrail_message"], str)
        assert len(result["guardrail_message"].strip()) > 0


# ── AC8 / five required test cases ────────────────────────────────────────────

class TestAC8RequiredCases:
    """The five cases required by AC8."""

    def test_all_stressors_flat_is_ok(self):
        """AC8-1: all stressors flat → guardrail_state is ok."""
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=100.0,
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
            weight_loss_rate_prev_week=0.3,
            weight_loss_rate_curr_week=0.3,
        )
        assert result["stressors_ramping"] == 0
        assert result["guardrail_state"] == "ok"

    def test_exactly_one_stressor_ramping_is_ok(self):
        """AC8-2: exactly one stressor ramping, productive ACWR → guardrail_state is ok."""
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=130.0,  # 30% rise — ramping
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,  # flat
            weight_loss_rate_prev_week=0.3,
            weight_loss_rate_curr_week=0.3,   # flat
        )
        assert result["stressors_ramping"] == 1
        assert result["guardrail_state"] == "ok"

    def test_two_stressors_ramping_is_warn(self):
        """AC8-3: two stressors ramping, productive ACWR → guardrail_state is warn."""
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=130.0,     # 30% rise
            plyometric_volume_prev_week=5.0,
            plyometric_volume_curr_week=7.0,  # 40% rise
            weight_loss_rate_prev_week=0.3,
            weight_loss_rate_curr_week=0.3,   # flat
        )
        assert result["stressors_ramping"] == 2
        assert result["guardrail_state"] == "warn"
        assert result["guardrail_message"] != ""

    def test_high_risk_acwr_alone_is_warn(self):
        """AC8-4: ACWR high_risk with only one stressor ramping → guardrail_state is warn."""
        result = compute_guardrail(
            _high_risk_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=130.0,  # only one ramping
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
            weight_loss_rate_prev_week=0.3,
            weight_loss_rate_curr_week=0.3,
        )
        assert result["acwr_state"] == "high_risk"
        assert result["stressors_ramping"] == 1
        assert result["guardrail_state"] == "warn"
        assert result["guardrail_message"] != ""

    def test_both_conditions_simultaneously_is_warn(self):
        """AC8-5: ACWR high_risk + two stressors ramping → guardrail_state is warn."""
        result = compute_guardrail(
            _high_risk_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=130.0,
            plyometric_volume_prev_week=5.0,
            plyometric_volume_curr_week=7.0,
            weight_loss_rate_prev_week=0.5,
            weight_loss_rate_curr_week=1.0,
        )
        assert result["acwr_state"] == "high_risk"
        assert result["stressors_ramping"] == 3
        assert result["guardrail_state"] == "warn"
        assert result["guardrail_message"] != ""


# ── AC9 / monthly summary service access ──────────────────────────────────────

class TestMonthlySummaryServiceAccess:
    def test_import_from_monthly_summary_service(self):
        """AC9: compute_monthly_summary can be imported without circular deps."""
        from backend.services.monthly_summary import compute_monthly_summary
        assert callable(compute_monthly_summary)

    def test_monthly_summary_output_contains_guardrail_state(self):
        """AC9/UAT6: monthly summary service output includes guardrail_state."""
        from backend.services.monthly_summary import compute_monthly_summary
        result = compute_monthly_summary(_flat_series())
        assert "guardrail_state" in result

    def test_monthly_summary_output_contains_guardrail_message(self):
        """AC9/UAT6: monthly summary service output includes guardrail_message."""
        from backend.services.monthly_summary import compute_monthly_summary
        result = compute_monthly_summary(_flat_series())
        assert "guardrail_message" in result

    def test_monthly_summary_guardrail_values_match_direct_call(self):
        """UAT6: monthly summary guardrail fields match direct compute_guardrail call."""
        from backend.services.monthly_summary import compute_monthly_summary
        series = _flat_series()
        running_prev = 100.0
        running_curr = 130.0
        plyo_prev = 5.0
        plyo_curr = 7.0
        weight_prev = 0.3
        weight_curr = 0.3

        direct = compute_guardrail(
            series,
            running_load_prev_week=running_prev,
            running_load_curr_week=running_curr,
            plyometric_volume_prev_week=plyo_prev,
            plyometric_volume_curr_week=plyo_curr,
            weight_loss_rate_prev_week=weight_prev,
            weight_loss_rate_curr_week=weight_curr,
        )
        summary = compute_monthly_summary(
            series,
            running_load_prev_week=running_prev,
            running_load_curr_week=running_curr,
            plyometric_volume_prev_week=plyo_prev,
            plyometric_volume_curr_week=plyo_curr,
            weight_loss_rate_prev_week=weight_prev,
            weight_loss_rate_curr_week=weight_curr,
        )
        assert summary["guardrail_state"] == direct["guardrail_state"]
        assert summary["guardrail_message"] == direct["guardrail_message"]


# ── Additional UAT coverage ────────────────────────────────────────────────────

class TestUATSteps:
    """Additional coverage matching UAT test steps from the issue."""

    def test_uat1_stable_history_is_ok(self):
        """UAT1: stable history → guardrail_state ok, stressors_ramping 0, message empty."""
        result = compute_guardrail(_flat_series())
        assert result["guardrail_state"] == "ok"
        assert result["stressors_ramping"] == 0
        assert result["guardrail_message"] == ""

    def test_uat2_only_running_load_ramping(self):
        """UAT2: only running load sharp → stressors_ramping 1, guardrail ok."""
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=130.0,
        )
        assert result["stressors_ramping"] == 1
        assert result["guardrail_state"] == "ok"

    def test_uat3_running_and_plyo_ramping(self):
        """UAT3: running load + plyometric volume both ramping → stressors 2, warn, message."""
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=130.0,
            plyometric_volume_prev_week=5.0,
            plyometric_volume_curr_week=7.0,
        )
        assert result["stressors_ramping"] == 2
        assert result["guardrail_state"] == "warn"
        msg = result["guardrail_message"]
        assert isinstance(msg, str) and len(msg.strip()) > 0

    def test_uat4_high_risk_acwr_one_stressor(self):
        """UAT4: ACWR high_risk + one stressor → acwr_state high_risk, warn, message."""
        result = compute_guardrail(
            _high_risk_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=130.0,
        )
        assert result["acwr_state"] == "high_risk"
        assert result["guardrail_state"] == "warn"
        msg = result["guardrail_message"]
        assert isinstance(msg, str) and len(msg.strip()) > 0

    def test_uat5_productive_zero_stressors(self):
        """UAT5: productive ACWR + zero stressors → guardrail ok, message empty."""
        result = compute_guardrail(_flat_series())
        assert result["acwr_state"] == "productive"
        assert result["guardrail_state"] == "ok"
        assert result["guardrail_message"] == ""

    def test_zero_from_baseline_counts_as_ramping(self):
        """Edge: stressor going from 0 to positive counts as rising sharply."""
        result = compute_guardrail(
            _flat_series(),
            plyometric_volume_prev_week=0.0,
            plyometric_volume_curr_week=2.0,
        )
        # Only one stressor ramped — should still be ok
        assert result["stressors_ramping"] == 1
        assert result["guardrail_state"] == "ok"

    def test_zero_to_zero_is_not_ramping(self):
        """Edge: stressor staying at 0 is not counted as ramping."""
        result = compute_guardrail(
            _flat_series(),
            running_load_prev_week=0.0,
            running_load_curr_week=0.0,
        )
        assert result["stressors_ramping"] == 0
