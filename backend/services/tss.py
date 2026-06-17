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
