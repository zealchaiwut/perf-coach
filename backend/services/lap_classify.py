"""Lap intensity band classifier for session-profile detection.

classify_laps is the pure core: it accepts a list of lap objects and a
preferences dict, and returns one classification result per lap with no
database calls.

A separate thin caller (classify_laps_for_workout) handles all database access:
it loads user_preferences and workout_splits, extracts the three threshold fields
into a plain dict, and passes them to classify_laps.

Band constants (ratio boundaries):
    easy       ratio below 0.80
    steady     ratio at least 0.80 and below 0.90
    tempo      ratio at least 0.90 and below 1.00
    threshold  ratio at least 1.00 and below 1.06
    hard       ratio at least 1.06

Threshold priority (first available basis wins):
    power then pace then hr

A basis is skipped when its threshold key is absent or null in prefs, or
when the lap object is missing the corresponding metric.

Ratio formulas (plain arithmetic, no symbols):
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


def _ratio_to_band(ratio):
    """Map a numeric ratio to an intensity band string.

    easy:      ratio below 0.80
    steady:    ratio at least 0.80 and below 0.90
    tempo:     ratio at least 0.90 and below 1.00
    threshold: ratio at least 1.00 and below 1.06
    hard:      ratio at least 1.06
    """
    if ratio < 0.80:
        return BAND_EASY
    if ratio < 0.90:
        return BAND_STEADY
    if ratio < 1.00:
        return BAND_TEMPO
    if ratio < 1.06:
        return BAND_THRESHOLD
    return BAND_HARD


def classify_laps(splits, prefs):
    """Classify each lap by intensity band using athlete thresholds from prefs.

    Accepts a list of lap objects (each with attributes avg_power, avg_hr,
    duration_seconds, distance_km) and a preferences dict with keys ftp_w,
    threshold_hr, and threshold_pace_seconds_per_km.  Returns a list with one
    classification dict per lap.

    Each result dict contains:
        ratio   float (two decimal places) or None when no basis succeeded
        band    "easy"|"steady"|"tempo"|"threshold"|"hard" or None
        basis   "power"|"pace"|"hr"|"none"
        reason  human-readable string describing skipped bases and absent
                metrics; None when the first-priority basis succeeded without
                any fallthrough

    Threshold priority: power is tried first, then pace, then hr.  A basis is
    skipped when its threshold key is absent or null in prefs, or when the lap
    object is missing the corresponding metric.  When no basis succeeds, basis
    is "none", ratio and band are None, and reason names all absent thresholds
    or metrics.

    No database calls are made inside this function.

    Worked examples
    ---------------
    Power basis (ftp_w = 200, lap avg_power = 220):
        ratio = 220 divided by 200 = 1.10
        band  = "hard" (ratio at least 1.06)
        basis = "power"
        reason = None (no fallthrough)

    Pace basis (threshold_pace_seconds_per_km = 300, lap duration = 600 s,
                lap distance = 2.4 km, so lap pace = 250 s/km):
        ratio = 300 divided by 250 = 1.20
        band  = "hard" (ratio at least 1.06)
        basis = "pace"

    HR basis (threshold_hr = 165, lap avg_hr = 155):
        ratio = 155 divided by 165 = 0.94 (two decimal places)
        band  = "tempo" (ratio at least 0.90 and below 1.00)
        basis = "hr"
    """
    ftp_w = prefs.get("ftp_w")
    threshold_hr = prefs.get("threshold_hr")
    threshold_pace = prefs.get("threshold_pace_seconds_per_km")

    results = []
    for lap in splits:
        result = _classify_single_lap(lap, ftp_w, threshold_pace, threshold_hr)
        results.append(result)
    return results


def _classify_single_lap(lap, ftp_w, threshold_pace, threshold_hr):
    """Return a single lap classification dict.

    Tries power, then pace, then hr in priority order.
    Records the reason for each skipped basis in a list joined at return time.
    """
    skipped = []

    # Power is the highest-quality basis: lap average power divided by ftp_w
    if ftp_w is not None:
        avg_power = getattr(lap, "avg_power", None)
        if avg_power is not None:
            ratio = round(avg_power / ftp_w, 2)
            return {
                "ratio": ratio,
                "band": _ratio_to_band(ratio),
                "basis": "power",
                "reason": None,
            }
        skipped.append("avg_power metric absent on lap")
    else:
        skipped.append("ftp_w threshold absent in preferences")

    # Pace basis: threshold_pace_seconds_per_km divided by lap pace in s/km
    # A faster lap (fewer s/km) produces a ratio above 1.0
    if threshold_pace is not None:
        duration = getattr(lap, "duration_seconds", None)
        distance = getattr(lap, "distance_km", None)
        lap_pace = None
        if duration is not None and distance is not None:
            try:
                lap_pace = duration / float(distance)
            except (TypeError, ZeroDivisionError):
                lap_pace = None

        if lap_pace is not None:
            ratio = round(threshold_pace / lap_pace, 2)
            return {
                "ratio": ratio,
                "band": _ratio_to_band(ratio),
                "basis": "pace",
                "reason": "; ".join(skipped) if skipped else None,
            }
        skipped.append("pace metric absent on lap (duration or distance missing)")
    else:
        skipped.append("threshold_pace_seconds_per_km threshold absent in preferences")

    # HR is the lowest-priority basis: lap average HR divided by threshold_hr
    if threshold_hr is not None:
        avg_hr = getattr(lap, "avg_hr", None)
        if avg_hr is not None:
            ratio = round(avg_hr / threshold_hr, 2)
            return {
                "ratio": ratio,
                "band": _ratio_to_band(ratio),
                "basis": "hr",
                "reason": "; ".join(skipped) if skipped else None,
            }
        skipped.append("avg_hr metric absent on lap")
    else:
        skipped.append("threshold_hr threshold absent in preferences")

    reason = "; ".join(skipped) if skipped else "no thresholds configured"
    return {
        "ratio": None,
        "band": None,
        "basis": "none",
        "reason": reason,
    }


def aggregate_intensity_zones(splits, prefs):
    """Aggregate per-lap band data into low/moderate/high zone percentages.

    Calls classify_laps internally to determine the intensity band for each
    split, then totals the duration_seconds for each composite zone:

        low      = easy + steady
        moderate = tempo
        high     = threshold + hard

    Splits whose band is None (unclassifiable due to missing thresholds or
    metrics) are excluded from the total; they do not count as any zone.

    Returns a dict with three keys:
        low_pct      float or None
        moderate_pct float or None
        high_pct     float or None

    Convention: when no split yields a classifiable band (total band time is
    zero), all three values are None rather than raising a ZeroDivisionError.
    """
    LOW_BANDS = {BAND_EASY, BAND_STEADY}
    MODERATE_BANDS = {BAND_TEMPO}
    HIGH_BANDS = {BAND_THRESHOLD, BAND_HARD}

    classifications = classify_laps(splits, prefs)

    low_s = 0.0
    moderate_s = 0.0
    high_s = 0.0

    for lap, cls in zip(splits, classifications):
        band = cls.get("band")
        if band is None:
            continue
        dur = getattr(lap, "duration_seconds", None) or 0
        if band in LOW_BANDS:
            low_s += dur
        elif band in MODERATE_BANDS:
            moderate_s += dur
        elif band in HIGH_BANDS:
            high_s += dur

    total = low_s + moderate_s + high_s
    if total == 0:
        return {"low_pct": None, "moderate_pct": None, "high_pct": None}

    return {
        "low_pct": round(low_s / total * 100, 2),
        "moderate_pct": round(moderate_s / total * 100, 2),
        "high_pct": round(high_s / total * 100, 2),
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
