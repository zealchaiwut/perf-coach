"""
TSS (Training Stress Score) computation utilities.

Formula:  TSS = (duration_seconds * IF²) / 36
            where IF = intensity factor (ratio of actual to threshold intensity).

IF method precedence (highest quality to lowest):
    power > pace > hr > duration_only

# Audit: rows where tss IS NULL AND duration_seconds IS NOT NULL in the workouts
# table are candidates for future backfill using estimate_tss_for_workout().
"""
import json
import logging

from sqlalchemy import text

THRESHOLD_PACE_SEC_PER_KM = 270  # ~4:30/km
THRESHOLD_HR = 170
FTP_W = 280

# Strength TSS per-set constants.
# STRENGTH_TSS_SCALE: multiplier applied to the raw set-stress sum so that a
# representative hard 45-minute strength session (e.g. 3 sets at RPE 8-10)
# yields a TSS between 50 and 70.  Value 5.85 produces ~60 for the
# docstring worked example (raw_sum=10.25 → scaled≈59.96).
STRENGTH_TSS_SCALE = 5.85

# STRENGTH_TSS_MAX: upper bound applied after scaling, before rounding.
# Prevents runaway scores from unusually high rep counts or RPE entries.
STRENGTH_TSS_MAX = 150

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


def get_user_thresholds(user_id, db) -> tuple:
    """Return (ftp_w, threshold_hr, threshold_pace_sec_per_km) for user_id.

    Reads from user_preferences. Returns None for each field when the user has
    no user_preferences row or the corresponding column is NULL. No hardcoded
    defaults are substituted — a missing threshold means the calling function
    must skip the computation that requires it.
    """
    if not user_id or db is None:
        return (None, None, None)

    try:
        row = db.execute(
            text(
                "SELECT ftp_w, threshold_hr, threshold_pace_seconds_per_km "
                "FROM user_preferences WHERE user_id = :uid"
            ),
            {"uid": str(user_id)},
        ).fetchone()
    except Exception:
        _log.warning("Could not query user_preferences for user %s; returning None thresholds", user_id)
        return (None, None, None)

    if row is None:
        _log.warning(
            "No user_preferences row for user %s; returning None thresholds", user_id
        )
        return (None, None, None)

    return (row.ftp_w, row.threshold_hr, row.threshold_pace_seconds_per_km)


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
    A zero value for threshold_hr or avg_hr is also treated as missing.

    Parameters
    ----------
    duration_seconds:
        Total workout duration in seconds (int or float). Required.
    avg_hr:
        Workout-level average heart rate in beats per minute. Used as a
        fallback when per-lap HR data are absent or incomplete. A value of
        zero is treated as missing.
    threshold_hr:
        The athlete's heart-rate threshold (lactate-threshold HR) in beats
        per minute, read from user_preferences by the caller. Must not be
        hardcoded here; pass None or 0 if the value is not set.
    laps:
        Optional iterable of lap objects (or dicts) each with avg_hr
        (beats per minute) and duration_seconds attributes. When all laps
        carry a valid avg_hr, the TSS is computed as the sum of per-lap
        contributions rather than from the workout-level avg_hr.

    Returns
    -------
    dict with exactly three keys:

        tss (int or None):
            Rounded Training Stress Score, or None when a required input is
            absent or zero.

        method (str):
            "hr" when TSS was successfully computed; "none" otherwise.

        debug (dict):
            Diagnostic values. Always contains:
              intensity_factor — avg_hr divided by threshold_hr (float or None)
              avg_hr_used      — effective HR used in the calculation (float or None)
              threshold_hr     — the threshold value passed in (int or None)
              duration_seconds — the duration value passed in (int or None)
              duration_hours   — duration_seconds divided by 3600 (float or None)
            When a required input is absent, also contains:
              reason — human-readable string describing which input is missing.

    Formula
    -------
    Step 1 — Determine effective average HR.
        When all laps supply avg_hr, compute the TSS as the sum of per-lap
        contributions: for each lap, lap_tss = (lap_duration / 3600) ×
        (lap_avg_hr / threshold_hr)² × 100.
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

        threshold_hr     = 170 bpm
        avg_hr           = 170 bpm
        duration_seconds = 3600

    Step 1 — No lap data; effective_avg_hr = 170.
    Step 2 — intensity_factor = 170 / 170 = 1.0.
    Step 3 — duration_hours = 3600 / 3600 = 1.0.
    Step 4 — TSS = 1.0 * 1.0 * 1.0 * 100 = 100.

    Return value:
        {
            "tss": 100,
            "method": "hr",
            "debug": {
                "intensity_factor": 1.0,
                "avg_hr_used": 170,
                "threshold_hr": 170,
                "duration_seconds": 3600,
                "duration_hours": 1.0,
            },
        }
    """
    def _get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    # Compute duration_hours where possible (used in debug regardless of outcome)
    duration_hours = duration_seconds / 3600 if duration_seconds is not None else None

    # Missing or zero threshold_hr — cannot compute IF or TSS
    if not threshold_hr:
        reason = (
            "threshold_hr not set in user preferences"
            if threshold_hr is None
            else "threshold_hr is zero"
        )
        return {
            "tss": None,
            "method": "none",
            "debug": {
                "intensity_factor": None,
                "avg_hr_used": None,
                "threshold_hr": threshold_hr,
                "duration_seconds": duration_seconds,
                "duration_hours": duration_hours,
                "reason": reason,
            },
        }

    # Missing duration_seconds — cannot compute TSS
    if duration_seconds is None:
        return {
            "tss": None,
            "method": "none",
            "debug": {
                "intensity_factor": None,
                "avg_hr_used": None,
                "threshold_hr": threshold_hr,
                "duration_seconds": None,
                "duration_hours": None,
                "reason": "duration_seconds is missing",
            },
        }

    # Per-lap path: sum of per-lap TSS contributions when all laps have avg_hr
    lap_list = list(laps) if laps else []
    if lap_list:
        lap_hrs = [_get(lap, "avg_hr") for lap in lap_list]
        lap_durs = [_get(lap, "duration_seconds") or 0 for lap in lap_list]
        if all(h is not None for h in lap_hrs) and sum(lap_durs) > 0:
            total_tss = 0.0
            for h, d in zip(lap_hrs, lap_durs):
                lap_if = h / threshold_hr
                total_tss += (d / 3600) * lap_if ** 2 * 100
            # Weighted average HR for debug display only
            avg_hr_used = sum(h * d for h, d in zip(lap_hrs, lap_durs)) / sum(lap_durs)
            intensity_factor = avg_hr_used / threshold_hr
            return {
                "tss": round(total_tss),
                "method": "hr",
                "debug": {
                    "intensity_factor": intensity_factor,
                    "avg_hr_used": avg_hr_used,
                    "threshold_hr": threshold_hr,
                    "duration_seconds": duration_seconds,
                    "duration_hours": duration_hours,
                },
            }

    # Fallback: workout-level avg_hr
    effective_avg_hr = avg_hr

    # Missing or zero HR — cannot compute TSS
    if not effective_avg_hr:
        return {
            "tss": None,
            "method": "none",
            "debug": {
                "intensity_factor": None,
                "avg_hr_used": None,
                "threshold_hr": threshold_hr,
                "duration_seconds": duration_seconds,
                "duration_hours": duration_hours,
                "reason": "avg_hr is missing or zero",
            },
        }

    intensity_factor = effective_avg_hr / threshold_hr
    tss = round(duration_hours * intensity_factor ** 2 * 100)

    return {
        "tss": tss,
        "method": "hr",
        "debug": {
            "intensity_factor": intensity_factor,
            "avg_hr_used": effective_avg_hr,
            "threshold_hr": threshold_hr,
            "duration_seconds": duration_seconds,
            "duration_hours": duration_hours,
        },
    }


def calc_strength_tss(
    session_rpe,
    duration_minutes,
    sets=None,
    user_preferences=None,
) -> dict:
    """Compute session-RPE Training Stress Score (TSS) for a strength session.

    All required inputs are supplied by the caller. No threshold defaults are
    assumed or hardcoded; any user-configurable values must be passed via
    user_preferences. This function performs no database reads or writes.

    Parameters
    ----------
    session_rpe:
        Athlete's perceived exertion for the whole session (0–10 scale), or
        None. When None, a derived value is computed from sets if available.
    duration_minutes:
        Total session duration in minutes (int or float), or None. Required
        for any TSS result; returns null when absent.
    sets:
        Optional list of set objects (dicts or objects) each with ``rpe``
        and ``reps`` attributes. Used to derive session RPE via a
        reps-weighted average when session_rpe is not supplied. Entries
        missing either ``rpe`` or ``reps`` are silently excluded.
    user_preferences:
        Reserved for caller-supplied user-configurable values. Not used by
        the current formula but accepted for forward compatibility.

    Returns
    -------
    dict with exactly four keys:

        tss (int or None):
            Rounded Training Stress Score, or None when a required input
            is absent.

        method (str):
            "session_rpe" when TSS was successfully computed; "none" otherwise.

        is_estimate (bool):
            Always True when method is "session_rpe".

        debug (dict):
            Diagnostic values. On success contains:
              session_rpe_source — "direct" or "derived"
              session_rpe        — RPE value used in the calculation
              duration_minutes   — duration used
              session_intensity  — session_rpe divided by 10
            On failure also contains:
              reason — human-readable string describing what is missing.

    Formula
    -------
    Step 1 — Resolve session RPE.
        Use session_rpe directly (source: "direct"). If absent but sets
        contain at least one entry with both rpe and reps, compute a
        reps-weighted average across valid sets (source: "derived").

    Step 2 — Compute session intensity (SI).
        SI = session_rpe divided by 10.
        This maps the 0–10 RPE scale to a 0–1 intensity ratio.

    Step 3 — Compute TSS.
        TSS = SI squared times (duration_minutes divided by 60) times 100.
        Round to the nearest whole integer.

    Worked examples
    ---------------
    Example 1 — 60 minutes at RPE 10 gives session_intensity of 1.0 and TSS of 100:
        session_rpe=10, duration_minutes=60
        SI = 10 / 10 = 1.0
        TSS = 1.0^2 × (60/60) × 100 = 100

    Example 2 — 60 minutes at RPE 7 gives session_intensity of 0.7 and TSS of 49:
        session_rpe=7, duration_minutes=60
        SI = 7 / 10 = 0.7
        TSS = 0.7^2 × (60/60) × 100 = 49
    """
    def _get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    # Resolve effective session RPE
    effective_rpe = session_rpe
    rpe_source = "direct"

    if effective_rpe is None:
        valid_sets = []
        for s in (sets or []):
            rpe_val = _get(s, "rpe")
            reps_val = _get(s, "reps")
            if rpe_val is not None and reps_val is not None:
                valid_sets.append((rpe_val, reps_val))

        if valid_sets:
            total_reps = sum(r for _, r in valid_sets)
            if total_reps > 0:
                effective_rpe = sum(rpe * reps for rpe, reps in valid_sets) / total_reps
                rpe_source = "derived"

    # Missing duration — cannot compute TSS
    if duration_minutes is None:
        return {
            "tss": None,
            "method": "none",
            "is_estimate": False,
            "debug": {
                "reason": "duration_minutes is missing",
            },
        }

    # Missing RPE (both direct and derivable from sets) — cannot compute TSS
    if effective_rpe is None:
        return {
            "tss": None,
            "method": "none",
            "is_estimate": False,
            "debug": {
                "reason": "session_rpe is missing and no valid sets available to derive it",
            },
        }

    session_intensity = effective_rpe / 10
    tss = round(session_intensity ** 2 * (duration_minutes / 60) * 100)

    return {
        "tss": tss,
        "method": "session_rpe",
        "is_estimate": True,
        "debug": {
            "session_rpe_source": rpe_source,
            "session_rpe": effective_rpe,
            "duration_minutes": duration_minutes,
            "session_intensity": session_intensity,
        },
    }


def estimate_tss_for_workout(workout, user_id=None, db=None) -> tuple:
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

    tried_intensity = False

    if avg_power is not None:
        tried_intensity = True
        if ftp_w is not None:
            return compute_tss(intensity_factor_from_power(avg_power, ftp_w), duration), "power"

    if avg_pace is not None:
        tried_intensity = True
        if threshold_pace is not None:
            return compute_tss(intensity_factor_from_pace(avg_pace, threshold_pace), duration), "pace"

    if avg_hr is not None:
        tried_intensity = True
        if threshold_hr is not None:
            return compute_tss(intensity_factor_from_hr(avg_hr, threshold_hr), duration), "hr"

    if tried_intensity:
        return None, "none"

    return compute_tss(0.7, duration), "duration_only"


def calculate_strength_tss_per_set(sets) -> dict:
    """Compute Training Stress Score for a strength session using per-set RPE data.

    Each set contributes a stress value equal to reps multiplied by the square of
    the RPE fraction (rpe divided by 10).  The contributions are summed, multiplied
    by STRENGTH_TSS_SCALE, clamped to STRENGTH_TSS_MAX, and rounded to a whole
    integer.

    Parameters
    ----------
    sets:
        List of dicts, each with keys ``reps`` (int) and ``rpe`` (int or float,
        1–10 scale).  The caller fetches this data from the database; this
        function performs no DB access.

    Returns
    -------
    dict with exactly three keys:

        tss (int or None):
            Rounded TSS, or None when any required input is absent or invalid.

        method (str):
            ``"per_set"`` when TSS was successfully computed; ``"none"``
            otherwise.

        debug (dict):
            Diagnostic values:
              per_set_contributions — list of set_stress floats, one per set
              raw_sum               — sum of per_set_contributions (float)
              scaled_sum            — raw_sum * STRENGTH_TSS_SCALE (float)
              clamped               — min(scaled_sum, STRENGTH_TSS_MAX) (float)
            On failure, also contains:
              reason — human-readable string describing the invalid input.

    Formula (per set)
    -----------------
        set_stress = reps × (rpe ÷ 10) × (rpe ÷ 10)
        raw_sum    = Σ set_stress
        scaled_sum = raw_sum × STRENGTH_TSS_SCALE
        clamped    = min(scaled_sum, STRENGTH_TSS_MAX)
        tss        = round(clamped)

    Worked example (three sets)
    ---------------------------
    Inputs: [
      { reps: 5, rpe: 8 },
      { reps: 5, rpe: 9 },
      { reps: 3, rpe: 10 }
    ]

    Set 1 stress: 5 × (8 ÷ 10) × (8 ÷ 10) = 5 × 0.64 = 3.20
    Set 2 stress: 5 × (9 ÷ 10) × (9 ÷ 10) = 5 × 0.81 = 4.05
    Set 3 stress: 3 × (10 ÷ 10) × (10 ÷ 10) = 3 × 1.00 = 3.00

    Raw sum: 3.20 + 4.05 + 3.00 = 10.25
    Scaled sum: 10.25 × STRENGTH_TSS_SCALE (5.85) ≈ 59.96
    Clamped: min(59.96, STRENGTH_TSS_MAX) = 59.96
    tss (whole number): 60
    """
    def _fail(reason):
        return {
            "tss": None,
            "method": "none",
            "debug": {"reason": reason},
        }

    try:
        if not sets:
            return _fail("set list is empty or None")

        contributions = []
        for i, s in enumerate(sets):
            if s is None:
                return _fail(f"set {i} is None")
            reps = s.get("reps") if isinstance(s, dict) else getattr(s, "reps", None)
            rpe = s.get("rpe") if isinstance(s, dict) else getattr(s, "rpe", None)

            if reps is None:
                return _fail(f"set {i} is missing reps")
            if rpe is None:
                return _fail(f"set {i} is missing rpe")

            reps_f = float(reps)
            rpe_f = float(rpe)
            stress = reps_f * (rpe_f / 10) * (rpe_f / 10)
            contributions.append(stress)

    except (TypeError, ValueError) as exc:
        return _fail(f"invalid input value: {exc}")

    raw_sum = sum(contributions)
    scaled_sum = raw_sum * STRENGTH_TSS_SCALE
    clamped = min(scaled_sum, STRENGTH_TSS_MAX)
    tss = round(clamped)

    return {
        "tss": tss,
        "method": "per_set",
        "debug": {
            "per_set_contributions": contributions,
            "raw_sum": raw_sum,
            "scaled_sum": scaled_sum,
            "clamped": clamped,
        },
    }


def calculate_strength_tss_per_set_with_prefs(sets, scale_constant, max_tss) -> dict:
    """Compute Training Stress Score for a strength session using per-set RPE data.

    This is a pure function — all database access must happen in the caller.
    The caller is responsible for reading ``scale_constant`` and ``max_tss``
    from ``user_preferences`` and passing them in. Neither value is hardcoded
    here; if either is absent (None) the function returns a null result.

    Parameters
    ----------
    sets:
        List of dicts, each with keys ``reps`` (int) and ``rpe`` (int or float,
        1–10 scale). The caller fetches this data from the database.
    scale_constant:
        Multiplier applied to the raw set-stress sum, read from
        ``user_preferences.scale_constant`` by the caller. Must not be
        hardcoded. A representative hard 45-minute session should yield TSS
        between 50 and 70 at the chosen value. Pass None when the preference
        is not set; the function will return a null result with a reason.
    max_tss:
        Upper bound applied after scaling, read from
        ``user_preferences.max_tss`` by the caller. Must not be hardcoded.
        Pass None when the preference is not set; the function will return a
        null result with a reason.

    Returns
    -------
    dict with exactly three keys:

        tss (int or None):
            Rounded TSS as a whole integer on success, or None when any
            required input is absent or invalid.

        method (str):
            ``"per_set"`` when TSS was successfully computed; ``"none"``
            on any failure.

        debug (dict):
            On success contains:
              per_set_contributions — list of set_stress floats, one per set
              raw_sum               — sum of per_set_contributions (pre-scale)
              scaled_sum            — raw_sum × scale_constant
              clamped               — min(scaled_sum, max_tss)
            On failure also contains:
              reason — human-readable string identifying the missing field
                       and set index (when applicable).

    Formula (per set)
    -----------------
        set_stress = reps × (rpe ÷ 10) × (rpe ÷ 10)
        raw_sum    = Σ set_stress
        scaled_sum = raw_sum × scale_constant
        clamped    = min(scaled_sum, max_tss)
        tss        = round(clamped)

    Worked example (three sets)
    ---------------------------
    Inputs: [
      { reps: 5, rpe: 8 },
      { reps: 5, rpe: 9 },
      { reps: 3, rpe: 10 }
    ]
    scale_constant = 5.85, max_tss = 150

    Set 1 stress: 5 × (8 ÷ 10) × (8 ÷ 10) = 5 × 0.8 × 0.8 = 3.20
    Set 2 stress: 5 × (9 ÷ 10) × (9 ÷ 10) = 5 × 0.9 × 0.9 = 4.05
    Set 3 stress: 3 × (10 ÷ 10) × (10 ÷ 10) = 3 × 1.0 × 1.0 = 3.00

    Raw sum: 3.20 + 4.05 + 3.00 = 10.25
    Scaled sum: 10.25 × 5.85 = 59.9625
    Clamped: min(59.9625, 150) = 59.9625
    tss (whole number): 60
    """
    def _fail(reason):
        return {"tss": None, "method": "none", "debug": {"reason": reason}}

    if scale_constant is None:
        return _fail("scale_constant preference is not set in user_preferences")

    if max_tss is None:
        return _fail("max_tss preference is not set in user_preferences")

    if not sets:
        return _fail("set list is empty or None")

    contributions = []
    try:
        for i, s in enumerate(sets):
            if s is None:
                return _fail(f"set {i} is None")
            reps = s.get("reps") if isinstance(s, dict) else getattr(s, "reps", None)
            rpe = s.get("rpe") if isinstance(s, dict) else getattr(s, "rpe", None)

            if reps is None:
                return _fail(f"set {i} is missing reps")
            if rpe is None:
                return _fail(f"set {i} is missing rpe")

            stress = float(reps) * (float(rpe) / 10) * (float(rpe) / 10)
            contributions.append(stress)
    except (TypeError, ValueError) as exc:
        return _fail(f"invalid input value: {exc}")

    raw_sum = sum(contributions)
    scaled_sum = raw_sum * float(scale_constant)
    clamped = min(scaled_sum, float(max_tss))
    return {
        "tss": round(clamped),
        "method": "per_set",
        "debug": {
            "per_set_contributions": contributions,
            "raw_sum": raw_sum,
            "scaled_sum": scaled_sum,
            "clamped": clamped,
        },
    }


def compute_strength_tss(workout, exercises, prefs) -> dict:
    """Compute TSS for a strength workout from plain data objects (no DB access).

    Tries two methods in priority order — per_set → session_rpe — and returns
    the result from the first method that has all required inputs. Returns
    ``{"tss": None, "method": "none", "partial": False, "debug": {"reason": ...}}``
    when no method can run.

    Parameters
    ----------
    workout:
        Object with attributes ``duration_seconds`` (int|None) and optionally
        ``session_rpe`` (int 1–10|None) for session-level RPE fallback.
        Dict access also accepted.
    exercises:
        Iterable of exercise objects (or dicts) with attributes ``rpe``
        (int 1–10|None), ``reps`` (int|None), ``weight_kg`` (float|None),
        ``sets`` (int|None), and ``sets_json`` (str|None — JSON array of
        per-set dicts, each optionally carrying ``reps``, ``rpe``,
        ``weight_kg``). May be None or empty.
    prefs:
        Object (or dict) with ``strength_tss_scale`` (float|None) and
        ``strength_tss_max`` (int|None), both read from user_preferences by
        the caller. None means the threshold is unset; no defaults are assumed.

    Returns
    -------
    dict with keys:
        tss        — whole integer or None
        method     — "per_set" | "session_rpe" | "none"
        partial    — True when TSS is from an incomplete set of per-set records
                     (some sets were missing RPE and therefore excluded)
        debug      — diagnostic dict; always present; contains a "reason" string
                     when method is "none"

    Method selection
    ----------------
    per_set:
        Any exercise provides set-level volume data (rpe AND reps, with or
        without weight_kg). Data may come from sets_json (per-set detail) or
        from exercise-level rpe + reps + optional sets count. When not all
        sets carry complete rpe+reps data, TSS is computed from the sets that
        do and ``partial`` is set to True.

    session_rpe:
        No set-level volume data exists, but a session RPE is available
        (from ``workout.session_rpe`` or averaged from exercise-level RPEs
        when those exercises carry rpe without reps/weight) and the workout
        has a positive ``duration_seconds``.

    none:
        Neither RPE nor duration is available; ``tss`` is null and
        ``debug.reason`` explains which inputs are missing.

    Formulas
    --------
    per_set:
        For each set i with reps_i and rpe_i:
            set_stress_i = reps_i × (rpe_i / 10)²
        raw_sum = Σ set_stress_i
        scaled_sum = raw_sum × strength_tss_scale     (from prefs)
        clamped = min(scaled_sum, strength_tss_max)   (from prefs)
        tss = round(clamped)

    session_rpe:
        IF = session_rpe / 10
        raw_tss = (duration_seconds / 3600) × IF² × 100
        clamped = min(raw_tss, strength_tss_max)      (from prefs)
        tss = round(clamped)

    Worked examples
    ---------------
    Example 1 – per_set method (three sets, strength_tss_scale=5.85, max=150):
        sets = [{reps:5, rpe:8}, {reps:5, rpe:9}, {reps:3, rpe:10}]

        Step 1 — set stresses:
            set1: 5 × (8/10)² = 5 × 0.64 = 3.20
            set2: 5 × (9/10)² = 5 × 0.81 = 4.05
            set3: 3 × (10/10)² = 3 × 1.00 = 3.00

        Step 2 — raw_sum: 3.20 + 4.05 + 3.00 = 10.25

        Step 3 — scaled_sum: 10.25 × 5.85 = 59.9625

        Step 4 — clamped: min(59.9625, 150) = 59.9625

        Step 5 — tss: round(59.9625) = 60

    Example 2 – session_rpe method (45 min, session_rpe=8, strength_tss_max=150):
        Step 1 — IF = 8 / 10 = 0.8

        Step 2 — raw_tss = (2700 / 3600) × 0.8² × 100
                         = 0.75 × 0.64 × 100 = 48.0

        Step 3 — clamped: min(48.0, 150) = 48.0

        Step 4 — tss: round(48.0) = 48
    """
    import json as _json

    def _g(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    strength_tss_scale = _g(prefs, "strength_tss_scale")
    strength_tss_max = _g(prefs, "strength_tss_max")
    duration = _g(workout, "duration_seconds") or 0
    exercise_list = list(exercises) if exercises else []

    # ── Collect all sets from exercises ────────────────────────────────────────
    # Each entry: dict with reps, rpe, weight_kg (all may be None)
    all_sets = []
    exercise_rpes = []  # RPEs from exercises without volume data (for session_rpe fallback)

    for ex in exercise_list:
        sets_json_raw = _g(ex, "sets_json")
        ex_rpe = _g(ex, "rpe")
        ex_reps = _g(ex, "reps")
        ex_weight = _g(ex, "weight_kg")
        ex_sets_count = _g(ex, "sets") or 1

        if sets_json_raw is not None:
            try:
                parsed = _json.loads(sets_json_raw) if isinstance(sets_json_raw, str) else sets_json_raw
                if isinstance(parsed, list):
                    for s in parsed:
                        all_sets.append({
                            "reps": s.get("reps") if isinstance(s, dict) else None,
                            "rpe": s.get("rpe") if isinstance(s, dict) else None,
                            "weight_kg": s.get("weight_kg") if isinstance(s, dict) else None,
                        })
            except (ValueError, TypeError):
                pass
        elif ex_rpe is not None or ex_reps is not None or ex_weight is not None:
            if ex_rpe is not None and (ex_reps is not None or ex_weight is not None):
                # Exercise has volume data — treat as N identical sets
                for _ in range(int(ex_sets_count)):
                    all_sets.append({"reps": ex_reps, "rpe": ex_rpe, "weight_kg": ex_weight})
            elif ex_rpe is not None:
                # RPE present but no volume — contributes to session_rpe fallback
                exercise_rpes.append(ex_rpe)

    # ── Determine which sets can be scored (have rpe + reps) ──────────────────
    scored_sets = [s for s in all_sets if s.get("rpe") is not None and s.get("reps") is not None]
    has_per_set = bool(scored_sets) or bool(
        # unscored sets that still have reps or weight (volume exists but rpe missing)
        [s for s in all_sets if (s.get("reps") is not None or s.get("weight_kg") is not None)]
    )
    unscored_volume_sets = [
        s for s in all_sets
        if (s.get("reps") is not None or s.get("weight_kg") is not None)
        and s.get("rpe") is None
    ]

    # ── Method 1: per_set ─────────────────────────────────────────────────────
    if has_per_set:
        if strength_tss_scale is None:
            return {
                "tss": None,
                "method": "none",
                "partial": False,
                "debug": {"reason": "strength_tss_scale not set in user preferences"},
            }
        if strength_tss_max is None:
            return {
                "tss": None,
                "method": "none",
                "partial": False,
                "debug": {"reason": "strength_tss_max not set in user preferences"},
            }

        partial = bool(unscored_volume_sets)
        per_set_contributions = [
            s["reps"] * (s["rpe"] / 10) ** 2 for s in scored_sets
        ]
        raw_sum = sum(per_set_contributions)
        scaled_sum = raw_sum * strength_tss_scale
        clamped = min(scaled_sum, strength_tss_max)
        return {
            "tss": round(clamped),
            "method": "per_set",
            "partial": partial,
            "debug": {
                "per_set_contributions": per_set_contributions,
                "raw_sum": raw_sum,
                "scaled_sum": scaled_sum,
                "clamped": clamped,
            },
        }

    # ── Method 2: session_rpe ─────────────────────────────────────────────────
    session_rpe = _g(workout, "session_rpe")
    if session_rpe is None and exercise_rpes:
        session_rpe = round(sum(exercise_rpes) / len(exercise_rpes))

    if session_rpe is not None and duration > 0:
        if strength_tss_max is None:
            return {
                "tss": None,
                "method": "none",
                "partial": False,
                "debug": {"reason": "strength_tss_max not set in user preferences"},
            }
        if_val = session_rpe / 10
        raw_tss = (duration / 3600) * if_val ** 2 * 100
        clamped = min(raw_tss, strength_tss_max)
        return {
            "tss": round(clamped),
            "method": "session_rpe",
            "partial": False,
            "debug": {
                "session_rpe": session_rpe,
                "intensity_factor": if_val,
                "duration_hours": duration / 3600,
                "raw_tss": raw_tss,
                "clamped": clamped,
            },
        }

    # ── No usable data ─────────────────────────────────────────────────────────
    missing = []
    if session_rpe is None and not exercise_rpes:
        missing.append("no RPE data")
    if duration <= 0:
        missing.append("no duration")
    reason = "; ".join(missing) if missing else "insufficient data for strength TSS"
    return {
        "tss": None,
        "method": "none",
        "partial": False,
        "debug": {"reason": reason},
    }


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

    # Write computed value when: (a) no TSS stored yet, or (b) previously computed TSS
    # (tss_source="calculated") so threshold changes refresh the stored value.
    # Never overwrites manually-entered or externally-sourced TSS values.
    if (workout.tss is None or workout.tss_source == "calculated") and result["tss"] is not None:
        workout.tss = result["tss"]
        workout.tss_source = "calculated"

    return result


def compute_running_tss_pace_from_prefs(
    user_id,
    laps,
    whole_workout_average_pace_seconds_per_km,
    total_duration_seconds,
    db,
) -> dict:
    """Thin DB-access wrapper around :func:`~backend.services.running_tss_pace.calculate_running_tss_pace`.

    Reads ``threshold_pace_seconds_per_km`` from ``user_preferences`` for
    ``user_id`` and passes it directly to the pure function.  No default value
    is substituted when the preference is absent; a missing threshold produces
    ``{tss: None, method: "none", ...}`` so the caller can surface that to the
    user rather than silently computing a meaningless score.

    Parameters
    ----------
    user_id:
        The authenticated user's id.
    laps:
        List of lap dicts with ``lap_duration_seconds`` and
        ``lap_pace_seconds_per_km``.  May be None or empty.
    whole_workout_average_pace_seconds_per_km:
        Fallback average pace for the whole workout when laps are absent.
    total_duration_seconds:
        Total workout duration used for the fallback calculation.
    db:
        Active SQLAlchemy session or connection.
    """
    from backend.services.running_tss_pace import calculate_running_tss_pace

    threshold = None
    if user_id is not None and db is not None:
        try:
            row = db.execute(
                text(
                    "SELECT threshold_pace_seconds_per_km "
                    "FROM user_preferences WHERE user_id = :uid"
                ),
                {"uid": str(user_id)},
            ).fetchone()
            if row is not None:
                threshold = row.threshold_pace_seconds_per_km
        except Exception:
            _log.warning(
                "Could not query user_preferences for user %s; threshold will be None",
                user_id,
                exc_info=True,
            )

    return calculate_running_tss_pace(
        threshold_pace_seconds_per_km=threshold,
        laps=laps,
        whole_workout_average_pace_seconds_per_km=whole_workout_average_pace_seconds_per_km,
        total_duration_seconds=total_duration_seconds,
    )


def recompute_user_running_tss(user_id, session) -> int:
    """Recompute TSS for every running workout owned by user_id.

    Called when the user's threshold preferences change so that all stored TSS
    values reflect the new thresholds on next fetch.  Only workouts with
    workout_type matching 'run' (case-insensitive) are processed.  The caller
    must commit the session after this function returns.

    Returns the number of workouts processed so callers can report it without
    running an independent count query that might diverge from this filter.
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
        # Release each workout's loaded state (splits etc.) after persisting so
        # a full-user recompute holds ~one workout in memory, not the whole
        # history. The pending tss/tss_method writes are flushed by expire.
        session.flush()
        session.expire(w)
    return len(workouts)


