"""Power and pace duration curve computation.

Duration curves identify the best power output or fastest pace an athlete
sustained continuously for a set of standard time windows within a single
workout.  Two pure, database-free functions do all the maths; a thin caller
fetches data from the database and delegates to them.
"""
from __future__ import annotations

from typing import Optional

STANDARD_DURATION_LADDER = [1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 5400]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _rolling_averages(stream: list, window: int) -> list:
    """Return all rolling averages of length `window` over `stream`."""
    return [
        sum(stream[i: i + window]) / window
        for i in range(len(stream) - window + 1)
    ]


def _val(obj, key):
    """Get a field from either a dict or an ORM-like object."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


# ── Pure computation functions ────────────────────────────────────────────────

def compute_power_curve(
    workout_id,
    stream: Optional[list],
    laps: Optional[list],
    aggregates,
    duration_ladder: list,
) -> tuple[list, dict]:
    """Compute best average power sustained for each duration in the ladder.

    The function computes a power duration curve from a per-second power
    stream (watts), falling back to lap and workout aggregates when the stream
    is absent or too short for a given duration window.

    Parameters
    ----------
    workout_id:
        Identifier embedded in each returned duration-point as
        ``source_workout_id``.
    stream:
        Ordered per-second power readings in watts, one element per second of
        elapsed workout time.  May be ``None`` or an empty list when no
        stream was recorded.
    laps:
        List of lap/split records.  Each record must expose (as dict keys or
        attributes) ``duration_seconds`` (int) and ``avg_power`` (int or
        ``None``).
    aggregates:
        Workout-level aggregate record exposing ``duration_seconds``,
        ``avg_power``, and ``workout_date`` (ISO-8601 string or ``None``).
        May be ``None`` when no workout row exists.
    duration_ladder:
        Ordered list of duration values in seconds for which to compute the
        curve.  Passed by the caller; never hardcoded inside this function.

    Returns
    -------
    A two-element tuple ``(points, debug)``.

    ``points`` — list of duration-point dicts, one per element of
        ``duration_ladder``, each with:
        ``duration_seconds`` (int), ``best_value`` (float or ``None``),
        ``source_workout_id`` (str), ``date`` (ISO-8601 str or ``None``),
        ``confidence`` (``"measured"``, ``"approx"``, or ``None``).

    ``debug`` — dict with:
        ``stream_length_seconds`` (int), ``durations_from_stream`` (list of
        duration values resolved via rolling average), ``durations_from_aggregates``
        (list resolved via lap or workout fallback), ``durations_skipped``
        (list of human-readable reason strings for durations with no data).

    Worked example
    --------------
    Given a stream of 360 seconds of power values (one watt reading per
    second), the best 5-minute (300-second) power equals the highest average
    of any 300 consecutive values in that stream.  A flat 280-watt stream
    produces a 300-second best of 280 watts with confidence "measured".

    Fallback example
    ----------------
    When no stream is available but a 10-minute lap of 600 seconds exists
    with avg_power 250 watts, the best 5-minute (300-second) power is
    approximated as 250 watts (confidence "approx") because the lap lasted
    at least 300 seconds at that average power.  If the workout aggregate
    shows a total duration of 3600 seconds with avg_power 220 watts, that
    value is used for windows longer than any individual lap's duration.
    When neither laps nor aggregates cover a given duration, best_value is
    null and the reason is recorded in debug["durations_skipped"].
    """
    stream_list = stream if stream else []
    stream_length = len(stream_list)

    debug: dict = {
        "stream_length_seconds": stream_length,
        "durations_from_stream": [],
        "durations_from_aggregates": [],
        "durations_skipped": [],
    }

    workout_date = _val(aggregates, "workout_date")
    workout_date_str = str(workout_date) if workout_date is not None else None
    workout_id_str = str(workout_id)

    points = []
    for d in duration_ladder:
        if stream_list and stream_length >= d:
            averages = _rolling_averages(stream_list, d)
            best = max(averages)
            confidence = "measured"
            debug["durations_from_stream"].append(d)
        else:
            # Lap fallback: any lap that lasted at least d seconds with power data.
            qualifying = [
                _val(lap, "avg_power")
                for lap in (laps or [])
                if (_val(lap, "duration_seconds") or 0) >= d
                and _val(lap, "avg_power") is not None
            ]
            if qualifying:
                best = max(qualifying)
                confidence = "approx"
                debug["durations_from_aggregates"].append(d)
            elif (
                aggregates is not None
                and (_val(aggregates, "duration_seconds") or 0) >= d
                and _val(aggregates, "avg_power") is not None
            ):
                best = _val(aggregates, "avg_power")
                confidence = "approx"
                debug["durations_from_aggregates"].append(d)
            else:
                agg_dur = (_val(aggregates, "duration_seconds") or 0) if aggregates else 0
                if not stream_list and not (laps or []) and aggregates is None:
                    reason = f"no stream and no laps and no aggregate for {d} s"
                elif not qualifying and agg_dur < d:
                    reason = (
                        f"no stream and no lap or aggregate with duration >= {d} s"
                    )
                else:
                    reason = f"no stream and no lap or aggregate with power data for {d} s"
                debug["durations_skipped"].append(reason)
                points.append({
                    "duration_seconds": d,
                    "best_value": None,
                    "source_workout_id": workout_id_str,
                    "date": workout_date_str,
                    "confidence": None,
                })
                continue

        points.append({
            "duration_seconds": d,
            "best_value": best,
            "source_workout_id": workout_id_str,
            "date": workout_date_str,
            "confidence": confidence,
        })

    return points, debug


def compute_pace_curve(
    workout_id,
    stream: Optional[list],
    laps: Optional[list],
    aggregates,
    duration_ladder: list,
) -> tuple[list, dict]:
    """Compute best pace (lowest seconds per km) sustained for each duration in the ladder.

    Pace is expressed in seconds per kilometre; a lower value means a faster
    pace, so "best" is the minimum rolling average over the duration window.

    Parameters
    ----------
    workout_id:
        Identifier embedded in each returned duration-point as
        ``source_workout_id``.
    stream:
        Ordered per-second pace readings in seconds per kilometre (s/km),
        one element per second of elapsed workout time.  May be ``None`` or
        empty when no pace stream was recorded.
    laps:
        List of lap/split records.  Each record must expose ``duration_seconds``
        (int) and ``distance_km`` (float or ``None``).
    aggregates:
        Workout-level aggregate record exposing ``duration_seconds``,
        ``distance_km``, and ``workout_date``.  May be ``None``.
    duration_ladder:
        Ordered list of duration values in seconds.  Passed by the caller;
        never hardcoded inside this function.

    Returns
    -------
    Same structure as :func:`compute_power_curve`: ``(points, debug)``.

    Worked example
    --------------
    Given a stream of 360 seconds of pace values (one reading per second in
    seconds per kilometre), the best 5-minute (300-second) pace equals the
    lowest average of any 300 consecutive values in that stream.  A flat
    300 s/km stream produces a 300-second best of 300 s/km with confidence
    "measured".

    Fallback example
    ----------------
    When no stream is available but a 10-minute lap covering 2 km exists, its
    average pace is 600 s / 2 km = 300 s/km.  For any duration up to 600 s,
    this lap qualifies (it lasted at least that long) and 300 s/km is returned
    with confidence "approx".  Among multiple qualifying laps the fastest
    (lowest s/km) is chosen.  If no lap or aggregate covers a requested
    duration, best_value is null and the reason is recorded in
    debug["durations_skipped"].
    """
    stream_list = stream if stream else []
    stream_length = len(stream_list)

    debug: dict = {
        "stream_length_seconds": stream_length,
        "durations_from_stream": [],
        "durations_from_aggregates": [],
        "durations_skipped": [],
    }

    workout_date = _val(aggregates, "workout_date")
    workout_date_str = str(workout_date) if workout_date is not None else None
    workout_id_str = str(workout_id)

    points = []
    for d in duration_ladder:
        if stream_list and stream_length >= d:
            averages = _rolling_averages(stream_list, d)
            best = min(averages)  # fastest pace = lowest s/km
            confidence = "measured"
            debug["durations_from_stream"].append(d)
        else:
            # Lap fallback: laps lasting >= d seconds with distance data.
            qualifying_paces = []
            for lap in (laps or []):
                lap_dur = _val(lap, "duration_seconds") or 0
                lap_dist = _val(lap, "distance_km")
                if lap_dur >= d and lap_dist and float(lap_dist) > 0:
                    qualifying_paces.append(lap_dur / float(lap_dist))

            if qualifying_paces:
                best = min(qualifying_paces)
                confidence = "approx"
                debug["durations_from_aggregates"].append(d)
            else:
                agg_dur = (_val(aggregates, "duration_seconds") or 0) if aggregates else 0
                agg_dist = _val(aggregates, "distance_km") if aggregates else None
                if agg_dur >= d and agg_dist and float(agg_dist) > 0:
                    best = agg_dur / float(agg_dist)
                    confidence = "approx"
                    debug["durations_from_aggregates"].append(d)
                else:
                    if not stream_list and not (laps or []) and aggregates is None:
                        reason = f"no stream and no laps and no aggregate for {d} s"
                    elif not qualifying_paces and agg_dur < d:
                        reason = (
                            f"no stream and no lap or aggregate with duration >= {d} s"
                        )
                    else:
                        reason = f"no stream and no lap or aggregate with distance data for {d} s"
                    debug["durations_skipped"].append(reason)
                    points.append({
                        "duration_seconds": d,
                        "best_value": None,
                        "source_workout_id": workout_id_str,
                        "date": workout_date_str,
                        "confidence": None,
                    })
                    continue

        points.append({
            "duration_seconds": d,
            "best_value": best,
            "source_workout_id": workout_id_str,
            "date": workout_date_str,
            "confidence": confidence,
        })

    return points, debug


# ── Thin database caller ───────────────────────────────────────────────────────

def fetch_and_compute_curves(workout_id, db) -> dict:
    """Fetch stream, laps, and workout aggregate from the database and compute curves.

    This is the only function in this module that performs database access.
    It reads the ``activity_streams``, ``workout_splits``, and ``workouts``
    tables for the given workout, converts the ORM rows to plain dicts, and
    delegates to :func:`compute_power_curve` and :func:`compute_pace_curve`
    with the standard 12-duration ladder.

    Parameters
    ----------
    workout_id:
        UUID (or string representation) of the target workout.
    db:
        Active SQLAlchemy session.

    Returns
    -------
    A dict ``{"power_curve": [...], "pace_curve": [...]}`` where each list
    contains exactly 12 duration-point dicts matching
    :data:`STANDARD_DURATION_LADDER`.
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

    power_curve, _ = compute_power_curve(
        workout_id, power_stream, laps, aggregates, STANDARD_DURATION_LADDER
    )
    pace_curve, _ = compute_pace_curve(
        workout_id, pace_stream, laps, aggregates, STANDARD_DURATION_LADDER
    )

    return {"power_curve": power_curve, "pace_curve": pace_curve}
