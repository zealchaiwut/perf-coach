"""Per-workout power and pace duration curve computation.

Duration curves identify the best power output or fastest pace an athlete
sustained continuously for a set of standard time windows within a single
workout. Two pure, database-free functions do all the maths; a thin caller
fetches data from the database and delegates to them.

Rolling-window arithmetic
--------------------------
A sliding window of width W moves one sample at a time across the stream
(e.g. W=300 for a 5-minute window). At each position the window covers W
consecutive samples; their arithmetic mean is one candidate value. The best
candidate (highest for power, lowest for pace) is the duration-curve value for
that window size.

Fallback hierarchy when a raw stream is unavailable
----------------------------------------------------
1. Raw stream — preferred when available and long enough for the window.
2. Lap/split aggregates — used when the stream is absent or too short.
3. Workout-level aggregates — used when no individual lap covers the window.
4. Empty result with reason — returned when none of the above apply.
"""

from __future__ import annotations

DURATION_LADDER = [1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 5400]


# ── Pure computation functions ────────────────────────────────────────────────

def compute_power_curve(
    workout_id,
    stream,
    laps,
    aggregates,
    duration_ladder,
):
    """Compute best average power sustained for each duration in the ladder.

    The function derives a power duration curve from a per-second power stream
    (watts), falling back to lap and workout aggregates when the stream is
    absent or too short for a given duration window.

    Best 5-minute power example: given a stream of 360 seconds of power values
    (one watt reading per second), the best 5-minute (300-second) power equals
    the highest average of any 300 consecutive values in that stream.
    A flat 280-watt stream produces a 300-second best of 280 watts with
    confidence "measured".

    Fallback example: when no stream is available but a 10-minute lap of 600
    seconds exists with avg_power 250 watts, the best 5-minute (300-second)
    power is approximated as 250 watts (confidence "approx") because the lap
    lasted at least 300 seconds at that average power.

    Parameters
    ----------
    workout_id:
        Identifier embedded in each returned duration-point as source_workout_id.
    stream:
        Ordered per-second power readings in watts, one element per second.
        May be None or an empty list when no stream was recorded.
    laps:
        List of lap/split records. Each must expose duration_seconds (int) and
        avg_power (int or None) as dict keys or object attributes.
    aggregates:
        Workout-level record exposing duration_seconds, avg_power, and
        workout_date (ISO-8601 string or None). May be None.
    duration_ladder:
        Ordered list of duration values in seconds for which to compute the
        curve. Passed by the caller; never hardcoded inside this function.

    Returns
    -------
    list[dict]
        One dict per element of duration_ladder. Each dict always contains:
        duration_seconds, value, source_workout_id, date, confidence, debug.
        Points with no data additionally contain a reason string explaining
        why that duration was skipped.
    """
    stream_list = list(stream) if stream else []
    stream_length = len(stream_list)
    workout_id_str = str(workout_id)
    workout_date_str = _get_date(aggregates)
    laps_list = laps or []

    points = []
    for d in duration_ladder:
        if stream_list and stream_length >= d:
            # Sliding-window path: find the highest arithmetic mean over any
            # d consecutive samples. This directly measures what the athlete
            # sustained for exactly d seconds at their best.
            value = _rolling_max_avg(stream_list, d)
            points.append({
                "duration_seconds": d,
                "value": value,
                "source_workout_id": workout_id_str,
                "date": workout_date_str,
                "confidence": "measured",
                "debug": {
                    "window_size": d,
                    "num_samples": stream_length,
                    "aggregation_method": "rolling_max_avg",
                },
            })
            continue

        # Lap fallback: any lap that lasted at least d seconds and has power
        # data qualifies. We pick the highest avg_power among qualifying laps
        # because a longer lap at a given average implies that average was
        # sustained for at least d seconds.
        lap_candidates = [
            _get_field(lap, "avg_power")
            for lap in laps_list
            if (_get_field(lap, "duration_seconds") or 0) >= d
            and _get_field(lap, "avg_power") is not None
        ]
        if lap_candidates:
            points.append({
                "duration_seconds": d,
                "value": max(lap_candidates),
                "source_workout_id": workout_id_str,
                "date": workout_date_str,
                "confidence": "approx",
                "debug": {
                    "window_size": d,
                    "num_samples": len(lap_candidates),
                    "aggregation_method": "lap_avg_power",
                },
            })
            continue

        # Workout aggregate fallback: if the total workout duration covers the
        # window and we have workout-level avg_power, use it. This is a coarser
        # approximation — the whole workout average may hide peaks, but it is
        # a conservative lower bound.
        agg_dur = (_get_field(aggregates, "duration_seconds") or 0) if aggregates else 0
        agg_power = _get_field(aggregates, "avg_power") if aggregates else None
        if agg_dur >= d and agg_power is not None:
            points.append({
                "duration_seconds": d,
                "value": float(agg_power),
                "source_workout_id": workout_id_str,
                "date": workout_date_str,
                "confidence": "approx",
                "debug": {
                    "window_size": d,
                    "num_samples": 1,
                    "aggregation_method": "workout_avg_power",
                    "workout_duration_seconds": agg_dur,
                },
            })
            continue

        # No data covers this window — return an empty result with a
        # human-readable explanation of why it was skipped.
        reason = _power_skip_reason(d, stream_length, laps_list, aggregates)
        points.append({
            "duration_seconds": d,
            "value": None,
            "source_workout_id": workout_id_str,
            "date": workout_date_str,
            "confidence": None,
            "reason": reason,
            "debug": {},
        })

    return points


