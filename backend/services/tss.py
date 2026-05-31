"""
TSS (Training Stress Score) computation utilities.

Formula:  TSS = (duration_seconds * IF²) / 36
            where IF = intensity factor (ratio of actual to threshold intensity).

IF method precedence (highest quality to lowest):
    power > pace > hr > duration_only

# Audit: rows where tss IS NULL AND duration_seconds IS NOT NULL in the workouts
# table are candidates for future backfill using estimate_tss_for_workout().
"""

THRESHOLD_PACE_SEC_PER_KM = 270  # ~4:30/km
THRESHOLD_HR = 170
FTP_W = 280


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


def estimate_tss_for_workout(workout) -> tuple[int, str]:
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
        return compute_tss(intensity_factor_from_power(avg_power, FTP_W), duration), "power"

    if avg_pace is not None:
        return compute_tss(intensity_factor_from_pace(avg_pace, THRESHOLD_PACE_SEC_PER_KM), duration), "pace"

    if avg_hr is not None:
        return compute_tss(intensity_factor_from_hr(avg_hr, THRESHOLD_HR), duration), "hr"

    return compute_tss(0.7, duration), "duration_only"
