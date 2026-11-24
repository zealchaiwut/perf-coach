"""Lap intensity band classifier with basis-chosen-once semantics.

classify_laps(splits, prefs) is a pure function: no database calls, no side
effects, no hardcoded numeric thresholds.  It selects a single basis for the
entire call based on the thresholds present in prefs, then applies that basis
to every lap.  If a specific lap is missing the metric required by the chosen
basis, that lap returns band=None and a reason string — it does NOT fall
through to the next basis.

A separate thin caller (classify_laps_for_workout) owns all database access.

Band constants (ratio boundaries):
    easy       ratio below 0.80
    steady     ratio at least 0.80 and below 0.90
    tempo      ratio at least 0.90 and below 1.00
    threshold  ratio at least 1.00 and below 1.06
    hard       ratio at least 1.06

Threshold priority (first available basis from prefs wins for ALL laps):
    power (requires ftp_w) → pace (requires threshold_pace_seconds_per_km)
    → hr (requires threshold_hr)

Ratio formulas:
    power: lap average power divided by ftp_w
    pace:  threshold_pace_seconds_per_km divided by lap pace in seconds per km
           (a faster lap has fewer seconds per km so the ratio exceeds 1.0)
    hr:    lap average HR divided by threshold_hr
"""

BAND_EASY = "easy"
BAND_STEADY = "steady"
BAND_TEMPO = "tempo"
BAND_THRESHOLD = "threshold"
BAND_HARD = "hard"

_BOUNDARY_STEADY = 0.80
_BOUNDARY_TEMPO = 0.90
_BOUNDARY_THRESHOLD = 1.00
_BOUNDARY_HARD = 1.06


def _ratio_to_band(ratio):
    """Map a numeric ratio to an intensity band string using named boundaries."""
    if ratio < _BOUNDARY_STEADY:
        return BAND_EASY
    if ratio < _BOUNDARY_TEMPO:
        return BAND_STEADY
    if ratio < _BOUNDARY_THRESHOLD:
        return BAND_TEMPO
    if ratio < _BOUNDARY_HARD:
        return BAND_THRESHOLD
    return BAND_HARD


def classify_laps(splits, prefs):
    """Classify each lap by intensity band using athlete thresholds from prefs.

    Accepts a list of lap objects (each with attributes avg_power, avg_hr,
    duration_seconds, distance_km) and a preferences dict with keys ftp_w,
    threshold_hr, and threshold_pace_seconds_per_km.  Returns a list with one
    classification dict per lap.

    The basis is determined ONCE from prefs and applied to ALL laps.  A lap
    that is missing the metric required by the chosen basis returns band=None
    and a reason string; it does NOT fall through to the next basis.  Other
    laps in the same call are unaffected.

    Each result dict contains:
        ratio   float (two decimal places) or None when the metric is absent
        band    "easy"|"steady"|"tempo"|"threshold"|"hard" or None
        basis   "power"|"pace"|"hr"|"none"
        reason  human-readable string when band is None, else None

    Threshold priority: power (requires ftp_w), then pace (requires
    threshold_pace_seconds_per_km), then hr (requires threshold_hr).  The
    first whose threshold key is present and non-null in prefs becomes the
    sole basis for the entire call.

    No database calls are made inside this function.

    Worked examples
    ---------------
    Power basis (ftp_w = 200, lap avg_power = 220):
        ratio = 220 divided by 200 = 1.10
        band  = "hard" (ratio at least 1.06)
        basis = "power"
        reason = None

    Pace basis (threshold_pace_seconds_per_km = 300, lap duration = 600 s,
                lap distance = 2.4 km, so lap pace = 250 s/km):
        ratio = 300 divided by 250 = 1.20
        band  = "hard" (ratio at least 1.06)
        basis = "pace"
        reason = None

    HR basis (threshold_hr = 165, lap avg_hr = 155):
        ratio = 155 divided by 165 = 0.94 (rounded to two decimal places)
        band  = "tempo" (ratio at least 0.90 and below 1.00)
        basis = "hr"
        reason = None

    None path (no threshold configured in prefs):
        All thresholds absent or null means no basis can be selected.
        ratio = None, band = None, basis = "none"
        reason = human-readable string explaining that no threshold was found
        This applies to every lap in the call when prefs contain no thresholds.
    """
    ftp_w = prefs.get("ftp_w")
    threshold_pace = prefs.get("threshold_pace_seconds_per_km")
    threshold_hr = prefs.get("threshold_hr")

    # Determine the single basis for this call based on prefs
    if ftp_w is not None:
        basis = "power"
    elif threshold_pace is not None:
        basis = "pace"
    elif threshold_hr is not None:
        basis = "hr"
    else:
        basis = "none"

    return [_classify_single_lap(lap, basis, ftp_w, threshold_pace, threshold_hr)
            for lap in splits]


def _classify_single_lap(lap, basis, ftp_w, threshold_pace, threshold_hr):
    """Apply the pre-selected basis to a single lap; return a classification dict."""
    if basis == "power":
        avg_power = getattr(lap, "avg_power", None)
        if avg_power is None:
            return {
                "ratio": None,
                "band": None,
                "basis": "power",
                "reason": "avg_power metric absent on lap",
            }
        ratio = round(avg_power / ftp_w, 2)
        return {"ratio": ratio, "band": _ratio_to_band(ratio), "basis": "power", "reason": None}

    if basis == "pace":
        duration = getattr(lap, "duration_seconds", None)
        distance = getattr(lap, "distance_km", None)
        lap_pace = None
        if duration is not None and distance is not None:
            try:
                lap_pace = duration / float(distance)
            except (TypeError, ZeroDivisionError):
                lap_pace = None
        if lap_pace is None:
            return {
                "ratio": None,
                "band": None,
                "basis": "pace",
                "reason": "pace metric absent on lap (duration or distance missing or zero)",
            }
        ratio = round(threshold_pace / lap_pace, 2)
        return {"ratio": ratio, "band": _ratio_to_band(ratio), "basis": "pace", "reason": None}

    if basis == "hr":
        avg_hr = getattr(lap, "avg_hr", None)
        if avg_hr is None:
            return {
                "ratio": None,
                "band": None,
                "basis": "hr",
                "reason": "avg_hr metric absent on lap",
            }
        ratio = round(avg_hr / threshold_hr, 2)
        return {"ratio": ratio, "band": _ratio_to_band(ratio), "basis": "hr", "reason": None}

    # basis == "none": no threshold was configured
    return {
        "ratio": None,
        "band": None,
        "basis": "none",
        "reason": "no threshold configured in preferences (ftp_w, threshold_pace_seconds_per_km, and threshold_hr are all absent or null)",
    }


def classify_laps_for_workout(workout_id, session):
    """Thin caller: load splits and user_preferences from DB; pass to classify_laps.

    This is the only function in this module that accesses the database.
    It extracts the three threshold fields into a plain dict and delegates
    all math to the pure classify_laps function.

    Returns the list from classify_laps, one classification dict per split.
    Returns an empty list when the workout does not exist.
    """
    from backend.models import Workout, WorkoutSplit, UserPreferences

    workout = session.get(Workout, workout_id)
    if workout is None:
        return []

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

    prefs = {
        "ftp_w": prefs_row.ftp_w if prefs_row is not None else None,
        "threshold_hr": prefs_row.threshold_hr if prefs_row is not None else None,
        "threshold_pace_seconds_per_km": (
            prefs_row.threshold_pace_seconds_per_km if prefs_row is not None else None
        ),
    }

    return classify_laps(splits, prefs)
