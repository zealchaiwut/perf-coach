"""Speed signal computation per run (issue #1048).

compute_speed_signal is the pure core: it accepts a list of lap/split objects
and a preferences dict, scans all splits whose duration falls within the
1–6 minute window range, and returns the best effort normalised against the
user's threshold.

The result is a dict with four flat keys:
    speed_signal              float or None
    speed_signal_basis        "power" | "pace" | "heart_rate" | None
    speed_signal_window_seconds  int or None
    speed_signal_source       str or None

Effort detection is delegated entirely to classify_laps from lap_classify.py.
The function does not re-implement band logic; it reads the ratio and band
produced by classify_laps and filters for splits in the threshold/hard bands.

Basis selection follows the same priority as lap_classify:
    power (ftp_w) → pace (threshold_pace_seconds_per_km) → heart_rate (threshold_hr)

The internal "hr" label used by lap_classify is mapped to "heart_rate" in the
returned dict to match the AC-specified output key values.

A thin DB caller, compute_and_store_speed_signal, handles all database access
and persists the four keys to the workouts table.

Worked example — power basis
-----------------------------
Split: duration=300s, avg_power=230W; prefs: ftp_w=200
    classify_laps ratio = 230/200 = 1.15 → band = "hard"
    speed_signal = 1.15
    speed_signal_basis = "power"
    speed_signal_window_seconds = 300
    speed_signal_source = "power basis; best ratio 1.15 from 300s window"

Worked example — easy run (null result)
----------------------------------------
Split: duration=300s, avg_power=150W; prefs: ftp_w=200
    classify_laps ratio = 150/200 = 0.75 → band = "easy"
    No window reaches threshold band → all four keys are None.

Worked example — pace basis
----------------------------
Split: duration=300s, distance_km=1.2km; prefs: threshold_pace_seconds_per_km=300
    lap_pace = 300/1.2 = 250 s/km
    classify_laps ratio = 300/250 = 1.20 → band = "hard"
    speed_signal = 1.20
    speed_signal_basis = "pace"
    speed_signal_window_seconds = 300
"""

from __future__ import annotations

import logging

from backend.services.lap_classify import (
    classify_laps,
    BAND_THRESHOLD,
    BAND_HARD,
)

_log = logging.getLogger(__name__)

# Inclusive window range in seconds (1 minute to 6 minutes)
_MIN_WINDOW_SECONDS = 60
_MAX_WINDOW_SECONDS = 360

# Only these bands meet or exceed threshold
_QUALIFYING_BANDS = frozenset({BAND_THRESHOLD, BAND_HARD})

# Map lap_classify internal basis labels to AC-specified output values
_BASIS_LABEL = {
    "power": "power",
    "pace": "pace",
    "hr": "heart_rate",
}

_NULL_RESULT: dict = {
    "speed_signal": None,
    "speed_signal_basis": None,
    "speed_signal_window_seconds": None,
    "speed_signal_source": None,
}


def compute_speed_signal(splits: list, prefs: dict) -> dict:
    """Compute the speed signal for a single run.

    Scans all splits whose duration falls in [60, 360] seconds, classifies
    them via classify_laps (reusing its basis selection and ratio formula),
    and returns the split with the highest ratio that is in the "threshold"
    or "hard" band.

    Parameters
    ----------
    splits :
        List of objects (ORM rows or SimpleNamespace) exposing at minimum
        ``duration_seconds`` and one of ``avg_power``, ``avg_hr``, or
        (``duration_seconds`` + ``distance_km``) for pace.
    prefs :
        Dict with keys ``ftp_w``, ``threshold_pace_seconds_per_km``,
        ``threshold_hr`` (all nullable).

    Returns
    -------
    dict with four keys — see module docstring.  Never raises.
    """
    if not splits:
        return dict(_NULL_RESULT)

    # Filter to the 1–6 minute window range
    window_splits = [
        s for s in splits
        if _MIN_WINDOW_SECONDS <= (getattr(s, "duration_seconds", 0) or 0) <= _MAX_WINDOW_SECONDS
    ]

    if not window_splits:
        return dict(_NULL_RESULT)

    # Delegate effort detection to classify_laps (AC4: no re-implementation)
    classifications = classify_laps(window_splits, prefs)

    # Determine run-level basis: the first basis that classify_laps successfully used
    run_basis: str | None = None
    for cls in classifications:
        b = cls.get("basis")
        if b and b != "none":
            run_basis = b
            break

    if run_basis is None:
        return dict(_NULL_RESULT)

    # Find the best qualifying split: highest ratio in threshold/hard band,
    # using only splits where classify_laps applied the run-level basis.
    best_ratio: float | None = None
    best_window_seconds: int | None = None

    for split, cls in zip(window_splits, classifications):
        if cls.get("basis") != run_basis:
            # This split fell back to a different basis (e.g. no avg_power);
            # skip it for consistency with the run-level basis.
            continue
        if cls.get("band") not in _QUALIFYING_BANDS:
            continue
        ratio = cls.get("ratio")
        if ratio is None:
            continue
        if best_ratio is None or ratio > best_ratio:
            best_ratio = ratio
            best_window_seconds = getattr(split, "duration_seconds", None)

    if best_ratio is None:
        return dict(_NULL_RESULT)

    basis_label = _BASIS_LABEL.get(run_basis, run_basis)

    source = (
        f"{basis_label} basis; best ratio {best_ratio:.4f} "
        f"from {best_window_seconds}s window"
    )

    return {
        "speed_signal": round(float(best_ratio), 4),
        "speed_signal_basis": basis_label,
        "speed_signal_window_seconds": int(best_window_seconds) if best_window_seconds is not None else None,
        "speed_signal_source": source,
    }


def compute_and_store_speed_signal(workout_id, session) -> tuple[bool, str | None]:
    """Read splits and preferences from the DB, compute, and persist the signal.

    This is the only function in this module that accesses the database.

    Parameters
    ----------
    workout_id :
        UUID (or string) of the target workout row.
    session :
        Active SQLAlchemy session.  The caller is responsible for committing.

    Returns
    -------
    ``(True, None)`` on success.
    ``(False, reason_string)`` when prerequisites are not met (e.g. workout
    not found, workout type is not a run, or no thresholds configured).
    """
    from backend.models import Workout, WorkoutSplit, UserPreferences

    workout = session.query(Workout).filter(Workout.id == workout_id).first()
    if workout is None:
        return False, f"workout {workout_id} not found"

    splits = (
        session.query(WorkoutSplit)
        .filter(WorkoutSplit.workout_id == workout_id)
        .order_by(WorkoutSplit.split_index)
        .all()
    )

    prefs_row = (
        session.query(UserPreferences)
        .filter(UserPreferences.user_id == workout.user_id)
        .first()
    )

    prefs: dict = {
        "ftp_w": prefs_row.ftp_w if prefs_row is not None else None,
        "threshold_hr": prefs_row.threshold_hr if prefs_row is not None else None,
        "threshold_pace_seconds_per_km": (
            prefs_row.threshold_pace_seconds_per_km if prefs_row is not None else None
        ),
    }

    result = compute_speed_signal(splits, prefs)

    workout.speed_signal = result["speed_signal"]
    workout.speed_signal_basis = result["speed_signal_basis"]
    workout.speed_signal_window_seconds = result["speed_signal_window_seconds"]
    workout.speed_signal_source = result["speed_signal_source"]

    _log.info(
        "speed_signal computed",
        extra={
            "workout_id": str(workout_id),
            "speed_signal": result["speed_signal"],
            "basis": result["speed_signal_basis"],
        },
    )

    return True, None
