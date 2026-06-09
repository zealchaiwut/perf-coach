"""Reconcile strava_activities cache into unified workout rows."""
from __future__ import annotations

import uuid as _uuid
from datetime import date, timedelta, timezone

from sqlalchemy.orm import Session as _Session

_TOLERANCE = timedelta(minutes=5)

_WORKOUT_TYPE_MAP = {
    "Run": "run",
    "Ride": "bike",
    "WeightTraining": "strength",
    "Workout": "wod",
}


def _map_workout_type(activity_type: str) -> str:
    return _WORKOUT_TYPE_MAP.get(activity_type, "other")


def _find_match(activity, workouts: list, tolerance: timedelta):
    """Return closest existing workout on same date within tolerance, or None."""
    if activity.start_time is None:
        return None
    act_date = activity.start_time.astimezone(timezone.utc).date()
    act_ts = activity.start_time
    lower = act_ts - tolerance
    upper = act_ts + tolerance
    candidates = [
        w for w in workouts
        if w.workout_date == act_date
        and w.start_time is not None
        and lower <= w.start_time <= upper
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda w: abs((w.start_time - act_ts).total_seconds()))


def reconcile_strava_to_workouts(
    user_id,
    tolerance: timedelta = _TOLERANCE,
) -> dict:
    """Convert unlinked strava_activities rows into workout records.

    Skips activities that are already linked (strava_activity_pk set on a workout).
    On match: fills null columns from the cache row, sets source to 'both' if
    the existing workout was manual.
    On no match: creates a new workout row with source='strava'.

    Returns: {"matched_to_existing": N, "created_new": N, "total_processed": N}
    """
    from backend.db import engine
    from backend.models import StravaActivity, Workout
    from backend.services.tss import estimate_tss_for_workout

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    matched = 0
    created = 0

    with _Session(engine) as session:
        all_strava = (
            session.query(StravaActivity)
            .filter(StravaActivity.user_id == uid)
            .all()
        )
        existing_workouts = (
            session.query(Workout)
            .filter(Workout.user_id == uid)
            .all()
        )

        linked_ids = {
            w.strava_activity_pk
            for w in existing_workouts
            if w.strava_activity_pk is not None
        }
        unlinked = [a for a in all_strava if a.id not in linked_ids]

        for act in unlinked:
            tss_val, tss_src = estimate_tss_for_workout(act, uid, session)
            hit = _find_match(act, existing_workouts, tolerance)

            if hit:
                hit.strava_activity_pk = act.id
                hit.source = "both" if hit.source == "manual" else "strava"
                if hit.distance_km is None:
                    hit.distance_km = act.distance_km
                if hit.duration_seconds is None:
                    hit.duration_seconds = act.duration_seconds
                if hit.avg_hr is None:
                    hit.avg_hr = act.avg_hr
                if hit.tss is None:
                    hit.tss = tss_val
                    hit.tss_source = tss_src
                matched += 1
            else:
                wdate = (
                    act.start_time.astimezone(timezone.utc).date()
                    if act.start_time
                    else date.today()
                )
                w = Workout(
                    user_id=uid,
                    workout_date=wdate,
                    name=act.name or "Untitled",
                    workout_type=_map_workout_type(act.activity_type),
                    source="strava",
                    strava_activity_pk=act.id,
                    start_time=act.start_time,
                    distance_km=act.distance_km,
                    duration_seconds=act.duration_seconds,
                    avg_hr=act.avg_hr,
                    max_hr=act.max_hr,
                    elevation_m=act.elevation_m,
                    tss=tss_val,
                    tss_source=tss_src,
                )
                session.add(w)
                existing_workouts.append(w)
                created += 1

        session.commit()

    return {
        "matched_to_existing": matched,
        "created_new": created,
        "total_processed": matched + created,
    }
