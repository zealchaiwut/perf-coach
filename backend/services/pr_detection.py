"""Personal-record detection from run history.

Three pure detection functions compare completed runs and duration curves against
historical bests.  A thin caller function handles all database reads and passes
results to the pure layer.

Standard distances tracked (in kilometres):
    1 km, 1 mile (1.60934 km), 5 km, 10 km, half marathon (21.0975 km), marathon (42.195 km)

Standard power durations tracked (in seconds):
    1 minute (60 s), 5 minutes (300 s), 20 minutes (1200 s)
"""

import datetime

STANDARD_DISTANCES_KM = {
    "1km": 1.0,
    "1mile": 1.60934,
    "5km": 5.0,
    "10km": 10.0,
    "half_marathon": 21.0975,
    "marathon": 42.195,
}

STANDARD_POWER_DURATIONS_SECONDS = {
    "best1Min": 60,
    "best5Min": 300,
    "best20Min": 1200,
}


def detect_speed_records(duration_curve, completed_runs):
    """Return the fastest time and best pace for each of the six standard distances.

    Pure function — accepts plain data arguments, returns plain data, performs no
    database access, and has no side effects.

    For each standard distance d the function scans the pace duration curve for
    points whose implied running distance (duration in seconds divided by pace in
    seconds per kilometre) is at least d.  Among all qualifying points the function
    selects the one with the fastest pace (lowest seconds per kilometre) and
    estimates the time for exactly d as: estimated time equals d multiplied by
    that fastest pace.

    If no curve point reaches the implied distance d, that distance is omitted and
    a ``"reason"`` string explains what data was absent.

    Tie-breaking: when two qualifying points share the same fastest pace, the one
    with the earlier date is selected.

    Parameters
    ----------
    duration_curve : list[dict]
        Best-effort pace curve.  Each point must have ``duration_seconds`` (int)
        and ``best_value`` (float, pace expressed as seconds per kilometre).
        Optional fields: ``source_workout_id`` (str), ``date`` (ISO-8601 str),
        ``source_workout`` (full workout dict — embedded by the caller for direct
        use as the ``sourceWorkout`` return field).
    completed_runs : list[dict]
        Completed run workouts.  Each dict must have at minimum ``id`` and
        ``workout_date``.  Used as a fallback source for ``sourceWorkout`` when a
        curve point does not embed the full workout object.

    Returns
    -------
    dict
        Keys are standard distance labels (``"1km"``, ``"1mile"``, ``"5km"``,
        ``"10km"``, ``"half_marathon"``, ``"marathon"``).  Each value is either:
        - a record dict with exactly three fields: ``value`` (float, fastest
          elapsed time in seconds), ``date`` (ISO-8601 string), and
          ``sourceWorkout`` (the full workout dict); or
        - an omitted-distance dict with a single ``"reason"`` string.

        A top-level ``"debug"`` dict lists every candidate value compared for
        each distance, enabling engineers to trace why a particular curve point
        was or was not selected.

        When any required input is missing or empty the function returns an empty
        result dict with a single top-level ``"reason"`` field explaining what
        was absent.

    Worked example — single run that sets a new 5 km personal record and a new
    best 20-minute power simultaneously
    -------------------------------------------------------------------------
    The run covers 5.02 km in 1302 seconds.
    Pace equals elapsed seconds divided by distance in kilometres,
    so pace equals 1302 divided by 5.02, approximately 259.4 seconds per km.

    Input duration_curve::

        [
            {
                "duration_seconds": 1302,
                "best_value": 259.4,
                "source_workout_id": "run-abc",
                "date": "2026-01-15",
                "source_workout": {
                    "id": "run-abc",
                    "workout_date": "2026-01-15",
                    "distance_km": 5.02,
                    "duration_seconds": 1302
                }
            }
        ]

    For the 5 km distance (5.0 km target):
    Implied distance equals 1302 divided by 259.4, approximately 5.02 km.
    Because 5.02 km is greater than or equal to 5.0 km the point qualifies.
    Estimated time for 5 km equals 5.0 multiplied by 259.4, approximately 1297 seconds.

    Expected output (5 km record)::

        {
            "5km": {
                "value": 1297.0,
                "date": "2026-01-15",
                "sourceWorkout": {
                    "id": "run-abc",
                    "workout_date": "2026-01-15",
                    "distance_km": 5.02,
                    "duration_seconds": 1302
                }
            },
            "debug": {
                "5km": {
                    "candidates": [
                        {
                            "implied_distance_km": 5.02,
                            "duration_seconds": 1302,
                            "pace_sec_per_km": 259.4,
                            "source_workout_id": "run-abc",
                            "date": "2026-01-15"
                        }
                    ],
                    "winner": {
                        "source_workout_id": "run-abc",
                        "pace_sec_per_km": 259.4,
                        "implied_distance_km": 5.02,
                        "estimated_time_seconds": 1297.0
                    }
                }
            }
        }

    Math note: pace equals elapsed seconds divided by distance in kilometres.
    Estimated time for a target distance equals target distance multiplied by pace.
    """
    if not completed_runs and not duration_curve:
        return {"reason": "no completed runs provided and duration curve is empty"}
    if not completed_runs:
        return {"reason": "no completed runs provided"}
    if not duration_curve:
        return {"reason": "duration curve is empty"}

    runs_by_id = {str(r.get("id", "")): r for r in completed_runs if r.get("id")}

    # Build enriched curve points with implied distance
    enriched = []
    for pt in duration_curve:
        pace = pt.get("best_value")
        dur = pt.get("duration_seconds")
        if not pace or not dur or pace <= 0 or dur <= 0:
            continue
        enriched.append({
            "implied_distance_km": dur / pace,
            "duration_seconds": dur,
            "pace_sec_per_km": pace,
            "source_workout_id": str(pt.get("source_workout_id") or ""),
            "date": pt.get("date") or "",
            "source_workout": pt.get("source_workout"),
        })

    records = {}
    debug = {}

    for label, dist_km in STANDARD_DISTANCES_KM.items():
        candidates_for_debug = [
            {
                "implied_distance_km": p["implied_distance_km"],
                "duration_seconds": p["duration_seconds"],
                "pace_sec_per_km": p["pace_sec_per_km"],
                "source_workout_id": p["source_workout_id"],
                "date": p["date"],
            }
            for p in enriched
        ]
        debug[label] = {"candidates": candidates_for_debug, "winner": None}

        qualifying = [p for p in enriched if p["implied_distance_km"] >= dist_km]
        if not qualifying:
            max_dist = max((p["implied_distance_km"] for p in enriched), default=0.0)
            records[label] = {
                "reason": (
                    f"curve has no data for distances at or above {dist_km:.4f} km; "
                    f"longest implied distance in curve is {max_dist:.4f} km"
                )
            }
            continue

        # Select fastest pace (lowest sec/km); tie-break on earlier date (ISO-8601 strings sort correctly).
        best = min(qualifying, key=lambda p: (p["pace_sec_per_km"], p["date"]))
        # Estimated time equals target distance multiplied by the fastest qualifying pace.
        best_time = dist_km * best["pace_sec_per_km"]
        source_id = best["source_workout_id"]
        source_workout = best.get("source_workout") or runs_by_id.get(source_id)

        debug[label]["winner"] = {
            "source_workout_id": source_id,
            "pace_sec_per_km": best["pace_sec_per_km"],
            "implied_distance_km": best["implied_distance_km"],
            "estimated_time_seconds": best_time,
        }

        records[label] = {
            "value": best_time,
            "date": best["date"],
            "sourceWorkout": source_workout,
        }

    records["debug"] = debug
    return records


