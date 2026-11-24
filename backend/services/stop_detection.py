"""Race result time, per-lap stop detection and sensor-glitch flags (revamp P6-2, #1876).

Pure functions — no DB access. All thresholds are named constants; every figure
is computed deterministically (no LLM).

Lap input shape (dicts)::

    {"moving_time_seconds": int, "elapsed_time_seconds": int | None,
     "distance_km": float, "avg_hr": int | None, "cadence_spm": int | None}

Rules:
* A lap is a *stop lap* if ``elapsed - moving >= STOP_GAP_SECONDS`` or its pace
  (moving time / distance) is slower than ``STOP_PACE_FACTOR`` x the median lap pace.
* Stopped time = sum over stop laps of ``max(0, lap elapsed - median lap moving time)``.
* A lap is a *sensor glitch* if cadence > ``GLITCH_CADENCE_SPM`` while pace is
  slower than ``GLITCH_PACE_S_PER_KM`` (9:00/km), or its HR differs by more than
  ``GLITCH_HR_JUMP`` bpm from BOTH neighbours in the same direction (spike/dip).
  Glitches are flagged, never dropped.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Iterable

STOP_GAP_SECONDS = 60
STOP_PACE_FACTOR = 1.6
GLITCH_CADENCE_SPM = 200
GLITCH_PACE_S_PER_KM = 540  # 9:00/km
GLITCH_HR_JUMP = 15


def race_result_time(
    chip_seconds: int | None,
    elapsed_seconds: int | None,
    moving_seconds: int | None,
) -> dict[str, Any]:
    """Race result = chip time if entered, else elapsed. Never moving time.

    Moving time is returned alongside (shown second). ``result_seconds`` is None
    when neither chip nor elapsed time is known.
    """
    if chip_seconds:
        result, source = int(chip_seconds), "chip"
    elif elapsed_seconds:
        result, source = int(elapsed_seconds), "elapsed"
    else:
        result, source = None, None
    return {
        "result_seconds": result,
        "result_source": source,
        "moving_time_seconds": moving_seconds,
    }


def laps_from_strava(strava_laps: Iterable[dict] | None) -> list[dict]:
    """Normalise raw Strava laps (metres, per-leg cadence) to the lap input shape."""
    out = []
    for lap in strava_laps or []:
        moving = lap.get("moving_time")
        if moving is None:
            continue
        cad = lap.get("average_cadence")
        hr = lap.get("average_heartrate")
        out.append({
            "moving_time_seconds": int(moving),
            "elapsed_time_seconds": lap.get("elapsed_time"),
            "distance_km": float(lap.get("distance") or 0) / 1000.0,
            # Strava run cadence is steps per leg per minute.
            "cadence_spm": round(float(cad) * 2) if cad is not None else None,
            "avg_hr": round(float(hr)) if hr is not None else None,
        })
    return out


def laps_from_splits(splits: Iterable[Any] | None) -> list[dict]:
    """Normalise WorkoutSplit rows; moving/elapsed fall back to duration_seconds."""
    out = []
    for s in splits or []:
        moving = getattr(s, "moving_time_seconds", None) or s.duration_seconds
        out.append({
            "moving_time_seconds": int(moving or 0),
            "elapsed_time_seconds": getattr(s, "elapsed_time_seconds", None),
            "distance_km": float(s.distance_km or 0),
            "cadence_spm": s.cadence_spm,
            "avg_hr": s.avg_hr,
        })
    return out


def _pace(lap: dict) -> float | None:
    d = lap.get("distance_km") or 0
    return lap["moving_time_seconds"] / d if d > 0 else None


def detect_stops_and_glitches(laps: list[dict]) -> dict[str, Any]:
    """Return per-lap stop/glitch flags plus stopped-time total.

    Lap indexes in the output are 1-based (lap 1 = first lap).
    """
    if not laps:
        return {"stop_laps": [], "stopped_time_seconds": 0, "glitch_laps": [], "laps": []}

    median_moving = median(l["moving_time_seconds"] for l in laps)
    paces = [p for p in (_pace(l) for l in laps) if p is not None]
    median_pace = median(paces) if paces else None

    flags = []
    stopped = 0.0
    for i, lap in enumerate(laps):
        moving = lap["moving_time_seconds"]
        elapsed = lap.get("elapsed_time_seconds") or moving
        pace = _pace(lap)
        is_stop = (elapsed - moving >= STOP_GAP_SECONDS) or (
            pace is not None and median_pace is not None and pace > STOP_PACE_FACTOR * median_pace
        )
        excess = max(0.0, elapsed - median_moving) if is_stop else 0.0
        stopped += excess

        reasons = []
        cad = lap.get("cadence_spm")
        if cad is not None and cad > GLITCH_CADENCE_SPM and pace is not None and pace > GLITCH_PACE_S_PER_KM:
            reasons.append("cadence")
        hr = lap.get("avg_hr")
        if hr is not None and 0 < i < len(laps) - 1:
            prev_hr, next_hr = laps[i - 1].get("avg_hr"), laps[i + 1].get("avg_hr")
            if prev_hr is not None and next_hr is not None:
                dp, dn = hr - prev_hr, hr - next_hr
                if abs(dp) > GLITCH_HR_JUMP and abs(dn) > GLITCH_HR_JUMP and dp * dn > 0:
                    reasons.append("hr_jump")

        flags.append({
            "lap_index": i + 1,
            "is_stop_lap": is_stop,
            "stopped_seconds": int(round(excess)),
            "sensor_glitch": bool(reasons),
            "glitch_reasons": reasons,
        })

    return {
        "stop_laps": [f["lap_index"] for f in flags if f["is_stop_lap"]],
        "stopped_time_seconds": int(round(stopped)),
        "glitch_laps": [f["lap_index"] for f in flags if f["sensor_glitch"]],
        "laps": flags,
    }
