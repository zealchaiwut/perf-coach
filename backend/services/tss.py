"""
TSS (Training Stress Score) computation utilities.

Formula:  TSS = (duration_seconds * IF²) / 36
            where IF = intensity factor (ratio of actual to threshold intensity).

IF method precedence (highest quality to lowest):
    power > pace > hr > duration_only

# Audit: rows where tss IS NULL AND duration_seconds IS NOT NULL in the workouts
# table are candidates for future backfill using estimate_tss_for_workout().
"""
import logging

from sqlalchemy import text

THRESHOLD_PACE_SEC_PER_KM = 270  # ~4:30/km
THRESHOLD_HR = 170
FTP_W = 280

_log = logging.getLogger(__name__)


def compute_tss(intensity_factor: float, duration_seconds: int) -> int:
    return round((duration_seconds * intensity_factor**2) / 36)


def intensity_factor_from_pace(
    avg_pace_seconds_per_km: float, threshold_pace_seconds_per_km: float
) -> float:
    return threshold_pace_seconds_per_km / avg_pace_seconds_per_km


def intensity_factor_from_hr(avg_hr: int, threshold_hr: int) -> float:
    return avg_hr / threshold_hr


def intensity_factor_from_power(avg_power_w: int, ftp_w: int) -> float:
    return avg_power_w / ftp_w


def get_user_thresholds(user_id, db) -> tuple[int, int, int]:
    """Return (ftp_w, threshold_hr, threshold_pace_sec_per_km) for user_id.

    Reads from user_preferences. Falls back to module-level defaults when the
    row is absent or a field is NULL, and logs a warning in that case.
    """
    defaults = (FTP_W, THRESHOLD_HR, THRESHOLD_PACE_SEC_PER_KM)
    if not user_id or db is None:
        return defaults

    try:
        row = db.execute(
            text(
                "SELECT ftp_w, threshold_hr, threshold_pace_seconds_per_km "
                "FROM user_preferences WHERE user_id = :uid"
            ),
            {"uid": str(user_id)},
        ).fetchone()
    except Exception:
        _log.warning("Could not query user_preferences for user %s; using defaults", user_id)
        return defaults

    if row is None:
        _log.warning(
            "No user_preferences row for user %s; using default thresholds", user_id
        )
        return defaults

    ftp = row.ftp_w if row.ftp_w is not None else FTP_W
    hr = row.threshold_hr if row.threshold_hr is not None else THRESHOLD_HR
    pace = (
        row.threshold_pace_seconds_per_km
        if row.threshold_pace_seconds_per_km is not None
        else THRESHOLD_PACE_SEC_PER_KM
    )

    if row.ftp_w is None or row.threshold_hr is None or row.threshold_pace_seconds_per_km is None:
        _log.warning(
            "Null threshold field(s) in user_preferences for user %s; using defaults for null fields",
            user_id,
        )

    return (ftp, hr, pace)