def detect_power_records(power_curve):
    """Return the highest mean power for the best 1-minute, 5-minute, and 20-minute durations.

    Pure function — accepts plain data arguments, returns plain data, performs no
    database access, and has no side effects.

    For each standard power duration the function looks up the matching curve point
    by exact duration in seconds.  If a duration is absent from the curve it is
    omitted with a ``"reason"`` string.

    Tie-breaking: when two curve points share the same duration and the same power
    value, the one with the earlier date is selected.

    Parameters
    ----------
    power_curve : list[dict]
        Best-effort power curve.  Each point must have ``duration_seconds`` (int)
        and ``best_value`` (float, mean power in watts).  Optional fields:
        ``source_workout_id`` (str), ``date`` (ISO-8601 str), ``source_workout``
        (full workout dict — embedded by the caller for direct use as the
        ``sourceWorkout`` return field).

    Returns
    -------
    dict
        Keys are power duration labels (``"best1Min"``, ``"best5Min"``,
        ``"best20Min"``).  Each value is either:
        - a record dict with exactly three fields: ``value`` (float, highest
          mean power in watts), ``date`` (ISO-8601 string), and ``sourceWorkout``
          (the full workout dict); or
        - an omitted-duration dict with a single ``"reason"`` string.

        A top-level ``"debug"`` dict lists every candidate value compared for
        each duration.

        When the input is empty the function returns a dict with a single
        top-level ``"reason"`` field.

    Worked example — single run that sets a new best 20-minute power and a new
    5 km personal record simultaneously
    -------------------------------------------------------------------------
    The run covers 5.02 km in 1302 seconds and sustains a 20-minute best power
    of 285 watts.

    Input power_curve::

        [
            {"duration_seconds": 60,   "best_value": 320.0,
             "source_workout_id": "run-abc", "date": "2026-01-15",
             "source_workout": {"id": "run-abc", "workout_date": "2026-01-15",
                                "distance_km": 5.02, "duration_seconds": 1302}},
            {"duration_seconds": 300,  "best_value": 295.0,
             "source_workout_id": "run-abc", "date": "2026-01-15",
             "source_workout": {"id": "run-abc", "workout_date": "2026-01-15",
                                "distance_km": 5.02, "duration_seconds": 1302}},
            {"duration_seconds": 1200, "best_value": 285.0,
             "source_workout_id": "run-abc", "date": "2026-01-15",
             "source_workout": {"id": "run-abc", "workout_date": "2026-01-15",
                                "distance_km": 5.02, "duration_seconds": 1302}},
        ]

    Best 20-minute power: the curve contains a point at 1200 seconds with
    best_value 285.0 watts.  That value is taken directly.

    Expected output (20-minute power record)::

        {
            "best1Min":  {"value": 320.0, "date": "2026-01-15", "sourceWorkout": {...}},
            "best5Min":  {"value": 295.0, "date": "2026-01-15", "sourceWorkout": {...}},
            "best20Min": {"value": 285.0, "date": "2026-01-15", "sourceWorkout": {...}},
            "debug": {
                "all_curve_durations": [60, 300, 1200],
                "best20Min": {
                    "candidates": [
                        {"duration_seconds": 1200, "best_value": 285.0,
                         "source_workout_id": "run-abc", "date": "2026-01-15"}
                    ]
                }
            }
        }

    Math note: higher power in watts means a better record; the function selects
    the maximum value at each duration.
    """
    if not power_curve:
        return {"reason": "duration curve is empty"}

    # Group points by exact duration; resolve ties (same power) by earlier date.
    by_duration = {}
    for pt in power_curve:
        dur = pt.get("duration_seconds")
        val = pt.get("best_value")
        if dur is None or val is None:
            continue
        existing = by_duration.get(dur)
        if existing is None:
            by_duration[dur] = pt
        else:
            existing_val = existing.get("best_value", 0)
            new_date = pt.get("date") or ""
            existing_date = existing.get("date") or ""
            # Higher power wins; on equal power earlier date wins.
            if val > existing_val or (val == existing_val and new_date < existing_date):
                by_duration[dur] = pt

    records = {}
    debug = {
        "all_curve_durations": sorted(by_duration.keys()),
    }

    for label, dur_sec in STANDARD_POWER_DURATIONS_SECONDS.items():
        debug[label] = {
            "candidates": [
                {
                    "duration_seconds": p.get("duration_seconds"),
                    "best_value": p.get("best_value"),
                    "source_workout_id": str(p.get("source_workout_id") or ""),
                    "date": p.get("date"),
                }
                for p in power_curve
                if p.get("duration_seconds") == dur_sec
            ]
        }

        pt = by_duration.get(dur_sec)
        if pt is None:
            available = sorted(by_duration.keys())
            records[label] = {
                "reason": (
                    f"no curve data for {dur_sec}-second duration; "
                    f"available durations in seconds: {available}"
                )
            }
            continue

        records[label] = {
            "value": float(pt["best_value"]),
            "date": pt.get("date") or "",
            "sourceWorkout": pt.get("source_workout"),
        }

    records["debug"] = debug
    return records


