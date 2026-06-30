"""UAT tests for rate guardrail and stressor ramp check (issue #1057).

These tests verify the guardrail computation function works correctly with
realistic training data scenarios that simulate different athlete conditions.
"""

from __future__ import annotations

from backend.services.guardrail import compute_guardrail, STRESSOR_RAMP_THRESHOLD_PCT
from backend.services.acwr import HIGH_BOUND


# ── Series builders for realistic scenarios ────────────────────────────────────

def _stable_series(weekly_total: float = 300.0, weeks: int = 4) -> list:
    """28-day series of equal weekly totals — athlete in steady state."""
    daily = weekly_total / 7
    return [daily] * (weeks * 7)


def _high_risk_acwr_series() -> list:
    """28-day series where acute load spikes above chronic baseline."""
    chronic_weekly = 300.0
    acute_weekly = chronic_weekly * (HIGH_BOUND + 0.2)
    prior = [chronic_weekly / 7] * 21
    spike = [acute_weekly / 7] * 7
    return prior + spike


# ── UAT Step 1: Stable recent history ──────────────────────────────────────────

class TestUAT1_StableHistory:
    """UAT Step 1: Retrieve the guardrail result for an athlete with a stable
    recent training history (no sharp increases).

    Expected: `guardrail_state` is `ok`, `stressors_ramping` is `0`,
    `guardrail_message` is empty.
    """

    def test_uat1_stable_no_stressor_changes(self):
        """Stable history with no stressor changes returns ok."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=300.0,
            running_load_curr_week=300.0,
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
            weight_loss_rate_prev_week=0.5,
            weight_loss_rate_curr_week=0.5,
        )
        assert result["guardrail_state"] == "ok"
        assert result["stressors_ramping"] == 0
        assert result["guardrail_message"] == ""

    def test_uat1_structure_has_all_required_keys(self):
        """Result contains exactly the required keys."""
        result = compute_guardrail(_stable_series())
        assert set(result.keys()) == {"acwr", "acwr_state", "stressors_ramping", "guardrail_state", "guardrail_message"}


# ── UAT Step 2: Single stressor ramping ────────────────────────────────────────

class TestUAT2_SingleStressorRamping:
    """UAT Step 2: Simulate a week where only running load increased sharply
    (plyometric volume and weight loss rate unchanged).

    Expected: `stressors_ramping` is `1`, `guardrail_state` is `ok`.
    """

    def test_uat2_only_running_load_increases(self):
        """Only running load increases sharply → stressors=1, state=ok."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=250.0,  # 25% increase
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
            weight_loss_rate_prev_week=0.5,
            weight_loss_rate_curr_week=0.5,
        )
        assert result["stressors_ramping"] == 1
        assert result["guardrail_state"] == "ok"

    def test_uat2_message_is_empty_when_ok(self):
        """Message is empty when guardrail_state is ok."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=250.0,
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
        )
        assert result["guardrail_message"] == ""

    def test_uat2_other_stressors_flat(self):
        """Verify other stressors did not ramp."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=250.0,
            plyometric_volume_prev_week=4.0,
            plyometric_volume_curr_week=4.0,
            weight_loss_rate_prev_week=1.0,
            weight_loss_rate_curr_week=1.0,
        )
        assert result["stressors_ramping"] == 1  # Only running load


# ── UAT Step 3: Multiple stressors ramping ─────────────────────────────────────

class TestUAT3_MultipleStressorsRamping:
    """UAT Step 3: Simulate a week where both running load and plyometric
    volume increased sharply.

    Expected: `stressors_ramping` is `2`, `guardrail_state` is `warn`,
    `guardrail_message` is a non-empty sentence referencing multiple stressors.
    """

    def test_uat3_two_stressors_increase(self):
        """Two stressors increase sharply → stressors=2, state=warn."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=260.0,  # 30% increase
            plyometric_volume_prev_week=2.0,
            plyometric_volume_curr_week=3.0,  # 50% increase
            weight_loss_rate_prev_week=0.5,
            weight_loss_rate_curr_week=0.5,
        )
        assert result["stressors_ramping"] == 2
        assert result["guardrail_state"] == "warn"

    def test_uat3_message_is_non_empty_for_warn(self):
        """Message is non-empty when guardrail_state is warn."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=260.0,
            plyometric_volume_prev_week=2.0,
            plyometric_volume_curr_week=3.0,
        )
        assert result["guardrail_message"] != ""
        assert len(result["guardrail_message"].strip()) > 0

    def test_uat3_message_references_stressors(self):
        """Message mentions multiple stressors when warn."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=260.0,
            plyometric_volume_prev_week=2.0,
            plyometric_volume_curr_week=3.0,
        )
        msg = result["guardrail_message"].lower()
        # Message should reference stressors or training
        assert any(word in msg for word in ["stressor", "training", "ramp", "sharply", "increasing"])

    def test_uat3_all_three_stressors_ramping(self):
        """All three stressors can ramp simultaneously."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=260.0,
            plyometric_volume_prev_week=2.0,
            plyometric_volume_curr_week=3.0,
            weight_loss_rate_prev_week=0.5,
            weight_loss_rate_curr_week=1.0,  # 100% increase
        )
        assert result["stressors_ramping"] == 3
        assert result["guardrail_state"] == "warn"


