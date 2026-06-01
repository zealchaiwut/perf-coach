"""Helpers for merging workout data from multiple sources (manual, Strava, Stryd)."""
from datetime import timedelta
import uuid as _uuid

from sqlalchemy.orm import Session as _Session


def compute_best_values(workout) -> dict:
    """Return best field values across manual_overrides → Strava → Stryd → legacy workout.

    Works with any object that has the expected attributes (ORM instance or SimpleNamespace).
    """
    overrides = workout.manual_overrides or {}
    strava = getattr(workout, "strava_activity", None)
    stryd = getattr(workout, "stryd_activity", None)

    def _pick(key, strava_attr, stryd_attr, workout_attr):
        if key in overrides and overrides[key] is not None:
            return overrides[key]
        strava_val = getattr(strava, strava_attr, None) if strava and strava_attr else None
        stryd_val = getattr(stryd, stryd_attr, None) if stryd and stryd_attr else None
        workout_val = getattr(workout, workout_attr, None) if workout_attr else None
        if strava_val is not None:
            return strava_val
        if stryd_val is not None:
            return stryd_val
        return workout_val

    return {
        "best_distance_km": _pick("distance_km", "distance_km", "distance_km", "distance_km"),
        "best_duration_seconds": _pick("duration_seconds", "duration_seconds", "duration_seconds", "duration_seconds"),
        "best_avg_hr": _pick("avg_hr", "avg_hr", "avg_hr", "avg_hr"),
        "best_avg_power_w": _pick("avg_power_w", "avg_power_w", "avg_power_w", None),
        "best_tss": _pick("tss", None, "tss", "tss"),
        "best_name": _pick("name", "name", "name", "name"),
    }


def find_matching_workout(start_time, user_id, tolerance_minutes: int = 5, *, session=None):
    """Return the Workout whose start_time is closest to start_time within ±tolerance_minutes.

    Returns None if no workout exists within the window.
    Accepts an optional session kwarg for testing; otherwise opens its own.
    """
    from backend.db import engine
    from backend.models import Workout

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    window = timedelta(minutes=tolerance_minutes)
    lower = start_time - window
    upper = start_time + window

    def _query(s):
        return (
            s.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.start_time >= lower,
                Workout.start_time <= upper,
            )
            .all()
        )

    if session is not None:
        candidates = _query(session)
    else:
        with _Session(engine) as s:
            candidates = _query(s)

    if not candidates:
        return None
    return min(candidates, key=lambda w: abs((w.start_time - start_time).total_seconds()))
