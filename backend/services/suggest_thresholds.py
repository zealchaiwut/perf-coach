"""Auto-threshold suggestion derived from an athlete's duration curve and recent runs.

This module exposes a single pure function, :func:`suggest_thresholds`, that
derives evidence-based threshold candidates from a user's own performance
history.  It performs **no** database access and has **no** side effects.
The calling layer is responsible for reading existing manual thresholds from
``user_preferences`` and deciding whether to surface a suggestion; a manually
set threshold always takes precedence over any suggestion from this function.

Worked example (FTP)
--------------------
Best 20-minute average power of 300 watts.
Multiply by 95 percent → suggested FTP = 285 watts (high confidence).

Worked example (Pace / HR)
--------------------------
Two qualifying runs of 22 minutes and 25 minutes.
Best (lowest) average pace among qualifying runs → suggested threshold pace.
Average HR from that same run → suggested threshold HR.
"""
from __future__ import annotations

from typing import Optional

# ── Duration constants (seconds) ──────────────────────────────────────────────

_20_MIN = 1200   # 20 minutes in seconds — primary FTP window
_60_MIN = 3600   # 60 minutes in seconds — upper bound of FTP fallback window

# Qualifying pace/HR window: roughly 20–30 minutes inclusive
_PACE_MIN = 1200   # 20 minutes in seconds (lower bound, inclusive)
_PACE_MAX = 1800   # 30 minutes in seconds (upper bound, inclusive)

# The FTP multiplier: best 20-minute (or fallback) power × 0.95 = FTP estimate.
# Source: Coggan's CP20 field-test protocol; multiply 20-min power by 95 percent
# to approximate functional threshold power.
_FTP_MULTIPLIER = 0.95


# ── Public API ────────────────────────────────────────────────────────────────

def suggest_thresholds(
    duration_curve: Optional[dict],
    recent_runs: Optional[list],
) -> dict:
    """Derive threshold suggestions from a duration curve and recent run history.

    This is a pure function: it reads only the arguments supplied, performs no
    I/O, and raises no exceptions for missing or empty data.

    Parameters
    ----------
    duration_curve:
        Mapping of duration-in-seconds (int) to best average power in watts
        (float).  May be ``None`` or an empty dict.
    recent_runs:
        List of run objects.  Each object must contain (as dict keys)
        ``duration_seconds`` (int), ``avg_pace_seconds_per_km`` (float), and
        ``avg_hr_bpm`` (int).  May be ``None`` or an empty list.

    Returns
    -------
    On success, a dict with the following keys:

    ``suggestions``
        Dict containing any or all of:
        ``ftp_w``, ``threshold_pace_seconds_per_km``, ``threshold_hr``.
        Each value is ``{"value": <number>, "high_confidence": <bool>}``.

    ``debug``
        Dict keyed by suggestion name.  Each entry has:
        ``duration_used`` (int, seconds), ``raw_value`` (float, before
        multiplier), ``formula_applied`` (str, plain-English description).

    When there is not enough data to produce any suggestion, returns::

        {"suggestions": {}, "reason": "not enough history yet"}

    Worked examples
    ---------------
    300 W best 20-minute power → FTP = 285 W (300 × 0.95), high confidence.
    No 20-minute point but 320 W at 45 minutes → FTP = 304 W (320 × 0.95), low confidence.
    """
    # Guard: treat None inputs the same as empty containers.
    if not duration_curve and not recent_runs:
        return {"suggestions": {}, "reason": "not enough history yet"}

    curve = duration_curve or {}
    runs = recent_runs or []

    suggestions: dict = {}
    debug: dict = {}

    # ── Power / FTP ────────────────────────────────────────────────────────────
    ftp_result = _suggest_ftp(curve)
    if ftp_result is not None:
        suggestion, dbg = ftp_result
        suggestions["ftp_w"] = suggestion
        debug["ftp_w"] = dbg

    # ── Pace and HR ───────────────────────────────────────────────────────────
    pace_hr_result = _suggest_pace_and_hr(runs)
    if pace_hr_result is not None:
        pace_sug, hr_sug, pace_dbg, hr_dbg = pace_hr_result
        suggestions["threshold_pace_seconds_per_km"] = pace_sug
        suggestions["threshold_hr"] = hr_sug
        debug["threshold_pace_seconds_per_km"] = pace_dbg
        debug["threshold_hr"] = hr_dbg

    if not suggestions:
        return {"suggestions": {}, "reason": "not enough history yet"}

    return {"suggestions": suggestions, "debug": debug}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _suggest_ftp(curve: dict):
    """Return (suggestion_dict, debug_dict) for FTP, or None if no data qualifies.

    Primary window: 20 minutes exactly (1200 seconds).
    Multiply 20-minute best power by 95 percent to estimate FTP.

    Fallback window: any effort whose duration falls between 20 and 60 minutes
    (1200–3600 seconds, both inclusive).  The best (highest) power in that range
    is selected and the same 95 percent multiplier is applied; high_confidence
    is set to False.
    """
    if not curve:
        return None

    # Primary: exact 20-minute key present?
    if _20_MIN in curve and curve[_20_MIN] is not None:
        raw = float(curve[_20_MIN])
        # Multiply by 95 percent to derive FTP from 20-minute best power.
        ftp_value = raw * _FTP_MULTIPLIER
        return (
            {"value": ftp_value, "high_confidence": True},
            {
                "duration_used": _20_MIN,
                "raw_value": raw,
                "formula_applied": "best 20-minute power multiplied by 95 percent",
            },
        )

    # Fallback: best power in the 20–60 minute window (excluding the 20-min key
    # which was already checked above).  Both endpoints are inclusive.
    candidates = {
        dur: pwr
        for dur, pwr in curve.items()
        if _20_MIN <= dur <= _60_MIN and pwr is not None
    }
    if not candidates:
        return None

    best_dur = max(candidates, key=lambda d: candidates[d])
    raw = float(candidates[best_dur])
    # Multiply by 95 percent — same formula as the 20-minute path.
    ftp_value = raw * _FTP_MULTIPLIER
    return (
        {"value": ftp_value, "high_confidence": False},
        {
            "duration_used": best_dur,
            "raw_value": raw,
            "formula_applied": (
                f"best power in 20–60 minute range "
                f"(at {best_dur // 60} min) multiplied by 95 percent"
            ),
        },
    )


