"""Interval and set detection for the session-profile pipeline.

detect_intervals and detect_sets are pure functions — no database access,
no side effects, no hardcoded numbers inline. A thin caller layer in the
DB/service layer is the only place that fetches lap data from the database
before passing it into these functions.

Terminology
-----------
hard rep:  a lap whose band is 'tempo' or 'threshold' (as assigned by
           classify_laps).
recovery:  an 'easy' or 'steady' lap that immediately follows a hard rep.
cycle:     one complete hard-rep + recovery pair — the basic repeating unit.
set:       a contiguous block of cycles separated from adjacent blocks by an
           unusually long recovery lap.

Pipeline position
-----------------
detect_intervals sits above classify_laps: it takes the list of classified
laps (output of classify_laps merged with original split data) and looks for
alternating hard/recovery patterns. detect_sets then refines a detected
Intervals phase by splitting it into sets wherever a long recovery occurs.
"""

# ── Configuration constants ────────────────────────────────────────────────────

HARD_REP_TOLERANCE = 0.25
"""Fractional tolerance controlling hard-rep consistency within a sequence.

A hard rep is consistent with its peers when the absolute difference between
its duration_seconds and the median hard-rep duration of the candidate sequence
is less than HARD_REP_TOLERANCE multiplied by that median.

A value of 0.25 allows each rep to vary up to ±25 % from the group median.
A rep that exceeds this tolerance is considered anomalous and terminates the
alternating sequence at that point.
"""

SET_BOUNDARY_MULTIPLIER = 1.5
"""Ratio used to identify a set-boundary recovery lap.

A recovery lap is treated as a set boundary when its duration_seconds exceeds
the median recovery duration of the Intervals phase multiplied by
SET_BOUNDARY_MULTIPLIER.

The default value of 1.5 means a recovery that is 50 % longer than the group
median marks the start of a new set.
"""

# ── Internal band classification ───────────────────────────────────────────────

# A "hard rep" is any lap at or above threshold intensity. This includes the
# 'hard' band (classify_laps ratio ≥ 1.06) — a genuine interval rep (e.g. an
# 8×400m at ~1.25×FTP) lands in 'hard', so it MUST count here or real interval
# sessions go undetected.
_HARD_BANDS = frozenset({"tempo", "threshold", "hard"})
_RECOVERY_BANDS = frozenset({"easy", "steady"})


# ── Helpers ────────────────────────────────────────────────────────────────────

def _plain_median(values):
    """Return the median of *values* using plain arithmetic — no library imports.

    Sorts the list, then returns the middle element for an odd-length list or
    the arithmetic average of the two middle elements for an even-length list.

    Example (odd):  [90, 90, 270]   → sorted [90, 90, 270], middle index 1 → 90
    Example (even): [90, 90, 180, 180] → middle pair (90, 180), average → 135
    """
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_vals[mid])
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def _get(lap, key):
    """Retrieve a value from a lap dict or object attribute."""
    if isinstance(lap, dict):
        return lap.get(key)
    return getattr(lap, key, None)


def _band(lap):
    return _get(lap, "band")


def _dur(lap):
    return _get(lap, "duration_seconds") or 0.0


def _dist(lap):
    return _get(lap, "distance_km") or 0.0


def _validate_laps(laps):
    """Return (True, None) when laps is usable; (False, reason_str) otherwise."""
    if laps is None:
        return False, "laps is null"
    if len(laps) == 0:
        return False, "laps is empty"
    return True, None


def _build_phase(cycles, laps):
    """Assemble the Intervals phase dict from a validated list of (hard, rec) cycles."""
    all_indexes = []
    for hi, ri in cycles:
        all_indexes.append(hi)
        all_indexes.append(ri)

    total_dist = sum(_dist(laps[i]) for i in all_indexes)
    total_dur = sum(_dur(laps[i]) for i in all_indexes)
    avg_pace = total_dur / total_dist if total_dist > 0 else None

    hr_vals = [_get(laps[i], "avg_hr") for i in all_indexes if _get(laps[i], "avg_hr") is not None]
    pw_vals = [_get(laps[i], "avg_power") for i in all_indexes if _get(laps[i], "avg_power") is not None]
    avg_hr = sum(hr_vals) / len(hr_vals) if hr_vals else None
    avg_power = sum(pw_vals) / len(pw_vals) if pw_vals else None

    return {
        "label": "Intervals",
        "reps_detected": len(cycles),
        "sets_detected": 1,
        "lap_indexes": all_indexes,
        "distance_km": total_dist,
        "duration_seconds": total_dur,
        "avg_pace_seconds_per_km": avg_pace,
        "avg_hr": avg_hr,
        "avg_power": avg_power,
    }, None


