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
    """Compute TSS for a running workout from plain data objects (no DB access).

    Tries three methods in priority order — Power → Pace → HR — and returns
    the result from the first method that has all required inputs. Returns
    ``{"tss": None, "method": "none", "partial": False}`` when no method can
    run.

    Parameters
    ----------
    workout:
        Object with attributes ``np`` (normalized power, int|None),
        ``avg_hr`` (int|None), ``distance_km`` (float|None),
        ``duration_seconds`` (int|None). Dict access also accepted.
    splits:
        Iterable of objects (or dicts) with ``duration_seconds``,
        ``distance_km``, and ``avg_hr``. May be None or empty.
    prefs:
        Object (or dict) with ``ftp_w``, ``threshold_pace_seconds_per_km``,
        ``threshold_hr`` — all int|None. None means the threshold is unset;
        no defaults are assumed.

    Returns
    -------
    dict with keys:
        tss        — whole integer or None
        method     — "power" | "pace" | "hr" | "none"
        partial    — True when workout-level average was used instead of
                     per-lap data because laps were absent or incomplete

    Formulas (all methods share the same TSS equation)
    ---------------------------------------------------
    TSS = (duration_s × IF² / 3600) × 100
    where IF = intensity factor for the chosen method:
        Power: IF = NP / FTP_W
        Pace:  IF = threshold_pace_s_per_km / lap_pace_s_per_km
        HR:    IF = avg_hr / threshold_hr

    Worked examples
    ---------------
    Example 1 – Power method (60 min at FTP = 100):
        ftp_w=280, np=280, duration=3600 s
        IF = 280/280 = 1.0
        TSS = (3600 × 1.0² / 3600) × 100 = 100  ✓

    Example 2 – Pace method per-lap (60 min at threshold pace = 100):
        threshold_pace=300 s/km, single lap: 12 km in 3600 s
        lap_pace = 3600/12 = 300 s/km  →  IF = 300/300 = 1.0
        lap_tss = (3600/3600) × 1.0² × 100 = 100  →  total TSS = 100  ✓

    Example 3 – HR method (60 min at threshold HR = 100):
        threshold_hr=170, avg_hr=170, duration=3600 s
        IF = 170/170 = 1.0
        TSS = (3600 × 1.0² / 3600) × 100 = 100  ✓
    """
    def _g(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    duration = _g(workout, "duration_seconds") or 0
    if duration <= 0:
        return {"tss": None, "method": "none", "partial": False}

    ftp_w = _g(prefs, "ftp_w")
    threshold_pace = _g(prefs, "threshold_pace_seconds_per_km")
    threshold_hr = _g(prefs, "threshold_hr")
    np_val = _g(workout, "np")
    avg_hr = _g(workout, "avg_hr")
    distance_km = _g(workout, "distance_km")

    split_list = list(splits) if splits else []

    # ── Method 1: Power ────────────────────────────────────────────────────────
    if ftp_w and np_val:
        if_val = np_val / ftp_w
        return {"tss": round((duration * if_val ** 2 / 3600) * 100), "method": "power", "partial": False}

    # ── Method 2: Pace ─────────────────────────────────────────────────────────
    if threshold_pace:
        if split_list:
            total = 0.0
            valid = True
            for s in split_list:
                lap_dur = _g(s, "duration_seconds") or 0
                lap_dist_raw = _g(s, "distance_km")
                try:
                    lap_dist = float(lap_dist_raw) if lap_dist_raw is not None else None
                except (TypeError, ValueError):
                    lap_dist = None
                if not lap_dur or not lap_dist or lap_dist <= 0:
                    valid = False
                    break
                lap_pace = lap_dur / lap_dist
                lap_if = threshold_pace / lap_pace
                total += (lap_dur / 3600) * lap_if ** 2 * 100
            if valid:
                return {"tss": round(total), "method": "pace", "partial": False}

        # Fallback: whole-workout average pace
        try:
            dist_f = float(distance_km) if distance_km is not None else None
        except (TypeError, ValueError):
            dist_f = None
        if dist_f and dist_f > 0:
            avg_pace = duration / dist_f
            if_val = threshold_pace / avg_pace
            return {"tss": round((duration * if_val ** 2 / 3600) * 100), "method": "pace", "partial": True}

    # ── Method 3: HR ───────────────────────────────────────────────────────────
    if threshold_hr:
        if split_list:
            lap_hrs = [_g(s, "avg_hr") for s in split_list]
            if all(hr is not None for hr in lap_hrs):
                total = 0.0
                for s, hr in zip(split_list, lap_hrs):
                    lap_dur = _g(s, "duration_seconds") or 0
                    lap_if = hr / threshold_hr
                    total += (lap_dur / 3600) * lap_if ** 2 * 100
                return {"tss": round(total), "method": "hr", "partial": False}

        # Fallback: workout-level avg_hr
        if avg_hr:
            if_val = avg_hr / threshold_hr
            return {"tss": round((duration * if_val ** 2 / 3600) * 100), "method": "hr", "partial": True}

    return {"tss": None, "method": "none", "partial": False}


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
