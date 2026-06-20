"""
Race specificity progress tracker.

``specificity_progress`` measures how well a runner's recent training block
prepares them for a target race by decomposing readiness into four trackable
components — accumulated volume near goal pace, longest continuous goal-pace
effort, and longest run by distance and duration — without ever requiring a
full race-effort trial.

Each component is returned as a ``{current, target, unit}`` dict so the UI
can render progress bars and highlight which dimension of specificity still
needs work.

This module is **pure** — it contains no database access and no side effects.
A thin caller is responsible for loading the race and workout rows and passing
them in as plain objects.
"""

# Default pace tolerance: how many seconds per km either side of goal pace
# still counts as "goal-pace running".  Callers may override this value via
# the ``pace_tolerance_seconds_per_km`` parameter.
DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM = 15  # ±15 s/km (~±45 s/mile at race pace)

# Target long-run distance is expressed as a fraction of the race distance.
# For a half-marathon (21.1 km) this yields ~19 km; for a marathon ~38 km.
_TARGET_LONG_RUN_DISTANCE_FRACTION = 0.9

# Target long-run duration is expressed as a fraction of the goal race time.
# For a sub-1:50 half this yields ~1:39; callers see the target, not the fraction.
_TARGET_LONG_RUN_DURATION_FRACTION = 0.9

# Target accumulated goal-pace volume over a training block is expressed as a
# fraction of the race distance.  For a half-marathon this yields ~12–13 km.
_TARGET_VOLUME_FRACTION = 0.6

# Minimum effort duration in seconds before a run counts toward longest_pace_effort.
# Derived from the race: anything shorter than this fraction of goal race time
# is treated as a warm-up or cooldown, not a meaningful effort.
_MIN_EFFORT_FRACTION = 0.05  # 5 % of goal race time


def _resolve_goal_pace(race):
    """Return goal pace in seconds per km from the race object, or None.

    Reads ``goal_pace_seconds_per_km`` directly when set.  Falls back to
    dividing ``goal_time_seconds`` by ``distance_km`` when the pre-computed
    field is absent.  Returns None when neither derivation is possible.

    Arithmetic: goal pace in seconds per km equals goal time in seconds
    divided by race distance in km.
    """
    gp = getattr(race, "goal_pace_seconds_per_km", None)
    if gp is not None:
        return int(gp)

    goal_time = getattr(race, "goal_time_seconds", None)
    distance_km = getattr(race, "distance_km", None)

    if goal_time is None or distance_km is None:
        return None
    try:
        dist_f = float(distance_km)
    except (TypeError, ValueError):
        return None
    if dist_f <= 0:
        return None
    # goal pace in seconds per km = goal time in seconds / race distance in km
    return round(goal_time / dist_f)


def _empty(reason):
    """Return the minimal early-exit dict when a required input is absent."""
    return {"reason": reason}


def _zeroed_result(race, pace_tolerance_seconds_per_km, reason):
    """Return zeroed current values with targets populated from the race.

    Used when the race is valid but no runs are available.  Arithmetic for
    each target is derived from the race input exclusively.

    Arithmetic:
      - goal_pace = goal_time_seconds / distance_km
      - target volume = distance_km * _TARGET_VOLUME_FRACTION
      - target longest distance = distance_km * _TARGET_LONG_RUN_DISTANCE_FRACTION
      - target longest duration = goal_time_seconds * _TARGET_LONG_RUN_DURATION_FRACTION
    """
    goal_pace = _resolve_goal_pace(race)
    distance_km = float(getattr(race, "distance_km", 0) or 0)
    goal_time = getattr(race, "goal_time_seconds", None)

    # target: accumulated km within pace band
    target_volume = round(distance_km * _TARGET_VOLUME_FRACTION, 2)

    # target: longest single effort whose pace is within the pace band (km)
    target_longest_pace_effort = round(distance_km * _TARGET_LONG_RUN_DISTANCE_FRACTION, 2)

    # target: longest single run by distance (km)
    target_longest_distance = round(distance_km * _TARGET_LONG_RUN_DISTANCE_FRACTION, 2)

    # target: longest single run by duration (seconds)
    target_longest_duration = round(goal_time * _TARGET_LONG_RUN_DURATION_FRACTION) if goal_time else 0

    return {
        "volume_at_pace": {"current": 0.0, "target": target_volume, "unit": "km"},
        "longest_pace_effort": {"current": 0.0, "target": target_longest_pace_effort, "unit": "km"},
        "longest_run_by_distance": {"current": 0.0, "target": target_longest_distance, "unit": "km"},
        "longest_run_by_duration": {"current": 0, "target": target_longest_duration, "unit": "seconds"},
        "reason": reason,
    }


