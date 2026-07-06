"""Lap classification backfill and duration-curve recompute pipeline.

Thin caller layer: rebuild_athlete_duration_curve owns all database access.
Classification and curve-merge logic live in lap_classify.py and
duration_curve_best_effort.py respectively — no computation here.

Call rebuild_athlete_duration_curve after an athlete sets thresholds to ensure
the AthleteDurationCurve reflects all historical run workouts.  The function
is safe to call repeatedly (idempotent via merge_best_effort).
"""


def rebuild_athlete_duration_curve(user_id, db):
    """Rebuild the stored best-effort duration curve for an athlete from all runs.

    This is the thin caller that owns all database access.  For each run workout
    belonging to the athlete, it computes the per-workout power curve and merges
    it into the aggregate.  The final merged curve is persisted in
    AthleteDurationCurve (one row per athlete, upserted).

    Running this function more than once for the same athlete is safe: the
    merge logic always selects the best value at each duration, so the result
    is identical on repeated calls (idempotent).

    Manually entered workout values (e.g. manual_overrides on Workout, manual
    lap_type on WorkoutSplit) are read but never modified.

    Parameters
    ----------
    user_id : str or UUID
        The athlete whose curve to rebuild.
    db : sqlalchemy.orm.Session
        An open database session.  The caller owns commit / rollback.

    Returns
    -------
    (dict, str or None)
        (merged_curve, reason).  reason is None on success; a human-readable
        string on failure or when no run workouts exist.
    """
    from sqlalchemy.orm.attributes import flag_modified
    from backend.models import ActivityStream, AthleteDurationCurve, Workout
    from backend.services.duration_curve import fetch_and_compute_curves
    from backend.services.duration_curve_best_effort import merge_best_effort

    if user_id is None:
        return {}, "missing required input: user_id"

    run_workouts = (
        db.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_type.ilike("%run%"),
        )
        .order_by(Workout.workout_date.asc())
        .all()
    )

    if not run_workouts:
        return {}, None  # no runs yet; not an error

    # Start from an empty curve and merge every workout in chronological order.
    # This is a full rebuild — the result is always the true best-ever at each duration.
    # merge_best_effort handles empty point lists safely (no-op), so we always call it
    # regardless of whether the workout has power data, ensuring no workout is silently
    # skipped if its lap classification data becomes available after an earlier rebuild.
    merged_curve: dict = {}
    for workout in run_workouts:
        try:
            curves = fetch_and_compute_curves(workout.id, db)
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "rebuild_athlete_duration_curve: skipping workout %s: %s",
                workout.id, _exc,
            )
            curves = {"power_curve": []}
        new_points = curves.get("power_curve", [])
        merged_curve, reason = merge_best_effort(merged_curve, new_points, higher_is_better=True)
        if reason is not None:
            # Log and continue — one bad workout doesn't abort the entire rebuild
            merged_curve = merged_curve or {}
        # Release the ActivityStream from the identity map so its payload can be GC'd.
        # fetch_and_compute_curves loads it via db.get(ActivityStream, workout_id);
        # expunging removes the reference so Python can reclaim the arrays (~1–2 MB/run).
        _stream = db.get(ActivityStream, workout.id)
        if _stream is not None:
            db.expunge(_stream)

    # Persist the rebuilt curve
    record = db.get(AthleteDurationCurve, user_id)
    if record is None:
        record = AthleteDurationCurve(user_id=user_id, curve_data=merged_curve)
        db.add(record)
    else:
        record.curve_data = merged_curve
        flag_modified(record, "curve_data")

    db.commit()
    return merged_curve, None
