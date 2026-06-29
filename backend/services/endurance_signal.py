"""Endurance signal computation for run workouts (issue #1049).

Computes an aerobic durability metric by measuring how well a runner maintained
efficiency from the first half to the second half of a run.

Public API
----------
compute_endurance_signal(workout, splits)
    Pure function.  No I/O, no DB calls, no side effects.

Fields returned
---------------
endurance_signal       Float (0–100+): high means durable, low means faded.
                       Computed as (100 - decoupling_percent), floored at 0.
decoupling_percent     Float: ((e1 - e2) / e1) * 100.  Positive = fade.
efficiency_first_half  Float: power/HR or speed/HR for the first half.
efficiency_second_half Float: same metric for the second half.
endurance_signal_source "power_hr" | "speed_hr" | None

Eligibility
-----------
Only runs with more than 40 minutes of moving time (workout["duration_seconds"] > 2400)
are eligible.  Short runs and runs with missing data return all-null dicts.

Caller responsibility
---------------------
All DB access must be performed by the caller before invoking this function.
"""

from __future__ import annotations

from typing import Any

_MIN_MOVING_SECONDS = 2400  # 40 minutes; strictly greater than this is required


_NULL_RESULT: dict[str, Any] = {
    "endurance_signal": None,
    "decoupling_percent": None,
    "efficiency_first_half": None,
    "efficiency_second_half": None,
    "endurance_signal_source": None,
}


def compute_endurance_signal(
    workout: dict[str, Any],
    splits: list[dict] | None,
) -> dict[str, Any]:
    """Compute the endurance signal for a run from its km-splits.

    Parameters
    ----------
    workout:
        Plain dict with at least ``"duration_seconds"`` (the run's moving time).
    splits:
        List of split dicts.  Each dict should contain:
        - ``split_index`` (int)
        - ``duration_seconds`` (int | float, > 0)
        - ``avg_hr`` (float | int, > 0)
        - ``avg_power`` (float | int | None): watts, used when present
        - ``distance_km`` (float | None): used for speed when no power

    Returns
    -------
    Dict with five keys: ``endurance_signal``, ``decoupling_percent``,
    ``efficiency_first_half``, ``efficiency_second_half``,
    ``endurance_signal_source``.  All values are ``None`` when the signal
    cannot be computed.
    """
    duration = workout.get("duration_seconds") if workout else None
    if not isinstance(duration, (int, float)) or duration <= _MIN_MOVING_SECONDS:
        return dict(_NULL_RESULT)

    if not splits:
        return dict(_NULL_RESULT)

    valid = [
        s for s in splits
        if isinstance(s.get("duration_seconds"), (int, float))
        and s["duration_seconds"] > 0
    ]
    if len(valid) < 2:
        return dict(_NULL_RESULT)

    sorted_splits = sorted(valid, key=lambda s: s.get("split_index", 0))
    total_duration = sum(float(s["duration_seconds"]) for s in sorted_splits)
    midpoint = total_duration / 2.0

    first_half: list[dict] = []
    second_half: list[dict] = []
    cumulative = 0.0
    for s in sorted_splits:
        dur = float(s["duration_seconds"])
        mid_time = cumulative + dur / 2.0
        if mid_time <= midpoint:
            first_half.append(s)
        else:
            second_half.append(s)
        cumulative += dur

    if not first_half or not second_half:
        return dict(_NULL_RESULT)

    def _has_hr(half: list[dict]) -> bool:
        return all(
            isinstance(s.get("avg_hr"), (int, float)) and s["avg_hr"] > 0
            for s in half
        )

    if not _has_hr(first_half) or not _has_hr(second_half):
        return dict(_NULL_RESULT)

    all_splits = first_half + second_half
    use_power = all(
        isinstance(s.get("avg_power"), (int, float)) and s["avg_power"] > 0
        for s in all_splits
    )
    use_speed = (
        not use_power
        and all(
            isinstance(s.get("distance_km"), (int, float)) and s["distance_km"] > 0
            for s in all_splits
        )
    )

    if not use_power and not use_speed:
        return dict(_NULL_RESULT)

    def _weighted_efficiency(half: list[dict]) -> float:
        total_dur = sum(float(s["duration_seconds"]) for s in half)
        weighted_hr = (
            sum(float(s["avg_hr"]) * float(s["duration_seconds"]) for s in half)
            / total_dur
        )
        if weighted_hr <= 0:
            return 0.0
        if use_power:
            weighted_p = (
                sum(float(s["avg_power"]) * float(s["duration_seconds"]) for s in half)
                / total_dur
            )
            return weighted_p / weighted_hr
        # speed = distance_km / duration_seconds (km/s); efficiency = speed / hr
        weighted_speed = (
            sum(
                (float(s["distance_km"]) / float(s["duration_seconds"]))
                * float(s["duration_seconds"])
                for s in half
            )
            / total_dur
        )
        return weighted_speed / weighted_hr

    e1 = _weighted_efficiency(first_half)
    e2 = _weighted_efficiency(second_half)

    if e1 <= 0:
        return dict(_NULL_RESULT)

    decoupling_percent = round((e1 - e2) / e1 * 100, 2)
    endurance_signal = round(max(0.0, 100.0 - decoupling_percent), 2)
    source = "power_hr" if use_power else "speed_hr"

    return {
        "endurance_signal": endurance_signal,
        "decoupling_percent": decoupling_percent,
        "efficiency_first_half": round(e1, 6),
        "efficiency_second_half": round(e2, 6),
        "endurance_signal_source": source,
    }
