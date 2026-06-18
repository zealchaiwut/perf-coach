"""Duration curve computation: per-workout best power and pace for each duration window.

This module provides pure functions for computing the best-effort value at each
duration in a ladder. A per-second stream is preferred (confidence="measured");
lap-level and workout-level aggregates are used as fallbacks (confidence="approx").

Worked example — power curve from stream
-----------------------------------------
Given a 360-second power stream [300, 285, 310, …] and a duration ladder that
includes 300 seconds, the best 5-minute power equals the highest arithmetic
average of any 300 consecutive values in that stream. If the highest such average
is 295 watts, the duration-300 point is {duration_seconds: 300, best_value: 295,
confidence: "measured"}.

Worked example — power from laps (fallback)
---------------------------------------------
If no stream is available but the workout has a lap with duration_seconds=305 and
avg_power=280, that lap is used to estimate the best 300-second power as 280 watts
with confidence="approx". The lap's own avg_power is used directly (we cannot
infer a higher sustained effort from it).
"""

_DEFAULT_DURATION_LADDER = [1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 5400]


def compute_power_curve(workout_id, stream, laps, aggregates, duration_ladder):
    """Compute best-power duration curve for one workout. Pure function — no DB access.

    Parameters
    ----------
    workout_id : str or UUID
        Identifier embedded in every returned point so callers know the source.
    stream : list[float] or None
        Ordered per-second power readings in watts. Each element covers exactly
        one second. Pass None or an empty list when no stream is available.
    laps : list[dict]
        Each dict must have at minimum: ``duration_seconds`` (int) and
        ``avg_power`` (float or None). Used as fallback when the stream is
        absent or shorter than the requested window.
    aggregates : dict
        Workout-level summary with keys: ``avg_power`` (float or None),
        ``duration_seconds`` (int or None), ``workout_date`` (ISO-8601 str or None).
    duration_ladder : list[int]
        Duration windows to evaluate, in ascending order of seconds.

    Returns
    -------
    (points, debug)
        points — list of dicts with keys:
            ``duration_seconds``, ``best_value``, ``source_workout_id``,
            ``date``, ``confidence``.
        debug — dict with keys:
            ``stream_length_seconds``, ``durations_from_stream``,
            ``durations_from_aggregates``, ``durations_skipped``.
    """
    points = []
    debug = {
        "stream_length_seconds": len(stream) if stream else 0,
        "durations_from_stream": [],
        "durations_from_aggregates": [],
        "durations_skipped": [],
    }
    workout_date = aggregates.get("workout_date")

    for duration in duration_ladder:
        best_value = None
        confidence = None
        skip_reason = None

        if stream and len(stream) >= duration:
            best_value = _rolling_max_avg(stream, duration)
            confidence = "measured"
        else:
            best_value = _best_power_from_laps(duration, laps)
            if best_value is not None:
                confidence = "approx"
            else:
                best_value = _best_power_from_aggregates(duration, aggregates)
                if best_value is not None:
                    confidence = "approx"
                else:
                    skip_reason = _skip_reason_power(duration, stream, laps, aggregates)

        if best_value is not None:
            points.append({
                "duration_seconds": duration,
                "best_value": float(best_value),
                "source_workout_id": str(workout_id),
                "date": workout_date,
                "confidence": confidence,
            })
            if confidence == "measured":
                debug["durations_from_stream"].append(duration)
            else:
                debug["durations_from_aggregates"].append(duration)
        else:
            debug["durations_skipped"].append({
                "duration_seconds": duration,
                "reason": skip_reason,
            })

    return points, debug