def compute_pace_curve(
    workout_id,
    stream,
    laps,
    aggregates,
    duration_ladder,
):
    """Compute best pace (lowest seconds per km) sustained for each duration.

    Pace is expressed in seconds per kilometre. A lower value means a faster
    pace, so "best" is the minimum rolling average over the duration window —
    the opposite direction from power.

    Best 5-minute pace example: given a stream of 360 seconds of pace values
    (one reading per second in seconds per kilometre), the best 5-minute
    (300-second) pace equals the lowest average of any 300 consecutive values.
    A flat 300 s/km stream produces a 300-second best of 300 s/km with
    confidence "measured".

    Fallback example: when no stream is available but a 10-minute lap covering
    2 km exists, its average pace is 600 s / 2 km = 300 s/km. For any duration
    up to 600 s, this lap qualifies (it lasted at least that long) and 300 s/km
    is returned with confidence "approx". Among multiple qualifying laps the
    fastest (lowest s/km) is chosen.

    Parameters
    ----------
    workout_id:
        Identifier embedded in each returned duration-point as source_workout_id.
    stream:
        Ordered per-second pace readings in seconds per kilometre (s/km), one
        element per second. May be None or empty when no pace stream exists.
    laps:
        List of lap/split records. Each must expose duration_seconds (int) and
        distance_km (float or None) as dict keys or object attributes.
    aggregates:
        Workout-level record exposing duration_seconds, distance_km, and
        workout_date. May be None.
    duration_ladder:
        Ordered list of duration values in seconds. Passed by the caller;
        never hardcoded inside this function.

    Returns
    -------
    list[dict]
        Same structure as compute_power_curve. value is in seconds/km; a lower
        value means a faster (better) pace.
    """
    stream_list = list(stream) if stream else []
    stream_length = len(stream_list)
    workout_id_str = str(workout_id)
    workout_date_str = _get_date(aggregates)
    laps_list = laps or []

    points = []
    for d in duration_ladder:
        if stream_list and stream_length >= d:
            # Sliding-window path: find the lowest arithmetic mean over any
            # d consecutive samples. The minimum average represents the fastest
            # sustained pace for that exact duration.
            value = _rolling_min_avg(stream_list, d)
            points.append({
                "duration_seconds": d,
                "value": value,
                "source_workout_id": workout_id_str,
                "date": workout_date_str,
                "confidence": "measured",
                "debug": {
                    "window_size": d,
                    "num_samples": stream_length,
                    "aggregation_method": "rolling_min_avg",
                },
            })
            continue

        # Lap fallback: derive pace from each lap's duration and distance.
        # Only laps lasting at least d seconds qualify. The fastest (lowest
        # s/km) among qualifying laps is chosen.
        lap_paces = []
        for lap in laps_list:
            lap_dur = _get_field(lap, "duration_seconds") or 0
            lap_dist = _get_field(lap, "distance_km")
            if lap_dur >= d and lap_dist and float(lap_dist) > 0:
                # Pace = elapsed time divided by distance; a smaller result
                # means the athlete covered the distance faster.
                lap_paces.append(lap_dur / float(lap_dist))

        if lap_paces:
            points.append({
                "duration_seconds": d,
                "value": min(lap_paces),
                "source_workout_id": workout_id_str,
                "date": workout_date_str,
                "confidence": "approx",
                "debug": {
                    "window_size": d,
                    "num_samples": len(lap_paces),
                    "aggregation_method": "lap_pace_duration_over_distance",
                },
            })
            continue

        # Workout aggregate fallback: derive pace from total duration and
        # distance. This represents the whole-workout average pace, which is
        # a valid approximation for any window the workout covers.
        agg_dur = (_get_field(aggregates, "duration_seconds") or 0) if aggregates else 0
        agg_dist = _get_field(aggregates, "distance_km") if aggregates else None
        if agg_dur >= d and agg_dist and float(agg_dist) > 0:
            points.append({
                "duration_seconds": d,
                "value": agg_dur / float(agg_dist),
                "source_workout_id": workout_id_str,
                "date": workout_date_str,
                "confidence": "approx",
                "debug": {
                    "window_size": d,
                    "num_samples": 1,
                    "aggregation_method": "workout_pace_duration_over_distance",
                    "workout_duration_seconds": agg_dur,
                },
            })
            continue

        # No data covers this window — return an empty result with a
        # human-readable explanation of why it was skipped.
        reason = _pace_skip_reason(d, stream_length, laps_list, aggregates)
        points.append({
            "duration_seconds": d,
            "value": None,
            "source_workout_id": workout_id_str,
            "date": workout_date_str,
            "confidence": None,
            "reason": reason,
            "debug": {},
        })

    return points