def get_strength_tss_per_set_for_workout(workout_id, user_id, db) -> dict:
    """Thin caller: read per-set prefs from UserPreferences and delegate to the pure function.

    Reads ``scale_constant`` and ``max_tss`` from the ``user_preferences`` row
    for ``user_id``, collects set-level {reps, rpe} data from the workout's
    exercises, and delegates to ``calculate_strength_tss_per_set_with_prefs``.
    Neither preference value is given a hardcoded default here — if either is
    absent (None), it is passed as-is to the pure function, which returns a
    null result with a reason string.

    Parameters
    ----------
    workout_id:
        Primary key of the workout to compute TSS for.
    user_id:
        Primary key of the user whose ``UserPreferences`` row provides
        ``scale_constant`` and ``max_tss``.
    db:
        SQLAlchemy session (or compatible).

    Returns
    -------
    dict with keys ``tss`` (int|None), ``method`` (str), ``debug`` (dict) —
    same shape as ``calculate_strength_tss_per_set_with_prefs``.

    Raises
    ------
    ValueError
        When ``workout_id`` or ``user_id`` does not exist in the database.
    """
    from backend.models import User, UserPreferences, Workout, WorkoutExercise

    workout = db.get(Workout, workout_id)
    if workout is None:
        raise ValueError(f"Workout not found: {workout_id}")

    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"User not found: {user_id}")

    prefs = (
        db.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .first()
    )
    scale_constant = prefs.scale_constant if prefs is not None else None
    max_tss = prefs.max_tss if prefs is not None else None

    exercises = (
        db.query(WorkoutExercise)
        .filter(WorkoutExercise.workout_id == workout_id)
        .all()
    )

    sets = []
    for ex in exercises:
        sets_json_raw = getattr(ex, "sets_json", None)
        if sets_json_raw is not None:
            try:
                parsed = json.loads(sets_json_raw) if isinstance(sets_json_raw, str) else sets_json_raw
                if isinstance(parsed, list):
                    for s in parsed:
                        sets.append({
                            "reps": s.get("reps") if isinstance(s, dict) else None,
                            "rpe": s.get("rpe") if isinstance(s, dict) else None,
                        })
            except (ValueError, TypeError):
                pass
        else:
            ex_rpe = getattr(ex, "rpe", None)
            ex_reps = getattr(ex, "reps", None)
            ex_sets_count = getattr(ex, "sets", None) or 1
            if ex_rpe is not None or ex_reps is not None:
                for _ in range(int(ex_sets_count)):
                    sets.append({"reps": ex_reps, "rpe": ex_rpe})

    return calculate_strength_tss_per_set_with_prefs(sets, scale_constant, max_tss)
