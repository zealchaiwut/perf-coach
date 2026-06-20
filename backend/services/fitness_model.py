"""
Fitness / fatigue / form model — Banister CTL/ATL/TSB.

This module provides a single pure function, ``compute_fitness_series``, that
computes Chronic Training Load (CTL), Acute Training Load (ATL), and Training
Stress Balance (TSB) from a unified daily-load series.  All database work
belongs to the calling layer; this module contains no SQL and no side effects.

Math
----
CTL and ATL are exponential weighted moving averages (EWMAs) of daily load:

    new = prev + (load - prev) * alpha

where alpha is derived from the named time constant (CTL or ATL) via:

    alpha = 1 - exp(-1 / time_constant)

TSB for day N is the *previous* day's CTL minus the *previous* day's ATL
(the form the athlete carries *into* that day, before absorbing day N's load).
"""

from __future__ import annotations

import math

# ── EWMA time constants ───────────────────────────────────────────────────────
# Chronic Training Load time constant (days) — standard Banister value.
CTL_TIME_CONSTANT: int = 42
# Acute Training Load time constant (days) — must be less than CTL_TIME_CONSTANT.
ATL_TIME_CONSTANT: int = 7

# ── Readiness / TSB band constants ───────────────────────────────────────────
# Minimum TSB for the "Optimal" training band.
TSB_OPTIMAL_MIN: float = -10.0
# Minimum TSB for the "Fresh" (well-rested) band.
TSB_FRESH_MIN: float = 5.0

# ── Baseline history threshold ────────────────────────────────────────────────
# Minimum number of days of load history before the EWMA is considered
# representative.  Below this threshold building_baseline is True.
MIN_HISTORY_DAYS: int = 28


def compute_fitness_series(daily_load_series) -> dict:
    """Compute CTL, ATL, and TSB for each day in *daily_load_series*.

    This is a pure function: given the same input it always returns the same
    output, it performs no database access, and it never raises an unhandled
    exception.  The caller is responsible for fetching workouts and converting
    them to the unified daily-load format (e.g. via
    ``backend.services.daily_load.daily_load_series``).

    Parameters
    ----------
    daily_load_series:
        A list of dicts (the output of ``daily_load_series()``) where each
        dict has at minimum ``date`` (ISO-8601 string) and ``daily_load``
        (numeric; treated as 0 when absent or None).  The list should be
        ordered ascending by date.

    Returns
    -------
    dict with the following keys:

    ``days``
        Per-day list, one entry per input day, each containing:
        ``date``, ``ctl``, ``atl``, ``tsb``.  TSB for day N equals the
        *previous* day's CTL minus the *previous* day's ATL.

    ``summary``
        Dict with today's ``ctl``, ``atl``, ``tsb``, and a
        ``readiness_label`` string derived from ``TSB_FRESH_MIN`` and
        ``TSB_OPTIMAL_MIN``.  Uses the last day in the series.

    ``building_baseline``
        ``True`` when the input series is shorter than ``MIN_HISTORY_DAYS``;
        the EWMA values exist but are preliminary.

    ``reason``
        Empty string on success; a human-readable explanation when the
        input was invalid or when ``building_baseline`` is ``True``.

    ``debug``
        Dict containing the computed alpha values (``ctl_alpha``,
        ``atl_alpha``) and the seed values used to initialise the EWMAs
        (``ctl_seed``, ``atl_seed``).

    On any invalid input (None, empty list, or missing required columns) the
    function returns an empty result with a non-empty ``reason`` string.

    Worked example
    --------------
    A flat 50-per-day load series causes CTL and ATL to converge toward 50
    and TSB to converge toward 0.

    With CTL_TIME_CONSTANT = 42 and ATL_TIME_CONSTANT = 7:

    - alpha_ctl ≈ 0.0235, alpha_atl ≈ 0.1331
    - After ~200 days of load = 50, both EWMA values approach 50 because
      each day: new = prev + (50 − prev) * alpha → equilibrium at 50.
    - TSB on each day = CTL_yesterday − ATL_yesterday.  When both approach
      50, TSB approaches 50 − 50 = 0.

    Concrete check: after 200 days both CTL and ATL are within 1.0 of 50
    and TSB is within 1.0 of 0.
    """
    _empty = {
        "days": [],
        "summary": None,
        "building_baseline": False,
        "reason": "",
        "debug": None,
    }

    if not daily_load_series:
        return {**_empty, "reason": "daily_load_series is required and must be non-empty"}

    if not isinstance(daily_load_series, list):
        return {**_empty, "reason": "daily_load_series must be a list"}

    ctl_alpha = 1 - math.exp(-1 / CTL_TIME_CONSTANT)
    atl_alpha = 1 - math.exp(-1 / ATL_TIME_CONSTANT)

    ctl_seed = 0.0
    atl_seed = 0.0

    ctl = ctl_seed
    atl = atl_seed
    days = []

    for item in daily_load_series:
        if not isinstance(item, dict):
            return {**_empty, "reason": "each item in daily_load_series must be a dict"}
        raw_date = item.get("date")
        if raw_date is None:
            return {**_empty, "reason": "each item in daily_load_series must have a 'date' key"}
        load = item.get("daily_load") or 0
        try:
            load = float(load)
        except (TypeError, ValueError):
            load = 0.0

        tsb = ctl - atl
        ctl = ctl + (load - ctl) * ctl_alpha
        atl = atl + (load - atl) * atl_alpha

        days.append({
            "date": str(raw_date),
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "tsb": round(tsb, 2),
        })

    n = len(days)
    building_baseline = n < MIN_HISTORY_DAYS
    reason = (
        f"Only {n} day(s) of load history available; at least {MIN_HISTORY_DAYS} days "
        f"are needed for reliable fitness estimates."
        if building_baseline
        else ""
    )

    last = days[-1]
    readiness_label = _readiness_label(last["tsb"])

    summary = {
        "ctl": last["ctl"],
        "atl": last["atl"],
        "tsb": last["tsb"],
        "readiness_label": readiness_label,
    }

    debug = {
        "ctl_alpha": ctl_alpha,
        "atl_alpha": atl_alpha,
        "ctl_seed": ctl_seed,
        "atl_seed": atl_seed,
    }

    return {
        "days": days,
        "summary": summary,
        "building_baseline": building_baseline,
        "reason": reason,
        "debug": debug,
    }


def _readiness_label(tsb: float) -> str:
    """Classify TSB into a human-readable readiness band using named constants."""
    if tsb >= TSB_FRESH_MIN:
        return "Fresh"
    if tsb >= TSB_OPTIMAL_MIN:
        return "Optimal"
    return "Fatigued"