# ── Thin database caller ───────────────────────────────────────────────────────

def fetch_workout_curves(workout_id, db):
    """Fetch stream, laps, and workout aggregate from the database and compute curves.

    This is the only function in this module that performs database access.
    It reads the activity_streams, workout_splits, and workouts tables for the
    given workout, converts ORM rows to plain dicts, and delegates to
    compute_power_curve and compute_pace_curve with the standard 12-duration
    ladder defined in DURATION_LADDER.

    Parameters
    ----------
    workout_id:
        UUID (or string representation) of the target workout.
    db:
        Active SQLAlchemy session.

    Returns
    -------
    dict with keys:
        power_curve — list of 12 duration-point dicts (watts)
        pace_curve  — list of 12 duration-point dicts (seconds/km)
    """
    from backend.models import ActivityStream, WorkoutSplit, Workout

    stream_row = (
        db.query(ActivityStream)
        .filter(ActivityStream.workout_id == workout_id)
        .first()
    )

    splits = (
        db.query(WorkoutSplit)
        .filter(WorkoutSplit.workout_id == workout_id)
        .order_by(WorkoutSplit.split_index)
        .all()
    )

    workout = (
        db.query(Workout)
        .filter(Workout.id == workout_id)
        .first()
    )

    power_stream = list(stream_row.power_w) if stream_row and stream_row.power_w else None
    pace_stream = (
        list(stream_row.pace_seconds_per_km)
        if stream_row and stream_row.pace_seconds_per_km
        else None
    )

    laps = [
        {
            "duration_seconds": s.duration_seconds,
            "distance_km": float(s.distance_km) if s.distance_km is not None else None,
            "avg_power": s.avg_power,
        }
        for s in splits
    ]

    aggregates = None
    if workout:
        aggregates = {
            "duration_seconds": workout.duration_seconds,
            "distance_km": float(workout.distance_km) if workout.distance_km is not None else None,
            "avg_power": workout.avg_power,
            "workout_date": str(workout.workout_date) if workout.workout_date else None,
        }

    power_curve = compute_power_curve(
        workout_id, power_stream, laps, aggregates, DURATION_LADDER
    )
    pace_curve = compute_pace_curve(
        workout_id, pace_stream, laps, aggregates, DURATION_LADDER
    )

    return {"power_curve": power_curve, "pace_curve": pace_curve}