def detect_volume_records(completed_runs):
    """Return the longest run by distance and duration, plus best single-week totals.

    Pure function — accepts plain data arguments, returns plain data, performs no
    database access, and has no side effects.

    Weeks are defined as Monday-to-Sunday periods.  The week-start date is the
    Monday on or before each run's date.  Weekly totals sum distance in kilometres
    and training load (TSS) across all runs in the week.

    Tie-breaking: when two runs (or two weeks) share the same value, the one with
    the earlier date is selected.

    Parameters
    ----------
    completed_runs : list[dict]
        Completed run workouts.  Each dict should have ``id``, ``workout_date``
        (ISO-8601 str), ``distance_km`` (float or None), ``duration_seconds``
        (int or None), and ``tss`` (float or None for training load).

    Returns
    -------
    dict
        Keys present when data permits:
        - ``"longestByDistance"`` — record dict for the single run with the
          greatest distance in kilometres.
        - ``"longestByDuration"`` — record dict for the single run with the
          greatest elapsed time in seconds.
        - ``"weeklyDistanceRecord"`` — record dict for the week with the highest
          total distance; ``sourceWorkout`` is a week-summary dict containing
          ``week_start``, ``total_distance_km``, ``total_tss``, and ``runs``.
        - ``"weeklyLoadRecord"`` — record dict for the week with the highest total
          TSS; ``sourceWorkout`` is the same week-summary structure.

        Each record dict has exactly three fields: ``value`` (float), ``date``
        (ISO-8601 string), and ``sourceWorkout``.

        A top-level ``"debug"`` dict lists all runs and weekly totals evaluated.

        When the input is empty the function returns a dict with a single
        top-level ``"reason"`` field.

    Worked example — single run that sets a new 5 km personal record and a new
    best 20-minute power simultaneously
    -------------------------------------------------------------------------
    One run of 5.02 km on 2026-01-15 is the entire history.

    Input completed_runs::

        [
            {
                "id": "run-abc",
                "workout_date": "2026-01-15",
                "distance_km": 5.02,
                "duration_seconds": 1302,
                "tss": 45.0
            }
        ]

    Because this is the only run it wins every volume category.

    Expected output::

        {
            "longestByDistance": {
                "value": 5.02,
                "date": "2026-01-15",
                "sourceWorkout": {"id": "run-abc", "workout_date": "2026-01-15", ...}
            },
            "longestByDuration": {
                "value": 1302.0,
                "date": "2026-01-15",
                "sourceWorkout": {"id": "run-abc", ...}
            },
            "weeklyDistanceRecord": {
                "value": 5.02,
                "date": "2026-01-12",
                "sourceWorkout": {
                    "week_start": "2026-01-12",
                    "total_distance_km": 5.02,
                    "total_tss": 45.0,
                    "runs": [{"id": "run-abc", ...}]
                }
            },
            "weeklyLoadRecord": {
                "value": 45.0,
                "date": "2026-01-12",
                "sourceWorkout": {"week_start": "2026-01-12", "total_tss": 45.0, ...}
            },
            "debug": {
                "all_runs_with_distance": [...],
                "all_runs_with_duration": [...],
                "weekly_totals": [{"week_start": "2026-01-12", "total_distance_km": 5.02, "total_tss": 45.0}]
            }
        }

    Math note: total weekly distance equals the sum of distance in kilometres for
    all runs whose date falls in the same Monday-to-Sunday week.  Weekly training
    load equals the sum of TSS values for the same set of runs.
    """
    if not completed_runs:
        return {"reason": "no completed runs provided"}

    def _week_start(date_str):
        d = datetime.date.fromisoformat(date_str)
        # Subtract the weekday index (Monday = 0) to reach the Monday of the week.
        return d - datetime.timedelta(days=d.weekday())

    # Accumulate weekly buckets keyed by week-start ISO string.
    weekly = {}
    for run in completed_runs:
        date_str = run.get("workout_date")
        if not date_str:
            continue
        ws = _week_start(date_str).isoformat()
        if ws not in weekly:
            weekly[ws] = {
                "week_start": ws,
                "total_distance_km": 0.0,
                "total_tss": 0.0,
                "runs": [],
            }
        weekly[ws]["total_distance_km"] += float(run.get("distance_km") or 0)
        weekly[ws]["total_tss"] += float(run.get("tss") or 0)
        weekly[ws]["runs"].append(run)

    # Longest run by distance — tie-break on earlier date.
    best_dist_run = None
    best_dist_val = None
    for run in completed_runs:
        d = run.get("distance_km")
        if d is None:
            continue
        d = float(d)
        date = run.get("workout_date", "")
        if (
            best_dist_val is None
            or d > best_dist_val
            or (d == best_dist_val and date < best_dist_run.get("workout_date", ""))
        ):
            best_dist_val = d
            best_dist_run = run

    # Longest run by elapsed duration — tie-break on earlier date.
    best_dur_run = None
    best_dur_val = None
    for run in completed_runs:
        dur = run.get("duration_seconds")
        if dur is None:
            continue
        dur = int(dur)
        date = run.get("workout_date", "")
        if (
            best_dur_val is None
            or dur > best_dur_val
            or (dur == best_dur_val and date < best_dur_run.get("workout_date", ""))
        ):
            best_dur_val = dur
            best_dur_run = run

    # Best single-week total distance — tie-break on earlier week-start.
    best_week_dist_entry = None
    best_week_dist_val = None
    for ws, entry in weekly.items():
        td = entry["total_distance_km"]
        if (
            best_week_dist_val is None
            or td > best_week_dist_val
            or (td == best_week_dist_val and ws < best_week_dist_entry["week_start"])
        ):
            best_week_dist_val = td
            best_week_dist_entry = entry

    # Best single-week total training load (TSS) — tie-break on earlier week-start.
    best_week_tss_entry = None
    best_week_tss_val = None
    for ws, entry in weekly.items():
        tt = entry["total_tss"]
        if (
            best_week_tss_val is None
            or tt > best_week_tss_val
            or (tt == best_week_tss_val and ws < best_week_tss_entry["week_start"])
        ):
            best_week_tss_val = tt
            best_week_tss_entry = entry

    debug = {
        "all_runs_with_distance": [
            {
                "id": str(r.get("id")),
                "date": r.get("workout_date"),
                "distance_km": r.get("distance_km"),
            }
            for r in completed_runs
            if r.get("distance_km") is not None
        ],
        "all_runs_with_duration": [
            {
                "id": str(r.get("id")),
                "date": r.get("workout_date"),
                "duration_seconds": r.get("duration_seconds"),
            }
            for r in completed_runs
            if r.get("duration_seconds") is not None
        ],
        "weekly_totals": [
            {
                "week_start": ws,
                "total_distance_km": e["total_distance_km"],
                "total_tss": e["total_tss"],
            }
            for ws, e in sorted(weekly.items())
        ],
    }

    result = {"debug": debug}

    if best_dist_run is not None:
        result["longestByDistance"] = {
            "value": float(best_dist_val),
            "date": best_dist_run.get("workout_date"),
            "sourceWorkout": best_dist_run,
        }

    if best_dur_run is not None:
        result["longestByDuration"] = {
            "value": float(best_dur_val),
            "date": best_dur_run.get("workout_date"),
            "sourceWorkout": best_dur_run,
        }

    if best_week_dist_entry is not None:
        result["weeklyDistanceRecord"] = {
            "value": float(best_week_dist_val),
            "date": best_week_dist_entry["week_start"],
            "sourceWorkout": best_week_dist_entry,
        }

    if best_week_tss_entry is not None:
        result["weeklyLoadRecord"] = {
            "value": float(best_week_tss_val),
            "date": best_week_tss_entry["week_start"],
            "sourceWorkout": best_week_tss_entry,
        }

    return result


