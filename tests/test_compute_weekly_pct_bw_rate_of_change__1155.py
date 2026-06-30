"""Unit tests for compute_weekly_pct_bw_rate_of_change (issue #1155).

AC coverage:
- normal loss  → negative percent value
- normal gain  → positive percent value
- flat trend   → 0.0 %/wk
- single data point → None
- zero-weight guard → ValueError
"""
import pytest

from backend.services.weight_ewma_rate import compute_weekly_pct_bw_rate_of_change


def test_normal_loss():
    """Losing weight produces a negative percent rate (AC: normal loss)."""
    # 90.0 kg → 89.3 kg over 7 days
    # expected = ((89.3 - 90.0) / 90.0) * 100 ≈ -0.7778 %/wk
    ewma = [90.0, 89.9, 89.8, 89.7, 89.6, 89.5, 89.4, 89.3]
    result = compute_weekly_pct_bw_rate_of_change(ewma)
    assert result is not None
    assert result < 0
    assert abs(result - (-0.7778)) < 0.001


def test_normal_gain():
    """Gaining weight produces a positive percent rate (AC: normal gain)."""
    # 80.0 kg → 80.6 kg over 7 days
    # expected = ((80.6 - 80.0) / 80.0) * 100 = 0.75 %/wk
    ewma = [80.0, 80.1, 80.2, 80.3, 80.4, 80.5, 80.6]
    result = compute_weekly_pct_bw_rate_of_change(ewma)
    assert result is not None
    assert result > 0
    assert abs(result - 0.75) < 0.001


def test_flat_trend():
    """All equal EWMA values → exactly 0.0 %/wk (AC: flat trend)."""
    ewma = [75.0] * 8
    result = compute_weekly_pct_bw_rate_of_change(ewma)
    assert result == 0.0


def test_single_data_point_returns_none():
    """A single EWMA value is insufficient → returns None (AC: single data point)."""
    result = compute_weekly_pct_bw_rate_of_change([80.0])
    assert result is None


def test_empty_list_returns_none():
    """Empty list also returns None (fewer than 2 data points)."""
    result = compute_weekly_pct_bw_rate_of_change([])
    assert result is None


def test_zero_start_weight_raises_value_error():
    """Zero ewma_start raises ValueError (AC: zero-weight guard)."""
    with pytest.raises(ValueError, match="zero"):
        compute_weekly_pct_bw_rate_of_change([0.0, 70.0])


def test_two_points_minimum():
    """Exactly two EWMA values compute a valid rate."""
    # ((85.0 - 90.0) / 90.0) * 100 = -5.556 %
    result = compute_weekly_pct_bw_rate_of_change([90.0, 85.0])
    assert result is not None
    assert abs(result - (-5.5556)) < 0.001


def test_positive_sign_means_gain():
    """Positive return value indicates weight gain (AC: sign convention)."""
    ewma = [70.0, 71.0]
    result = compute_weekly_pct_bw_rate_of_change(ewma)
    assert result > 0


def test_negative_sign_means_loss():
    """Negative return value indicates weight loss (AC: sign convention)."""
    ewma = [70.0, 69.0]
    result = compute_weekly_pct_bw_rate_of_change(ewma)
    assert result < 0
