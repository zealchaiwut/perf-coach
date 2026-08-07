"""Tests for issue #1443: form-metrics rolling mean is date-based, not run-count-based.

The bug: _rolling_mean used index-based window (last 28 entries by position).
Fix: include only entries whose run_date is within 27 calendar days of the current row.

Acceptance criteria:
- Sparse runs spread over >28 days do NOT bleed earlier values into the 28-day mean
- Dense runs all within 28 days ARE all included
- A run exactly 27 days before the current row is included; 28+ days before is excluded
- Entries with None values are skipped within the date window (pre-existing behaviour)
- Empty or single-entry series still work
"""
import datetime

import pytest


# Import the function under test via the module directly (avoids a running server)
from backend.main import _rolling_mean


def _d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


# ---------------------------------------------------------------------------
# Core correctness: date-based window
# ---------------------------------------------------------------------------

def test_sparse_runs_exclude_old_entries():
    """Runs spaced >28 days apart: earlier value must NOT appear in rolling mean."""
    # Two runs 60 days apart — only the current run should be in its own window.
    values = [
        (_d("2026-01-01"), 200.0),
        (_d("2026-03-02"), 220.0),  # 60 days later
    ]
    result = _rolling_mean(values)
    # The second entry's mean must be 220.0, not (200+220)/2 = 210.0
    assert result[1] == pytest.approx(220.0, abs=0.01), (
        f"Expected 220.0 (only current run in window), got {result[1]}"
    )


def test_dense_runs_all_included():
    """Runs all within 28 days: all should contribute to the rolling mean."""
    base = _d("2026-03-01")
    values = [(base + datetime.timedelta(days=d), float(d + 1)) for d in range(0, 28, 4)]
    result = _rolling_mean(values)
    # Last entry: all prior entries are within 27-day window → mean of all values
    all_vals = [v for _, v in values]
    expected = round(sum(all_vals) / len(all_vals), 4)
    assert result[-1] == pytest.approx(expected, abs=0.01)


def test_boundary_exactly_27_days_included():
    """Entry exactly 27 days before current row is included (within 28-day window)."""
    values = [
        (_d("2026-01-01"), 200.0),
        (_d("2026-01-28"), 240.0),  # 27 days later → included
    ]
    result = _rolling_mean(values)
    # Mean should be (200 + 240) / 2
    assert result[1] == pytest.approx(220.0, abs=0.01)


def test_boundary_exactly_28_days_excluded():
    """Entry exactly 28 days before current row is excluded."""
    values = [
        (_d("2026-01-01"), 200.0),
        (_d("2026-01-29"), 240.0),  # 28 days later → excluded
    ]
    result = _rolling_mean(values)
    assert result[1] == pytest.approx(240.0, abs=0.01)


def test_first_entry_mean_is_its_own_value():
    """The very first entry's rolling mean equals its own value."""
    values = [(_d("2026-03-01"), 185.0)]
    result = _rolling_mean(values)
    assert len(result) == 1
    assert result[0] == pytest.approx(185.0, abs=0.01)


def test_none_values_skipped_within_window():
    """None values within the date window are skipped, not treated as zero."""
    values = [
        (_d("2026-03-01"), None),
        (_d("2026-03-05"), 200.0),
        (_d("2026-03-10"), None),
        (_d("2026-03-15"), 220.0),
    ]
    result = _rolling_mean(values)
    # First entry → None (no non-null values)
    assert result[0] is None
    # Second → 200.0
    assert result[1] == pytest.approx(200.0, abs=0.01)
    # Third → still only 200.0 (the None is skipped)
    assert result[2] == pytest.approx(200.0, abs=0.01)
    # Fourth → mean of 200.0 and 220.0
    assert result[3] == pytest.approx(210.0, abs=0.01)


def test_all_none_within_window_returns_none():
    """When all entries in the date window are None, result is None."""
    values = [
        (_d("2026-03-01"), None),
        (_d("2026-03-10"), None),
    ]
    result = _rolling_mean(values)
    assert result[0] is None
    assert result[1] is None


def test_empty_series_returns_empty():
    """Empty input returns empty output."""
    assert _rolling_mean([]) == []


def test_multiple_clusters_independent():
    """Two clusters separated by >28 days: each cluster's mean is independent."""
    values = [
        (_d("2026-01-01"), 100.0),
        (_d("2026-01-10"), 110.0),
        # Gap of 60 days
        (_d("2026-03-11"), 200.0),
        (_d("2026-03-20"), 210.0),
    ]
    result = _rolling_mean(values)
    # First cluster: self-contained
    assert result[0] == pytest.approx(100.0, abs=0.01)
    assert result[1] == pytest.approx(105.0, abs=0.01)  # (100+110)/2
    # Second cluster: first two entries must NOT bleed in
    assert result[2] == pytest.approx(200.0, abs=0.01)
    assert result[3] == pytest.approx(205.0, abs=0.01)  # (200+210)/2


def test_run_dates_as_strings():
    """_rolling_mean must handle run_date values that are ISO-format strings."""
    values = [
        ("2026-03-01", 185.0),
        ("2026-03-15", 195.0),
    ]
    result = _rolling_mean(values)
    assert result[0] == pytest.approx(185.0, abs=0.01)
    assert result[1] == pytest.approx(190.0, abs=0.01)