# ── detect_intervals ──────────────────────────────────────────────────────────

def detect_intervals(laps):
    """Detect structured interval work from a list of classified laps.

    A lap is a hard rep when its band is 'tempo' or 'threshold' (as classified
    by classify_laps).  A lap is a recovery when its band is 'easy' or 'steady'
    and it immediately follows a hard rep.  One hard rep plus the recovery that
    follows it forms a single cycle.

    The function scans laps left to right, greedily collecting alternating
    hard/recovery cycles from the first hard rep it encounters.  Hard reps are
    considered consistent when the absolute difference between each rep's
    duration_seconds and the median hard-rep duration of the candidate sequence
    is less than HARD_REP_TOLERANCE multiplied by that median.  The first rep
    that violates this condition terminates the sequence; all laps after that
    point are excluded from the returned phase.  If the trimmed sequence has
    fewer than 2 cycles the function advances past the starting position and
    tries again from the next hard rep.

    At least 2 complete cycles are required.  Fewer cycles cause the function
    to return (None, reason_str).

    Parameters
    ----------
    laps:
        List of classified-lap dicts (output of classify_laps merged with
        original split data).  Each element must contain at minimum: band
        (str), duration_seconds (float), distance_km (float).  Optional:
        avg_hr (float|None), avg_power (float|None).

    Returns
    -------
    (phase_dict, None)   on success.
    (None, reason_str)   when laps is null/empty or fewer than 2 complete
                         hard/recovery cycles are found; never raises.

    The returned phase dict contains:
        label                    — "Intervals"
        reps_detected            — total hard reps in the phase (int)
        sets_detected            — 1 (call detect_sets to refine into sets)
        lap_indexes              — ordered 0-based indexes of all laps in the
                                   phase (hard reps interleaved with recoveries)
        distance_km              — sum of included lap distances
        duration_seconds         — sum of included lap durations
        avg_pace_seconds_per_km  — total_duration / total_distance, or None
                                   when total_distance is zero
        avg_hr                   — mean of non-None avg_hr values, or None
        avg_power                — mean of non-None avg_power values, or None

    Worked example
    --------------
    Six 200 m hard reps (band="tempo", ~60 s each) each followed by a 90 s
    easy recovery (band="easy"), all within HARD_REP_TOLERANCE of each other:

        laps = [
            {"band": "tempo", "duration_seconds": 60, "distance_km": 0.2},
            {"band": "easy",  "duration_seconds": 90, "distance_km": 0.3},
        ] * 6   # 12 laps total

        phase, reason = detect_intervals(laps)
        # → phase["label"] == "Intervals"
        # → phase["reps_detected"] == 6
        # → phase["sets_detected"] == 1
    """
    ok, reason = _validate_laps(laps)
    if not ok:
        return None, reason

    n = len(laps)

    i = 0
    while i < n:
        if _band(laps[i]) not in _HARD_BANDS:
            i += 1
            continue

        # Greedily collect alternating cycles starting at position i.
        cycles = []
        j = i
        while j + 1 < n:
            if _band(laps[j]) not in _HARD_BANDS:
                break
            if _band(laps[j + 1]) not in _RECOVERY_BANDS:
                break
            cycles.append((j, j + 1))
            j += 2

        if len(cycles) >= 2:
            # Apply tolerance: keep only the contiguous prefix of cycles whose
            # hard-rep duration is within HARD_REP_TOLERANCE of the median.
            hard_durs = [_dur(laps[hi]) for hi, ri in cycles]
            med_dur = _plain_median(hard_durs)
            valid_cycles = []
            for hi, ri in cycles:
                if med_dur > 0 and abs(_dur(laps[hi]) - med_dur) > HARD_REP_TOLERANCE * med_dur:
                    break
                valid_cycles.append((hi, ri))

            if len(valid_cycles) >= 2:
                return _build_phase(valid_cycles, laps)

        i += 1

    return None, "fewer than 2 complete hard/recovery cycles detected"


# ── detect_sets ───────────────────────────────────────────────────────────────

