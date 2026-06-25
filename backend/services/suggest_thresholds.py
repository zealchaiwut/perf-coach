"""Auto-threshold suggestion derived from an athlete's duration curve and recent runs.

This module exposes a single pure function, :func:`suggest_thresholds`, that
derives evidence-based threshold candidates from a user's own performance
history.  It performs **no** database access and has **no** side effects.
The calling layer is responsible for reading existing manual thresholds from
``user_preferences`` and passing them as plain data; a manually set threshold
always takes precedence and the corresponding suggestion is omitted entirely.

Worked example (FTP)
--------------------
Best 20-minute average power of 300 watts.
Multiply by 95 percent (0.95) → suggested FTP = 285 watts (high confidence).

Worked example (Pace / HR)
--------------------------
Two qualifying runs of 22 minutes and 25 minutes.
Best (lowest) average pace among qualifying runs → suggested threshold pace.
Average HR from that same run → suggested threshold HR.
If the best qualifying run has no HR data, threshold HR is omitted.

Worked example (Fallback FTP)
------------------------------
No 20-minute point but a 45-minute effort at 320 watts.
320 multiplied by 0.95 = 304 watts (low confidence — fallback window used).
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
    user_preferences: Optional[dict] = None,
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
        optionally ``avg_hr_bpm`` (int or None).  May be ``None`` or an empty
        list.
    user_preferences:
        Optional plain dict of manually set thresholds loaded by the caller from
        the database.  Recognised keys: ``ftp_w``, ``threshold_hr``,
        ``threshold_pace_seconds_per_km``.  When a key is present and non-None,
        the corresponding suggestion is omitted from the result — the manually
        set value always wins.  Passing ``None`` (the default) is equivalent to
        an empty dict (no manual overrides).

    Returns
    -------
    On success, a dict with the following keys:

    ``suggestions``
        Dict containing any or all of:
        ``ftp_w``, ``threshold_pace_seconds_per_km``, ``threshold_hr``.
        Each value is a dict with keys:
        ``value`` (number), ``high_confidence`` (bool, kept for compatibility),
        ``confidence`` (str: ``"high"`` or ``"low"``).

    ``debug``
        Dict keyed by suggestion name.  Each entry has:
        ``duration_used`` (int, seconds), ``raw_value`` (float, before
        multiplier), ``formula_applied`` (str, plain-English description of the
        arithmetic, e.g. "best 20-minute power multiplied by 0.95").

    When there is not enough data to produce any suggestion, returns::

        {"suggestions": {}, "reason": "not enough history yet"}

    Worked examples
    ---------------
    300 W best 20-minute power → FTP = 285 W (300 × 0.95), high confidence.
    No 20-minute point but 320 W at 45 minutes → FTP = 304 W (320 × 0.95),
    low confidence (fallback: best effort in the 20–60 minute window).
    """
    # Guard: treat None inputs the same as empty containers.
    if not duration_curve and not recent_runs:
        return {"suggestions": {}, "reason": "not enough history yet"}

    curve = duration_curve or {}
    runs = recent_runs or []
    prefs = user_preferences or {}

    suggestions: dict = {}
    debug: dict = {}

    # ── Power / FTP ────────────────────────────────────────────────────────────
    if _pref_not_set(prefs, "ftp_w"):
        ftp_result = _suggest_ftp(curve)
        if ftp_result is not None:
            suggestion, dbg = ftp_result
            suggestions["ftp_w"] = suggestion
            debug["ftp_w"] = dbg

    # ── Pace and HR ───────────────────────────────────────────────────────────
    pace_overridden = not _pref_not_set(prefs, "threshold_pace_seconds_per_km")
    hr_overridden = not _pref_not_set(prefs, "threshold_hr")

    if not pace_overridden:
        pace_hr_result = _suggest_pace_and_hr(runs)
        if pace_hr_result is not None:
            pace_sug, hr_sug, pace_dbg, hr_dbg = pace_hr_result
            suggestions["threshold_pace_seconds_per_km"] = pace_sug
            debug["threshold_pace_seconds_per_km"] = pace_dbg
            if hr_sug is not None and not hr_overridden:
                suggestions["threshold_hr"] = hr_sug
                debug["threshold_hr"] = hr_dbg

    if not suggestions:
        return {"suggestions": {}, "reason": "not enough history yet"}

    return {"suggestions": suggestions, "debug": debug}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _pref_not_set(prefs: dict, key: str) -> bool:
    """Return True when the caller has NOT set a manual override for this key."""
    return prefs.get(key) is None


