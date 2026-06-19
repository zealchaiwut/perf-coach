"""Aerobic decoupling metric for run workouts (issue #691).

Aerobic decoupling measures how much a runner's efficiency degrades over the
course of a run.  A high value indicates cardiovascular drift or late-run fade.

Public API
----------
compute_decoupling(workout, splits_or_stream, threshold)
    Pure function.  No I/O, no DB calls, no side effects.

Worked example
--------------
A run with first-half efficiency of 1.00 and second-half efficiency of 0.95:

    decoupling_pct = (1.00 - 0.95) / 1.00 * 100 = 5.0 percent

Thin caller responsibility
--------------------------
All DB access (fetching the workout, splits, streams, and the user's
aerobic_decoupling_threshold from user_preferences) must be performed by the
caller before invoking compute_decoupling.  This function receives only plain
Python values and dicts.
"""

from __future__ import annotations

from typing import Any


def compute_decoupling(
    workout: dict[str, Any],
    splits_or_stream: list[dict] | dict | None,
    threshold: float | None,
) -> tuple[dict[str, Any], None] | tuple[None, str]:
    """Compute aerobic decoupling for a run.

    Splits the run strictly by elapsed time into a first half and second half,
    then measures how much efficiency (power-to-HR or speed-to-HR) declines.

    Parameters
    ----------
    workout:
        Plain dict containing workout metadata.  Must be non-None.
        Used primarily for context; HR and power data come from
        splits_or_stream.
    splits_or_stream:
        Either:
        - A dict (stream): must contain at least ``"time"`` and
          ``"heartrate"`` keys, each with a nested ``"data"`` list.
          Optionally contains ``"watts"`` and/or ``"velocity_smooth"``.
        - A list of split dicts: each must have ``split_index``,
          ``duration_seconds``, and ``avg_hr``.  Optionally contain
          ``avg_power`` (watts) and ``distance_km`` (for speed).
        - None, empty dict, or empty list: metric cannot be computed.
    threshold:
        The user's aerobic_decoupling_threshold from user_preferences.
        When not None, ``faded_late`` is set to ``True`` if
        ``decoupling_pct`` strictly exceeds this value.  When None,
        ``faded_late`` defaults to ``False``.

    Returns
    -------
    On success:
        ``(result_dict, None)`` where result_dict contains:
        - ``decoupling_pct`` (float, two decimal places)
        - ``faded_late`` (bool)
        - ``debug`` (dict with ``first_half_efficiency`` and
          ``second_half_efficiency``)

    On failure:
        ``(None, reason_string)`` where reason_string explains why the
        metric could not be computed (e.g.
        ``"insufficient_data: fewer than 2 laps and no stream provided"``).
    """
    if not splits_or_stream:
        return None, "insufficient_data: fewer than 2 laps and no stream provided"

    if isinstance(splits_or_stream, dict):
        return _from_stream(splits_or_stream, threshold)
    if isinstance(splits_or_stream, list):
        return _from_splits(splits_or_stream, threshold)

    return None, "insufficient_data: unrecognised splits_or_stream type"


# ---------------------------------------------------------------------------
# Stream-based path
# ---------------------------------------------------------------------------

def _series(stream: dict, name: str) -> list[float]:
    """Extract a numeric data series from a stream dict."""
    v = stream.get(name)
    data = v.get("data") if isinstance(v, dict) else None
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, (int, float)) and not isinstance(x, bool)]