def fetch_and_detect_records(user_id, db):
    """Fetch all run data for a user and detect personal records.

    This is the only function in this module that performs database access.
    It reads the ``workouts`` and ``athlete_duration_curves`` tables, converts
    ORM rows to plain dicts, and delegates all detection logic to the three
    pure functions in this module.

    Parameters
    ----------
    user_id : UUID
        The athlete whose records to detect.
    db : sqlalchemy.orm.Session
        An open database session.

    Returns
    -------
    dict with keys:
        ``"speedRecords"``  — result of detect_speed_records
        ``"powerRecords"``  — result of detect_power_records
        ``"volumeRecords"`` — result of detect_volume_records
        ``"_meta"``         — logging metadata: ``duration_curve_populated`` (bool)
                              and ``runs_considered`` (int); stripped by the
                              endpoint before returning JSON to the client.
    """
    from backend.models import Workout, AthleteDurationCurve

    runs = (
        db.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_type.ilike("%run%"),
        )
        .order_by(Workout.workout_date)
        .all()
    )

    completed_runs = [
        {
            "id": str(r.id),
            "workout_date": r.workout_date.isoformat() if r.workout_date else None,
            "distance_km": float(r.distance_km) if r.distance_km else None,
            "duration_seconds": r.duration_seconds,
            "tss": r.tss,
            "avg_power": r.avg_power,
            "name": r.name,
            "workout_type": r.workout_type,
        }
        for r in runs
    ]

    # Build a pace duration curve from per-workout average pace.
    # Each run contributes one point: duration in seconds, pace equals
    # duration divided by distance in kilometres.
    pace_curve = []
    runs_by_id = {r["id"]: r for r in completed_runs}
    for run in completed_runs:
        d = run.get("distance_km")
        dur = run.get("duration_seconds")
        if d and dur and float(d) > 0 and dur > 0:
            pace_curve.append({
                "duration_seconds": dur,
                "best_value": dur / float(d),  # seconds per kilometre
                "source_workout_id": run["id"],
                "date": run["workout_date"],
                "source_workout": run,
            })

    # Build a power curve from the stored best-effort aggregate for this athlete.
    curve_record = db.get(AthleteDurationCurve, user_id)
    stored_curve = curve_record.curve_data if curve_record else {}

    power_curve = []
    for dur_str, entry in stored_curve.items():
        val = entry.get("best_value")
        if val is None:
            continue
        workout_id = entry.get("workout_id")
        power_curve.append({
            "duration_seconds": int(dur_str),
            "best_value": float(val),
            "source_workout_id": workout_id,
            "date": entry.get("date"),
            "source_workout": runs_by_id.get(str(workout_id)) if workout_id else None,
        })

    return {
        "speedRecords": detect_speed_records(pace_curve, completed_runs),
        "powerRecords": detect_power_records(power_curve),
        "volumeRecords": detect_volume_records(completed_runs),
        "_meta": {
            "duration_curve_populated": bool(curve_record),
            "runs_considered": len(completed_runs),
        },
    }