def compute_pace_curve(workout_id, stream, laps, aggregates, duration_ladder):
    """Compute best-pace duration curve for one workout. Pure function — no DB access.

    For pace, "best" means fastest (lowest seconds per km). Rolling minimum average
    is used when a stream is available.

    Parameters
    ----------
    workout_id : str or UUID
        Identifier embedded in every returned point.
    stream : list[float] or None
        Per-second pace values in seconds-per-km. Pass None/empty if unavailable.
    laps : list[dict]
        Each dict must have ``duration_seconds`` (int) and ``pace_seconds_per_km``
        (float or None). Computed from split ``distance_km`` and ``duration_seconds``
        when not stored directly.
    aggregates : dict
        Workout-level summary with keys: ``pace_seconds_per_km`` (float or None),
        ``duration_seconds`` (int or None), ``workout_date`` (ISO-8601 str or None).
    duration_ladder : list[int]
        Duration windows to evaluate, in ascending order of seconds.

    Returns
    -------
    (points, debug)
        Same structure as compute_power_curve. ``best_value`` is in seconds/km.
    """
    points = []
    debug = {
        "stream_length_seconds": len(stream) if stream else 0,
        "durations_from_stream": [],
        "durations_from_aggregates": [],
        "durations_skipped": [],
    }
    workout_date = aggregates.get("workout_date")

    for duration in duration_ladder:
        best_value = None
        confidence = None
        skip_reason = None

        if stream and len(stream) >= duration:
            best_value = _rolling_min_avg(stream, duration)
            confidence = "measured"
        else:
            best_value = _best_pace_from_laps(duration, laps)
            if best_value is not None:
                confidence = "approx"
            else:
                best_value = _best_pace_from_aggregates(duration, aggregates)
                if best_value is not None:
                    confidence = "approx"
                else:
                    skip_reason = _skip_reason_pace(duration, stream, laps, aggregates)

        if best_value is not None:
            points.append({
                "duration_seconds": duration,
                "best_value": float(best_value),
                "source_workout_id": str(workout_id),
                "date": workout_date,
                "confidence": confidence,
            })
            if confidence == "measured":
                debug["durations_from_stream"].append(duration)
            else:
                debug["durations_from_aggregates"].append(duration)
        else:
            debug["durations_skipped"].append({
                "duration_seconds": duration,
                "reason": skip_reason,
            })

    return points, debug


