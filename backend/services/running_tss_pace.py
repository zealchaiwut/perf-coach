"""Pure pace-based running TSS calculation with per-lap granularity.

This module contains no database access. All inputs are passed by the caller.
The DB-access caller (thin wrapper) reads ``threshold_pace_seconds_per_km``
from ``user_preferences`` and passes it directly into :func:`calculate_running_tss_pace`;
no threshold values are hardcoded or assumed anywhere in this module.

Worked two-lap example
----------------------
Threshold pace: 300 s/km (5:00/km)

Lap 1: duration=600 s, pace=280 s/km
    lap_intensity = 300 / 280 ≈ 1.0714
    lap_tss       = (600 / 3600) × 1.0714² × 100 ≈ 19.13

Lap 2: duration=900 s, pace=320 s/km
    lap_intensity = 300 / 320 = 0.9375
    lap_tss       = (900 / 3600) × 0.9375² × 100 ≈ 21.97

Total tss = round(19.13 + 21.97) = round(41.10) = 41
"""


def calculate_running_tss_pace(
    *,
    threshold_pace_seconds_per_km,
    laps,
    whole_workout_average_pace_seconds_per_km=None,
    total_duration_seconds=None,
) -> dict:
    """Compute running Training Stress Score from pace data with per-lap granularity.

    All inputs are passed directly by the caller; this function never reads from
    or writes to the database.

    A lap faster than threshold produces a lap_intensity greater than 1 because
    pace is measured in seconds-per-km (lower value = faster speed).

    Parameters
    ----------
    threshold_pace_seconds_per_km:
        Athlete's threshold pace in seconds per km. Must be provided and > 0.
        No default is assumed; if absent the function returns a null result.
    laps:
        List of lap objects. Each must have ``lap_duration_seconds`` (int/float)
        and ``lap_pace_seconds_per_km`` (int/float). May be None or empty, in
        which case the fallback parameters are used.
    whole_workout_average_pace_seconds_per_km:
        Fallback average pace for the whole workout (seconds per km). Used only
        when ``laps`` is absent or empty.
    total_duration_seconds:
        Total workout duration in seconds. Used only for the fallback single-lap
        calculation when ``laps`` is absent or empty.

    Returns
    -------
    On success::

        {
            "tss":    <int>,     # rounded sum of per-lap TSS values
            "method": "pace",
            "debug":  {
                "laps": [
                    {
                        "lap_duration_seconds":    <float>,
                        "lap_pace_seconds_per_km": <float>,
                        "lap_intensity":           <float>,
                        "lap_tss":                 <float>,
                    },
                    ...
                ]
            }
        }

    When ``threshold_pace_seconds_per_km`` is missing or zero::

        {"tss": None, "method": "none", "reason": "<explanation>", "debug": None}

    When both lap splits and fallback average pace are absent::

        {"tss": None, "method": "none", "reason": "<explanation>", "debug": None}

    Worked two-lap example
    ----------------------
    Threshold pace: 300 s/km

    Lap 1: duration=600 s, pace=280 s/km
        lap_intensity = 300 / 280 ≈ 1.0714
        lap_tss       = (600 / 3600) × 1.0714² × 100 ≈ 19.13

    Lap 2: duration=900 s, pace=320 s/km
        lap_intensity = 300 / 320 = 0.9375
        lap_tss       = (900 / 3600) × 0.9375² × 100 ≈ 21.97

    Total tss = round(19.13 + 21.97) = round(41.10) = 41
    """
    def _get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    # Guard: threshold required
    if not threshold_pace_seconds_per_km:
        return {
            "tss": None,
            "method": "none",
            "reason": "threshold_pace_seconds_per_km is missing or zero",
            "debug": None,
        }

    lap_list = list(laps) if laps else []
    computed_laps = []

    for lap in lap_list:
        lap_dur = _get(lap, "lap_duration_seconds")
        lap_pace = _get(lap, "lap_pace_seconds_per_km")
        if not lap_dur or not lap_pace or lap_pace <= 0:
            continue
        lap_intensity = threshold_pace_seconds_per_km / lap_pace
        lap_tss = (lap_dur / 3600) * lap_intensity ** 2 * 100
        computed_laps.append({
            "lap_duration_seconds": lap_dur,
            "lap_pace_seconds_per_km": lap_pace,
            "lap_intensity": lap_intensity,
            "lap_tss": lap_tss,
        })

    # Fallback: synthesise a single lap from whole-workout average pace
    if not computed_laps:
        avg_pace = whole_workout_average_pace_seconds_per_km
        dur = total_duration_seconds
        if not avg_pace or not dur or avg_pace <= 0 or dur <= 0:
            return {
                "tss": None,
                "method": "none",
                "reason": "no lap pace data and no whole-workout average pace provided",
                "debug": None,
            }
        lap_intensity = threshold_pace_seconds_per_km / avg_pace
        lap_tss = (dur / 3600) * lap_intensity ** 2 * 100
        computed_laps.append({
            "lap_duration_seconds": dur,
            "lap_pace_seconds_per_km": avg_pace,
            "lap_intensity": lap_intensity,
            "lap_tss": lap_tss,
        })

    tss = round(sum(lap["lap_tss"] for lap in computed_laps))
    return {
        "tss": tss,
        "method": "pace",
        "debug": {"laps": computed_laps},
    }
