"""Convert an expressible fitness score to an estimated race finish time (issue #1108).

Pure function module — no database access, no side effects.

The "expressible score" is a 0–100 fitness indicator (e.g. the endurance or
speed score from running_performance.py, or the score ceiling from
score_ceiling.py).  The conversion maps the score to an estimated pace using
the user's configured threshold pace, then multiplies by the entry distance
to produce the total finish time.

Mathematical model
------------------
At score=100 (peak fitness) the athlete is estimated to perform at their
threshold pace.  At score=0 (minimum fitness) the estimated pace is
SLOW_FACTOR × threshold pace (twice as slow by default).  All values in
between are interpolated linearly:

    estimated_pace = threshold_pace × (1 + (1 − score/100) × (SLOW_FACTOR − 1))

For the default SLOW_FACTOR of 2.0 this simplifies to:

    estimated_pace = threshold_pace × (2 − score/100)

This guarantees that a higher score always yields a faster (lower) finish time
for the same distance, satisfying the monotonic trend property required by AC3.

Worked example
--------------
score=75, threshold_pace=300 s/km, distance=10 km:

    estimated_pace = 300 × (2 − 0.75) = 300 × 1.25 = 375 s/km
    finish_time    = 375 × 10 = 3750 s  →  "01:02:30"
"""
from __future__ import annotations

# ── Constants ─────────────────────────────────────────────────────────────────

# Multiplier applied to threshold pace when the score is 0.
# A value of 2.0 means the slowest estimated pace is 2× the threshold pace.
SLOW_FACTOR: float = 2.0


# ── Public API ────────────────────────────────────────────────────────────────

def score_to_estimated_finish_time(
    score: float | None,
    thresholds: dict | None,
    distance_km: float | None,
) -> dict:
    """Convert an expressible fitness score to an estimated race finish time.

    Parameters
    ----------
    score:
        Fitness score on the 0–100 scale.  Values outside [0, 100] are clamped.
        None returns a null result with a descriptive reason.
    thresholds:
        User preference dict.  Must contain ``threshold_pace_seconds_per_km``
        (a positive number) to compute a meaningful estimate.  None or a dict
        without the key returns a null result.
    distance_km:
        Race or checkpoint distance in kilometres (must be positive).

    Returns
    -------
    dict with keys:
        ``estimated_finish_seconds`` — int total seconds, or None on failure
        ``estimated_finish_time``    — "HH:MM:SS" string, or None on failure
        ``reason``                   — None on success; descriptive string on failure
    """
    _null = {"estimated_finish_seconds": None, "estimated_finish_time": None}

    if score is None:
        return {**_null, "reason": "score is None"}

    if not isinstance(thresholds, dict):
        return {**_null, "reason": "thresholds must be a dict"}

    threshold_pace = thresholds.get("threshold_pace_seconds_per_km")
    if threshold_pace is None:
        return {**_null, "reason": "threshold_pace_seconds_per_km not set"}
    try:
        threshold_pace = float(threshold_pace)
    except (TypeError, ValueError):
        return {**_null, "reason": "threshold_pace_seconds_per_km is not numeric"}
    if threshold_pace <= 0:
        return {**_null, "reason": "threshold_pace_seconds_per_km must be positive"}

    if distance_km is None:
        return {**_null, "reason": "distance_km is None"}
    try:
        distance_km = float(distance_km)
    except (TypeError, ValueError):
        return {**_null, "reason": "distance_km is not numeric"}
    if distance_km <= 0:
        return {**_null, "reason": "distance_km must be positive"}

    clamped_score = max(0.0, min(100.0, float(score)))

    # Linear interpolation between threshold pace (score=100) and SLOW_FACTOR×threshold (score=0).
    estimated_pace = threshold_pace * (
        1.0 + (1.0 - clamped_score / 100.0) * (SLOW_FACTOR - 1.0)
    )
    total_seconds = int(round(estimated_pace * distance_km))

    return {
        "estimated_finish_seconds": total_seconds,
        "estimated_finish_time": _format_hhmmss(total_seconds),
        "reason": None,
    }


def apply_finish_estimates(
    entries: list[dict],
    thresholds: dict | None,
) -> list[dict]:
    """Augment each entry dict with an estimated finish time.

    Each entry must have ``"expressible_score"`` (float or None) and
    ``"distance_km"`` (float or None) keys.  The function adds
    ``"estimated_finish_seconds"`` and ``"estimated_finish_time"`` in-place
    and returns the same list so callers can chain the call.

    Entries that are missing a score or distance receive None values for both
    fields — they are never skipped and no exception is raised (UAT step 5).
    """
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
