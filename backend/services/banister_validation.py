"""Banister impulse-response model validation via held-out MSE (issue #1205).

Provides ``validate_banister_fit``, which partitions paired training-load /
performance history 80/20 chronologically, runs both a set of fitted
parameters and a set of population-default parameters through the Banister
model on the held-out segment, and returns a comparison dict.

The Banister model
------------------
Performance at time t is:

    P(t) = p0 + k1·g(t) − k2·h(t)

where the fitness (g) and fatigue (h) impulse-response signals satisfy:

    g[t] = g[t−1]·exp(−1/τ₁) + w[t−1]
    h[t] = h[t−1]·exp(−1/τ₂) + w[t−1]

with g[0] = h[0] = 0 and w[t] the daily training load.

Validation strategy
-------------------
1. Split the paired series chronologically: first floor(n·0.8) points are the
   *training* segment; the remainder is the *held-out* segment.
2. For each parameter set, run the Banister signals forward through ALL data
   so that the held-out segment benefits from the warm-up accumulated during
   training.
3. Estimate the linear baseline p0 from the training segment only:
       p0 = mean(perf[i] − k1·g[i] + k2·h[i])  for i in train
4. Predict held-out performance and compute MSE.
5. Return {"fitted_mse", "default_mse", "improvement"} and log the result.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

# Population-default Banister parameters (τ₁, τ₂, k₁, k₂).
POPULATION_DEFAULT_PARAMS: tuple[float, float, float, float] = (42.0, 7.0, 1.0, 1.0)


def validate_banister_fit(
    load_series,
    perf_series,
    fitted_params: tuple[float, float, float, float],
    default_params: tuple[float, float, float, float],
    *,
    user_id: int | None = None,
) -> dict:
    """Validate fitted Banister parameters against population defaults via held-out MSE.

    Parameters
    ----------
    load_series:
        Sequence of numeric daily training-load values (oldest first).
    perf_series:
        Sequence of numeric performance measurements paired with load_series.
    fitted_params:
        ``(τ₁, τ₂, k₁, k₂)`` from the personalised fitting step.
    default_params:
        ``(τ₁, τ₂, k₁, k₂)`` population defaults to compare against.
    user_id:
        Optional; included in the structured log entry for traceability.

    Returns
    -------
    dict with keys:

    ``fitted_mse``
        Mean squared error of ``fitted_params`` predictions on the held-out
        segment.
    ``default_mse``
        Mean squared error of ``default_params`` predictions on the held-out
        segment.
    ``improvement``
        ``True`` when ``fitted_mse < default_mse``; ``False`` otherwise.
        Never raises on a regression — always returns the dict.
    """
    loads = [float(x) for x in load_series]
    perfs = [float(x) for x in perf_series]

    n = min(len(loads), len(perfs))
    loads = loads[:n]
    perfs = perfs[:n]

    train_size = max(1, math.floor(n * 0.8))

    fitted_mse = _compute_holdout_mse(loads, perfs, fitted_params, train_size)
    default_mse = _compute_holdout_mse(loads, perfs, default_params, train_size)

    improvement = fitted_mse < default_mse

    logger.info(
        "banister_validation user_id=%s fitted_mse=%.6f default_mse=%.6f improvement=%s",
        user_id,
        fitted_mse,
        default_mse,
        improvement,
    )

    return {
        "fitted_mse": fitted_mse,
        "default_mse": default_mse,
        "improvement": improvement,
    }


# ── internal helpers ──────────────────────────────────────────────────────────


def _banister_signals(loads: list[float], tau1: float, tau2: float):
    """Compute cumulative fitness (g) and fatigue (h) signals for all days."""
    alpha1 = math.exp(-1.0 / tau1)
    alpha2 = math.exp(-1.0 / tau2)
    g, h = 0.0, 0.0
    gs, hs = [], []
    for w in loads:
        g = g * alpha1 + w
        h = h * alpha2 + w
        gs.append(g)
        hs.append(h)
    return gs, hs


def _compute_holdout_mse(
    loads: list[float],
    perfs: list[float],
    params: tuple[float, float, float, float],
    train_size: int,
) -> float:
    """Run the Banister model over all data; return MSE on the held-out tail.

    The baseline p0 is estimated from the training segment only, ensuring
    no information from the held-out window leaks into the prediction.
    """
    tau1, tau2, k1, k2 = params

    gs, hs = _banister_signals(loads, tau1, tau2)

    # Estimate p0 from the training segment:
    #   P(t) = p0 + k1*g(t) - k2*h(t)  ⟹  p0 = P(t) - k1*g(t) + k2*h(t)
    residuals = [perfs[i] - k1 * gs[i] + k2 * hs[i] for i in range(train_size)]
    p0 = sum(residuals) / train_size

    holdout_indices = range(train_size, len(perfs))
    if not holdout_indices:
        return 0.0

    sse = sum(
        (perfs[i] - (p0 + k1 * gs[i] - k2 * hs[i])) ** 2
        for i in holdout_indices
    )
    return sse / len(holdout_indices)
