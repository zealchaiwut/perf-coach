"""Banister held-out MSE validation (issue #1205).

Provides ``validate_banister_fit``, which compares fitted vs population
Banister parameters on a held-out test set to confirm that personalised
parameters actually outperform population defaults.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


def validate_banister_fit(
    load_series,
    perf_series,
    fitted_params,
    default_params,
) -> dict | None:
    """Compare fitted vs default Banister parameters on held-out data.

    Splits the input chronologically 80 / 20 (train / held-out), trains
    (discarded; assumes input is already fitted), then evaluates both
    parameter sets forward through the Banister model on the held-out segment.

    Parameters
    ----------
    load_series:
        Sequence of numeric daily training-load values (oldest first).
    perf_series:
        Sequence of numeric performance measurements paired with *load_series*.
    fitted_params:
        Tuple (τ₁, τ₂, k₁, k₂) — estimated personalised parameters.
    default_params:
        Tuple (τ₁, τ₂, k₁, k₂) — population / fallback parameters.

    Returns
    -------
    dict with keys ``fitted_mse``, ``default_mse``, and ``improvement``
    (bool; True iff fitted_mse < default_mse), or None on invalid input.
    """
    # ── guard: invalid input ────────────────────────────────────────────────
    if (
        load_series is None
        or perf_series is None
        or fitted_params is None
        or default_params is None
    ):
        return None

    try:
        loads = [float(x) for x in load_series]
        perfs = [float(x) for x in perf_series]
    except (TypeError, ValueError):
        return None

    if not loads or not perfs or len(loads) != len(perfs):
        return None

    try:
        tau1_f, tau2_f, k1_f, k2_f = fitted_params
        tau1_d, tau2_d, k1_d, k2_d = default_params
    except (TypeError, ValueError):
        return None

    # ── partition: chronological 80/20 split ────────────────────────────────
    n = len(loads)
    train_size = max(1, int(0.8 * n))
    test_size = n - train_size

    if test_size < 1:
        # Entire dataset is training; no held-out set. Return None.
        return None

    train_loads = loads[:train_size]
    test_loads = loads[train_size:]
    test_perfs = perfs[train_size:]

    # ── compute Banister signals on held-out data ───────────────────────────
    # For each param set, compute g/h from training, then forecast on test.

    def _banister_signals_and_forecast(
            loads_train, loads_test, tau1, tau2, k1, k2):
        """Compute g, h from training data, then forecast on test data."""
        alpha1 = math.exp(-1.0 / tau1)
        alpha2 = math.exp(-1.0 / tau2)

        # Initialize from training data
        g, h = 0.0, 0.0
        for w in loads_train:
            g = g * alpha1 + w
            h = h * alpha2 + w

        # Forecast on test data
        forecasts = []
        for w in loads_test:
            g = g * alpha1 + w
            h = h * alpha2 + w
            forecast = 250.0 + k1 * g - k2 * h
            forecasts.append(forecast)

        return forecasts

    # Use the same p0 = 250.0 baseline for both (AC does not specify, using
    # convention)
    fitted_forecasts = _banister_signals_and_forecast(
        train_loads, test_loads, tau1_f, tau2_f, k1_f, k2_f
    )
    default_forecasts = _banister_signals_and_forecast(
        train_loads, test_loads, tau1_d, tau2_d, k1_d, k2_d
    )

    # ── compute MSE ──────────────────────────────────────────────────────────
    fitted_mse = (
        sum((test_perfs[i] - fitted_forecasts[i])
            ** 2 for i in range(test_size))
        / test_size
    )
    default_mse = (
        sum((test_perfs[i] - default_forecasts[i])
            ** 2 for i in range(test_size))
        / test_size
    )

    improvement = fitted_mse < default_mse

    result = {
        "fitted_mse": float(fitted_mse),
        "default_mse": float(default_mse),
        "improvement": improvement,
    }

    # ── log the result ───────────────────────────────────────────────────────
    logger.info(
        "Banister validation: fitted_mse=%.4f, default_mse=%.4f,"
        " improvement=%s",
        fitted_mse,
        default_mse,
        improvement,
    )

    return result
