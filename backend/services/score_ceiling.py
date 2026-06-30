"""Score ceiling derived from projected CTL (issue #1106).

Maps a Chronic Training Load (CTL) projection to upper bounds on Endurance
and Speed performance scores.  This keeps the load-only ceiling path
self-contained and testable; economy-based refinement is deferred to Layer 4.

The ceiling is a linear scale from CTL = 0 to CTL_CEILING_REFERENCE, clamped
to [0, SCORE_CEILING_MAX].  Both endurance and speed use the same reference
scale at this layer; Layer 4 may introduce economy-weighted divergence between
the two ceilings.

Pure function — no database access, no side effects.
"""

from __future__ import annotations

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
    economy=None,  # TODO Layer 4 — wire real running-economy value here
) -> dict[str, float]:
    """Map projected CTL to Endurance and Speed score ceilings.

    Parameters
    ----------
    ctl:
        Projected Chronic Training Load (TSS-based EWMA, same scale as
        ``compute_fitness_series`` output).  Values ≤ 0 yield the minimum
        non-negative ceiling (0.0).
    economy:
        Stubbed — accepted for API stability but ignored.
        Layer 4 will supply a real economy coefficient (e.g. running economy
        in kcal/kg/km or a W/kg ratio) to diverge endurance and speed ceilings.

    Returns
    -------
    dict with keys:
        ``endurance_ceiling`` — float in [0, SCORE_CEILING_MAX]
        ``speed_ceiling``     — float in [0, SCORE_CEILING_MAX]
    """
    raw = max(0.0, float(ctl)) / CTL_CEILING_REFERENCE * SCORE_CEILING_MAX
    ceiling = min(SCORE_CEILING_MAX, round(raw, 2))

    return {
        "endurance_ceiling": ceiling,
        "speed_ceiling": ceiling,
    }
