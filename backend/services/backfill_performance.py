"""Full performance backfill pipeline for an athlete (issue #1023).

backfill_performance_for_athlete is the callable entry point used by both the
CLI script and the POST /api/performance/backfill endpoint.  It runs the three
steps the on-the-fly performance scoring depends on:

1. Verifies that at least one threshold is configured (ftp_w, threshold_hr, or
   threshold_pace_seconds_per_km).  If none are set the function returns early
   with thresholds_found=False and makes no DB writes.

2. Recomputes running TSS for every run workout owned by the athlete, using the
   current thresholds stored in user_preferences.  TSS values are persisted in
   the workouts.tss column and are used by the fitness/fatigue/form chart.

3. Rebuilds the athlete's best-effort duration curve (AthleteDurationCurve table)
   from all historical run workouts.  The curve is used by the speed score to
   compare current performance against peak historical performance.

Lap classification is intentionally NOT stored.  It is a pure function of splits
+ thresholds and is computed on-the-fly each time the performance endpoint is
called, so it is always consistent with the current thresholds.

The function is idempotent: calling it twice with the same athlete and same
thresholds leaves the DB in the same state.

DB access is intentionally confined to this module (the thin caller layer).
Recompute logic lives in tss.py and lap_recompute.py respectively.
"""

from __future__ import annotations

import logging

from backend.models import UserPreferences, Workout
from backend.services.tss import recompute_user_running_tss
from backend.services.lap_recompute import rebuild_athlete_duration_curve

_log = logging.getLogger(__name__)


def backfill_performance_for_athlete(user_id, db) -> dict:
    """Run the full performance backfill pipeline for one athlete.

    Parameters
    ----------
    user_id : str or UUID
        The athlete whose historical data should be backfilled.
    db : sqlalchemy.orm.Session
        An open database session.  The caller owns the session lifetime;
        this function may call db.commit() to persist intermediate results.

    Returns
    -------
    dict with keys:
        thresholds_found : bool  — True when at least one threshold is configured
        runs_processed   : int   — number of run workouts found for the athlete
        tss_recomputed   : bool  — True when TSS recompute completed without error
        curve_rebuilt    : bool  — True when the duration curve was rebuilt successfully
        reason           : str or None — human-readable message on skip or error
    """
    # Step 1: Check whether any threshold is configured.
    prefs = (
        db.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .first()
    )

    has_threshold = prefs is not None and any(
        getattr(prefs, k, None) is not None
        for k in ("ftp_w", "threshold_hr", "threshold_pace_seconds_per_km")
    )

    if not has_threshold:
        return {
            "thresholds_found": False,
            "runs_processed": 0,
            "tss_recomputed": False,
            "curve_rebuilt": False,
            "reason": "No thresholds configured — backfill skipped.",
        }

    # Step 2: Count run workouts (used for the summary; the individual services
    # do their own queries internally).
    run_count = (
        db.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_type.ilike("%run%"),
        )
        .count()
    )

    # Step 3: Recompute running TSS for all run workouts so the fitness chart
    # uses TSS values derived from the current thresholds.
    tss_recomputed = False
    tss_reason: str | None = None
    try:
        recompute_user_running_tss(user_id, db)
        db.commit()
        tss_recomputed = True
    except Exception as exc:
        tss_reason = str(exc)
        _log.warning(
            "backfill: TSS recompute failed for user %s: %s", user_id, exc, exc_info=True
        )

    # Step 4: Rebuild the best-effort duration curve so the speed score can
    # compare current runs against peak historical performance.
    curve_rebuilt = False
    curve_reason: str | None = None
    try:
        _, reason = rebuild_athlete_duration_curve(user_id, db)
        if reason is None:
            curve_rebuilt = True
        else:
            curve_reason = reason
            _log.warning(
                "backfill: curve rebuild returned reason for user %s: %s", user_id, reason
            )
    except Exception as exc:
        curve_reason = str(exc)
        _log.warning(
            "backfill: curve rebuild failed for user %s: %s", user_id, exc, exc_info=True
        )

    return {
        "thresholds_found": True,
        "runs_processed": run_count,
        "tss_recomputed": tss_recomputed,
        "curve_rebuilt": curve_rebuilt,
        "reason": tss_reason or curve_reason,
    }