# ── UAT Step 4: High ACWR alone triggers warning ─────────────────────────────────

class TestUAT4_HighACWRAlone:
    """UAT Step 4: Simulate an athlete whose ACWR falls in the `high_risk`
    range with only one stressor ramping.

    Expected: `acwr_state` is `high_risk`, `guardrail_state` is `warn`,
    `guardrail_message` is a non-empty sentence referencing workload ratio.
    """

    def test_uat4_high_risk_acwr_alone_is_warn(self):
        """High-risk ACWR with one stressor ramping → state=warn."""
        result = compute_guardrail(
            _high_risk_acwr_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=260.0,  # 30% increase
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
            weight_loss_rate_prev_week=0.5,
            weight_loss_rate_curr_week=0.5,
        )
        assert result["acwr_state"] == "high_risk"
        assert result["stressors_ramping"] == 1
        assert result["guardrail_state"] == "warn"

    def test_uat4_message_non_empty(self):
        """Message is non-empty for high-risk ACWR."""
        result = compute_guardrail(
            _high_risk_acwr_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=260.0,
        )
        assert result["guardrail_message"] != ""

    def test_uat4_message_references_workload(self):
        """Message mentions workload or ACWR when warn due to ACWR."""
        result = compute_guardrail(
            _high_risk_acwr_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=200.0,  # No stressor ramping
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
        )
        msg = result["guardrail_message"].lower()
        # Should reference workload, ratio, or injury risk
        assert any(word in msg for word in ["workload", "ratio", "injury", "overuse", "reduce"])

    def test_uat4_high_risk_with_no_stressor_ramp(self):
        """High ACWR alone (no stressor ramps) still triggers warn."""
        result = compute_guardrail(
            _high_risk_acwr_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=200.0,
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
        )
        assert result["acwr_state"] == "high_risk"
        assert result["stressors_ramping"] == 0
        assert result["guardrail_state"] == "warn"


# ── UAT Step 5: Productive ACWR with zero stressors ──────────────────────────────

class TestUAT5_ProductiveNoStressors:
    """UAT Step 5: Simulate an athlete with `acwr_state` of `productive` and
    zero stressors ramping.

    Expected: `guardrail_state` is `ok`, `guardrail_message` is empty.
    """

    def test_uat5_productive_and_flat_is_ok(self):
        """Productive ACWR with flat stressors → state=ok, message empty."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=200.0,
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
            weight_loss_rate_prev_week=0.5,
            weight_loss_rate_curr_week=0.5,
        )
        assert result["acwr_state"] == "productive"
        assert result["stressors_ramping"] == 0
        assert result["guardrail_state"] == "ok"
        assert result["guardrail_message"] == ""

    def test_uat5_minor_changes_below_threshold(self):
        """Small changes below ramp threshold do not trigger warn."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=200.0,
            running_load_curr_week=210.0,  # Only 5% increase
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.1,  # Only 3% increase
        )
        assert result["stressors_ramping"] == 0
        assert result["guardrail_state"] == "ok"


# ── UAT Step 6: Monthly summary service integration ──────────────────────────────