# ── Private helpers ───────────────────────────────────────────────────────────

def _rolling_max_avg(stream, window_size):
    """Return the highest arithmetic average over any window_size consecutive samples.

    Uses an efficient sliding-sum: subtract the departing sample and add the
    arriving sample rather than re-summing the entire window each step.
    """
    if len(stream) < window_size:
        return None
    # Compute the sum of the first window to get the initial average.
    window_sum = sum(stream[:window_size])
    best = window_sum / window_size
    for i in range(window_size, len(stream)):
        # Slide the window one position forward without a full re-sum.
        window_sum += stream[i] - stream[i - window_size]
        avg = window_sum / window_size
        if avg > best:
            best = avg
    return best


def _rolling_min_avg(stream, window_size):
    """Return the lowest arithmetic average over any window_size consecutive samples.

    Same sliding-sum technique as _rolling_max_avg, but records the minimum
    (fastest pace) rather than the maximum (highest power).
    """
    if len(stream) < window_size:
        return None
    window_sum = sum(stream[:window_size])
    best = window_sum / window_size
    for i in range(window_size, len(stream)):
        window_sum += stream[i] - stream[i - window_size]
        avg = window_sum / window_size
        if avg < best:
            best = avg
    return best


def _get_field(obj, key):
    """Read a named field from a dict or an ORM-like object without raising."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _get_date(aggregates):
    """Extract workout_date as a string from the aggregates record, or None."""
    val = _get_field(aggregates, "workout_date") if aggregates else None
    return str(val) if val is not None else None


def _power_skip_reason(duration, stream_length, laps, aggregates):
    """Build a human-readable explanation for why a power duration point is empty."""
    agg_dur = (_get_field(aggregates, "duration_seconds") or 0) if aggregates else 0
    agg_power = _get_field(aggregates, "avg_power") if aggregates else None

    # The workout itself is too short for this window.
    if agg_dur > 0 and agg_dur < duration:
        return f"workout duration ({agg_dur} s) is shorter than window ({duration} s)"

    # The workout covers the window but has no power data.
    if agg_dur >= duration and agg_power is None:
        return f"workout covers the {duration} s window but has no avg_power data"

    # A stream exists but is too short.
    if stream_length > 0:
        return f"stream length ({stream_length} s) is shorter than window ({duration} s)"

    return f"no power data (stream, laps, or aggregate) covers the {duration} s window"


def _pace_skip_reason(duration, stream_length, laps, aggregates):
    """Build a human-readable explanation for why a pace duration point is empty."""
    agg_dur = (_get_field(aggregates, "duration_seconds") or 0) if aggregates else 0
    agg_dist = _get_field(aggregates, "distance_km") if aggregates else None

    # The workout is too short for this window.
    if agg_dur > 0 and agg_dur < duration:
        return f"workout duration ({agg_dur} s) is shorter than window ({duration} s)"

    # The workout covers the window but has no distance data to compute pace.
    if agg_dur >= duration and (not agg_dist or float(agg_dist) <= 0):
        return f"workout covers the {duration} s window but has no distance data for pace"

    # A stream exists but is too short.
    if stream_length > 0:
        return f"stream length ({stream_length} s) is shorter than window ({duration} s)"

    return f"no pace data (stream, laps, or aggregate) covers the {duration} s window"