def _suggest_pace_and_hr(runs: list):
    """Return (pace_sug, hr_sug, pace_dbg, hr_dbg) or None if no runs qualify.

    Qualifying runs: duration between 1200 s and 1800 s inclusive (20–30 min).
    Suggested threshold pace = best (lowest) average pace among qualifying runs.
    Suggested threshold HR = average HR recorded during that same run effort.
    high_confidence = True only when at least two qualifying runs are found.
    """
    qualifying = [
        r for r in runs
        if _run_val(r, "duration_seconds") is not None
        and _PACE_MIN <= int(_run_val(r, "duration_seconds")) <= _PACE_MAX
        and _run_val(r, "avg_pace_seconds_per_km") is not None
        and _run_val(r, "avg_hr_bpm") is not None
    ]
    if not qualifying:
        return None

    high_confidence = len(qualifying) >= 2

    # Best pace = lowest seconds per km (fastest speed).
    best_run = min(qualifying, key=lambda r: float(_run_val(r, "avg_pace_seconds_per_km")))
    best_pace = float(_run_val(best_run, "avg_pace_seconds_per_km"))
    best_hr = int(_run_val(best_run, "avg_hr_bpm"))
    dur_used = int(_run_val(best_run, "duration_seconds"))

    pace_sug = {"value": best_pace, "high_confidence": high_confidence}
    hr_sug = {"value": best_hr, "high_confidence": high_confidence}

    label = "fastest (lowest seconds per km)"
    pace_dbg = {
        "duration_used": dur_used,
        "raw_value": best_pace,
        "formula_applied": f"{label} average pace among qualifying 20–30 min run efforts",
    }
    hr_dbg = {
        "duration_used": dur_used,
        "raw_value": best_hr,
        "formula_applied": "average HR from the same run effort that produced the threshold pace",
    }
    return pace_sug, hr_sug, pace_dbg, hr_dbg


def _run_val(run_obj, key):
    """Get a field from a dict or ORM-like run object."""
    if run_obj is None:
        return None
    if isinstance(run_obj, dict):
        return run_obj.get(key)
    return getattr(run_obj, key, None)