class TestUAT6_MonthlySummaryIntegration:
    """UAT Step 6: Confirm the monthly summary service can call the function
    and includes `guardrail_state` and `guardrail_message` in its output.

    Expected: Summary response contains both fields with correct values
    matching the direct function call.
    """

    def test_uat6_monthly_summary_includes_guardrail_fields(self):
        """Monthly summary service returns guardrail fields."""
        from backend.services.monthly_summary import compute_monthly_summary

        result = compute_monthly_summary(_stable_series())
        assert "guardrail_state" in result
        assert "guardrail_message" in result
        assert "acwr" in result
        assert "acwr_state" in result
        assert "stressors_ramping" in result

    def test_uat6_summary_matches_direct_call_for_ok_scenario(self):
        """Monthly summary guardrail values match direct compute_guardrail call (ok scenario)."""
        from backend.services.monthly_summary import compute_monthly_summary

        series = _stable_series()
        stressor_kwargs = {
            "running_load_prev_week": 200.0,
            "running_load_curr_week": 200.0,
            "plyometric_volume_prev_week": 3.0,
            "plyometric_volume_curr_week": 3.0,
            "weight_loss_rate_prev_week": 0.5,
            "weight_loss_rate_curr_week": 0.5,
        }

        direct = compute_guardrail(series, **stressor_kwargs)
        summary = compute_monthly_summary(series, **stressor_kwargs)

        assert summary["guardrail_state"] == direct["guardrail_state"]
        assert summary["guardrail_message"] == direct["guardrail_message"]
        assert summary["acwr_state"] == direct["acwr_state"]
        assert summary["stressors_ramping"] == direct["stressors_ramping"]

    def test_uat6_summary_matches_direct_call_for_warn_scenario(self):
        """Monthly summary guardrail values match direct compute_guardrail call (warn scenario)."""
        from backend.services.monthly_summary import compute_monthly_summary

        series = _stable_series()
        stressor_kwargs = {
            "running_load_prev_week": 200.0,
            "running_load_curr_week": 260.0,
            "plyometric_volume_prev_week": 2.0,
            "plyometric_volume_curr_week": 3.0,
            "weight_loss_rate_prev_week": 0.5,
            "weight_loss_rate_curr_week": 0.5,
        }

        direct = compute_guardrail(series, **stressor_kwargs)
        summary = compute_monthly_summary(series, **stressor_kwargs)

        assert summary["guardrail_state"] == "warn"
        assert direct["guardrail_state"] == "warn"
        assert summary["guardrail_state"] == direct["guardrail_state"]
        assert summary["guardrail_message"] == direct["guardrail_message"]

    def test_uat6_no_circular_dependencies(self):
        """Can import and use monthly summary without circular dependencies."""
        # This import should succeed without circular import errors
        from backend.services.monthly_summary import compute_monthly_summary
        from backend.services.guardrail import compute_guardrail

        assert callable(compute_monthly_summary)
        assert callable(compute_guardrail)


# ── Additional integration scenarios ───────────────────────────────────────────────

class TestIntegrationScenarios:
    """Additional scenarios to ensure robustness of guardrail computation."""

    def test_zero_from_baseline_counts_as_ramping(self):
        """Stressor going from 0 to positive counts as rising sharply (zero baseline)."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=0.0,
            running_load_curr_week=1.0,  # From zero → ramping
            plyometric_volume_prev_week=3.0,
            plyometric_volume_curr_week=3.0,
        )
        assert result["stressors_ramping"] == 1
        assert result["guardrail_state"] == "ok"  # Only one, so ok

    def test_zero_to_zero_is_not_ramping(self):
        """Stressor staying at 0 is not counted as ramping."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=0.0,
            running_load_curr_week=0.0,
            plyometric_volume_prev_week=0.0,
            plyometric_volume_curr_week=0.0,
        )
        assert result["stressors_ramping"] == 0

    def test_threshold_is_exclusive(self):
        """Increase of exactly threshold_pct does NOT count (strict > comparison)."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=120.0,  # Exactly 20% — not > 20%
            ramp_threshold_pct=STRESSOR_RAMP_THRESHOLD_PCT,
        )
        assert result["stressors_ramping"] == 0

    def test_above_threshold_counts_as_ramping(self):
        """Increase above threshold counts as ramping."""
        result = compute_guardrail(
            _stable_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=121.0,  # 21% — above 20%
        )
        assert result["stressors_ramping"] == 1

    def test_custom_threshold_parameter(self):
        """Custom ramp_threshold_pct parameter overrides module default."""
        # At 30% threshold, 21% should NOT trigger
        result_strict = compute_guardrail(
            _stable_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=121.0,
            ramp_threshold_pct=30.0,
        )
        assert result_strict["stressors_ramping"] == 0

        # At 10% threshold, 21% SHOULD trigger
        result_loose = compute_guardrail(
            _stable_series(),
            running_load_prev_week=100.0,
            running_load_curr_week=121.0,
            ramp_threshold_pct=10.0,
        )
        assert result_loose["stressors_ramping"] == 1

    def test_acwr_none_defaults_to_productive(self):
        """When ACWR cannot be computed, acwr_state defaults to productive."""
        short_series = [50.0] * 10  # Too short for ACWR
        result = compute_guardrail(short_series)
        assert result["acwr"] is None
        assert result["acwr_state"] == "productive"
        assert result["guardrail_state"] == "ok"

    def test_return_type_is_dict(self):
        """Function always returns a dict."""
        result = compute_guardrail(_stable_series())
        assert isinstance(result, dict)

    def test_all_keys_present_in_result(self):
        """Result dict contains exactly the five required keys."""
        result = compute_guardrail(_stable_series())
        expected_keys = {"acwr", "acwr_state", "stressors_ramping", "guardrail_state", "guardrail_message"}
        assert set(result.keys()) == expected_keys
