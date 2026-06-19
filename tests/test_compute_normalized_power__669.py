"""Tests for issue #669: Add compute_normalized_power pure function.

Acceptance criteria covered:
  AC-exists        — function exists, is callable, has a docstring
  AC-docstring     — docstring includes a worked example for 250 W steady input
  AC-steady        — 120 samples at 250 W with 1-s interval → integer 250
  AC-variable      — variable input returns a non-null integer
  AC-null          — power_samples=None → (None, {"reason": ...})
  AC-empty         — power_samples=[] → (None, {"reason": ...})
  AC-short         — total duration < 30 s → (None, {"reason": ...})
  AC-boundary      — exactly 30 s total duration → non-null result (inclusive boundary)
  AC-fourth-power  — each rolling average is raised to the fourth power
  AC-mean          — mean of fourth-power values is computed
  AC-fourth-root   — fourth root of mean is the final (pre-rounding) value
  AC-integer       — returned watts value is int, not float
  AC-debug         — debug dict has rolling_window_count, mean_of_fourth_powers, final_value
  AC-window-30s    — rolling window is exactly 30 s (derived from sample_interval_seconds)
  AC-no-side-effects — calling the function twice gives identical results (pure)
  AC-no-hardcode   — 30-second window duration is a parameter, not a module constant
"""

import inspect

from backend.services.normalized_power import compute_normalized_power


# ── AC-exists: function callable with correct signature ───────────────────────


def test_function_exists_and_is_callable():
    """AC-exists: compute_normalized_power is importable and callable."""
    assert callable(compute_normalized_power)


def test_function_accepts_two_positional_args():
    """AC-exists: function signature includes power_samples and sample_interval_seconds."""
    sig = inspect.signature(compute_normalized_power)
    params = list(sig.parameters)
    assert "power_samples" in params
    assert "sample_interval_seconds" in params


# ── AC-docstring: docstring with worked example ──────────────────────────────


def test_docstring_exists():
    """AC-docstring: function has a non-empty docstring."""
    assert compute_normalized_power.__doc__
    assert len(compute_normalized_power.__doc__.strip()) > 0


def test_docstring_contains_250_watt_example():
    """AC-docstring: docstring includes worked example with 250-watt steady stream."""
    doc = compute_normalized_power.__doc__
    assert "250" in doc


# ── AC-steady: steady 250 W → NP = 250 ───────────────────────────────────────


def test_steady_250w_returns_integer_250():
    """AC-steady: 120 samples at 250 W, 1-s interval → integer result of 250."""
    watts, debug = compute_normalized_power([250.0] * 120, 1)
    assert watts == 250
    assert isinstance(watts, int)


def test_steady_debug_rolling_window_count():
    """AC-steady: 120 samples with 30-sample window → 91 rolling windows."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert debug["rolling_window_count"] == 91


def test_steady_debug_mean_fourth_power():
    """AC-steady: steady 250 W → mean of fourth powers ≈ 3,906,250,000."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert abs(debug["mean_of_fourth_powers"] - 3_906_250_000.0) < 1.0


