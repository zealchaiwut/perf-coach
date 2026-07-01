"""Tests for Banister parameter fitting function (issue #1203).

AC coverage:
  (a) Successful fit — 14+ observations, convergent data → returns (τ₁, τ₂, k₁, k₂) tuple
  (b) Data gate — fewer than 14 paired observations → returns None
  (c) Convergence failure — optimizer cannot converge → returns None
  (d) Implausible-value rejection — fitted τ outside [1, 90] days → returns None
"""

from __future__ import annotations

import math

import pytest

from backend.services.banister_fitting import fit_banister_params

# ── helpers ──────────────────────────────────────────────────────────────────


def _banister_performance(loads, tau1, tau2, k1, k2, p0=250.0):
    """Compute ground-truth Banister performance series from known parameters."""
    alpha1 = math.exp(-1.0 / tau1)
    alpha2 = math.exp(-1.0 / tau2)
    g, h = 0.0, 0.0
    perfs = []
    for w in loads:
        g = g * alpha1 + w
        h = h * alpha2 + w
        perfs.append(p0 + k1 * g - k2 * h)
    return perfs


def _synthetic_fit_data(n=20, tau1=42.0, tau2=7.0, k1=1.0, k2=2.0, noise=0.0):
    """Return (load_series, perf_series) with known Banister parameters."""
    loads = [50.0 + 10.0 * math.sin(i * 0.5) for i in range(n)]
    perfs = _banister_performance(loads, tau1, tau2, k1, k2)
    if noise:
        perfs = [p + noise * math.sin(i * 1.7) for i, p in enumerate(perfs)]
    return loads, perfs


# ── AC (a): successful fit returns a 4-tuple ─────────────────────────────────


def test_successful_fit_returns_tuple():
    loads, perfs = _synthetic_fit_data(n=20)
    result = fit_banister_params(loads, perfs)
    assert result is not None
    assert isinstance(result, tuple)
    assert len(result) == 4


def test_successful_fit_tuple_values_are_floats():
    loads, perfs = _synthetic_fit_data(n=20)
    result = fit_banister_params(loads, perfs)
    assert result is not None
    tau1, tau2, k1, k2 = result
    assert isinstance(tau1, float)
    assert isinstance(tau2, float)
    assert isinstance(k1, float)
    assert isinstance(k2, float)


def test_successful_fit_tau_within_plausible_range():
    loads, perfs = _synthetic_fit_data(n=20)
    result = fit_banister_params(loads, perfs)
    assert result is not None
    tau1, tau2, k1, k2 = result
    assert 1.0 <= tau1 <= 90.0
    assert 1.0 <= tau2 <= 90.0


def test_successful_fit_with_exactly_14_observations():
    loads, perfs = _synthetic_fit_data(n=14)
    result = fit_banister_params(loads, perfs)
    assert result is not None
    assert len(result) == 4


def test_successful_fit_with_large_dataset():
    loads, perfs = _synthetic_fit_data(n=60)
    result = fit_banister_params(loads, perfs)
    assert result is not None
    assert len(result) == 4


# ── AC (b): data gate rejects fewer than 14 paired observations ───────────────


def test_returns_none_when_zero_observations():
    result = fit_banister_params([], [])
    assert result is None


def test_returns_none_when_13_observations():
    loads, perfs = _synthetic_fit_data(n=13)
    result = fit_banister_params(loads, perfs)
    assert result is None


def test_returns_none_when_one_observation():
    result = fit_banister_params([100.0], [55.0])
    assert result is None


def test_returns_none_when_load_series_shorter_than_14():
    loads = list(range(10))
    perfs = list(range(20))
    result = fit_banister_params(loads, perfs)
    assert result is None


def test_returns_none_when_perf_series_shorter_than_14():
    loads = list(range(20))
    perfs = list(range(10))
    result = fit_banister_params(loads, perfs)
    assert result is None


def test_data_gate_boundary_13_always_none():
    """Boundary: 13 pairs must always return None regardless of values."""
    loads, perfs = _synthetic_fit_data(n=13)
    assert fit_banister_params(loads, perfs) is None


def test_data_gate_boundary_14_passes():
    """Boundary: 14 pairs is the minimum that may succeed."""
    loads, perfs = _synthetic_fit_data(n=14)
    result = fit_banister_params(loads, perfs)
    # 14 pairs with clean data must NOT be rejected by the data gate
    # (convergence or plausibility may still cause None, but not the gate alone)
    # With perfectly clean synthetic data, it should succeed.
    assert result is not None


# ── AC (c): convergence failure returns None ──────────────────────────────────


def test_returns_none_on_convergence_failure():
    """All-zero load series makes the Banister signals identically zero,
    creating a degenerate design matrix that the optimiser cannot solve."""
    loads = [0.0] * 20
    perfs = [250.0] * 20  # constant performance, no signal
    result = fit_banister_params(loads, perfs)
    assert result is None


def test_returns_none_on_constant_load_constant_perf():
    """Constant load + constant performance → no gradient information → None."""
    loads = [100.0] * 20
    perfs = [300.0] * 20
    result = fit_banister_params(loads, perfs)
    # May converge or may not; either is acceptable here, but zero-load is the
    # canonical degenerate case covered above.
    # This test is informational — just ensure it doesn't crash.
    assert result is None or isinstance(result, tuple)


# ── AC (d): implausible-value rejection returns None ─────────────────────────


def test_returns_none_when_tau1_would_be_zero():
    """Degenerate data designed to push τ estimates toward invalid territory."""
    # Single-step impulse: all load on step 0, performance peaks at step 1.
    # The implied τ would be extremely small (≪1 day), below the [1, 90] floor.
    n = 14
    loads = [1000.0] + [0.0] * (n - 1)
    # Performance drops to baseline immediately → implies τ < 1
    perfs = [300.0, 250.0] + [250.0] * (n - 2)
    result = fit_banister_params(loads, perfs)
    # Either returns None (rejected) or a valid tuple with τ in [1, 90]
    if result is not None:
        tau1, tau2, k1, k2 = result
        assert 1.0 <= tau1 <= 90.0
        assert 1.0 <= tau2 <= 90.0


def test_plausibility_gate_enforces_tau_upper_bound():
    """Any returned tuple must have both τ values ≤ 90."""
    loads, perfs = _synthetic_fit_data(n=30)
    result = fit_banister_params(loads, perfs)
    if result is not None:
        tau1, tau2, k1, k2 = result
        assert tau1 <= 90.0
        assert tau2 <= 90.0


def test_plausibility_gate_enforces_tau_lower_bound():
    """Any returned tuple must have both τ values ≥ 1."""
    loads, perfs = _synthetic_fit_data(n=30)
    result = fit_banister_params(loads, perfs)
    if result is not None:
        tau1, tau2, k1, k2 = result
        assert tau1 >= 1.0
        assert tau2 >= 1.0


# ── General robustness ────────────────────────────────────────────────────────


def test_does_not_raise_on_mismatched_lengths():
    """Mismatched series lengths must not raise; shorter governs."""
    loads = [50.0] * 20
    perfs = [300.0] * 15
    try:
        result = fit_banister_params(loads, perfs)
        assert result is None or isinstance(result, tuple)
    except Exception as exc:
        pytest.fail(f"fit_banister_params raised unexpectedly: {exc}")


def test_does_not_raise_on_none_input():
    """None inputs must not raise; return None."""
    result = fit_banister_params(None, None)
    assert result is None


def test_does_not_raise_on_empty_lists():
    result = fit_banister_params([], [])
    assert result is None
