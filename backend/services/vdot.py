"""Shared VDOT helper — universal VO2-equivalent fitness band (issue: score re-anchor).

Pure functions, no DB / no FastAPI. This is the single source of truth for the
VDOT math so the later Projection-estimator rework can reuse it. See
docs/calculations/score-reanchor-proposal.md (§4) for the decided design.

VDOT (Daniels/Gilbert) is a VO2max-equivalent derived from a race/effort's pace
and duration. The displayed 0–100 band is a linear rescale of VDOT so any
athlete's efforts land on the same absolute scale.

Tuning knobs (one line each):
    VDOT_FLOOR / VDOT_CEIL — the band endpoints (VDOT 30 → 0, 85 → 100).
    GRACE_WEEKS            — weeks of no-decay grace after an effort.
    DECAY_PER_WEEK         — points/week a best effort loses after the grace.
    TOP_K                  — how many decayed efforts the aggregate averages.
"""
from __future__ import annotations

import math

# ── Tunable constants (proposal §4) ───────────────────────────────────────────
VDOT_FLOOR = 30.0
VDOT_CEIL = 85.0
GRACE_WEEKS = 2
DECAY_PER_WEEK = 1.5
TOP_K = 3


def vdot_from_pace_duration(velocity_m_per_min: float, duration_min: float) -> float:
    """VDOT (VO2max-equivalent) from sustained velocity and effort duration.

    Daniels/Gilbert:
        VO2      = −4.60 + 0.182258·v + 0.000104·v²          (v in m/min)
        %VO2max  = 0.8 + 0.1894393·e^(−0.012778·t)
                       + 0.2989558·e^(−0.1932605·t)          (t in min)
        VDOT     = VO2 / %VO2max

    Returns 0.0 for non-positive / non-finite inputs (caller treats as
    unqualifying rather than crashing).
    """
    v = velocity_m_per_min
    t = duration_min
    if not (isinstance(v, (int, float)) and isinstance(t, (int, float))):
        return 0.0
    if v <= 0 or t <= 0 or not math.isfinite(v) or not math.isfinite(t):
        return 0.0

    vo2 = -4.60 + 0.182258 * v + 0.000104 * v * v
    pct = (
        0.8
        + 0.1894393 * math.exp(-0.012778 * t)
        + 0.2989558 * math.exp(-0.1932605 * t)
    )
    if pct <= 0:
        return 0.0
    vdot = vo2 / pct
    return vdot if vdot > 0 else 0.0


def vdot_from_pace_seconds(pace_seconds_per_km: float, duration_min: float) -> float:
    """Convenience: VDOT from pace (s/km) + duration (min).

    velocity = 1000 m / (pace_seconds_per_km / 60) m·min⁻¹.
    """
    if not pace_seconds_per_km or pace_seconds_per_km <= 0:
        return 0.0
    velocity_m_per_min = 1000.0 / (pace_seconds_per_km / 60.0)
    return vdot_from_pace_duration(velocity_m_per_min, duration_min)


def rescale_to_score(vdot: float) -> float:
    """Map a VDOT to the displayed 0–100 band: (VDOT − 30) / 55 × 100, clamped."""
    if not isinstance(vdot, (int, float)) or not math.isfinite(vdot):
        return 0.0
    span = VDOT_CEIL - VDOT_FLOOR
    score = (vdot - VDOT_FLOOR) / span * 100.0
    return max(0.0, min(100.0, score))


def decay_points(days: float) -> float:
    """Points a best effort loses `days` after it: 1.5 × max(0, days/7 − 2).

    Two-week grace (no decay), then DECAY_PER_WEEK points per week thereafter.
    """
    if days is None or days <= 0:
        return 0.0
    weeks = days / 7.0
    return DECAY_PER_WEEK * max(0.0, weeks - GRACE_WEEKS)
