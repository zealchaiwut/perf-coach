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


# ── Two-anchor blend: Endurance + Speed scores → race estimate ───────────────
# The athlete's two displayed scores are two anchor points on their personal
# pace-duration curve: Endurance (from easy/steady aerobic efforts,
# HR-extrapolated to threshold) anchors the LONG end; Speed (from best
# sustained hard efforts) anchors the SHORT end. For a race distance D the
# blended VDOT is the linear interpolation between them in log-distance
# space, centred on the half marathon:
#
#     w_s(D)   = clamp(0.5 − SPEED_WEIGHT_SLOPE · ln(D / SPEED_WEIGHT_REFERENCE_KM),
#                      SPEED_WEIGHT_MIN, SPEED_WEIGHT_MAX)
#     vdot(D)  = w_s · vdot(Speed) + (1 − w_s) · vdot(Endurance)
#     pace(D)  = vdot_to_race_pace_seconds(vdot(D), D)      # Daniels inversion
#     finish   = pace × D
#
# i.e. a 10 K leans on Speed (w_s ≈ 0.63), a marathon leans on Endurance
# (w_s ≈ 0.38), a half is the 50/50 midpoint. Same weighting the
# required-score badges already use (main._plan_race_scores) — one formula,
# two consumers. Blending on the score scale or the VDOT scale is identical
# (score→VDOT is linear); done on VDOT here for the interpretable per-anchor
# paces in the returned basis.
SPEED_WEIGHT_REFERENCE_KM: float = 21.1
SPEED_WEIGHT_SLOPE: float = 0.18
SPEED_WEIGHT_MIN: float = 0.15
SPEED_WEIGHT_MAX: float = 0.85


def speed_weight_for_distance(distance_km: float) -> float:
    """Speed-anchor weight for a race distance (see block comment above)."""
    le = math.log(float(distance_km) / SPEED_WEIGHT_REFERENCE_KM)
    return max(SPEED_WEIGHT_MIN, min(SPEED_WEIGHT_MAX, 0.5 - SPEED_WEIGHT_SLOPE * le))


def blended_scores_estimate(
    endurance_score: float | None,
    speed_score: float | None,
    distance_km: float | None,
    thresholds: dict | None,
) -> dict:
    """Race estimate anchored on the athlete's DISPLAYED End/Spd scores.

    Returns the score_to_estimated_finish_time shape plus a ``basis`` dict —
    the interpretable decomposition ("with this Endurance you hold X:XX /km
    at this distance; with this Speed, Y:YY /km; blended at w_s → Z:ZZ /km"):

        basis = {
          endurance_score, endurance_vdot, endurance_pace_seconds_per_km,
          speed_score, speed_vdot, speed_pace_seconds_per_km,
          speed_weight, blended_vdot, blended_pace_seconds_per_km,
        }

    Endurance is mandatory (it anchors every race distance); with no Speed
    score the blend degenerates to endurance-only (w_s = 0). Falls back to
    score_to_estimated_finish_time's own fallback chain when a VDOT pace
    can't be formed.
    """
    _null = {"estimated_finish_seconds": None, "estimated_finish_time": None, "basis": None}
    if endurance_score is None:
        return {**_null, "reason": "endurance score is None"}
    if distance_km is None:
        return {**_null, "reason": "distance_km is None"}
    try:
        distance_km = float(distance_km)
    except (TypeError, ValueError):
        return {**_null, "reason": "distance_km is not numeric"}
    if distance_km <= 0:
        return {**_null, "reason": "distance_km must be positive"}

    e = max(0.0, min(100.0, float(endurance_score)))
    s = max(0.0, min(100.0, float(speed_score))) if speed_score is not None else None

    vdot_e = score_to_vdot(e)
    vdot_s = score_to_vdot(s) if s is not None else None
    w_s = speed_weight_for_distance(distance_km) if vdot_s is not None else 0.0
    blended_vdot = w_s * (vdot_s or 0.0) + (1.0 - w_s) * vdot_e

    pace = vdot_to_race_pace_seconds(blended_vdot, distance_km)
    if pace is None:
        # Same threshold-pace fallback contract as the single-score estimator.
        blended_score = w_s * (s or 0.0) + (1.0 - w_s) * e
        return {**score_to_estimated_finish_time(blended_score, thresholds, distance_km), "basis": None}

    pace_e = vdot_to_race_pace_seconds(vdot_e, distance_km)
    pace_s = vdot_to_race_pace_seconds(vdot_s, distance_km) if vdot_s is not None else None

    total_seconds = int(round(pace * distance_km))
    return {
        "estimated_finish_seconds": total_seconds,
        "estimated_finish_time": _format_hhmmss(total_seconds),
        "reason": None,
        "basis": {
            "endurance_score": round(e, 1),
            "endurance_vdot": round(vdot_e, 1),
            "endurance_pace_seconds_per_km": round(pace_e) if pace_e is not None else None,
            "speed_score": round(s, 1) if s is not None else None,
            "speed_vdot": round(vdot_s, 1) if vdot_s is not None else None,
            "speed_pace_seconds_per_km": round(pace_s) if pace_s is not None else None,
            "speed_weight": round(w_s, 3),
            "blended_vdot": round(blended_vdot, 1),
            "blended_pace_seconds_per_km": round(pace),
        },
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