def fetch_and_compute_curves(workout_id, db):
    """Fetch stream, splits, and workout from the DB then compute both duration curves.

    This is the thin caller that handles all database reads and delegates all
    curve arithmetic to compute_power_curve and compute_pace_curve.

    Parameters
    ----------
    workout_id : UUID
        The workout to compute curves for.
    db : sqlalchemy.orm.Session
        An open database session.

    Returns
    -------
    dict with keys:
        ``power_curve``  — list of duration-point dicts (watts)
        ``pace_curve``   — list of duration-point dicts (seconds/km)
        ``power_debug``  — debug dict from compute_power_curve
        ``pace_debug``   — debug dict from compute_pace_curve
    """
    from backend.models import ActivityStream, Workout, WorkoutSplit

    workout = db.get(Workout, workout_id)
    if workout is None:
        return {
            "power_curve": [],
            "pace_curve": [],
            "power_debug": {"stream_length_seconds": 0, "durations_from_stream": [], "durations_from_aggregates": [], "durations_skipped": []},
            "pace_debug": {"stream_length_seconds": 0, "durations_from_stream": [], "durations_from_aggregates": [], "durations_skipped": []},
        }

    stream_row = db.get(ActivityStream, workout_id)
    power_stream = (stream_row.power_w or []) if stream_row else []
    pace_stream = (stream_row.pace_seconds_per_km or []) if stream_row else []

    splits = (
        db.query(WorkoutSplit)
        .filter(WorkoutSplit.workout_id == workout_id)
        .order_by(WorkoutSplit.split_index)
        .all()
    )
    laps = [
        {
            "duration_seconds": s.duration_seconds,
            "avg_power": s.avg_power,
            "distance_km": float(s.distance_km) if s.distance_km else None,
        }
        for s in splits
        if s.duration_seconds is not None and s.duration_seconds > 0
    ]
    # Derive per-lap pace where not directly stored
    for lap in laps:
        if lap.get("distance_km") and lap["distance_km"] > 0:
            lap["pace_seconds_per_km"] = lap["duration_seconds"] / lap["distance_km"]
        else:
            lap["pace_seconds_per_km"] = None

    workout_date = workout.workout_date.isoformat() if workout.workout_date else None
    # Derive workout-level pace from distance/duration when not stored
    workout_pace = None
    if workout.distance_km and float(workout.distance_km) > 0 and workout.duration_seconds:
        workout_pace = workout.duration_seconds / float(workout.distance_km)

    aggregates = {
        "workout_date": workout_date,
        "avg_power": workout.avg_power,
        "duration_seconds": workout.duration_seconds,
        "pace_seconds_per_km": workout_pace,
    }

    power_curve, power_debug = compute_power_curve(
        workout_id, power_stream, laps, aggregates, _DEFAULT_DURATION_LADDER
    )
    pace_curve, pace_debug = compute_pace_curve(
        workout_id, pace_stream, laps, aggregates, _DEFAULT_DURATION_LADDER
    )

    return {
        "power_curve": power_curve,
        "pace_curve": pace_curve,
        "power_debug": power_debug,
        "pace_debug": pace_debug,
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _rolling_max_avg(stream, window_size):
    """Return the highest arithmetic average over any consecutive window_size samples."""
    if len(stream) < window_size:
        return None
    window_sum = sum(stream[:window_size])
    best = window_sum / window_size
    for i in range(window_size, len(stream)):
        window_sum += stream[i] - stream[i - window_size]
        avg = window_sum / window_size
        if avg > best:
            best = avg
    return best


def _rolling_min_avg(stream, window_size):
    """Return the lowest arithmetic average over any consecutive window_size samples."""
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


def _best_power_from_laps(duration, laps):
    """Return the highest avg_power from any lap covering at least `duration` seconds."""
    candidates = [
        lap["avg_power"]
        for lap in laps
        if (
            lap.get("avg_power") is not None
            and lap.get("duration_seconds") is not None
            and lap["duration_seconds"] >= duration
        )
    ]
    return max(candidates) if candidates else None


def _best_pace_from_laps(duration, laps):
    """Return the fastest (lowest) pace_seconds_per_km from any lap covering the duration."""
    candidates = [
        lap["pace_seconds_per_km"]
        for lap in laps
        if (
            lap.get("pace_seconds_per_km") is not None
            and lap.get("duration_seconds") is not None
            and lap["duration_seconds"] >= duration
        )
    ]
    return min(candidates) if candidates else None


def _best_power_from_aggregates(duration, aggregates):
    """Use workout-level avg_power when the workout is at least as long as the duration."""
    if (
        aggregates.get("avg_power") is not None
        and aggregates.get("duration_seconds") is not None
        and aggregates["duration_seconds"] >= duration
    ):
        return aggregates["avg_power"]
    return None


def _best_pace_from_aggregates(duration, aggregates):
    """Use workout-level pace when the workout is at least as long as the duration."""
    if (
        aggregates.get("pace_seconds_per_km") is not None
        and aggregates.get("duration_seconds") is not None
        and aggregates["duration_seconds"] >= duration
    ):
        return aggregates["pace_seconds_per_km"]
    return None


def _skip_reason_power(duration, stream, laps, aggregates):
    stream_len = len(stream) if stream else 0
    if not stream:
        base = "no power stream"
    else:
        base = f"stream length {stream_len}s is shorter than {duration}s window"
    lap_count = len([
        lap for lap in laps
        if lap.get("avg_power") is not None and (lap.get("duration_seconds") or 0) >= duration
    ])
    if lap_count == 0:
        return f"{base} and no lap longer than {duration}s with power data"
    return f"{base} and no qualifying aggregate for {duration}s"


def _skip_reason_pace(duration, stream, laps, aggregates):
    stream_len = len(stream) if stream else 0
    if not stream:
        base = "no pace stream"
    else:
        base = f"stream length {stream_len}s is shorter than {duration}s window"
    return f"{base} and no qualifying lap or aggregate for {duration}s"
