"""Auto-complete planned races from synced run workouts.

Checkpoints already auto-detect via ``checkpoint_detector``; races stayed
``planned`` until the athlete manually picked a history run or called
``POST /api/races/{id}/calibrate``. This closes that gap: when a run on the
race date matches the planned distance, mark the race ``done`` and set
``actual_time_seconds`` from the workout duration.

Pure matching logic lives in ``match_workout_to_race``; DB wrappers are at
the bottom. Runs on the **webapp** (workout ingest + sync reconcile + plan
bundle self-heal) — no worker/Mac required.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from backend.services.checkpoint_detector import RUN_WORKOUT_TYPES, is_run_workout

_log = logging.getLogger(__name__)

# Relative distance slack — GPS / course variation (e.g. 21.45 km for a half).
DISTANCE_TOLERANCE_FRACTION: float = 0.06
# Never accept less than this absolute km gap (covers 10K rounding).
DISTANCE_TOLERANCE_MIN_KM: float = 0.75


def _distance_ok(race_distance_km: float, run_distance_km: float) -> bool:
    if race_distance_km <= 0 or run_distance_km <= 0:
        return False
    diff = abs(float(run_distance_km) - float(race_distance_km))
    tol = max(DISTANCE_TOLERANCE_MIN_KM, float(race_distance_km) * DISTANCE_TOLERANCE_FRACTION)
    return diff <= tol


def match_workout_to_race(
    race_date: date,
    race_distance_km: Optional[float],
    race_status: str,
    race_type: str,
    workout_date: date,
    workout_type: str,
    workout_distance_km: Optional[float],
) -> bool:
    """Return True when *workout* should complete the planned race."""
    if race_type != "race":
        return False
    if race_status != "planned":
        return False
    if race_date != workout_date:
        return False
    if not is_run_workout(workout_type or ""):
        return False
    if race_distance_km is None or workout_distance_km is None:
        return False
    return _distance_ok(float(race_distance_km), float(workout_distance_km))


def apply_race_autocomplete_for_workout(session, workout) -> bool:
    """Mark matching planned races done for one workout. Returns True if any updated."""
    if not is_run_workout(workout.workout_type or ""):
        return False
    if workout.workout_date is None or workout.duration_seconds is None:
        return False
    if workout.distance_km is None:
        return False

    from backend.models import Race

    races = (
        session.query(Race)
        .filter(
            Race.user_id == workout.user_id,
            Race.status == "planned",
            Race.race_type == "race",
            Race.race_date == workout.workout_date,
        )
        .all()
    )
    if not races:
        return False

    run_dist = float(workout.distance_km)
    candidates = [
        r
        for r in races
        if r.distance_km is not None
        and _distance_ok(float(r.distance_km), run_dist)
    ]
    if not candidates:
        return False

    # Closest distance wins when multiple races share a date.
    candidates.sort(key=lambda r: abs(float(r.distance_km) - run_dist))
    race = candidates[0]
    race.status = "done"
    race.actual_time_seconds = int(workout.duration_seconds)
    race.updated_at = datetime.now(timezone.utc)
    _log.info(
        "race auto-complete: race %s (%s) ← workout %s (%.2f km, %ss)",
        race.id,
        race.name,
        workout.id,
        run_dist,
        workout.duration_seconds,
    )
    return True


def backfill_planned_races(session, user_id) -> int:
    """Self-heal: complete any past planned race that has a matching run."""
    from backend.models import Race, Workout

    from backend.utils.time import today_bangkok

    today = today_bangkok()
    planned = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.status == "planned",
            Race.race_type == "race",
            Race.race_date <= today,
            Race.distance_km.isnot(None),
        )
        .all()
    )
    if not planned:
        return 0

    updated = 0
    for race in planned:
        runs = (
            session.query(Workout)
            .filter(
                Workout.user_id == user_id,
                Workout.workout_date == race.race_date,
                Workout.duration_seconds.isnot(None),
                Workout.distance_km.isnot(None),
            )
            .all()
        )
        run_dist_target = float(race.distance_km)
        best = None
        best_diff = None
        for w in runs:
            if not is_run_workout(w.workout_type or ""):
                continue
            if not _distance_ok(run_dist_target, float(w.distance_km)):
                continue
            diff = abs(float(w.distance_km) - run_dist_target)
            if best is None or diff < best_diff:
                best = w
                best_diff = diff
        if best is None:
            continue
        race.status = "done"
        race.actual_time_seconds = int(best.duration_seconds)
        race.updated_at = datetime.now(timezone.utc)
        updated += 1
        _log.info(
            "race backfill: race %s (%s) ← workout %s",
            race.id,
            race.name,
            best.id,
        )
    return updated
