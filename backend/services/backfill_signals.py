"""Backfill speed and endurance signals across run history (issue #1050).

backfill_signals_for_athlete loops over every run workout for an athlete and
computes the speed and endurance signals using the same functions called by
the live computation path.

Speed signal
------------
Delegates to compute_and_store_speed_signal from speed_signal.py — the same
thin caller invoked when a run is ingested on the live path.  Each run's
splits are read inside compute_and_store_speed_signal.

Endurance signal
----------------
Delegates to compute_endurance_signal from endurance_signal.py — the same
pure function used on the live path in reconcile.py and main.py.  The thin
DB caller (loading splits + storing results) lives here to match the backfill
context, but the computation is fully delegated to the pure function.

Idempotency
-----------
Both signals are pure functions of the workout's splits and the athlete's
current thresholds.  Calling this function twice for the same athlete with
the same data always produces identical stored values and never inserts new
rows; it only updates existing workout fields.

Qualification rules (enforced by the called functions, not duplicated here)
---------------------------------------------------------------------------
Speed: runs with at least one 1–6 min split at threshold/hard band → non-null.
Endurance: runs with duration > 40 min and at least two splits → non-null.
Runs that do not qualify receive null values in all signal fields.
"""

from __future__ import annotations

import logging

from backend.services.speed_signal import compute_and_store_speed_signal
from backend.services.endurance_signal import compute_endurance_signal

_log = logging.getLogger(__name__)


def backfill_signals_for_athlete(user_id, db) -> dict:
    """Compute and store speed + endurance signals for every run of an athlete.

    Parameters
    ----------
    user_id : str or UUID
        The athlete whose historical runs should be backfilled.
    db : sqlalchemy.orm.Session
        An open database session.  The caller owns the session lifetime.
        This function calls db.commit() after processing all runs.

    Returns
    -------
    dict with keys:
        thresholds_found : bool  — True when at least one threshold is configured.
        runs_processed   : int   — number of run workouts found.
        speed_computed   : int   — number of runs where speed signal was written.
        endurance_computed : int — number of runs where endurance signal was written.
        reason           : str or None — human-readable message on skip or error.
    """
    from backend.models import UserPreferences, Workout, WorkoutSplit

    prefs_row = (
        db.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .first()
    )

    has_threshold = prefs_row is not None and any(
        getattr(prefs_row, k, None) is not None
        for k in ("ftp_w", "threshold_hr", "threshold_pace_seconds_per_km")
    )

    if not has_threshold:
        return {
            "thresholds_found": False,
            "runs_processed": 0,
            "speed_computed": 0,
            "endurance_computed": 0,
            "reason": "No thresholds configured — signal backfill skipped.",
        }

    run_workouts = (
        db.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_type.ilike("%run%"),
        )
        .order_by(Workout.workout_date.asc())
        .all()
    )

    speed_computed = 0
    endurance_computed = 0

    for workout in run_workouts:
        # Speed signal — delegated entirely to the live-path thin caller.
        try:
            ok, _ = compute_and_store_speed_signal(workout.id, db)
            if ok and workout.speed_signal is not None:
                speed_computed += 1
        except Exception as exc:
            _log.warning(
                "backfill_signals: speed signal failed for workout %s: %s",
                workout.id, exc, exc_info=True,
            )

        # Endurance signal — load splits, call the same pure function as the live path.
        try:
            splits = (
                db.query(WorkoutSplit)
                .filter(WorkoutSplit.workout_id == workout.id)
                .order_by(WorkoutSplit.split_index)
                .all()
            )
            split_dicts = [
                {
                    "split_index": s.split_index,
                    "duration_seconds": s.duration_seconds,
                    "avg_hr": s.avg_hr,
                    "avg_power": s.avg_power,
                    "distance_km": (
                        float(s.distance_km) if s.distance_km is not None else None
                    ),
                }
                for s in splits
            ]
            workout_dict = {"duration_seconds": workout.duration_seconds}
            es = compute_endurance_signal(workout_dict, split_dicts)
            workout.endurance_signal = es["endurance_signal"]
            workout.decoupling_percent = es["decoupling_percent"]
            workout.efficiency_first_half = es["efficiency_first_half"]
            workout.efficiency_second_half = es["efficiency_second_half"]
            workout.endurance_signal_source = es["endurance_signal_source"]
            if es["endurance_signal"] is not None:
                endurance_computed += 1
        except Exception as exc:
            _log.warning(
                "backfill_signals: endurance signal failed for workout %s: %s",
                workout.id, exc, exc_info=True,
            )

    commit_failure_reason = None
    try:
        db.commit()
    except Exception as exc:
        _log.warning(
            "backfill_signals: commit failed for user %s: %s",
            user_id, exc, exc_info=True,
        )
        commit_failure_reason = "commit failed — changes not saved"

    if commit_failure_reason is None:
        _log.info(
            "backfill_signals complete",
            extra={
                "user_id": str(user_id),
                "runs_processed": len(run_workouts),
                "speed_computed": speed_computed,
                "endurance_computed": endurance_computed,
            },
        )

    return {
        "thresholds_found": True,
        "runs_processed": len(run_workouts),
        "speed_computed": speed_computed,
        "endurance_computed": endurance_computed,
        "reason": commit_failure_reason,
    }
