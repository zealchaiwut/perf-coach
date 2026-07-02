"""Thin caller for detect_session_profile.

Loads workout splits and user preferences from the database, then
delegates to detect_session_profile.  Contains no detection logic
and no hardcoded threshold values.

Declared builder structure takes precedence: when workout.manual_overrides
contains a "session_profile" key, that declared structure is returned
directly and detect_session_profile is never called.
"""

import types

from backend.services.session_profile import detect_session_profile


def get_session_profile_for_workout(workout, split_rows, prefs, manual_laps=None):
    """Return a session profile for a workout.

    Parameters
    ----------
    workout:
        Workout model object.  Its manual_overrides JSONB field is checked for
        a pre-declared "session_profile" key before detection runs.
    split_rows:
        List of WorkoutSplit objects ordered by split_index, already loaded
        from the database.  The caller is responsible for loading these.
    prefs:
        UserPreferences model object, or None when no preferences row exists
        for the user.
    manual_laps:
        Optional list of pre-computed manual-lap objects (from the Stryd
        streams), each exposing duration_seconds/distance_km/avg_power/avg_hr.
        The endpoint loads them (the caller stays DB-free). When present and
        richer than the stored splits, detection runs on these so real interval
        reps (in the manual presses) are found; ``lap_source`` in the result is
        "manual" (else "splits").

    Returns
    -------
    A session profile dict as returned by detect_session_profile, or the
    declared builder structure from manual_overrides["session_profile"] when
    that key is present.  Adds a ``lap_source`` key ("manual"|"splits") on the
    detection path.  Never raises.
    """
    # Declared builder structure takes precedence over detection
    manual_overrides = workout.manual_overrides or {}
    if "session_profile" in manual_overrides:
        return manual_overrides["session_profile"]

    prefs_dict = {
        "ftp_w": prefs.ftp_w if prefs is not None else None,
        "threshold_hr": prefs.threshold_hr if prefs is not None else None,
        "threshold_pace_seconds_per_km": (
            prefs.threshold_pace_seconds_per_km if prefs is not None else None
        ),
    }

    # Interval reps are logged as manual lap presses (in the Stryd streams), not
    # as rows in workout_splits (which only holds the 1 km auto-splits, too long
    # to expose a 400 m rep). When the endpoint has pre-computed genuine manual
    # laps (more than the stored splits), run detection on THOSE so a real 8×400
    # is detected. lap_roles then aligns with the manual lap order — the lap set
    # the run-detail view draws for these sessions. The caller stays DB-free: the
    # endpoint loads the streams and passes manual_laps in.
    if manual_laps and len(manual_laps) > max(1, len(split_rows or [])):
        splits_container = types.SimpleNamespace(laps=manual_laps, lap_type="manual")
        profile = detect_session_profile(splits_container, prefs_dict)
        profile["lap_source"] = "manual"
        return profile

    # Determine the workout-level lap type from the first split row;
    # fall back to "auto" when no splits exist.
    lap_type = "auto"
    if split_rows:
        first_type = split_rows[0].lap_type
        if first_type:
            lap_type = first_type

    splits_container = types.SimpleNamespace(
        laps=split_rows,
        lap_type=lap_type,
    )

    profile = detect_session_profile(splits_container, prefs_dict)
    profile["lap_source"] = "splits"
    return profile
