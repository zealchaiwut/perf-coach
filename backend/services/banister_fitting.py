"""Banister impulse-response model parameter fitting (issue #1203).

Provides ``fit_banister_params``, a pure function that estimates personalised
(τ₁, τ₂, k₁, k₂) from paired training-load / performance history.

The Banister model
------------------
Performance at time t is modelled as:

    P(t) = p₀ + k₁·g(t) − k₂·h(t)

where the fitness (g) and fatigue (h) impulse-response signals are computed
via the recurrences:

    g[t] = g[t−1]·exp(−1/τ₁) + w[t−1]
    h[t] = h[t−1]·exp(−1/τ₂) + w[t−1]

with g[0] = h[0] = 0 and w[t] the training load on day t.

Fitting strategy
----------------
τ₁ and τ₂ enter the model non-linearly; k₁, k₂, and p₀ appear linearly.
``scipy.optimize.curve_fit`` (or its equivalent) is used to minimise the sum
of squared residuals over all four parameters simultaneously.  The optimiser
runs with parameter bounds of [1, 90] for both τ values to keep the search
within the plausible physiological range.

Guard-rails (all return ``None``)
----------------------------------
1. **Data gate** — fewer than 14 paired observations.
2. **Plausibility check** — any fitted τ outside [1, 90] days.
3. **Convergence guard** — optimiser raises an exception (non-convergence,
   singular covariance matrix, runtime error, etc.).
"""

from __future__ import annotations

import math

# Minimum number of paired (load, performance) observations required before
# fitting is attempted.
MIN_FIT_PAIRS: int = 14

# Physiologically plausible range for τ (time constants, in days).
TAU_MIN: float = 1.0
TAU_MAX: float = 90.0


def validate_banister_fit(
    tau1: float,
    tau2: float,
    k1: float,
    k2: float,
) -> bool:
    """Return True if fitted Banister params pass post-fit plausibility checks.

    Called after a successful (non-None) ``fit_banister_params`` result to
    catch degenerate values that bypass the optimiser's internal guards (e.g.
    NaN / inf from edge-case data shapes).

    Checks:
    * All four values are finite (not NaN, not ±inf).
    * Both τ values lie within the physiological range [TAU_MIN, TAU_MAX].
    """
    if any(not math.isfinite(v) for v in (tau1, tau2, k1, k2)):
        return False
    if not (TAU_MIN <= tau1 <= TAU_MAX):
        return False
    if not (TAU_MIN <= tau2 <= TAU_MAX):
        return False
    return True


def fit_banister_params(
    load_series,
    perf_series,
) -> tuple[float, float, float, float] | None:
    """Estimate Banister model parameters from paired load/performance history.

    Parameters
    ----------
    load_series:
        Sequence of numeric daily training-load values (oldest first).
    perf_series:
        Sequence of numeric performance measurements paired with *load_series*.

    Returns
    -------
    ``(τ₁, τ₂, k₁, k₂)`` — four floats — when fitting succeeds, or ``None``
    when any guard-rail triggers:

    * fewer than 14 paired observations (data gate)
    * optimiser does not converge (convergence guard)
    * any fitted τ lies outside [1, 90] days (plausibility check)
    """
    # ── guard: invalid / missing input ──────────────────────────────────────
    if load_series is None or perf_series is None:
        return None

    try:
        loads = [float(x) for x in load_series]
        perfs = [float(x) for x in perf_series]
    except (TypeError, ValueError):
        return None

    # Use only the paired prefix (shortest series governs).
    n = min(len(loads), len(perfs))

    # ── guard: data gate (< 14 paired observations) ────────────────────────
    if n < MIN_FIT_PAIRS:
        return None

    loads = loads[:n]
    perfs = perfs[:n]

    # ── optimisation ────────────────────────────────────────────────────────
    try:
        result = _fit(loads, perfs)
    except Exception:
        return None

    if result is None:
        return None

    tau1, tau2, k1, k2 = result

    # ── guard: plausibility check ──────────────────────────────────────────
    if not (TAU_MIN <= tau1 <= TAU_MAX) or not (TAU_MIN <= tau2 <= TAU_MAX):
        return None

    return (float(tau1), float(tau2), float(k1), float(k2))


# ── internal helpers ────────────────────────────────────────────────────


def _banister_signals(loads: list[float], tau1: float, tau2: float):
    """Compute fitness (g) and fatigue (h) signals for the given τ values."""
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


def _fit(loads: list[float], perfs: list[float]):
    """Run the non-linear least-squares fit and return (τ₁, τ₂, k₁, k₂).

    Uses ``scipy.optimize.curve_fit`` with bounds [1, 90] on both τ values.
    Returns ``None`` on failure; propagates exceptions to the caller.
    """
    from scipy.optimize import curve_fit  # deferred import for portability

    # Degenerate guard: if loads have zero variance, the Banister signals g
    # and h are proportional to each other regardless of τ, giving the
    # optimiser nothing to work with for k₁ and k₂. Treat as failure.
    load_mean = sum(loads) / len(loads)
    load_var = sum((w - load_mean) ** 2 for w in loads)
    if load_var == 0.0:
        return None

    n = len(loads)

    def model(_, tau1, tau2, k1, k2, p0):
        gs, hs = _banister_signals(loads, tau1, tau2)
        return [p0 + k1 * gs[i] - k2 * hs[i] for i in range(n)]

    x_dummy = list(range(n))

    # Initial guess: τ₁=42 (fitness), τ₂=7 (fatigue), equal scale factors.
    perf_range = max(perfs) - min(perfs)
    scale = perf_range / max(load_mean, 1.0) if perf_range > 0 else 1.0
    p0_guess = min(perfs)
    p0_init = [42.0, 7.0, scale, scale, p0_guess]

    lower = [TAU_MIN, TAU_MIN, -1e6, -1e6, -1e9]
    upper = [TAU_MAX, TAU_MAX, 1e6, 1e6, 1e9]

    try:
        popt, _ = curve_fit(
            model,
            x_dummy,
            perfs,
            p0=p0_init,
            bounds=(lower, upper),
            maxfev=10_000,
        )
    except RuntimeError:
        # curve_fit raises RuntimeError on non-convergence.
        return None

    tau1, tau2, k1, k2, _p0 = popt

    # Reject degenerate solutions where τ₁ ≈ τ₂ (model collapses).
    if abs(tau1 - tau2) < 0.5:
        return None

    return (float(tau1), float(tau2), float(k1), float(k2))