def _confidence(high: bool) -> str:
    """Map a boolean confidence flag to the canonical string label."""
    return "high" if high else "low"


def _suggest_ftp(curve: dict):
    """Return (suggestion_dict, debug_dict) for FTP, or None if no data qualifies.

    Primary window: 20 minutes exactly (1200 seconds).
    Multiply 20-minute best power by 95 percent to estimate FTP.

    Fallback window: any effort whose duration falls between 20 and 60 minutes
    (1200–3600 seconds, both inclusive).  The best (highest) power in that range
    is selected and the same 95 percent multiplier is applied; confidence is
    set to "low" (high_confidence False).
    """
    if not curve:
        return None

    # Primary: exact 20-minute key present?
    if _20_MIN in curve and curve[_20_MIN] is not None:
        raw = float(curve[_20_MIN])
        # Multiply by 95 percent to derive FTP from 20-minute best power.
        ftp_value = raw * _FTP_MULTIPLIER
        return (
            {"value": ftp_value, "high_confidence": True, "confidence": "high"},
            {
                "duration_used": _20_MIN,
                "raw_value": raw,
                "formula_applied": "best 20-minute power multiplied by 0.95",
            },
        )

    # Fallback: best power in the 20–60 minute window.  Both endpoints are
    # inclusive.  The same 95 percent multiplier is applied.
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
        {"value": ftp_value, "high_confidence": False, "confidence": "low"},
        {
            "duration_used": best_dur,
            "raw_value": raw,
            "formula_applied": (
                f"best power in 20–60 minute range "
                f"(at {best_dur // 60} min) multiplied by 0.95"
            ),
        },
    )


def _suggest_pace_and_hr(runs: list):
    """Return (pace_sug, hr_sug, pace_dbg, hr_dbg) or None if no runs qualify.

    Qualifying runs: duration between 1200 s and 1800 s inclusive (20–30 min)
    with a non-None avg_pace_seconds_per_km.  HR data is optional — if the
    best-pace run has no HR, hr_sug is returned as None.

    Suggested threshold pace = best (lowest) average pace among qualifying runs.
    Suggested threshold HR = average HR recorded during that same run effort, or
    None when HR is absent for that run.

    confidence (and high_confidence) = "high" (True) only when at least two
    qualifying runs are found.
    """
    qualifying = [
        r for r in runs
        if _run_val(r, "duration_seconds") is not None
        and _PACE_MIN <= int(_run_val(r, "duration_seconds")) <= _PACE_MAX
        and _run_val(r, "avg_pace_seconds_per_km") is not None
    ]
    if not qualifying:
        return None

    high_confidence = len(qualifying) >= 2
    conf_str = _confidence(high_confidence)

    # Best pace = lowest seconds per km (fastest speed).
    best_run = min(qualifying, key=lambda r: float(_run_val(r, "avg_pace_seconds_per_km")))
    best_pace = float(_run_val(best_run, "avg_pace_seconds_per_km"))
    dur_used = int(_run_val(best_run, "duration_seconds"))

    pace_sug = {"value": best_pace, "high_confidence": high_confidence, "confidence": conf_str}

    pace_dbg = {
        "duration_used": dur_used,
        "raw_value": best_pace,
        "formula_applied": "fastest (lowest seconds per km) average pace among qualifying 20–30 min run efforts",
    }

    # HR is optional: present only when the selected run has HR data.
    hr_raw = _run_val(best_run, "avg_hr_bpm")
    if hr_raw is not None:
        hr_sug = {"value": int(hr_raw), "high_confidence": high_confidence, "confidence": conf_str}
        hr_dbg = {
            "duration_used": dur_used,
            "raw_value": int(hr_raw),
            "formula_applied": "average HR from the same run effort that produced the threshold pace",
        }
    else:
        hr_sug = None
        hr_dbg = None

    return pace_sug, hr_sug, pace_dbg, hr_dbg


def _run_val(run_obj, key):
    """Get a field from a dict or ORM-like run object."""
    if run_obj is None:
        return None
    if isinstance(run_obj, dict):
        return run_obj.get(key)
    return getattr(run_obj, key, None)