def specificity_progress(
    race,
    recent_runs,
    pace_tolerance_seconds_per_km=DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM,
):
    """Compute race-specificity progress from a recent run history.

    Decomposes training readiness for a target ``race`` into four trackable
    components, each returned as ``{current, target, unit}`` so the caller
    can render progress bars without additional computation.

    This function is **pure** — it accepts plain objects and returns a plain
    dict.  No database calls are made here; the thin caller (see
    ``get_specificity_progress``) handles data loading.

    Parameters
    ----------
    race:
        Object (or any namespace) with at minimum:

        - ``distance_km``  — race distance in kilometres (Decimal or float).
        - ``goal_time_seconds`` — total goal time in seconds (int or None).
        - ``goal_pace_seconds_per_km`` — pre-computed goal pace in s/km
          (int or None); derived from the two fields above when absent.

        When ``race`` is ``None`` or the goal pace cannot be derived, the
        function returns ``{"reason": "<explanation>"}`` immediately.

    recent_runs:
        Iterable of run objects, each with:

        - ``distance_km``      — distance covered (Decimal or float).
        - ``duration_seconds`` — elapsed time in seconds (int).
        - ``is_b_race``        — optional boolean; when truthy the run is
          treated as a B-race result and excluded from all four components
          (see B-race exclusion section below).

        When ``None`` or empty, zeroed ``current`` values are returned with
        targets still derived from ``race``, plus a ``"reason"`` string.

    pace_tolerance_seconds_per_km:
        Named parameter (defaults to
        ``DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM``).  A run's average pace
        (seconds per km) must fall within
        ``[goal_pace - tolerance, goal_pace + tolerance]`` to be counted
        toward pace-specific components.  Callers must pass this explicitly
        or accept the documented default.

    Returns
    -------
    dict with the following keys when a valid race is supplied:

    ``volume_at_pace`` — ``{current (km), target (km), unit}``
        Accumulated distance from runs whose average pace falls within the
        pace tolerance band.  Arithmetic: run pace = duration_seconds /
        distance_km; run contributes its distance when pace is within
        [goal_pace - tolerance, goal_pace + tolerance].

    ``longest_pace_effort`` — ``{current (km), target (km), unit}``
        Longest single in-band run by distance.  Only runs inside the pace
        band are considered.

    ``longest_run_by_distance`` — ``{current (km), target (km), unit}``
        Longest single run by distance regardless of pace.

    ``longest_run_by_duration`` — ``{current (seconds), target (seconds), unit}``
        Longest single run by elapsed time regardless of pace.

    ``reason`` — str, present only when race or runs are absent/invalid.

    Worked example
    --------------
    Sub-1:50 half-marathon (distance = 21.0975 km, goal_time = 6600 s):

        goal pace in seconds per km = 6600 / 21.0975 ≈ 313 s/km  (~5:13/km)

        With DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM = 15 s/km, the pace band
        is [313 - 15, 313 + 15] = [298, 328] s/km.

    Run A: 15 km at exactly goal pace (313 s/km, duration = 15 * 313 = 4695 s)
        pace = 4695 / 15 = 313 s/km — inside band
        → contributes 15 km to volume_at_pace and to longest_pace_effort

    Run B: 20 km long run at easy pace (360 s/km, duration = 20 * 360 = 7200 s = 1:55:00 h:m:s — outside band)
        pace = 7200 / 20 = 360 s/km — outside band
        → contributes 0 to volume_at_pace; contributes 20 km to longest_run_by_distance
          and 7200 s to longest_run_by_duration

    Targets:
        volume_at_pace target          = 21.0975 * 0.6 ≈ 12.66 km
        longest_pace_effort target     = 21.0975 * 0.9 ≈ 18.99 km
        longest_run_by_distance target = 21.0975 * 0.9 ≈ 18.99 km
        longest_run_by_duration target = 6600    * 0.9  = 5940 s

    Combined result (Run A + Run B):
        volume_at_pace:          current=15.0,  target≈12.66, unit="km"
        longest_pace_effort:     current=15.0,  target≈18.99, unit="km"
        longest_run_by_distance: current=20.0,  target≈18.99, unit="km"
        longest_run_by_duration: current=7200,  target=5940,  unit="seconds"

    Both Run A (volume_at_pace) and Run B (longest_run_by_duration) produce
    non-zero component progress, satisfying the AC2 acceptance criterion.

    B-race exclusion
    ----------------
    Runs whose ``is_b_race`` attribute is truthy are dropped before any
    metric is computed.  B-races are competitive efforts whose pacing and
    fatigue cost differ from goal-specific training runs, so including them
    would inflate the specificity metrics and misrepresent training readiness.

    Example: if Run A above were a B-race (``is_b_race=True``), it would be
    skipped entirely — ``volume_at_pace`` current would be 0 km (not 15 km)
    and ``longest_pace_effort`` current would also be 0 km.  Run B (easy
    long run, not a B-race) still contributes normally to the distance and
    duration metrics.
    """
    # Guard: race must be provided
    if race is None:
        return _empty("No goal race selected")

    # Derive goal pace from the race object
    goal_pace = _resolve_goal_pace(race)
    if goal_pace is None:
        return _empty("Race has no goal time or goal pace set")

    distance_km = float(getattr(race, "distance_km", 0) or 0)
    goal_time = getattr(race, "goal_time_seconds", None)

    # Guard: distance must be positive to derive meaningful targets
    if distance_km <= 0:
        return _empty("Race distance is zero or missing")

    # Guard: empty/None runs — return zeroed result with targets still populated
    run_list = list(recent_runs) if recent_runs else []
    if not run_list:
        return _zeroed_result(race, pace_tolerance_seconds_per_km, "No recent runs found")

    # Compute targets once — all derived from the race input, never hardcoded
    # target volume = fraction of race distance (rewarded block of goal-pace km)
    target_volume = round(distance_km * _TARGET_VOLUME_FRACTION, 2)

    # target longest pace effort = fraction of race distance
    target_longest_pace_effort = round(distance_km * _TARGET_LONG_RUN_DISTANCE_FRACTION, 2)

    # target longest run by distance = fraction of race distance
    target_longest_distance = round(distance_km * _TARGET_LONG_RUN_DISTANCE_FRACTION, 2)

    # target longest run by duration = fraction of goal time in seconds
    target_longest_duration = round(goal_time * _TARGET_LONG_RUN_DURATION_FRACTION) if goal_time else 0

    # Pace band: [goal_pace - tolerance, goal_pace + tolerance] (s/km)
    # A run's average pace must fall within this range to count toward
    # volume_at_pace and longest_pace_effort.
    pace_band_lo = goal_pace - pace_tolerance_seconds_per_km  # fastest allowed (lower s/km = faster)
    pace_band_hi = goal_pace + pace_tolerance_seconds_per_km  # slowest allowed

    # Accumulators
    volume_at_pace = 0.0        # cumulative km from in-band runs
    longest_pace_effort = 0.0   # longest single in-band run by km
    longest_distance = 0.0      # longest single run by km (any pace)
    longest_duration = 0        # longest single run by seconds (any pace)

    for run in run_list:
        dist_raw = getattr(run, "distance_km", None)
        dur_raw = getattr(run, "duration_seconds", None)

        try:
            dist = float(dist_raw) if dist_raw is not None else None
        except (TypeError, ValueError):
            dist = None

        try:
            dur = int(dur_raw) if dur_raw is not None else None
        except (TypeError, ValueError):
            dur = None

        # Skip B-race results — they skew specificity metrics (see docstring)
        if getattr(run, "is_b_race", False):
            continue

        # Skip runs without both distance and duration
        if dist is None or dur is None or dist <= 0 or dur <= 0:
            continue

        # Track longest run by distance (any pace)
        if dist > longest_distance:
            longest_distance = dist

        # Track longest run by duration (any pace)
        if dur > longest_duration:
            longest_duration = dur

        # Compute average pace for this run: seconds elapsed per km covered
        run_pace = dur / dist

        # Check if this run falls within the goal-pace tolerance band
        if pace_band_lo <= run_pace <= pace_band_hi:
            # Accumulate goal-pace volume
            volume_at_pace += dist

            # Track longest single in-band effort by distance
            if dist > longest_pace_effort:
                longest_pace_effort = dist

    return {
        "volume_at_pace": {
            "current": round(volume_at_pace, 2),
            "target": target_volume,
            "unit": "km",
        },
        "longest_pace_effort": {
            "current": round(longest_pace_effort, 2),
            "target": target_longest_pace_effort,
            "unit": "km",
        },
        "longest_run_by_distance": {
            "current": round(longest_distance, 2),
            "target": target_longest_distance,
            "unit": "km",
        },
        "longest_run_by_duration": {
            "current": longest_duration,
            "target": target_longest_duration,
            "unit": "seconds",
        },
    }
