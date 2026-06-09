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