def detect_sets(intervals_phase, laps):
    """Split an Intervals phase into sets based on unusually long recovery laps.

    Within the Intervals phase produced by detect_intervals, each recovery lap
    whose duration_seconds exceeds the median recovery duration multiplied by
    SET_BOUNDARY_MULTIPLIER is treated as a set-boundary recovery — it marks
    the end of one set and the start of the next.  The final recovery (the one
    after the last hard rep) is never treated as a set boundary.

    The median recovery duration is computed in plain arithmetic: sort the
    recovery durations, take the middle value for an odd count, or the average
    of the two middle values for an even count.

    The returned phase dict always includes reps_per_set (a list of integers,
    one entry per set).  When no long recovery is found sets_detected is 1 and
    reps_per_set contains the single total rep count.  If all sets are even,
    reps_detected is updated to the per-set count; if sets are uneven,
    reps_detected is set to None and a human-readable reason string is returned.

    Parameters
    ----------
    intervals_phase:
        A phase dict returned by detect_intervals.  Must include lap_indexes
        (list) and reps_detected (int).
    laps:
        The original classified-lap list passed to detect_intervals.

    Returns
    -------
    (updated_phase_dict, None)    when sets are even.
    (updated_phase_dict, reason)  when sets are uneven; reps_detected is None.
    (None, reason_str)            when inputs are null or invalid; never raises.

    The updated phase dict always contains:
        sets_detected  — integer ≥ 1
        reps_per_set   — list of integers, one entry per set

    Worked example (a)
    ------------------
    Six hard reps (band="tempo", ~60 s each) each followed by a short (~90 s)
    easy recovery — all recoveries uniform, no long rest:

        updated, reason = detect_sets(intervals_phase, laps)
        # → updated["sets_detected"] == 1
        # → updated["reps_detected"] == 6
        # → updated["reps_per_set"] == [6]
        # → reason is None

    Worked example (b)
    ------------------
    Twelve hard reps in total: reps 1–6 each followed by a short (~90 s)
    recovery, then one long recovery (~270 s, roughly 3× the median), then
    reps 7–12 each followed by short recoveries:

        updated, reason = detect_sets(intervals_phase, laps)
        # → updated["sets_detected"] == 2
        # → updated["reps_detected"] == 6
        # → updated["reps_per_set"] == [6, 6]
        # → reason is None
    """
    if intervals_phase is None:
        return None, "intervals_phase is null"

    if isinstance(intervals_phase, dict):
        lap_indexes = intervals_phase.get("lap_indexes")
        total_reps = intervals_phase.get("reps_detected")
    else:
        lap_indexes = getattr(intervals_phase, "lap_indexes", None)
        total_reps = getattr(intervals_phase, "reps_detected", None)

    if not lap_indexes:
        return None, "intervals_phase has no lap_indexes"

    if total_reps is None:
        return None, "intervals_phase has no reps_detected"

    ok, reason = _validate_laps(laps)
    if not ok:
        return None, reason

    # Walk the phase's lap_indexes, recording each recovery and how many hard
    # reps preceded it within this phase.
    hard_count = 0
    recovery_entries = []  # list of (hard_reps_before_this_recovery, duration)
    for idx in lap_indexes:
        b = _band(laps[idx])
        if b in _HARD_BANDS:
            hard_count += 1
        elif b in _RECOVERY_BANDS:
            recovery_entries.append((hard_count, _dur(laps[idx])))

    if len(recovery_entries) < 2:
        # Not enough recoveries to establish a median; treat as a single set.
        updated = dict(intervals_phase)
        updated["sets_detected"] = 1
        updated["reps_per_set"] = [total_reps]
        return updated, None

    med_rec = _plain_median([dur for _, dur in recovery_entries])

    # A recovery is a set boundary when its duration exceeds
    # SET_BOUNDARY_MULTIPLIER × median_recovery_duration.  The final recovery
    # (hard_count == total_reps) is excluded — it follows the last rep and
    # does not separate sets.
    boundaries = []
    for hard_before, dur in recovery_entries:
        if hard_before == total_reps:
            continue
        if med_rec > 0 and dur > SET_BOUNDARY_MULTIPLIER * med_rec:
            boundaries.append(hard_before)

    sets_count = len(boundaries) + 1
    set_boundaries = [0] + boundaries + [total_reps]
    reps_per_set = [set_boundaries[k + 1] - set_boundaries[k] for k in range(sets_count)]

    updated = dict(intervals_phase)
    updated["sets_detected"] = sets_count
    updated["reps_per_set"] = reps_per_set

    if len(set(reps_per_set)) == 1:
        updated["reps_detected"] = reps_per_set[0]
        return updated, None

    updated["reps_detected"] = None
    return updated, f"set sizes are uneven: {reps_per_set}"