def compute_running_tss(workout, splits, prefs) -> dict:
    """Compute TSS for a running workout using priority-based method selection (no DB access).

    Tries three methods in order — Power → Pace → HR — and returns the result
    from the first method whose required inputs are all present. Each skipped
    method is recorded in ``debug`` with a human-readable explanation.

    Parameters
    ----------
    workout:
        Object (or dict) with ``np`` (normalized power, int|None),
        ``avg_hr`` (int|None), ``distance_km`` (float|None),
        ``duration_seconds`` (int|None).
    splits:
        Iterable of objects (or dicts) with ``duration_seconds``,
        ``distance_km``, and ``avg_hr``. May be None or empty.
    prefs:
        Object (or dict) with ``ftp_w``, ``threshold_pace_seconds_per_km``,
        ``threshold_hr`` — all int|None. None means unset; no defaults assumed.

    Returns
    -------
    dict with exactly four keys:
        tss     — whole integer when computable, None when no method succeeds
        method  — "power" | "pace" | "hr" | "none" ("none" only when tss is None)
        partial — True when the chosen method worked from incomplete data
                  (e.g. whole-workout average instead of per-lap data, or
                  splits that cover less than 95 % of the total duration)
        debug   — dict keyed by method name; value is "used", "not attempted",
                  or a "skipped: <reason>" string for each method tried

    Formulas (all methods share TSS = hours × IF² × 100)
    -----------------------------------------------------
    Power: IF = normalized_power / ftp_w
    Pace:  IF = threshold_pace_s_per_km / lap_pace_s_per_km
    HR:    IF = avg_hr / threshold_hr

    Worked examples
    ---------------
    Example 1 – Power method, 60 min at FTP:
        ftp_w=280, np=280, duration=3600 s
        IF = 280/280 = 1.0
        TSS = (3600/3600) × 1.0² × 100 = 100
        → {tss: 100, method: "power", partial: False}

    Example 2 – Pace method, 60 min at threshold pace (single lap):
        threshold_pace=300 s/km, 12 km in 3600 s → lap_pace=300 s/km
        IF = 300/300 = 1.0
        lap_tss = (3600/3600) × 1.0² × 100 = 100
        → {tss: 100, method: "pace", partial: False}

    Example 3 – HR method, 60 min at threshold HR:
        threshold_hr=170, avg_hr=170, duration=3600 s
        IF = 170/170 = 1.0
        TSS = (3600/3600) × 1.0² × 100 = 100
        → {tss: 100, method: "hr", partial: True} (partial because no per-lap HR)

    Example 4 – No method succeeds (all prefs absent):
        → {tss: None, method: "none", partial: False,
           debug: {power: "skipped: …", pace: "skipped: …", hr: "skipped: …"}}
    """
    from backend.services.running_tss_power import calculate_running_tss_power

    def _g(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    debug: dict = {}

    duration = _g(workout, "duration_seconds") or 0
    ftp_w = _g(prefs, "ftp_w")
    threshold_pace = _g(prefs, "threshold_pace_seconds_per_km")
    threshold_hr = _g(prefs, "threshold_hr")
    np_val = _g(workout, "np")
    avg_hr = _g(workout, "avg_hr")
    distance_km = _g(workout, "distance_km")
    split_list = list(splits) if splits else []

    # ── Method 1: Power ───────────────────────────────────────────────────────
    # Delegate to the dedicated power module; it validates duration, np, and ftp_w
    power_result = calculate_running_tss_power(
        duration_seconds=duration if duration > 0 else None,
        np=np_val,
        ftp_w=ftp_w,
    )
    if power_result["tss"] is not None:
        # Power method succeeded — mark pace and hr as never reached
        debug["power"] = "used"
        debug["pace"] = "not attempted"
        debug["hr"] = "not attempted"
        return {"tss": power_result["tss"], "method": "power", "partial": False, "debug": debug}
    # Record why power was skipped (e.g. "normalized_power missing" or "ftp_w missing or invalid")
    debug["power"] = "skipped: " + power_result["debug"].get("reason", "missing required input")

    if duration <= 0:
        # No meaningful duration → pace and hr also cannot run
        debug["pace"] = "skipped: duration missing or zero"
        debug["hr"] = "skipped: duration missing or zero"
        return {"tss": None, "method": "none", "partial": False, "debug": debug}

    # ── Method 2: Pace ────────────────────────────────────────────────────────
    if not threshold_pace:
        debug["pace"] = "skipped: threshold_pace_seconds_per_km not set in prefs"
    else:
        # Try per-lap computation: each lap contributes its own TSS slice
        valid_laps = []
        total_tss = 0.0
        for s in split_list:
            lap_dur = _g(s, "duration_seconds") or 0
            lap_dist_raw = _g(s, "distance_km")
            try:
                lap_dist = float(lap_dist_raw) if lap_dist_raw is not None else None
            except (TypeError, ValueError):
                lap_dist = None
            if not lap_dur or not lap_dist or lap_dist <= 0:
                # Skip invalid laps silently; they will affect partial flag
                continue
            # lap pace: seconds elapsed for each km covered in this lap
            lap_pace = lap_dur / lap_dist
            # intensity: how fast relative to threshold (faster → value > 1.0)
            lap_if = threshold_pace / lap_pace
            # lap TSS = fraction of an hour × intensity squared × 100
            total_tss += (lap_dur / 3600) * lap_if ** 2 * 100
            valid_laps.append(lap_dur)

        if valid_laps:
            # Determine whether laps cover substantially all of the workout
            # (coverage < 95 % means GPS dropout or incomplete data → partial)
            coverage = sum(valid_laps) / duration
            partial = coverage < 0.95
            debug["pace"] = "used"
            debug["hr"] = "not attempted"
            return {"tss": round(total_tss), "method": "pace", "partial": partial, "debug": debug}

        # Fallback: synthesise a single lap from whole-workout average pace
        try:
            dist_f = float(distance_km) if distance_km is not None else None
        except (TypeError, ValueError):
            dist_f = None

        if dist_f and dist_f > 0:
            # average pace = total seconds / total km for the whole run
            avg_pace = duration / dist_f
            # intensity = threshold pace / average pace
            if_val = threshold_pace / avg_pace
            # TSS = hours × intensity squared × 100
            tss = round((duration / 3600) * if_val ** 2 * 100)
            debug["pace"] = "used"
            debug["hr"] = "not attempted"
            return {"tss": tss, "method": "pace", "partial": True, "debug": debug}

        debug["pace"] = "skipped: no valid split data and distance_km not available"

    # ── Method 3: HR ─────────────────────────────────────────────────────────
    if not threshold_hr:
        debug["hr"] = "skipped: threshold_hr not set in prefs"
    else:
        # Try per-lap HR: use duration-weighted average heart rate across laps
        if split_list:
            lap_hrs = [_g(s, "avg_hr") for s in split_list]
            if all(h is not None for h in lap_hrs):
                total_tss = 0.0
                for s, hr in zip(split_list, lap_hrs):
                    lap_dur = _g(s, "duration_seconds") or 0
                    # intensity = lap HR / threshold HR
                    lap_if = hr / threshold_hr
                    # lap TSS = fraction of an hour × intensity squared × 100
                    total_tss += (lap_dur / 3600) * lap_if ** 2 * 100
                debug["hr"] = "used"
                return {"tss": round(total_tss), "method": "hr", "partial": False, "debug": debug}

        # Fallback: workout-level avg_hr (less precise, hence partial=True)
        if avg_hr:
            # intensity = workout average HR / threshold HR
            if_val = avg_hr / threshold_hr
            # TSS = hours × intensity squared × 100
            tss = round((duration / 3600) * if_val ** 2 * 100)
            debug["hr"] = "used"
            return {"tss": tss, "method": "hr", "partial": True, "debug": debug}

        debug["hr"] = "skipped: avg_hr not present in workout and no per-lap HR available"

    return {"tss": None, "method": "none", "partial": False, "debug": debug}


def calculate_pace_tss(
    splits,
    threshold_pace_seconds_per_km,
    workout_duration_seconds,
    workout_avg_pace_seconds_per_km,
) -> dict:
    """Compute TSS for a running workout using pace only (no DB access).

    Intensity for each lap is the ratio of threshold pace to lap pace.
    Because pace is in seconds-per-km, a *faster* lap (lower s/km) produces
    an intensity factor greater than 1.

    Formula per lap
    ---------------
    lap_pace     = lap_duration_seconds / lap_distance_km
    lap_intensity = threshold_pace_seconds_per_km / lap_pace
    lap_tss       = (lap_duration_seconds / 3600) × lap_intensity² × 100
    tss           = round(sum of all lap_tss)

    When ``splits`` is absent or empty the function synthesises a single lap
    from ``workout_duration_seconds`` and ``workout_avg_pace_seconds_per_km``.

    Worked two-lap example
    ----------------------
    threshold = 330 s/km (5:30/km)
    Lap 1: 1080 s, 3.00 km → lap_pace = 360 s/km
        lap_intensity = 330 / 360 ≈ 0.9167
        lap_tss = (1080/3600) × 0.9167² × 100 ≈ 25.21
    Lap 2: 1080 s, 3.60 km → lap_pace = 300 s/km
        lap_intensity = 330 / 300 = 1.1
        lap_tss = (1080/3600) × 1.1² × 100 = 36.30
    tss = round(25.21 + 36.30) = round(61.51) = 62
    """
    def _g(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    # Guard: threshold required to compute any intensity factor
    if not threshold_pace_seconds_per_km:
        return {
            "tss": None,
            "method": "none",
            "debug": {"laps": [], "reason": "missing threshold_pace_seconds_per_km"},
        }

    split_list = list(splits) if splits else []
    laps = []

    for s in split_list:
        lap_dur = _g(s, "duration_seconds") or 0
        lap_dist_raw = _g(s, "distance_km")
        try:
            lap_dist = float(lap_dist_raw) if lap_dist_raw is not None else None
        except (TypeError, ValueError):
            lap_dist = None
        if not lap_dur or not lap_dist or lap_dist <= 0:
            continue
        # lap pace in seconds per km
        lap_pace = lap_dur / lap_dist
        # intensity: threshold pace divided by actual lap pace
        lap_intensity = threshold_pace_seconds_per_km / lap_pace
        # lap TSS = fraction of an hour × intensity squared × 100
        lap_tss = (lap_dur / 3600) * lap_intensity ** 2 * 100
        laps.append({
            "lap_duration_seconds": lap_dur,
            "lap_pace_seconds_per_km": lap_pace,
            "lap_intensity": lap_intensity,
            "lap_tss": lap_tss,
        })

    if not laps:
        # Fallback: synthetic single lap from whole-workout average pace
        avg_pace = workout_avg_pace_seconds_per_km
        dur = workout_duration_seconds or 0
        if not avg_pace or not dur:
            return {
                "tss": None,
                "method": "none",
                "debug": {"laps": [], "reason": "missing pace data"},
            }
        # intensity from workout average pace
        lap_intensity = threshold_pace_seconds_per_km / avg_pace
        # TSS for the whole workout treated as one lap
        lap_tss = (dur / 3600) * lap_intensity ** 2 * 100
        laps.append({
            "lap_duration_seconds": dur,
            "lap_pace_seconds_per_km": avg_pace,
            "lap_intensity": lap_intensity,
            "lap_tss": lap_tss,
        })

    tss = round(sum(lap["lap_tss"] for lap in laps))
    return {"tss": tss, "method": "pace", "debug": {"laps": laps}}


def calculate_hr_tss(
    duration_seconds,
    avg_hr,
    threshold_hr,
    laps=None,
) -> dict:
    """Compute HR-based Training Stress Score (TSS) for a running workout.

    All required inputs must be supplied by the caller. No default thresholds
    are assumed; if threshold_hr is not set in user preferences the caller must
    pass None and the function will return a null result with a reason string.

    Parameters
    ----------
    duration_seconds:
        Total workout duration in seconds (int or float). Required.
    avg_hr:
        Workout-level average heart rate in beats per minute. Used as a
        fallback when per-lap HR data are absent or incomplete.
    threshold_hr:
        The athlete's heart-rate threshold (lactate-threshold HR) in beats
        per minute, read from user_preferences by the caller. Must not be
        hardcoded here; pass None if the value is not set.
    laps:
        Optional iterable of lap objects (or dicts) each with avg_hr
        (beats per minute) and duration_seconds attributes. When all laps
        carry a valid avg_hr, a duration-weighted average HR is derived from
        the laps and used instead of the workout-level avg_hr.

    Returns
    -------
    dict with exactly three keys:

        tss (int or None):
            Rounded Training Stress Score, or None when a required input is
            absent.

        method (str):
            "hr" when TSS was successfully computed; "none" otherwise.

        debug (dict):
            Diagnostic values. Always contains:
              intensity_factor — avg_hr divided by threshold_hr (float or None)
              duration_hours   — duration_seconds divided by 3600 (float or None)
            When a required input is absent, also contains:
              reason — human-readable string describing which input is missing.

    Formula
    -------
    Step 1 — Determine effective average HR.
        When all laps supply avg_hr, compute a duration-weighted average:
            weighted_avg_hr = sum(lap_avg_hr * lap_duration) / total_duration.
        When per-lap HR is absent or incomplete, fall back to the
        workout-level avg_hr argument.

    Step 2 — Compute intensity factor (IF).
        IF = effective_avg_hr divided by threshold_hr.
        This ratio expresses how hard the effort was relative to the athlete's
        heart-rate threshold.

    Step 3 — Compute duration in hours.
        duration_hours = duration_seconds divided by 3600.

    Step 4 — Compute TSS.
        TSS = duration_hours times IF squared times 100.
        Round to the nearest whole integer.

    Worked example
    --------------
    A runner completes a 60-minute run at exactly their threshold heart rate.

        threshold_hr    = 170 bpm
        avg_hr          = 170 bpm
        duration_seconds = 3600

    Step 1 — No lap data; effective_avg_hr = 170.
    Step 2 — intensity_factor = 170 / 170 = 1.0.
    Step 3 — duration_hours = 3600 / 3600 = 1.0.
    Step 4 — TSS = 1.0 * 1.0 * 1.0 * 100 = 100.

    Return value:
        {
            "tss": 100,
            "method": "hr",
            "debug": {"intensity_factor": 1.0, "duration_hours": 1.0},
        }
    """
    def _get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    # Compute duration_hours where possible (used in debug regardless of outcome)
    duration_hours = duration_seconds / 3600 if duration_seconds is not None else None

    # Missing threshold_hr — cannot compute IF or TSS
    if threshold_hr is None:
        return {
            "tss": None,
            "method": "none",
            "debug": {
                "intensity_factor": None,
                "duration_hours": duration_hours,
                "reason": "threshold_hr not set in user preferences",
            },
        }

    # Missing duration_seconds — cannot compute TSS
    if duration_seconds is None:
        return {
            "tss": None,
            "method": "none",
            "debug": {
                "intensity_factor": None,
                "duration_hours": None,
                "reason": "duration_seconds is missing",
            },
        }

    # Resolve effective average HR from per-lap data when available
    effective_avg_hr = None
    lap_list = list(laps) if laps else []
    if lap_list:
        lap_hrs = [_get(lap, "avg_hr") for lap in lap_list]
        lap_durs = [_get(lap, "duration_seconds") or 0 for lap in lap_list]
        if all(h is not None for h in lap_hrs) and sum(lap_durs) > 0:
            effective_avg_hr = sum(h * d for h, d in zip(lap_hrs, lap_durs)) / sum(lap_durs)

    if effective_avg_hr is None:
        effective_avg_hr = avg_hr

    # Missing HR — cannot compute TSS
    if effective_avg_hr is None:
        return {
            "tss": None,
            "method": "none",
            "debug": {
                "intensity_factor": None,
                "duration_hours": duration_hours,
                "reason": "avg_hr is missing",
            },
        }

    intensity_factor = effective_avg_hr / threshold_hr
    tss = round(duration_hours * intensity_factor ** 2 * 100)

    return {
        "tss": tss,
        "method": "hr",
        "debug": {
            "intensity_factor": intensity_factor,
            "duration_hours": duration_hours,
        },
    }


def estimate_tss_for_workout(workout, user_id=None, db=None) -> tuple[int, str]:
    ftp_w, threshold_hr, threshold_pace = get_user_thresholds(user_id, db)

    duration = getattr(workout, "duration_seconds", None) or 0
    avg_power = getattr(workout, "avg_power_w", None)
    avg_pace = getattr(workout, "avg_pace_seconds_per_km", None)
    avg_hr = getattr(workout, "avg_hr", None)
    distance_km = getattr(workout, "distance_km", None)

    if avg_pace is None and duration and distance_km:
        try:
            avg_pace = duration / float(distance_km)
        except (TypeError, ZeroDivisionError):
            avg_pace = None

    if avg_power is not None:
        return compute_tss(intensity_factor_from_power(avg_power, ftp_w), duration), "power"

    if avg_pace is not None:
        return compute_tss(intensity_factor_from_pace(avg_pace, threshold_pace), duration), "pace"

    if avg_hr is not None:
        return compute_tss(intensity_factor_from_hr(avg_hr, threshold_hr), duration), "hr"

    return compute_tss(0.7, duration), "duration_only"


def persist_running_tss(workout_id, session) -> dict:
    """Thin caller: load workout, splits, and user prefs from session; persist running TSS.

    No math or hardcoded thresholds — all computation is delegated to
    compute_running_tss.  Only writes the computed value to workout.tss when
    that field is currently null (a manually-entered TSS is never overwritten).
    Always writes workout.tss_method so the UI can show the computation method
    even when a manual override is in place.

    The caller is responsible for calling session.commit() after this function
    returns so that multiple writes can be batched in one round-trip.

    Returns the compute_running_tss result dict (tss, method, partial, debug)
    so the caller can surface the computed value for comparison display without
    reading it back from the database.
    """
    from backend.models import Workout, WorkoutSplit, UserPreferences

    workout = session.get(Workout, workout_id)
    if workout is None:
        return {"tss": None, "method": "none", "partial": False, "debug": {}}

    splits = (
        session.query(WorkoutSplit)
        .filter(WorkoutSplit.workout_id == workout_id)
        .order_by(WorkoutSplit.split_index)
        .all()
    )
    prefs = (
        session.query(UserPreferences)
        .filter(UserPreferences.user_id == workout.user_id)
        .first()
    )

    result = compute_running_tss(workout, splits, prefs or UserPreferences())

    # Always persist the computation method (enables comparison display in UI)
    if result["method"] != "none":
        workout.tss_method = result["method"]

    # Only write computed value when no TSS is currently stored — manual entry wins
    if workout.tss is None and result["tss"] is not None:
        workout.tss = result["tss"]
        workout.tss_source = "calculated"

    return result


def recompute_user_running_tss(user_id, session) -> None:
    """Recompute TSS for every running workout owned by user_id.

    Called when the user's threshold preferences change so that all stored TSS
    values reflect the new thresholds on next fetch.  Only workouts with
    workout_type matching 'run' (case-insensitive) are processed.  The caller
    must commit the session after this function returns.
    """
    from backend.models import Workout

    workouts = (
        session.query(Workout)
        .filter(Workout.user_id == user_id)
        .filter(Workout.workout_type.ilike("run%"))
        .all()
    )
    for w in workouts:
        persist_running_tss(w.id, session)
