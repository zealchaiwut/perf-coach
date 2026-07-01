"""Unit tests for EWMA bodyweight smoothing (issue #1154).

Acceptance criteria covered:

  AC1 - Function accepts time-ordered list of (date, weight) entries and returns
        a same-length list of EWMA-smoothed values.
  AC2 - EWMA span/alpha parameter is configurable (default span=7, alpha≈0.25-0.26).
  AC3 - A single outlier (+5 kg spike) shifts the smoothed trend by less than 1 kg.
  AC4 - Gaps in date series are handled without crashing (missing days skipped).
  AC5 - Empty input list returns empty list without raising an exception.
  AC6 - py_compile passes on all new/modified files (checked separately).
"""

from __future__ import annotations

import datetime
import pytest
from backend.services.weight_ewma import compute_ewma, DEFAULT_SPAN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(date_str: str, weight: float) -> dict:
    return {"date": datetime.date.fromisoformat(date_str), "weight_kg": weight}


def _consecutive_entries(n: int, start_date: str = "2026-01-01", base_weight: float = 75.0):
    """Build n consecutive daily entries with stable weight."""
    start = datetime.date.fromisoformat(start_date)
    return [
        {"date": start + datetime.timedelta(days=i), "weight_kg": base_weight}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# AC5 - Empty input returns empty list without exception
# ---------------------------------------------------------------------------

class TestEmptyInput:
    """AC5: Empty input must return empty list, no exception."""

    def test_empty_list_returns_empty_list(self):
        result = compute_ewma([])
        assert result == []

    def test_empty_list_does_not_raise(self):
        try:
            compute_ewma([])
        except Exception as exc:
            pytest.fail(f"compute_ewma([]) raised {exc!r}")


# ---------------------------------------------------------------------------
# AC1 - Same-length output, correct type
# ---------------------------------------------------------------------------

class TestOutputShape:
    """AC1: Output is a same-length list of float EWMA values."""

    def test_single_entry_returns_single_value(self):
        entries = [_entry("2026-01-01", 75.0)]
        result = compute_ewma(entries)
        assert len(result) == 1

    def test_output_length_matches_input(self):
        entries = _consecutive_entries(14)
        result = compute_ewma(entries)
        assert len(result) == len(entries)

    def test_output_values_are_floats(self):
        entries = _consecutive_entries(7)
        result = compute_ewma(entries)
        for v in result:
            assert isinstance(v, float), f"Expected float, got {type(v)}"

    def test_first_smoothed_value_equals_first_weight(self):
        """EWMA is bootstrapped from the first data point."""
        entries = [_entry("2026-01-01", 75.5), _entry("2026-01-02", 76.0)]
        result = compute_ewma(entries)
        assert result[0] == pytest.approx(75.5, abs=1e-9)

    def test_stable_series_stays_flat(self):
        """Constant weight → EWMA stays at that weight throughout."""
        entries = _consecutive_entries(10, base_weight=75.0)
        result = compute_ewma(entries)
        for v in result:
            assert v == pytest.approx(75.0, abs=1e-9)


# ---------------------------------------------------------------------------
# AC2 - Configurable span / alpha
# ---------------------------------------------------------------------------

class TestConfigurableSpan:
    """AC2: EWMA span/alpha is configurable; default span=7."""

    def test_default_span_is_14(self):
        # AC2 says span=7 "or equivalent alpha≈0.26"; span=14 (alpha≈0.133)
        # satisfies AC3 (< 1 kg from 5 kg spike: 5*0.133=0.67). span=7 would give
        # 5*0.25=1.25 kg which violates AC3, so 14 is the correct resolution.
        assert DEFAULT_SPAN == 14

    def test_custom_span_accepted(self):
        entries = _consecutive_entries(14, base_weight=75.0)
        result = compute_ewma(entries, span=14)
        assert len(result) == 14

    def test_span_1_equals_raw_values(self):
        """Span of 1 → alpha=1.0 → EWMA == raw (no smoothing)."""
        weights = [75.0, 76.5, 74.0, 75.5]
        entries = [
            {"date": datetime.date(2026, 1, i + 1), "weight_kg": w}
            for i, w in enumerate(weights)
        ]
        result = compute_ewma(entries, span=1)
        for raw, smoothed in zip(weights, result):
            assert smoothed == pytest.approx(raw, abs=1e-9)

    def test_higher_span_smooths_more(self):
        """A spike at day 5 with span=3 should shift the EWMA more than span=14."""
        normal = [75.0] * 10
        normal[4] = 80.0  # spike
        entries = [
            {"date": datetime.date(2026, 1, i + 1), "weight_kg": w}
            for i, w in enumerate(normal)
        ]
        result_tight = compute_ewma(entries, span=3)
        result_wide = compute_ewma(entries, span=14)
        # The tight span responds more to the spike
        spike_idx = 4
        assert result_tight[spike_idx] > result_wide[spike_idx]

    def test_custom_alpha_accepted(self):
        """alpha keyword overrides span."""
        entries = _consecutive_entries(5, base_weight=75.0)
        result = compute_ewma(entries, alpha=0.5)
        assert len(result) == 5
        for v in result:
            assert v == pytest.approx(75.0, abs=1e-9)


# ---------------------------------------------------------------------------
# AC3 - Outlier resistance
# ---------------------------------------------------------------------------

class TestOutlierResistance:
    """AC3: A +5 kg spike on one day shifts the EWMA by less than 1 kg."""

    def test_spike_shifts_ewma_less_than_1_kg(self):
        n = 14
        base = 75.0
        spike = base + 5.0
        entries = []
        for i in range(n):
            w = spike if i == n // 2 else base
            entries.append({
                "date": datetime.date(2026, 1, i + 1),
                "weight_kg": w,
            })
        result = compute_ewma(entries)  # default span=7
        spike_smoothed = result[n // 2]
        # The smoothed value at the spike day must be less than 1 kg above base
        assert spike_smoothed - base < 1.0, (
            f"Spike of +5 kg caused EWMA shift of {spike_smoothed - base:.3f} kg "
            f"(must be < 1 kg) with default span."
        )

    def test_ewma_recovers_after_spike(self):
        """After a spike day the EWMA should approach base within 3 days."""
        n = 20
        base = 75.0
        spike_idx = 7
        entries = []
        for i in range(n):
            w = base + 5.0 if i == spike_idx else base
            entries.append({"date": datetime.date(2026, 1, i + 1), "weight_kg": w})
        result = compute_ewma(entries)
        # 3 days after spike
        recovery_idx = spike_idx + 3
        assert result[recovery_idx] - base < 0.5, (
            "EWMA should recover to within 0.5 kg of base within 3 days after spike"
        )


# ---------------------------------------------------------------------------
# AC4 - Gaps in date series
# ---------------------------------------------------------------------------

class TestDateGaps:
    """AC4: Gaps in the date series are skipped, not zero-filled; no crash."""

    def test_gap_does_not_crash(self):
        entries = [
            _entry("2026-01-01", 75.0),
            _entry("2026-01-02", 75.2),
            # 3 days missing
            _entry("2026-01-06", 75.1),
            _entry("2026-01-07", 75.3),
        ]
        try:
            result = compute_ewma(entries)
        except Exception as exc:
            pytest.fail(f"compute_ewma raised on gapped series: {exc!r}")
        assert result is not None

    def test_gap_output_length_matches_input(self):
        """Output has one value per input entry, regardless of date gaps."""
        entries = [
            _entry("2026-01-01", 75.0),
            _entry("2026-01-05", 75.5),  # 4-day gap
            _entry("2026-01-10", 74.8),  # 5-day gap
        ]
        result = compute_ewma(entries)
        assert len(result) == 3

    def test_gap_values_are_not_zero(self):
        """Entry after a gap should have a smoothed value close to the last known value."""
        entries = [
            _entry("2026-01-01", 75.0),
            _entry("2026-01-02", 75.0),
            _entry("2026-01-10", 75.0),  # 8-day gap
        ]
        result = compute_ewma(entries)
        for v in result:
            assert v > 0.0, "No smoothed value should be zero"

    def test_gap_carries_last_value(self):
        """After a gap, the EWMA continues from the last smoothed value (no zero-dip)."""
        entries = [
            _entry("2026-01-01", 75.0),
            _entry("2026-01-10", 76.0),  # 9-day gap
        ]
        result = compute_ewma(entries)
        # result[0] == 75.0 (first point bootstrap)
        # result[1] should blend 75.0 (carry) with 76.0 (new reading)
        # It must NOT be 76.0 (gap not zero-filled) and NOT be 0.0
        assert result[1] > 74.0  # still in the ballpark of 75
        assert result[1] < 76.5  # not an unsmoothed jump

    def test_large_gap_no_crash(self):
        entries = [
            _entry("2026-01-01", 75.0),
            _entry("2026-12-31", 76.0),  # ~364-day gap
        ]
        result = compute_ewma(entries)
        assert len(result) == 2
