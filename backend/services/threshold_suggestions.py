"""Threshold suggestion engine.

Pure function ``suggest_thresholds`` derives evidence-based threshold candidates
from a user's own performance history so the UI can prompt a one-tap confirmation.

This module performs *no* database access and has *no* side effects.  The calling
layer is responsible for reading data from the database, deciding what to surface,
and persisting any accepted values.
"""
from __future__ import annotations

from typing import Union


def _val(obj, key):
    """Read a field from a dict or an ORM-like object."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def suggest_thresholds(
    duration_curve: Union[dict, None],
    recent_runs: Union[list, None],
) -> dict:
    """Suggest FTP, threshold pace, and threshold HR from performance data.

    Parameters
    ----------
    duration_curve:
        Mapping of duration-in-seconds to best average power in watts.
        Example: ``{1200: 300.0}`` means the best 20-minute power was 300 W.
    recent_runs:
        List of run objects (dicts or objects with attributes):
        - ``duration_seconds`` (int) — effort duration
        - ``avg_pace_seconds_per_km`` (float) — lower means faster
        - ``avg_hr_bpm`` (float or None) — average heart rate

    Returns
    -------
    On success: a dict with keys ``ftp_w``, ``threshold_pace_seconds_per_km``,
    ``threshold_hr`` (each ``{"value": int, "high_confidence": bool}``), and
    ``debug`` (source effort details for each suggestion).

    When either input is ``None``, empty, or contains too few qualifying data
    points: ``{"suggestions": {}, "reason": "not enough history yet"}``.

    Worked example — power
    ----------------------
    Best 20-minute power of 300 watts yields a suggested FTP of 285 watts
    (300 multiplied by 0.95, rounded to the nearest integer).
    """
    curve = duration_curve or {}
    runs = recent_runs or []

    if not curve and not runs:
        return {"suggestions": {}, "reason": "not enough history yet"}

    suggestions: dict = {}
    debug: dict = {}

    # ── Power: FTP = best 20-minute average power × 0.95 ─────────────────────
    # 20 minutes = 1 200 seconds.  If no exact 20-minute point exists, fall back
    # to the best sustained effort whose duration falls between 20 and 60 minutes
    # (1 200 – 3 600 seconds inclusive) and apply the same 95 percent multiplier.

    ftp_w = None
    high_confidence_power = False
    power_debug: dict = {}

    if 1200 in curve and curve[1200] is not None:
        raw_power = float(curve[1200])
        ftp_w = round(raw_power * 0.95)
        high_confidence_power = True
        power_debug = {
            "duration_used": 1200,
            "raw_value": raw_power,
            "formula": "best 20-minute power multiplied by 0.95",
        }
    else:
        # Fallback: find the best effort between 20 and 60 minutes.
        best_power = None
        best_duration = None
        for d in sorted(curve.keys()):
            if 1200 <= d <= 3600 and curve[d] is not None:
                if best_power is None or float(curve[d]) > best_power:
                    best_power = float(curve[d])
                    best_duration = d
        if best_power is not None:
            ftp_w = round(best_power * 0.95)
            high_confidence_power = False
            power_debug = {
                "duration_used": best_duration,
                "raw_value": best_power,
                "formula": (
                    f"best {best_duration // 60}-minute power multiplied by 0.95 "
                    "(fallback: no 20-minute point found in curve)"
                ),
            }

    if ftp_w is not None:
        suggestions["ftp_w"] = {"value": ftp_w, "high_confidence": high_confidence_power}
    debug["ftp_w"] = power_debug

    # ── Pace + HR: from runs of 20–30 minutes (1 200 – 1 800 seconds) ─────────
    # Suggested threshold pace equals the best (fastest) average pace from any
    # qualifying run effort.  Suggested threshold HR equals the average HR
    # recorded during that same run effort.
    #
    # ``high_confidence`` is ``True`` for both pace and HR only when at least
    # two qualifying run efforts exist.

    qualifying_runs = [
        r for r in runs
        if _val(r, "duration_seconds") is not None
        and 1200 <= _val(r, "duration_seconds") <= 1800
        and _val(r, "avg_pace_seconds_per_km") is not None
    ]

    high_confidence_pace = len(qualifying_runs) >= 2
    pace_debug: dict = {}

    if qualifying_runs:
        # Best (fastest) pace = lowest seconds per km.
        best_run = min(
            qualifying_runs,
            key=lambda r: float(_val(r, "avg_pace_seconds_per_km")),
        )
        threshold_pace = round(float(_val(best_run, "avg_pace_seconds_per_km")))
        hr = _val(best_run, "avg_hr_bpm")
        threshold_hr = round(float(hr)) if hr is not None else None

        pace_debug = {
            "duration_used": _val(best_run, "duration_seconds"),
            "raw_value": float(_val(best_run, "avg_pace_seconds_per_km")),
            "formula": (
                "fastest average pace from run efforts of 20–30 minutes duration "
                "(1 200 – 1 800 seconds)"
            ),
        }

        suggestions["threshold_pace_seconds_per_km"] = {
            "value": threshold_pace,
            "high_confidence": high_confidence_pace,
        }
        if threshold_hr is not None:
            suggestions["threshold_hr"] = {
                "value": threshold_hr,
                "high_confidence": high_confidence_pace,
            }

    debug["threshold_pace_seconds_per_km"] = pace_debug
    debug["threshold_hr"] = {
        "duration_used": pace_debug.get("duration_used"),
        "raw_value": suggestions.get("threshold_hr", {}).get("value"),
        "formula": (
            "average HR from the same run effort that produced the suggested "
            "threshold pace"
        ),
    }

    if not suggestions:
        return {"suggestions": {}, "reason": "not enough history yet"}

    # Return suggestions at the top level alongside debug.
    return {**suggestions, "debug": debug}
