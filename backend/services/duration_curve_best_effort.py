"""Aggregate and persist per-athlete best-effort duration curve.

All curve arithmetic (rolling windows, fallback selection) lives in
duration_curve.py. This module handles only storage access and the
merge logic that selects the best value across multiple runs.
"""

from backend.services.duration_curve import fetch_and_compute_curves


def merge_best_effort(existing, new_points, higher_is_better=True):
    """Merge new duration-point list into an existing best-effort curve dict.

    Pure function — no database access.

    Parameters
    ----------
    existing : dict
        Current stored curve keyed by str(duration_seconds). Each value is a
        dict with keys: ``best_value``, ``workout_id``, ``date``, ``confidence``.
    new_points : list[dict]
        Points from a freshly computed workout curve. Each dict must have:
        ``duration_seconds``, ``best_value``, ``source_workout_id``, ``date``,
        ``confidence``. Points with ``best_value=None`` are silently skipped.
    higher_is_better : bool
        True (default) for power — larger value wins.
        False for pace — smaller value (faster) wins.

    Returns
    -------
    dict
        New best-effort curve with the same structure as ``existing``. Only
        entries where ``new_points`` provides a strictly better value are
        replaced; all other entries are preserved unchanged.

    Worked example
    --------------
    existing = {"60": {"best_value": 250.0, "workout_id": "abc", "date": "2026-01-10"}}
    new_points = [{"duration_seconds": 60, "best_value": 270.0, "source_workout_id": "xyz",
                   "date": "2026-01-15", "confidence": "measured"}]
    result = merge_best_effort(existing, new_points)
    # result["60"]["best_value"] == 270.0, result["60"]["workout_id"] == "xyz"
    """
    result = {k: dict(v) for k, v in existing.items()}

    for point in new_points:
        if point.get("best_value") is None:
            continue
        duration = point["duration_seconds"]
        key = str(duration)
        new_val = point["best_value"]
        current = result.get(key)

        if current is None or current.get("best_value") is None:
            result[key] = {
                "best_value": new_val,
                "workout_id": str(point["source_workout_id"]),
                "date": point.get("date"),
                "confidence": point.get("confidence", "measured"),
            }
        else:
            stored_val = current["best_value"]
            is_better = (
                (higher_is_better and new_val > stored_val)
                or (not higher_is_better and new_val < stored_val)
            )
            if is_better:
                result[key] = {
                    "best_value": new_val,
                    "workout_id": str(point["source_workout_id"]),
                    "date": point.get("date"),
                    "confidence": point.get("confidence", "measured"),
                }

    return result


def update_athlete_power_curve(user_id, workout_id, db, duration_ladder=None):
    """Update stored best-effort power curve for one athlete after a new run is ingested.

    All database access lives in this function. Curve arithmetic is delegated to
    fetch_and_compute_curves (which calls compute_power_curve) and merge_best_effort.

    Parameters
    ----------
    user_id : UUID
        The athlete whose curve to update.
    workout_id : UUID
        The newly ingested workout to evaluate.
    db : sqlalchemy.orm.Session
        Open session.
    duration_ladder : list[int] or None
        Duration windows in seconds. Defaults to the ladder defined in duration_curve.py.
    """
    from sqlalchemy.orm.attributes import flag_modified
    from backend.models import AthleteDurationCurve

    curves = fetch_and_compute_curves(workout_id, db)
    new_power_points = curves.get("power_curve", [])

    record = db.get(AthleteDurationCurve, user_id)
    existing_data = record.curve_data if record else {}

    merged = merge_best_effort(existing_data, new_power_points, higher_is_better=True)

    if record is None:
        record = AthleteDurationCurve(user_id=user_id, curve_data=merged)
        db.add(record)
    else:
        record.curve_data = merged
        flag_modified(record, "curve_data")

    db.commit()


def get_athlete_duration_curve(user_id, db):
    """Return the stored best-effort curve for an athlete, or None if absent.

    Parameters
    ----------
    user_id : UUID
        Athlete identifier.
    db : sqlalchemy.orm.Session
        Open session.

    Returns
    -------
    dict or None
        The curve_data dict keyed by str(duration_seconds), or None if the athlete
        has no curve record.
    """
    from backend.models import AthleteDurationCurve

    record = db.get(AthleteDurationCurve, user_id)
    if record is None:
        return None
    return record.curve_data or {}
