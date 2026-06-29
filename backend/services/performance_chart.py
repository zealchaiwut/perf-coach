"""Performance chart time-series computation (issue #703).

compute_performance_chart is the pure core: it accepts pre-fetched daily
load data, pre-classified run data, user preferences, and a date range,
then returns five aligned time-series arrays (CTL, ATL, TSB, endurance
score, speed score) with no database access.

The caller layer (the endpoint handler in main.py) is responsible for all
database work: fetching workouts, splits, lap classifications, and user
preferences before calling this function.

Response shape (normal)
-----------------------
{
    "dates": ["2026-01-01", "2026-01-02", ...],
    "ctl": [12.5, 13.0, ...],
    "atl": [10.0, 11.0, ...],
    "tsb": [2.5, 2.0, ...],
    "endurance_score": [null, 45.5, null, ...],
    "speed_score": [null, null, 60.0, ...],
    "building_baseline": false,
    "reason": ""
}

Response shape (empty — athlete not found / invalid dates / no data)
----------------------------------------------------------------------
{
    "dates": [], "ctl": [], "atl": [], "tsb": [],
    "endurance_score": [], "speed_score": [],
    "building_baseline": false,
    "reason": "athlete_not_found"
}

Worked example
--------------
Given three days of load data (TSS 50, 60, 0) and one easy run on day 2:

    fitness model output:
        day 1: ctl=1.17, atl=6.27, tsb=0.0
        day 2: ctl=2.33, atl=11.89, tsb=−5.10
        day 3: ctl=2.27, atl=11.07, tsb=−9.56

    endurance_score: [null, 50.0, null]   (only day 2 has a qualifying run)
    speed_score:     [null, null, null]   (no hard/interval laps → building_baseline)
    building_baseline: true               (fewer than MIN_HISTORY_DAYS days loaded)

All thresholds (MIN_HISTORY_DAYS, MIN_QUALIFYING_RUNS) are read from
fitness_model.MIN_HISTORY_DAYS and zone_constants.MIN_QUALIFYING_RUNS —
nothing is hardcoded in this module.
"""

from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta
from typing import Any

from backend.services.fitness_model import compute_fitness_series, MIN_HISTORY_DAYS
from backend.services.running_performance import (
    compute_endurance_score,
    compute_speed_score,
    _qualifying_laps,
)
from backend.services.zone_constants import make_zone_constants


