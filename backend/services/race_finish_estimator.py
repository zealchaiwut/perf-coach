"""Convert an expressible fitness score to an estimated race finish time — VDOT.

Pure function module — no database access, no side effects.

The "expressible score" is a 0–100 fitness indicator on the same **universal
VDOT band** as the Endurance/Speed scores (see backend/services/vdot.py). This
module maps that score to a predicted race pace at the race's own distance, then
multiplies by the distance to produce the finish time.

Model (VDOT-based, re-anchored)
-------------------------------
1. score → VDOT via the inverse band rescale (vdot.py constants FLOOR/CEIL):
       VDOT = score/100 × (VDOT_CEIL − VDOT_FLOOR) + VDOT_FLOOR
2. VDOT → predicted race pace at the race distance by inverting
   ``vdot_from_pace_duration``. The Daniels %VO2max term depends on the effort
   DURATION, and duration = pace × distance, so we iterate: guess a pace →
   duration → %VO2max → the velocity that yields this VDOT at that duration →
   new pace, repeating to convergence.
3. finish_time = predicted_pace × distance.

Higher score → higher VDOT → faster pace → shorter finish time (monotonic),
preserving the property the linear model guaranteed. The threshold pace is now
only a *fallback* reference when VDOT constants are unavailable.

Worked example (Daniels sanity)
-------------------------------
A VDOT-49.8 athlete (5k in 20:00) over 5 km: the solver converges to ≈240 s/km
→ 20:00, matching Daniels. On the recreational band (15/58) that VDOT is
score ≈ 81.
"""
from __future__ import annotations

import math

from backend.services.vdot import VDOT_FLOOR, VDOT_CEIL

# ── Constants ─────────────────────────────────────────────────────────────────

# Retained for the fallback path / backward-compat imports. The primary model is
# now VDOT-based; SLOW_FACTOR only drives the threshold-pace fallback used when a
# VDOT cannot be formed (e.g. score maps to VDOT ≤ 0).
SLOW_FACTOR: float = 2.0

# Iteration controls for inverting vdot_from_pace_duration.
_MAX_ITERS = 40
_TOL_SECONDS_PER_KM = 0.05


def score_to_vdot(score: float) -> float:
    """Inverse band rescale: 0–100 score → VDOT (vdot.py FLOOR/CEIL constants)."""
    s = max(0.0, min(100.0, float(score)))
    return s / 100.0 * (VDOT_CEIL - VDOT_FLOOR) + VDOT_FLOOR


def _velocity_for_vdot_at_duration(target_vdot: float, duration_min: float) -> float | None:
    """Velocity (m/min) that yields target_vdot at a fixed effort duration.

    Inverts VO2 = %VO2max(t) × VDOT for the fixed t, then solves the quadratic
    VO2 = −4.60 + 0.182258·v + 0.000104·v² for v.
    """
    if duration_min <= 0:
        return None
    pct = (
        0.8
        + 0.1894393 * math.exp(-0.012778 * duration_min)
        + 0.2989558 * math.exp(-0.1932605 * duration_min)
    )
    vo2 = pct * target_vdot
    # 0.000104 v² + 0.182258 v + (−4.60 − vo2) = 0
    a = 0.000104
    b = 0.182258
    c = -4.60 - vo2
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    v = (-b + math.sqrt(disc)) / (2 * a)
    return v if v > 0 else None


def vdot_to_race_pace_seconds(target_vdot: float, distance_km: float) -> float | None:
    """Predicted race pace (s/km) for a VDOT over a distance, by iteration.

    duration depends on pace and pace depends (via %VO2max) on duration, so we
    fixed-point iterate from an initial guess until the pace converges.
    """
    if target_vdot <= 0 or distance_km <= 0:
        return None
    # Initial guess: a moderate 5:00/km, then converge.
    pace = 300.0
    for _ in range(_MAX_ITERS):
        duration_min = pace * distance_km / 60.0
        v = _velocity_for_vdot_at_duration(target_vdot, duration_min)
        if v is None or v <= 0:
            return None
        new_pace = 1000.0 / (v / 60.0)  # s/km
        if abs(new_pace - pace) < _TOL_SECONDS_PER_KM:
            pace = new_pace
            break
        pace = new_pace
    return pace if pace > 0 else None


# ── Public API ────────────────────────────────────────────────────────────────

def score_to_estimated_finish_time(
    score: float | None,
    thresholds: dict | None,
    distance_km: float | None,
) -> dict:
    """Convert an expressible fitness score to an estimated race finish time.

    VDOT-based: score → VDOT → predicted pace at the race distance → finish time.
    Falls back to the old linear threshold-pace model only when a positive VDOT
    pace can't be formed (and a threshold pace is available).

    Returns a dict with ``estimated_finish_seconds`` / ``estimated_finish_time``
    (None on failure) and a ``reason`` (None on success).
    """
    _null = {"estimated_finish_seconds": None, "estimated_finish_time": None}

    if score is None:
        return {**_null, "reason": "score is None"}

    if distance_km is None:
        return {**_null, "reason": "distance_km is None"}
    try:
        distance_km = float(distance_km)
    except (TypeError, ValueError):
        return {**_null, "reason": "distance_km is not numeric"}
    if distance_km <= 0:
        return {**_null, "reason": "distance_km must be positive"}

    clamped_score = max(0.0, min(100.0, float(score)))

    # Primary: VDOT-based estimate.
    target_vdot = score_to_vdot(clamped_score)
    pace = vdot_to_race_pace_seconds(target_vdot, distance_km)

    if pace is None:
        # Fallback: linear threshold-pace model (only if a threshold is set).
        threshold_pace = None
        if isinstance(thresholds, dict):
            threshold_pace = thresholds.get("threshold_pace_seconds_per_km")
        if threshold_pace is None:
            return {**_null, "reason": "could not form a VDOT pace and no threshold_pace fallback"}
        try:
            threshold_pace = float(threshold_pace)
        except (TypeError, ValueError):
            return {**_null, "reason": "threshold_pace_seconds_per_km is not numeric"}
        if threshold_pace <= 0:
            return {**_null, "reason": "threshold_pace_seconds_per_km must be positive"}
        pace = threshold_pace * (1.0 + (1.0 - clamped_score / 100.0) * (SLOW_FACTOR - 1.0))

    total_seconds = int(round(pace * distance_km))
    return {
        "estimated_finish_seconds": total_seconds,
        "estimated_finish_time": _format_hhmmss(total_seconds),
        "reason": None,
    }


def apply_finish_estimates(
    entries: list[dict],
    thresholds: dict | None,
) -> list[dict]:
    """Augment each entry dict with an estimated finish time (in-place)."""
    for entry in entries:
        result = score_to_estimated_finish_time(
            score=entry.get("expressible_score"),
            thresholds=thresholds,
            distance_km=entry.get("distance_km"),
        )
        entry["estimated_finish_seconds"] = result["estimated_finish_seconds"]
        entry["estimated_finish_time"] = result["estimated_finish_time"]
    return entries


# ── Internal helpers ──────────────────────────────────────────────────────────

def _format_hhmmss(total_seconds: int) -> str:
    """Format a non-negative integer number of seconds as "HH:MM:SS"."""
    seconds = abs(total_seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
