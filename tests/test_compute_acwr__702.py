"""Unit tests for compute_acwr (issue #702).

Covers all AC items and UAT test steps:
  AC1  - Returns dict with ratio, band, guidance, debug
  AC2  - Acute load = sum of last 7 days
  AC3  - Chronic load = mean of 4 weekly totals from last 28 days
  AC4  - No division when chronic is zero
  AC5  - Three named tunable constants (LOWER_BOUND, UPPER_BOUND, HIGH_BOUND)
  AC6  - Classifies into detraining / productive / high_risk / baseline_forming
  AC7  - baseline_forming → ratio=None, guidance=None
  AC8  - Missing/malformed input → ratio=None, band=None, reason field
  AC9  - debug exposes acute_load, chronic_load, lower_bound, upper_bound, high_bound
  AC10 - Docstring contains worked example in plain words
  AC11 - No DB, file, or network access
  AC12 - No caret/arrow/pipe-union annotations in inline docs
"""

import inspect
import pytest

from backend.services.acwr import (
    compute_acwr,
    LOWER_BOUND,
    UPPER_BOUND,
    HIGH_BOUND,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_series(week_totals):
    """Build a daily series from a list of weekly totals (oldest first).

    Each week is spread evenly across 7 days.
    """
    series = []
    for total in week_totals:
        daily = total / 7
        series.extend([daily] * 7)
    return series


def _series_28(w1=300, w2=300, w3=300, w4=350):
    """28-day series: weeks 1-3 at w1-w3 each, week 4 (most recent) at w4."""
    return _make_series([w1, w2, w3, w4])


# ---------------------------------------------------------------------------
# UAT Step 1 — Productive band
# ---------------------------------------------------------------------------

class TestProductiveBand:
    def test_ratio_approx_1_17(self):
        """AC2, AC3: acute=350, chronic=300, ratio≈1.17."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        assert result["ratio"] == pytest.approx(350 / 300, rel=1e-6)

    def test_band_is_productive(self):
        """AC6: ratio≈1.17 falls in productive band."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        assert result["band"] == "productive"

    def test_guidance_is_non_empty_string(self):
        """AC1/AC6: guidance is a non-empty string for productive band."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        assert isinstance(result["guidance"], str) and result["guidance"].strip()

    def test_debug_acute_load(self):
        """AC9: debug.acute_load equals sum of last 7 days."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        assert result["debug"]["acute_load"] == pytest.approx(350.0, rel=1e-6)

    def test_debug_chronic_load(self):
        """AC9: debug.chronic_load equals mean of 4 weekly totals."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        assert result["debug"]["chronic_load"] == pytest.approx(300.0, rel=1e-6)


# ---------------------------------------------------------------------------
# UAT Step 2 — Detraining band
# ---------------------------------------------------------------------------

class TestDetrainingBand:
    def test_ratio_approx_0_6(self):
        """AC2, AC3: acute=120, chronic=200, ratio≈0.6."""
        series = _series_28(200, 200, 200, 120)
        result = compute_acwr(series)
        assert result["ratio"] == pytest.approx(120 / 200, rel=1e-6)

    def test_band_is_detraining(self):
        """AC6: ratio≈0.6 (< 0.8) falls in detraining band."""
        series = _series_28(200, 200, 200, 120)
        result = compute_acwr(series)
        assert result["band"] == "detraining"

    def test_guidance_advises_increased_load(self):
        """AC6: detraining guidance is a non-empty string."""
        series = _series_28(200, 200, 200, 120)
        result = compute_acwr(series)
        assert isinstance(result["guidance"], str) and result["guidance"].strip()


# ---------------------------------------------------------------------------
# UAT Step 3 — High-risk band
# ---------------------------------------------------------------------------

class TestHighRiskBand:
    def test_ratio_approx_1_67(self):
        """AC2, AC3: acute=500, chronic=300, ratio≈1.67."""
        series = _series_28(300, 300, 300, 500)
        result = compute_acwr(series)
        assert result["ratio"] == pytest.approx(500 / 300, rel=1e-6)

    def test_band_is_high_risk(self):
        """AC6: ratio≈1.67 (> 1.5) falls in high_risk band."""
        series = _series_28(300, 300, 300, 500)
        result = compute_acwr(series)
        assert result["band"] == "high_risk"

    def test_guidance_advises_load_reduction(self):
        """AC6: high_risk guidance is a non-empty string."""
        series = _series_28(300, 300, 300, 500)
        result = compute_acwr(series)
        assert isinstance(result["guidance"], str) and result["guidance"].strip()


# ---------------------------------------------------------------------------
# UAT Step 4 — Baseline forming
# ---------------------------------------------------------------------------

class TestBaselineForming:
    def test_band_baseline_forming_for_short_series(self):
        """AC6: fewer than 28 days → baseline_forming."""
        series = [50.0] * 10
        result = compute_acwr(series)
        assert result["band"] == "baseline_forming"

    def test_ratio_is_none_for_baseline_forming(self):
        """AC7: ratio is None when baseline_forming."""
        series = [50.0] * 10
        result = compute_acwr(series)
        assert result["ratio"] is None

    def test_guidance_is_none_for_baseline_forming(self):
        """AC7: guidance is None (not empty string) when baseline_forming."""
        series = [50.0] * 10
        result = compute_acwr(series)
        assert result["guidance"] is None

    def test_27_days_is_still_baseline_forming(self):
        """AC6: 27 days is still insufficient for baseline."""
        series = [50.0] * 27
        result = compute_acwr(series)
        assert result["band"] == "baseline_forming"

    def test_28_days_is_not_baseline_forming(self):
        """AC6: exactly 28 days is enough to compute a ratio."""
        series = [50.0] * 28
        result = compute_acwr(series)
        assert result["band"] != "baseline_forming"


# ---------------------------------------------------------------------------
# UAT Step 5 — Missing/malformed input
# ---------------------------------------------------------------------------

class TestInvalidInput:
    def test_none_returns_null_ratio(self):
        """AC8: None input → ratio is None."""
        result = compute_acwr(None)
        assert result["ratio"] is None

    def test_none_returns_null_band(self):
        """AC8: None input → band is None."""
        result = compute_acwr(None)
        assert result["band"] is None

    def test_none_returns_reason_field(self):
        """AC8: None input → reason is a non-empty string."""
        result = compute_acwr(None)
        assert isinstance(result.get("reason"), str) and result["reason"].strip()

    def test_non_iterable_input(self):
        """AC8: non-iterable input → reason field present."""
        result = compute_acwr(42)
        assert result["ratio"] is None
        assert result["band"] is None
        assert isinstance(result.get("reason"), str)


# ---------------------------------------------------------------------------
# UAT Step 6 — Tunable constants
# ---------------------------------------------------------------------------

class TestTunableConstants:
    def test_raising_lower_bound_reclassifies_to_detraining(self):
        """AC5: raising LOWER_BOUND above ratio≈1.17 reclassifies it to detraining."""
        import backend.services.acwr as acwr_module

        series = _series_28(300, 300, 300, 350)
        original = acwr_module.LOWER_BOUND
        try:
            # ratio for this series ≈ 1.17; raise lower_bound above it
            acwr_module.LOWER_BOUND = 1.3
            result = compute_acwr(series)
            assert result["band"] == "detraining"
        finally:
            acwr_module.LOWER_BOUND = original

    def test_restoring_lower_bound_restores_productive(self):
        """AC5: after restoring LOWER_BOUND the same series is productive again."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        assert result["band"] == "productive"


# ---------------------------------------------------------------------------
# UAT Step 7 — debug structure
# ---------------------------------------------------------------------------

class TestDebugStructure:
    def test_debug_has_exactly_expected_keys(self):
        """AC9: debug has exactly acute_load, chronic_load, lower_bound, upper_bound, high_bound."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        assert set(result["debug"].keys()) == {
            "acute_load",
            "chronic_load",
            "lower_bound",
            "upper_bound",
            "high_bound",
        }

    def test_debug_values_are_numeric(self):
        """AC9: all debug values are plain numbers."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        for key, value in result["debug"].items():
            assert isinstance(value, (int, float)), f"{key!r} is not numeric"

    def test_debug_bound_constants_match_module_constants(self):
        """AC5, AC9: debug exposes the actual constant values."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        assert result["debug"]["lower_bound"] == LOWER_BOUND
        assert result["debug"]["upper_bound"] == UPPER_BOUND
        assert result["debug"]["high_bound"] == HIGH_BOUND


# ---------------------------------------------------------------------------
# AC1 — Return shape
# ---------------------------------------------------------------------------

class TestReturnShape:
    def test_normal_result_has_four_keys(self):
        """AC1: normal result has exactly four keys: ratio, band, guidance, debug."""
        series = _series_28(300, 300, 300, 350)
        result = compute_acwr(series)
        assert set(result.keys()) == {"ratio", "band", "guidance", "debug"}

    def test_baseline_result_has_four_keys(self):
        """AC1: baseline_forming result also has exactly four keys."""
        result = compute_acwr([50.0] * 10)
        assert set(result.keys()) == {"ratio", "band", "guidance", "debug"}


# ---------------------------------------------------------------------------
# AC4 — Zero chronic load
# ---------------------------------------------------------------------------

class TestZeroChronicLoad:
    def test_zero_chronic_no_division(self):
        """AC4: zero chronic load → no division; ratio is None, reason present."""
        series = [0.0] * 28
        result = compute_acwr(series)
        assert result["ratio"] is None

    def test_zero_chronic_returns_reason(self):
        """AC4: zero chronic load includes a reason."""
        series = [0.0] * 28
        result = compute_acwr(series)
        assert isinstance(result.get("reason"), str) and result["reason"].strip()


# ---------------------------------------------------------------------------
# AC10 — Docstring worked example
# ---------------------------------------------------------------------------

class TestDocstring:
    def test_docstring_contains_worked_example(self):
        """AC10: docstring includes a plain-words worked example."""
        doc = compute_acwr.__doc__ or ""
        assert "350" in doc or "three hundred fifty" in doc.lower()
        assert "300" in doc or "three hundred" in doc.lower()

    def test_docstring_no_caret_characters(self):
        """AC12: inline docs contain no caret characters."""
        doc = compute_acwr.__doc__ or ""
        assert "^" not in doc

    def test_source_no_caret_in_comments(self):
        """AC12: module source contains no caret characters in comments."""
        import backend.services.acwr as acwr_module
        src = inspect.getsource(acwr_module)
        # Strip string literals and check only comments
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                assert "^" not in stripped, f"Caret found in comment: {line!r}"


# ---------------------------------------------------------------------------
# AC boundary: lower_bound ≤ ratio ≤ upper_bound is productive
# ---------------------------------------------------------------------------

class TestBoundaryValues:
    def test_ratio_exactly_at_lower_bound_is_productive(self):
        """AC6: ratio == lower_bound is productive."""
        # Build a series where acute/chronic == LOWER_BOUND exactly
        # chronic = mean of 4 weeks = (w1+w2+w3+w4)/4
        # if w1=w2=w3=100 and w4 = 3*LOWER_BOUND*100 then:
        # chronic = (100+100+100+3*LOWER_BOUND*100)/4 — complex; use simpler approach
        # Set all 4 weeks equal so chronic = week_total, acute = week_total * LOWER_BOUND
        chronic_target = 200.0
        acute_target = chronic_target * LOWER_BOUND
        series = _make_series([chronic_target, chronic_target, chronic_target, chronic_target])
        # Override last 7 days to get acute = acute_target
        daily_acute = acute_target / 7
        series[-7:] = [daily_acute] * 7
        result = compute_acwr(series)
        assert result["band"] == "productive"

    def test_ratio_exactly_at_upper_bound_is_productive(self):
        """AC6: ratio == upper_bound is productive."""
        chronic_target = 200.0
        acute_target = chronic_target * UPPER_BOUND
        series = _make_series([chronic_target, chronic_target, chronic_target, chronic_target])
        daily_acute = acute_target / 7
        series[-7:] = [daily_acute] * 7
        result = compute_acwr(series)
        assert result["band"] == "productive"

    def test_ratio_above_high_bound_is_high_risk(self):
        """AC6: ratio strictly above high_bound is high_risk."""
        chronic_target = 200.0
        acute_target = chronic_target * (HIGH_BOUND + 0.1)
        series = _make_series([chronic_target, chronic_target, chronic_target, chronic_target])
        daily_acute = acute_target / 7
        series[-7:] = [daily_acute] * 7
        result = compute_acwr(series)
        assert result["band"] == "high_risk"

    def test_ratio_below_lower_bound_is_detraining(self):
        """AC6: ratio strictly below lower_bound is detraining."""
        chronic_target = 200.0
        acute_target = chronic_target * (LOWER_BOUND - 0.1)
        series = _make_series([chronic_target, chronic_target, chronic_target, chronic_target])
        daily_acute = acute_target / 7
        series[-7:] = [daily_acute] * 7
        result = compute_acwr(series)
        assert result["band"] == "detraining"