def compute_performance_chart(
    daily_load_series: list[dict],
    runs: list[dict],
    preferences: dict[str, Any] | None,
    zone_constants: dict[str, Any] | None,
    start_date: str,
    end_date: str,
) -> dict:
    """Compute aligned CTL/ATL/TSB/endurance/speed time series for a date range.

    This is a pure function: no I/O, no side effects.

    Parameters
    ----------
    daily_load_series:
        Output of ``backend.services.daily_load.daily_load_series()``.
        Should span from at least MIN_HISTORY_DAYS before ``start_date``
        through ``end_date`` so the fitness EWMA has time to warm up.
        Each dict must have ``date`` (ISO-8601 string) and ``daily_load``
        (numeric).

    runs:
        List of run dicts ordered chronologically, each with:
        - ``run_id``: identifier (any hashable value, typically str/UUID)
        - ``run_date``: ISO-8601 date string (e.g. "2026-06-01")
        - ``laps``: list of lap dicts, each with ``band`` (str), ``avg_hr``
          (float|None), ``avg_power`` (float|None), ``distance_km``
          (float|None), ``duration_seconds`` (float|None)
        - ``decoupling_pct``: float or None (for endurance durability factor)

    preferences:
        User preferences dict.  May include ``duration_curve_bests`` for
        speed score anchoring.  Pass ``None`` when unavailable — scores will
        return a missing-input shape.

    zone_constants:
        Output of ``make_zone_constants()``.  Pass ``None`` to use defaults.

    start_date, end_date:
        ISO-8601 date strings for the requested output range (inclusive).
        The ``daily_load_series`` may extend before ``start_date`` for
        EWMA warmup; only [start_date, end_date] is included in the output.

    Returns
    -------
    dict with keys: dates, ctl, atl, tsb, endurance_score, speed_score,
    building_baseline, reason.
    """
    zc = make_zone_constants() if zone_constants is None else zone_constants
    endurance_bands = zc["endurance_bands"]
    speed_bands = zc["speed_bands"]
    min_qualifying = zc["min_qualifying_runs"]

    # Parse requested output range
    try:
        d_start = _date.fromisoformat(start_date)
        d_end = _date.fromisoformat(end_date)
    except (ValueError, TypeError):
        return _empty("invalid_date_range")

    # Filter full daily_load_series through fitness model
    fitness_result = compute_fitness_series(daily_load_series)
    fitness_by_date: dict[str, dict] = {
        row["date"]: row for row in fitness_result.get("days", [])
    }

    # Build the date spine for the requested range
    dates: list[str] = []
    d = d_start
    while d <= d_end:
        dates.append(str(d))
        d += _timedelta(days=1)

    if not dates:
        return _empty("no_data_in_range")

    # Assemble CTL/ATL/TSB arrays for the requested range
    ctl_arr: list[float | None] = []
    atl_arr: list[float | None] = []
    tsb_arr: list[float | None] = []
    for ds in dates:
        row = fitness_by_date.get(ds)
        if row is None:
            ctl_arr.append(None)
            atl_arr.append(None)
            tsb_arr.append(None)
        else:
            ctl_arr.append(row["ctl"])
            atl_arr.append(row["atl"])
            tsb_arr.append(row["tsb"])

    # Check building_baseline for the CTL/ATL/TSB series only.
    # building_baseline is True when:
    #   (a) the fitness model has fewer than MIN_HISTORY_DAYS of history, OR
    #   (b) the load series contains no non-zero load (brand-new athlete).
    # Endurance/speed score availability does NOT affect this flag — the Fitness
    # Fatigue Form chart (CTL/ATL/TSB) can render independently of scoring readiness.
    n_history = len(fitness_result.get("days", []))
    fitness_model_baseline = fitness_result.get("building_baseline", True) or n_history < MIN_HISTORY_DAYS
    has_any_load = any(
        float(row.get("daily_load") or 0) > 0
        for row in (daily_load_series or [])
        if isinstance(row, dict)
    )
    building_baseline = fitness_model_baseline or not has_any_load

    # Filter runs to the requested date range
    range_runs = [
        r for r in (runs or [])
        if d_start <= _date.fromisoformat(str(r["run_date"])) <= d_end
    ]

    # Compute endurance and speed scores via the existing pure functions
    endurance_result = compute_endurance_score(range_runs, preferences, zc)
    speed_result = compute_speed_score(range_runs, preferences, zc)

    # Map per-run trend values back to calendar dates.
    # The trend array is ordered by qualifying-run order (same as input runs).
    # We identify qualifying runs by replicating the band-filter the score
    # function applies (without touching the score function's internals).
    endurance_by_date = _map_trend_to_dates(
        range_runs, endurance_result, endurance_bands
    )
    speed_by_date = _map_trend_to_dates(
        range_runs, speed_result, speed_bands
    )

    endurance_arr = [endurance_by_date.get(ds) for ds in dates]
    speed_arr = [speed_by_date.get(ds) for ds in dates]

    # Determine overall reason string
    reason = ""
    if building_baseline:
        reason = (
            f"Training history is too short for stable estimates "
            f"(need at least {MIN_HISTORY_DAYS} days of load history "
            f"and {min_qualifying} qualifying runs)."
        )

    # no_data_in_range: all CTL values are None (no load data in range)
    if all(v is None for v in ctl_arr):
        return _empty("no_data_in_range")

    return {
        "dates": dates,
        "ctl": ctl_arr,
        "atl": atl_arr,
        "tsb": tsb_arr,
        "endurance_score": endurance_arr,
        "speed_score": speed_arr,
        "building_baseline": building_baseline,
        "reason": reason,
    }


def _map_trend_to_dates(
    runs: list[dict],
    score_result: dict,
    bands: list[str],
) -> dict[str, float | None]:
    """Map a score function's trend array back to calendar dates.

    The trend is ordered by qualifying-run order (same as input).  We
    identify qualifying runs by applying the same band filter the score
    functions use, then pair trend[i] with qualifying_run[i]["run_date"].

    When multiple qualifying runs fall on the same date the last one's
    value is used (most recent within the day).
    """
    if not isinstance(score_result, dict):
        return {}

    trend = score_result.get("trend")
    if not trend:
        return {}

    # Identify qualifying runs (those that have at least one lap in bands)
    qualifying_dates: list[str] = []
    for run in runs:
        laps = _qualifying_laps(run.get("laps") or [], bands)
        if laps:
            qualifying_dates.append(str(run["run_date"]))

    # Pair trend values with dates
    by_date: dict[str, float] = {}
    for ds, value in zip(qualifying_dates, trend):
        by_date[ds] = round(float(value), 2)

    return by_date


def _empty(reason: str) -> dict:
    """Return the canonical empty response payload."""
    return {
        "dates": [],
        "ctl": [],
        "atl": [],
        "tsb": [],
        "endurance_score": [],
        "speed_score": [],
        "building_baseline": False,
        "reason": reason,
    }
