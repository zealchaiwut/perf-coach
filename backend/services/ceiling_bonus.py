"""Lagged ceiling bonus via delayed stimulus ramp (issue #1147).

Models the idea that economy stimulus should not immediately raise the score
ceiling.  Instead the bonus ramps up over a configurable lag window (default
6–12 weeks) so that recent sessions contribute very little and sustained
engagement builds the ceiling over time.

The kernel is triangular:
  - lag 0 … onset_days:   linear ramp from 0 to MAX_ONSET_FRACTION (≤ 5 %)
  - lag onset_days … peak_days: linear ramp from MAX_ONSET_FRACTION to 1.0
  - lag peak_days … window_days: linear decay from 1.0 to 0
  - lag > window_days:    exactly 0

This gives smooth decay (no cliff) when training stops, and ensures that the
bonus builds toward its peak over 6–12 weeks of sustained stimulus.

Pure function — no database access, no side effects.
"""

from __future__ import annotations

from datetime import date
from typing import Sequence, Tuple

# ── Default configuration constants ──────────────────────────────────────────

# Sessions within this many calendar days contribute ≤ MAX_ONSET_FRACTION of
# peak kernel weight.  One calendar week.
LAG_ONSET_DAYS: int = 7

# Kernel weight reaches its maximum at this lag.  6 weeks.
LAG_PEAK_DAYS: int = 42

# Sessions older than this many days contribute nothing.  12 weeks.
LAG_WINDOW_DAYS: int = 84

# Maximum fraction of peak weight allowed within the onset window (≤ 5 %).
MAX_ONSET_FRACTION: float = 0.05


# ── Kernel ────────────────────────────────────────────────────────────────────

def _kernel_weight(
    lag_days: int,
    *,
    onset_days: int,
    peak_days: int,
    window_days: int,
) -> float:
    """Return the triangular kernel weight for a session ``lag_days`` in the past.

    Values outside [0, window_days] return 0.0.  Within the onset window the
    weight is at most MAX_ONSET_FRACTION, ensuring recent sessions barely
    register.
    """
    if lag_days < 0 or lag_days > window_days:
        return 0.0
    if lag_days <= onset_days:
        # Ramp from 0 at lag=0 to MAX_ONSET_FRACTION at lag=onset_days.
        return MAX_ONSET_FRACTION * lag_days / onset_days if onset_days > 0 else 0.0
    if lag_days <= peak_days:
        # Ramp from MAX_ONSET_FRACTION at onset to 1.0 at peak.
        t = (lag_days - onset_days) / (peak_days - onset_days)
        return MAX_ONSET_FRACTION + (1.0 - MAX_ONSET_FRACTION) * t
    # Decay from 1.0 at peak to 0.0 at window boundary.
    t = (lag_days - peak_days) / (window_days - peak_days)
    return 1.0 - t


# ── Public API ────────────────────────────────────────────────────────────────

def compute_ceiling_bonus(
    stimulus_history: Sequence[Tuple[date, float]],
    reference_date: date,
    *,
    lag_onset_days: int = LAG_ONSET_DAYS,
    lag_peak_days: int = LAG_PEAK_DAYS,
    lag_window_days: int = LAG_WINDOW_DAYS,
) -> float:
    """Compute a lagged ceiling bonus from a time-series of stimulus values.

    Parameters
    ----------
    stimulus_history:
        Sequence of ``(session_date, stimulus_value)`` pairs.  Sessions with
        ``session_date > reference_date`` (negative lag) are silently ignored.
        ``stimulus_value`` should be non-negative (e.g. a TSS or per-session
        load value).
    reference_date:
        The date from which session lags are computed (typically "today").
    lag_onset_days:
        Sessions within this many calendar days contribute at most
        ``MAX_ONSET_FRACTION`` (5 %) of peak weight.  Default 7 days.
    lag_peak_days:
        The kernel reaches its maximum at this lag.  Default 42 days (6 weeks).
    lag_window_days:
        Sessions older than this many days contribute nothing.  The bonus
        decays smoothly to zero as sessions age toward this boundary.
        Default 84 days (12 weeks).

    Returns
    -------
    float
        Weighted sum of stimulus values.  Returns exactly ``0.0`` when
        ``stimulus_history`` is empty or all sessions fall outside the
        active kernel window.
    """
    if not stimulus_history:
        return 0.0

    total = 0.0
    for session_date, stimulus_value in stimulus_history:
        lag = (reference_date - session_date).days
        w = _kernel_weight(
            lag,
            onset_days=lag_onset_days,
            peak_days=lag_peak_days,
            window_days=lag_window_days,
        )
        total += w * max(0.0, float(stimulus_value))

    return total
