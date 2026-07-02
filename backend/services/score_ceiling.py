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
from backend.services.vdot import vdot_from_pace_duration, rescale_to_score

# ── Constants ─────────────────────────────────────────────────────────────────

# Absolute ceiling for any score dimension (0–100 scale).
SCORE_CEILING_MAX: float = 100.0

# CTL value at which the ceiling reaches SCORE_CEILING_MAX.
# Athletes rarely sustain CTL above ~150; capping at this reference keeps the
# scale meaningful without penalising very high-fitness outliers.
CTL_CEILING_REFERENCE: float = 150.0

# How far the CTL-derived projected ceiling may exceed the athlete's current
# VDOT-band score. The projection lifts the ceiling as fitness builds, but not
# by an implausible amount over what's demonstrated now (a headroom cap).
CTL_CEILING_HEADROOM: float = 20.0


# ── Public API ────────────────────────────────────────────────────────────────

def projected_ctl_to_score_ceiling(
    ctl: float,
    economy=None,  # kept for API stability — noop
    stimulus_history: Optional[Sequence[Tuple[date, float]]] = None,
    reference_date: Optional[date] = None,
    current_score: Optional[float] = None,
    race_ceiling: Optional[float] = None,
) -> dict[str, float]:
    """Map projected CTL to Endurance and Speed score ceilings (VDOT-aware).

    The base ceiling is still the CTL scale (fitness builds → ceiling rises), but
    it is now kept SANE on the VDOT band:
      - anchored to the athlete's ``current_score`` on that band (the projected
        ceiling should sit near, and grow modestly above, what's demonstrated
        today — CTL_CEILING_HEADROOM points of headroom), and
      - capped at a demonstrated ``race_ceiling`` + headroom when a real race is
        available, so the projection can't wildly exceed what was actually raced.

    Parameters
    ----------
    ctl:
        Projected Chronic Training Load. Values ≤ 0 yield 0.0.
    economy:
        Accepted for API stability but ignored.
    stimulus_history / reference_date:
        Optional strength/plyo stimulus → economy ceiling bonus (unchanged).
    current_score:
        The athlete's current VDOT-band score (endurance). When provided, the
        ceiling is anchored at max(CTL-scale, current) and capped at
        current + CTL_CEILING_HEADROOM so it stays believable.
    race_ceiling:
        A demonstrated-race score on the VDOT band. When provided, caps the
        ceiling at race_ceiling + CTL_CEILING_HEADROOM.

    Returns
    -------
    dict with keys ``endurance_ceiling`` and ``speed_ceiling``.
    """
    raw = max(0.0, float(ctl)) / CTL_CEILING_REFERENCE * SCORE_CEILING_MAX
    base_ceiling = min(SCORE_CEILING_MAX, round(raw, 2))

    bonus = 0.0
    if stimulus_history is not None and reference_date is not None:
        bonus = compute_ceiling_bonus(stimulus_history, reference_date)

    ceiling = base_ceiling + bonus

    # Keep the CTL-derived ceiling sane on the VDOT band: not far above what's
    # currently demonstrated, and not far above a real race result.
    if current_score is not None:
        try:
            cs = float(current_score)
            ceiling = max(ceiling, cs)
            ceiling = min(ceiling, cs + CTL_CEILING_HEADROOM)
        except (TypeError, ValueError):
            pass
    if race_ceiling is not None:
        try:
            rc = float(race_ceiling)
            ceiling = min(ceiling, rc + CTL_CEILING_HEADROOM)
        except (TypeError, ValueError):
            pass

    ceiling = min(SCORE_CEILING_MAX, max(0.0, round(ceiling, 2)))

    return {
        "endurance_ceiling": ceiling,
        "speed_ceiling": ceiling,
    }


def ceiling_from_b_race_result(
    actual_time_seconds: int,
    distance_km: float,
    threshold_pace_spm: float,
) -> dict[str, float]:
    """Derive score ceilings from a B race actual finish result — VDOT (issue #1162).

    Re-anchored onto the universal VDOT band: the race's actual pace + duration
    → ``vdot_from_pace_duration`` → ``rescale_to_score`` gives the demonstrated
    score on the SAME band as the Endurance/Speed scores (no linear pace
    inversion). This lets the projection re-anchor its ceiling to what the
    athlete actually raced.

    ``threshold_pace_spm`` is retained in the signature for API stability but is
    no longer needed by the VDOT mapping (it is only sanity-checked > 0).

    Parameters
    ----------
    actual_time_seconds:
        Recorded finish time in seconds.  Values ≤ 0 return a zero ceiling.
    distance_km:
        Race distance in kilometres.  Values ≤ 0 return a zero ceiling.
    threshold_pace_spm:
        Athlete's threshold pace (s/km).  Values ≤ 0 return a zero ceiling
        (kept for signature stability).

    Returns
    -------
    dict with keys ``endurance_ceiling`` and ``speed_ceiling``, both
    clamped to ``[0, SCORE_CEILING_MAX]``.
    """
    if actual_time_seconds <= 0 or distance_km <= 0 or threshold_pace_spm <= 0:
        return {"endurance_ceiling": 0.0, "speed_ceiling": 0.0}
    # race velocity (m/min) and duration (min) → VDOT → band score.
    velocity_m_per_min = (distance_km * 1000.0) / (actual_time_seconds / 60.0)
    duration_min = actual_time_seconds / 60.0
    vdot = vdot_from_pace_duration(velocity_m_per_min, duration_min)
    score = rescale_to_score(vdot)
    ceiling = min(SCORE_CEILING_MAX, max(0.0, round(score, 2)))
    return {"endurance_ceiling": ceiling, "speed_ceiling": ceiling}