def test_steady_debug_final_value():
    """AC-steady: debug final_value ≈ 250.0 for steady 250 W input."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert abs(debug["final_value"] - 250.0) < 0.01


# ── AC-variable: variable input returns value > arithmetic mean ───────────────


def test_variable_input_returns_non_null_integer():
    """AC-variable: alternating 100 W / 400 W input returns a non-null integer."""
    samples = ([100.0] * 10 + [400.0] * 10) * 3  # 60 samples, 60 s
    watts, _ = compute_normalized_power(samples, 1)
    assert watts is not None
    assert isinstance(watts, int)


def test_variable_input_exceeds_arithmetic_mean():
    """AC-variable: fourth-power weighting causes NP to exceed the arithmetic mean."""
    samples = ([100.0] * 10 + [400.0] * 10) * 3
    arithmetic_mean = sum(samples) / len(samples)  # 250.0
    watts, _ = compute_normalized_power(samples, 1)
    assert watts > arithmetic_mean


# ── AC-null: None power_samples → (None, reason) ─────────────────────────────


def test_null_samples_first_element_is_none():
    """AC-null: None power_samples → first return element is None."""
    watts, info = compute_normalized_power(None, 1)
    assert watts is None


def test_null_samples_reason_present_and_non_empty():
    """AC-null: None input → info dict has non-empty 'reason' string."""
    _, info = compute_normalized_power(None, 1)
    assert "reason" in info
    assert isinstance(info["reason"], str)
    assert len(info["reason"]) > 0


# ── AC-empty: [] → (None, reason) ────────────────────────────────────────────


def test_empty_samples_first_element_is_none():
    """AC-empty: empty list → first return element is None."""
    watts, info = compute_normalized_power([], 1)
    assert watts is None


def test_empty_samples_reason_present_and_non_empty():
    """AC-empty: empty list → info dict has non-empty 'reason' string."""
    _, info = compute_normalized_power([], 1)
    assert "reason" in info
    assert isinstance(info["reason"], str)
    assert len(info["reason"]) > 0


# ── AC-short: total duration < 30 s → (None, reason) ─────────────────────────


def test_20s_duration_returns_none():
    """AC-short: 20 samples at 1-s interval (20 s total) → None."""
    watts, info = compute_normalized_power([250.0] * 20, 1)
    assert watts is None


def test_short_duration_reason_present():
    """AC-short: insufficient duration → info dict has non-empty 'reason' string."""
    _, info = compute_normalized_power([250.0] * 20, 1)
    assert "reason" in info
    assert isinstance(info["reason"], str)
    assert len(info["reason"]) > 0


# ── AC-boundary: exactly 30 s total is inclusive ─────────────────────────────


def test_exactly_30s_returns_non_null():
    """AC-boundary: 30 samples at 1-s interval (exactly 30 s) → non-null result."""
    watts, _ = compute_normalized_power([250.0] * 30, 1)
    assert watts is not None


# ── AC-fourth-power, AC-mean, AC-fourth-root: algorithm correctness ───────────


def test_rolling_averages_raised_to_fourth_power():
    """AC-fourth-power: mean_of_fourth_powers reflects ^4 weighting."""
    samples = [200.0] * 60
    _, debug = compute_normalized_power(samples, 1)
    expected_fourth_power = 200.0 ** 4
    assert abs(debug["mean_of_fourth_powers"] - expected_fourth_power) < 1.0


def test_final_value_is_fourth_root_of_mean():
    """AC-fourth-root: final_value equals fourth root of mean_of_fourth_powers."""
    samples = [300.0] * 60
    _, debug = compute_normalized_power(samples, 1)
    expected = debug["mean_of_fourth_powers"] ** 0.25
    assert abs(debug["final_value"] - expected) < 1e-9


# ── AC-integer: returned watts is int ────────────────────────────────────────


def test_return_type_is_int_not_float():
    """AC-integer: successful call returns int, not float."""
    watts, _ = compute_normalized_power([300.0] * 60, 1)
    assert isinstance(watts, int)


# ── AC-debug: debug object structure ─────────────────────────────────────────


def test_debug_has_all_required_keys():
    """AC-debug: debug dict contains rolling_window_count, mean_of_fourth_powers, final_value."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert "rolling_window_count" in debug
    assert "mean_of_fourth_powers" in debug
    assert "final_value" in debug


def test_debug_rolling_window_count_is_positive_int():
    """AC-debug: rolling_window_count is a positive integer."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert isinstance(debug["rolling_window_count"], int)
    assert debug["rolling_window_count"] > 0


def test_debug_mean_of_fourth_powers_is_positive():
    """AC-debug: mean_of_fourth_powers is a positive number."""
    _, debug = compute_normalized_power([250.0] * 120, 1)
    assert debug["mean_of_fourth_powers"] > 0


# ── AC-window-30s: rolling window derived from sample_interval_seconds ────────


def test_window_size_derived_at_half_second_interval():
    """AC-window-30s: 0.5-s interval → 60-sample window; 120 samples → 61 windows."""
    _, debug = compute_normalized_power([250.0] * 120, 0.5)
    assert debug["rolling_window_count"] == 61


def test_window_size_derived_at_two_second_interval():
    """AC-window-30s: 2-s interval → 15-sample window; 60 samples → 46 windows."""
    _, debug = compute_normalized_power([250.0] * 60, 2)
    assert debug["rolling_window_count"] == 46


# ── AC-no-side-effects: pure function ────────────────────────────────────────


def test_identical_calls_return_identical_results():
    """AC-no-side-effects: same inputs always produce same outputs (pure function)."""
    samples = [200.0, 300.0] * 40  # 80 samples
    result_a = compute_normalized_power(samples, 1)
    result_b = compute_normalized_power(samples, 1)
    assert result_a == result_b


# ── AC-no-hardcode: window_duration_seconds is a parameter ───────────────────


def test_window_duration_is_a_parameter():
    """AC-no-hardcode: window_duration_seconds appears as a named parameter in the signature."""
    sig = inspect.signature(compute_normalized_power)
    assert "window_duration_seconds" in sig.parameters


def test_window_duration_defaults_to_30():
    """AC-no-hardcode: default window_duration_seconds is 30 (the NP standard)."""
    sig = inspect.signature(compute_normalized_power)
    default = sig.parameters["window_duration_seconds"].default
    assert default == 30


def test_custom_window_duration_changes_behavior():
    """AC-no-hardcode: passing a different window_duration_seconds changes the window size.

    With a 10-second window and 1-s interval: window_size = 10 samples.
    40 samples → 31 windows.
    """
    _, debug = compute_normalized_power([250.0] * 40, 1, window_duration_seconds=10)
    assert debug["rolling_window_count"] == 31


def test_custom_window_short_data_allowed():
    """AC-no-hardcode: 15 samples that would fail the 30-s check pass a 10-s window."""
    watts, _ = compute_normalized_power([250.0] * 15, 1, window_duration_seconds=10)
    assert watts is not None