def _from_stream(
    stream: dict,
    threshold: float | None,
) -> tuple[dict, None] | tuple[None, str]:
    time_data = _series(stream, "time")
    hr_data = _series(stream, "heartrate")

    if len(hr_data) < 4:
        return None, "missing_hr: stream contains no usable heart rate data"
    if len(time_data) < 4:
        return None, "insufficient_data: stream time series is too short to split"
    if len(time_data) != len(hr_data):
        return None, "insufficient_data: time and heartrate series have different lengths"

    total_time = max(time_data)
    if total_time <= 0:
        return None, "insufficient_data: stream elapsed time is zero or negative"
    midpoint = total_time / 2

    first_idx = [i for i, t in enumerate(time_data) if t <= midpoint]
    second_idx = [i for i, t in enumerate(time_data) if t > midpoint]

    if not first_idx or not second_idx:
        return None, "insufficient_data: cannot split stream into two non-empty halves"

    watts = _series(stream, "watts")
    vel = _series(stream, "velocity_smooth")

    use_power = bool(watts) and len(watts) == len(hr_data)
    use_speed = bool(vel) and len(vel) == len(hr_data)

    if not use_power and not use_speed:
        return None, "insufficient_data: no power or speed data in stream"

    def _mean_efficiency(indices: list[int]) -> float | None:
        hr_vals = [hr_data[i] for i in indices if hr_data[i] > 0]
        if not hr_vals:
            return None
        avg_hr = sum(hr_vals) / len(hr_vals)
        if avg_hr <= 0:
            return None
        if use_power:
            p_vals = [watts[i] for i in indices if watts[i] > 0]
            if not p_vals:
                return None
            avg_p = sum(p_vals) / len(p_vals)
            return avg_p / avg_hr
        # speed path
        v_vals = [vel[i] for i in indices if vel[i] > 0]
        if not v_vals:
            return None
        avg_v = sum(v_vals) / len(v_vals)
        return avg_v / avg_hr

    e1 = _mean_efficiency(first_idx)
    e2 = _mean_efficiency(second_idx)

    if e1 is None or e2 is None or e1 == 0:
        return None, "insufficient_data: could not compute efficiency for one or both halves"

    return _build_result(e1, e2, threshold)


# ---------------------------------------------------------------------------
# Splits-based path
# ---------------------------------------------------------------------------

def _from_splits(
    splits: list[dict],
    threshold: float | None,
) -> tuple[dict, None] | tuple[None, str]:
    if len(splits) < 2:
        return None, "insufficient_data: fewer than 2 laps and no stream provided"

    valid = [s for s in splits if isinstance(s.get("duration_seconds"), (int, float)) and s["duration_seconds"] > 0]
    if len(valid) < 2:
        return None, "insufficient_data: fewer than 2 laps with valid duration"

    sorted_splits = sorted(valid, key=lambda s: s.get("split_index", 0))
    total_duration = sum(float(s["duration_seconds"]) for s in sorted_splits)
    midpoint = total_duration / 2

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
        return None, "insufficient_data: cannot split laps into two non-empty halves"

    # Check HR availability
    def _has_hr(half: list[dict]) -> bool:
        return all(isinstance(s.get("avg_hr"), (int, float)) and s["avg_hr"] > 0 for s in half)

    if not _has_hr(first_half) or not _has_hr(second_half):
        return None, "missing_hr: one or more laps have no heart rate data"

    # Determine metric: power or speed
    use_power = all(isinstance(s.get("avg_power"), (int, float)) and s["avg_power"] > 0 for s in first_half + second_half)
    use_speed = (
        not use_power
        and all(
            isinstance(s.get("distance_km"), (int, float)) and s["distance_km"] > 0
            for s in first_half + second_half
        )
    )

    if not use_power and not use_speed:
        return None, "insufficient_data: no power or distance data available for efficiency calculation"

    def _weighted_efficiency(half: list[dict]) -> float:
        total_dur = sum(float(s["duration_seconds"]) for s in half)
        if use_power:
            weighted_p = sum(float(s["avg_power"]) * float(s["duration_seconds"]) for s in half) / total_dur
            weighted_hr = sum(float(s["avg_hr"]) * float(s["duration_seconds"]) for s in half) / total_dur
        else:
            # speed = distance / duration_seconds (in km/s)
            weighted_speed = sum((float(s["distance_km"]) / float(s["duration_seconds"])) * float(s["duration_seconds"]) for s in half) / total_dur
            weighted_hr = sum(float(s["avg_hr"]) * float(s["duration_seconds"]) for s in half) / total_dur
            # efficiency = speed / hr
            if weighted_hr <= 0:
                return 0.0
            return weighted_speed / weighted_hr

        if weighted_hr <= 0:
            return 0.0
        return weighted_p / weighted_hr

    e1 = _weighted_efficiency(first_half)
    e2 = _weighted_efficiency(second_half)

    if e1 == 0:
        return None, "insufficient_data: first-half efficiency is zero"

    return _build_result(e1, e2, threshold)


# ---------------------------------------------------------------------------
# Shared result builder
# ---------------------------------------------------------------------------

def _build_result(
    e1: float,
    e2: float,
    threshold: float | None,
) -> tuple[dict, None]:
    decoupling_pct = round((e1 - e2) / e1 * 100, 2)

    if threshold is not None:
        faded_late = decoupling_pct > threshold
    else:
        faded_late = False

    return {
        "decoupling_pct": decoupling_pct,
        "faded_late": faded_late,
        "debug": {
            "first_half_efficiency": e1,
            "second_half_efficiency": e2,
        },
    }, None
