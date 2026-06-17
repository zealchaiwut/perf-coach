"""Tests for issue #575: Add compute_normalized_power pure calculation function.

Acceptance criteria covered:
  AC-steady      — 120 samples at 250 W with 1-s interval → watts=250
  AC-null        — power_samples=None → (None, {"reason": ...})
  AC-empty       — power_samples=[] → (None, {"reason": ...})
  AC-short       — fewer samples than one 30-s window → (None, {"reason": ...})
  AC-mixed       — alternating-intensity input → NP strictly greater than arithmetic mean
  AC-debug       — debug object exposes rolling_window_count, mean_of_fourth_powers, final_value
  AC-integer     — returned watts value is int, not float
  AC-final-value — debug final_value equals fourth root of mean_of_fourth_powers
  AC-window      — window_size derived from sample_interval_seconds (0.5 s → 60-sample window)
"""

import math

import pytest

from backend.services.normalized_power import compute_normalized_power


# ── AC-steady: steady 250 W → NP = 250 ───────────────────────────────────────


def test_steady_250w_returns_250():
    """AC-steady: 120 samples at 250 W, 1-s interval → NP should equal 250."""
    samples = [250.0] * 120
    watts, debug = compute_normalized_power(samples, 1)
    assert watts == 250


def test_steady_250w_debug_final_value_near_250():
    """AC-steady: final_value in debug is approximately 250 for steady input."""
    samples = [250.0] * 120
    watts, debug = compute_normalized_power(samples, 1)
    assert abs(debug["final_value"] - 250.0) < 1.0


# ── AC-integer: return type must be int ──────────────────────────────────────


def test_return_watts_is_integer():
    """AC-integer: the watts return value must be a Python int, not a float."""
    samples = [300.0] * 120
    watts, _ = compute_normalized_power(samples, 1)
    assert isinstance(watts, int)


# ── AC-null: None input → (None, reason dict) ────────────────────────────────


def test_null_samples_returns_none():
    """AC-null: None power_samples → first element of tuple is None."""
    watts, info = compute_normalized_power(None, 1)
    assert watts is None


def test_null_samples_reason_string_present():
    """AC-null: None power_samples → info dict contains non-empty 'reason' string."""
    _, info = compute_normalized_power(None, 1)
    assert "reason" in info
    assert isinstance(info["reason"], str)
    assert len(info["reason"]) > 0


# ── AC-empty: empty list → (None, reason dict) ───────────────────────────────


def test_empty_samples_returns_none():
    """AC-empty: empty power_samples list → first element of tuple is None."""
    watts, info = compute_normalized_power([], 1)
    assert watts is None


def test_empty_samples_reason_string_present():
    """AC-empty: empty power_samples list → info dict contains non-empty 'reason' string."""
    _, info = compute_normalized_power([], 1)
    assert "reason" in info
    assert isinstance(info["reason"], str)
    assert len(info["reason"]) > 0


# ── AC-short: data shorter than one 30-s window → (None, reason dict) ────────


def test_insufficient_data_returns_none():
    """AC-short: 10 samples at 1-s interval (10 s total) < 30-s window → None."""
    watts, info = compute_normalized_power([250.0] * 10, 1)
    assert watts is None


def test_insufficient_data_reason_string_present():
    """AC-short: too-short input → info dict contains a non-empty 'reason' string."""
    _, info = compute_normalized_power([250.0] * 10, 1)
    assert "reason" in info
    assert isinstance(info["reason"], str)
    assert len(info["reason"]) > 0


def test_exactly_one_window_worth_of_data_succeeds():
    """AC-short: exactly 30 samples at 1-s interval should succeed (not return None)."""
    watts, _ = compute_normalized_power([250.0] * 30, 1)
    assert watts is not None


# ── AC-mixed: mixed intensity → NP > arithmetic mean ─────────────────────────


def test_mixed_intensity_exceeds_arithmetic_mean():
    """AC-mixed: 30 s at 100 W then 30 s at 400 W → NP strictly greater than mean (250 W)."""
    samples = [100.0] * 30 + [400.0] * 30
    arithmetic_mean = sum(samples) / len(samples)  # 250.0
    watts, _ = compute_normalized_power(samples, 1)
    assert watts > arithmetic_mean


def test_alternating_60s_mixed_exceeds_mean():
    """AC-mixed: 60-second 10-s-block alternating stream → NP > arithmetic mean (250 W).

    Six 10-second blocks alternate between 100 W and 400 W. Because the 30-sample
    rolling window spans unequal proportions of the two power levels across blocks,
    rolling averages vary (from 200 W to 300 W). The fourth-power step then lifts
    the Normalized Power above the arithmetic mean of 250 W.
    """
    samples = ([100.0] * 10 + [400.0] * 10) * 3  # 60 samples, arithmetic mean = 250 W
    arithmetic_mean = sum(samples) / len(samples)  # 250.0
    watts, _ = compute_normalized_power(samples, 1)
    assert watts > arithmetic_mean


# ── AC-debug: debug object keys ───────────────────────────────────────────────


def test_debug_has_rolling_window_count():
    """AC-debug: successful call returns debug dict with 'rolling_window_count' key."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert "rolling_window_count" in debug


def test_debug_has_mean_of_fourth_powers():
    """AC-debug: successful call returns debug dict with 'mean_of_fourth_powers' key."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert "mean_of_fourth_powers" in debug


def test_debug_has_final_value():
    """AC-debug: successful call returns debug dict with 'final_value' key."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert "final_value" in debug


def test_debug_rolling_window_count_is_positive_integer():
    """AC-debug: rolling_window_count is a positive integer."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert isinstance(debug["rolling_window_count"], int)
    assert debug["rolling_window_count"] > 0


def test_debug_mean_of_fourth_powers_is_positive():
    """AC-debug: mean_of_fourth_powers is a positive number."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert debug["mean_of_fourth_powers"] > 0


# ── AC-final-value: final_value equals fourth root of mean_of_fourth_powers ──


def test_debug_final_value_is_fourth_root_of_mean():
    """AC-final-value: final_value must equal the fourth root of mean_of_fourth_powers."""
    _, debug = compute_normalized_power([200.0] * 60 + [300.0] * 60, 1)
    expected = debug["mean_of_fourth_powers"] ** 0.25
    assert abs(debug["final_value"] - expected) < 1e-9


# ── AC-window: window size derived from sample_interval_seconds ───────────────


def test_window_size_derived_from_sample_interval_half_second():
    """AC-window: 0.5-s interval → 60-sample window; 120 samples yields 61 windows."""
    # 30 s / 0.5 s per sample = 60-sample window
    # 120 samples − 60 window size + 1 = 61 windows
    samples = [250.0] * 120
    _, debug = compute_normalized_power(samples, 0.5)
    assert debug["rolling_window_count"] == 61


def test_window_size_derived_from_sample_interval_two_seconds():
    """AC-window: 2-s interval → 15-sample window; 60 samples yields 46 windows."""
    # 30 s / 2 s per sample = 15-sample window
    # 60 samples − 15 + 1 = 46 windows
    samples = [250.0] * 60
    _, debug = compute_normalized_power(samples, 2)
    assert debug["rolling_window_count"] == 46
