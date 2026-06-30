"""Score ceiling derived from projected CTL (issue #1106).

Maps a Chronic Training Load (CTL) projection to upper bounds on Endurance
and Speed performance scores.  This keeps the load-only ceiling path
self-contained and testable; economy-based refinement is applied via the
lagged ceiling bonus from ``backend.services.ceiling_bonus``.

The ceiling is a linear scale from CTL = 0 to CTL_CEILING_REFERENCE, clamped
to [0, SCORE_CEILING_MAX].  Both endurance and speed use the same reference
scale at this layer.  When strength/plyometric stimulus history is supplied
the economy ceiling bonus is computed and added to both ceilings before
clamping.

Pure function — no database access, no side effects.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Sequence, Tuple

from backend.services.ceiling_bonus import compute_ceiling_bonus

# ── Constants ─────────────────────────────────────────────────────────────────

# Absolute ceiling for any score dimension (0–100 scale).
SCORE_CEILING_MAX: float = 100.0

# CTL value at which the ceiling reaches SCORE_CEILING_MAX.
# Athletes rarely sustain CTL above ~150; capping at this reference keeps the
# scale meaningful without penalising very high-fitness outliers.
CTL_CEILING_REFERENCE: float = 150.0


# ── Public API ────────────────────────────────────────────────────────────────

def projected_ctl_to_score_ceiling(
    ctl: float,
    economy=None,  # kept for API stability — noop
    stimulus_history: Optional[Sequence[Tuple[date, float]]] = None,
    reference_date: Optional[date] = None,
) -> dict[str, float]:
    """Map projected CTL to Endurance and Speed score ceilings.

    Parameters
    ----------
    ctl:
        Projected Chronic Training Load (TSS-based EWMA, same scale as
        ``compute_fitness_series`` output).  Values ≤ 0 yield the minimum
        non-negative ceiling (0.0).
    economy:
        Accepted for API stability but ignored.
    stimulus_history:
        Optional sequence of ``(session_date, stimulus_value)`` pairs
        representing strength/plyometric session history.  When provided
        together with *reference_date*, the economy ceiling bonus is computed
        via ``compute_ceiling_bonus`` and added to both ceilings.  When
        ``None`` or empty the output is identical to the load-only baseline.
    reference_date:
        The date from which session lags are measured when computing the
        economy bonus.  Ignored when *stimulus_history* is ``None``.

    Returns
    -------
    dict with keys:
        ``endurance_ceiling`` — float in [0, SCORE_CEILING_MAX]
        ``speed_ceiling``     — float in [0, SCORE_CEILING_MAX]
    """
    raw = max(0.0, float(ctl)) / CTL_CEILING_REFERENCE * SCORE_CEILING_MAX
    base_ceiling = min(SCORE_CEILING_MAX, round(raw, 2))

    bonus = 0.0
    if stimulus_history is not None and reference_date is not None:
        bonus = compute_ceiling_bonus(stimulus_history, reference_date)

    ceiling = min(SCORE_CEILING_MAX, round(base_ceiling + bonus, 2))

    return {
        "endurance_ceiling": ceiling,
        "speed_ceiling": ceiling,
    }
