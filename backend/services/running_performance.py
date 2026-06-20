"""Endurance and Speed running performance scores (issue #701).

compute_endurance_score and compute_speed_score are pure functions.
They accept pre-assembled run data, user preferences, and zone constants,
then return a normalised score object.  No database access occurs inside
this module — all I/O is performed by the caller layer in the endpoint.

Response shapes
---------------
Normal score result::

    {
        "score": 72.5,              # float, 0–100
        "direction": "improving",   # "improving" | "flat" | "declining"
        "trend": [55.0, 62.0, 72.5],  # score history, oldest first
        "debug": {
            "perRunEfficiency": {"run_id_1": 1.75, "run_id_2": 1.80},
        }
    }

Building-baseline result (fewer than min qualifying runs)::

    {"state": "building_baseline", "reason": "Need at least 3 qualifying runs; 2 found."}

Missing-input result (None or malformed preferences / zone constants)::

    {"score": None, "reason": "missing: preferences not provided"}

Score computation — Endurance
------------------------------
1. Filter each run to laps whose band is in zone_constants["endurance_bands"]
   (default: easy, steady).  A run qualifies when it contains at least one
   such lap.
2. Compute per-run efficiency on those laps using duration-weighted averages
   of power/HR (power path) or speed/HR (speed path when power is absent).
   Efficiency formula power path: avg_power / avg_hr
   Efficiency formula speed path: (1 / pace_min_per_km) / avg_hr
3. Compute per-run durability from decoupling_pct when it is available.
   Durability factor = max(0, 1 − decoupling_pct / 50).  A perfectly durable
   run (0% decoupling) has factor 1.0; heavy fade (50%+ decoupling) has 0.0.
4. Adjusted efficiency = efficiency × durability_factor.  When decoupling is
   absent for a run, durability_factor defaults to 1.0 (no adjustment).
5. Normalise adjusted efficiency values to 0–100 using the athlete's own
   historical range (min/max across qualifying runs).  When all values are
   equal, every run scores 50.
6. score = most-recent score in the normalised trend.
   direction = slope derived from the last three trend values vs.
   zone_constants["direction_slope_threshold"].

Score computation — Speed
--------------------------
1. Filter to laps in zone_constants["speed_bands"] (default: hard, interval).
2. Compute per-run efficiency on those laps (same formula as endurance).
3. If preferences["duration_curve_bests"] contains a matching duration entry:
   a. Find the duration-curve best whose duration_seconds is closest to the
      average hard-lap duration for that run.
   b. Compute proximity = run_avg_power / best_value, capped at 1.0.
      (Proximity measures how close the run's power is to the athlete's
      all-time best at that duration.)
   c. adjusted_efficiency = efficiency × (0.5 + 0.5 × proximity).
      (Efficiency is scaled upward when the run approaches the curve best.)
   When no curve bests are available, adjusted_efficiency = efficiency.
4. Normalise and derive score/direction/trend as in the endurance algorithm.
5. The debug object always includes "durationCurveBestUsed" (None when not
   applicable).

Worked example — Endurance with decoupling
-------------------------------------------
Three easy runs, efficiencies [1.50, 1.55, 1.60], decoupling [8%, 5%, 3%]:

    durability factors:  [0.84, 0.90, 0.94]
    adjusted:            [1.26, 1.395, 1.504]
    min=1.26, max=1.504
    normalised:          [0.0, 57.4, 100.0]
    trend:               [0.0, 57.4, 100.0]
    score:               100.0
    direction:           "improving"

Worked example — Speed with duration-curve best
-------------------------------------------------
One hard lap per run (duration=300s), efficiencies [1.80, 1.90, 2.00].
Curve best at 300s: best_value=300W.  Run avg_powers: [270, 285, 300].

    proximities:         [0.90, 0.95, 1.00]
    adjusted:            [1.80×0.95, 1.90×0.975, 2.00×1.00]
                       = [1.71, 1.8525, 2.00]
    min=1.71, max=2.00
    normalised:          [0.0, 49.1, 100.0]
    score:               100.0
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_endurance_score(
    runs: list[dict] | None,
    preferences: dict[str, Any] | None,
    zone_constants: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute endurance performance score from easy/steady run data.

    Parameters
    ----------
    runs : list[dict] or None
        List of run dicts (see module docstring for per-run key contract).
        None or empty list triggers the building_baseline state.
    preferences : dict or None
        User preferences from the database.  Must be a non-None dict to
        proceed to score computation; None returns score: null.
    zone_constants : dict or None
        Zone band config from make_zone_constants().  Falls back to module
        defaults when None.

    Returns
    -------
    dict
        One of three shapes — see module docstring.
    """
    zc = _resolve_zone_constants(zone_constants)

    if preferences is None:
        return {"score": None, "reason": "missing: preferences not provided"}
    if not isinstance(preferences, dict):
        return {"score": None, "reason": "missing: preferences must be a dict"}

    runs = runs or []
    bands = zc["endurance_bands"]

    # Filter to qualifying runs and compute per-run efficiency with durability
    qualifying: list[tuple[str, float]] = []  # (run_id, adjusted_efficiency)
    per_run_efficiency: dict[str, float] = {}

    for run in runs:
        run_id = run.get("run_id", "")
        laps = _qualifying_laps(run.get("laps") or [], bands)
        if not laps:
            continue

        eff, reason = _efficiency_from_laps(laps)
        if eff is None:
            continue  # insufficient data for this run

        # Durability adjustment: multiply efficiency by durability_factor
        # A run with low decoupling is more durable and earns a higher score
        decoupling_pct = run.get("decoupling_pct")
        if isinstance(decoupling_pct, (int, float)) and not isinstance(decoupling_pct, bool):
            # Clamp to [0, 50]: 0% decoupling → factor 1.0; 50%+ → factor 0.0
            clamped = max(0.0, min(float(decoupling_pct), 50.0))
            durability_factor = 1.0 - clamped / 50.0
        else:
            durability_factor = 1.0  # no decoupling data; assume fully durable

        adjusted = eff * durability_factor
        per_run_efficiency[run_id] = round(eff, 6)
        qualifying.append((run_id, adjusted))

    min_runs = zc["min_qualifying_runs"]
    if len(qualifying) < min_runs:
        found = len(qualifying)
        return {
            "state": "building_baseline",
            "reason": (
                f"Need at least {min_runs} qualifying easy/steady runs; "
                f"{found} found."
            ),
        }

    trend = _normalise_to_trend(qualifying)
    direction = _compute_direction(trend, zc["direction_slope_threshold"])
    score = trend[-1]

    return {
        "score": round(score, 2),
        "direction": direction,
        "trend": [round(v, 2) for v in trend],
        "debug": {
            "perRunEfficiency": per_run_efficiency,
        },
    }


def compute_speed_score(
    runs: list[dict] | None,
    preferences: dict[str, Any] | None,
    zone_constants: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute speed performance score from hard/interval run data.

    Parameters
    ----------
    runs : list[dict] or None
        List of run dicts.  None or empty list triggers building_baseline.
    preferences : dict or None
        User preferences dict.  When it contains the key
        ``"duration_curve_bests"`` (a dict keyed by str(duration_seconds)),
        that curve is used as the reference baseline for speed scoring.
    zone_constants : dict or None
        Zone band config from make_zone_constants().  Falls back to module
        defaults when None.

    Returns
    -------
    dict
        One of three shapes — see module docstring.
    """
    zc = _resolve_zone_constants(zone_constants)

    if preferences is None:
        return {"score": None, "reason": "missing: preferences not provided"}
    if not isinstance(preferences, dict):
        return {"score": None, "reason": "missing: preferences must be a dict"}

    runs = runs or []
    bands = zc["speed_bands"]
    curve_bests = preferences.get("duration_curve_bests") or {}

    qualifying: list[tuple[str, float]] = []  # (run_id, adjusted_efficiency)
    per_run_efficiency: dict[str, float] = {}
    curve_best_used: dict | None = None

    for run in runs:
        run_id = run.get("run_id", "")
        laps = _qualifying_laps(run.get("laps") or [], bands)
        if not laps:
            continue

        eff, reason = _efficiency_from_laps(laps)
        if eff is None:
            continue

        # Duration-curve best adjustment: compare run's average power against
        # the athlete's all-time best power at the same duration window.
        adjusted = eff
        if curve_bests:
            avg_duration = _avg_lap_duration(laps)
            best_entry, best_duration = _find_closest_curve_entry(curve_bests, avg_duration)
            if best_entry is not None:
                best_value = best_entry.get("best_value")
                avg_power = _avg_lap_power(laps)
                if best_value and best_value > 0 and avg_power and avg_power > 0:
                    # proximity = fraction of best power achieved; capped at 1.0
                    proximity = min(1.0, avg_power / best_value)
                    # Scale efficiency up as athlete approaches curve best:
                    # factor = 0.5 + 0.5 × proximity
                    # (ranges from 0.5 when power is zero to 1.0 when at best)
                    adjusted = eff * (0.5 + 0.5 * proximity)
                    if curve_best_used is None:
                        curve_best_used = {
                            "duration_seconds": best_duration,
                            "best_value": best_value,
                        }

        per_run_efficiency[run_id] = round(eff, 6)
        qualifying.append((run_id, adjusted))

    min_runs = zc["min_qualifying_runs"]
    if len(qualifying) < min_runs:
        found = len(qualifying)
        return {
            "state": "building_baseline",
            "reason": (
                f"Need at least {min_runs} qualifying hard/interval runs; "
                f"{found} found."
            ),
        }

    trend = _normalise_to_trend(qualifying)
    direction = _compute_direction(trend, zc["direction_slope_threshold"])
    score = trend[-1]

    return {
        "score": round(score, 2),
        "direction": direction,
        "trend": [round(v, 2) for v in trend],
        "debug": {
            "perRunEfficiency": per_run_efficiency,
            "durationCurveBestUsed": curve_best_used,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_zone_constants(zone_constants: dict | None) -> dict:
    """Return zone_constants or the module-level defaults when None is passed."""
    from backend.services.zone_constants import make_zone_constants
    if zone_constants is None:
        return make_zone_constants()
    return zone_constants


def _qualifying_laps(laps: list[dict], bands: list[str]) -> list[dict]:
    """Return only those laps whose band appears in the allowed band list."""
    return [lap for lap in laps if lap.get("band") in bands]


def _efficiency_from_laps(laps: list[dict]) -> tuple[float | None, str | None]:
    """Compute duration-weighted efficiency for a list of laps.

    Returns (efficiency, None) on success, (None, reason) on failure.

    Power path: duration-weighted avg_power divided by duration-weighted avg_hr.
    Speed path: total_distance / total_duration_minutes divided by avg_hr, which
                equals (1 / pace_min_per_km) / avg_hr.
    """
    valid = [
        lap for lap in laps
        if isinstance(lap.get("duration_seconds"), (int, float))
        and lap["duration_seconds"] > 0
    ]
    if not valid:
        return None, "no laps with valid duration_seconds"

    total_dur = sum(float(lap["duration_seconds"]) for lap in valid)

    # All laps must have positive avg_hr
    if any(
        not isinstance(lap.get("avg_hr"), (int, float))
        or isinstance(lap.get("avg_hr"), bool)
        or lap["avg_hr"] <= 0
        for lap in valid
    ):
        return None, "missing: avg_hr on one or more laps"

    weighted_hr = (
        sum(float(lap["avg_hr"]) * float(lap["duration_seconds"]) for lap in valid) / total_dur
    )

    # Power path: all laps must have positive avg_power
    if all(
        isinstance(lap.get("avg_power"), (int, float))
        and not isinstance(lap.get("avg_power"), bool)
        and lap["avg_power"] > 0
        for lap in valid
    ):
        weighted_power = (
            sum(float(lap["avg_power"]) * float(lap["duration_seconds"]) for lap in valid) / total_dur
        )
        return round(weighted_power / weighted_hr, 6), None

    # Speed path: total distance divided by total duration in minutes gives km/min,
    # then divided by avg_hr gives efficiency in km / (min × bpm)
    if all(
        isinstance(lap.get("distance_km"), (int, float))
        and not isinstance(lap.get("distance_km"), bool)
        and lap["distance_km"] > 0
        for lap in valid
    ):
        total_dist = sum(float(lap["distance_km"]) for lap in valid)
        total_dur_min = total_dur / 60.0
        if total_dur_min <= 0 or weighted_hr <= 0:
            return None, "zero duration or HR"
        speed = total_dist / total_dur_min  # km/min
        return round(speed / weighted_hr, 6), None

    return None, "missing: avg_power or distance_km on laps"


def _avg_lap_duration(laps: list[dict]) -> float:
    """Return the average duration in seconds across laps."""
    durations = [
        float(lap["duration_seconds"])
        for lap in laps
        if isinstance(lap.get("duration_seconds"), (int, float)) and lap["duration_seconds"] > 0
    ]
    if not durations:
        return 0.0
    return sum(durations) / len(durations)


def _avg_lap_power(laps: list[dict]) -> float | None:
    """Return the duration-weighted average power across laps, or None."""
    valid = [
        lap for lap in laps
        if isinstance(lap.get("avg_power"), (int, float))
        and not isinstance(lap.get("avg_power"), bool)
        and lap["avg_power"] > 0
        and isinstance(lap.get("duration_seconds"), (int, float))
        and lap["duration_seconds"] > 0
    ]
    if not valid:
        return None
    total_dur = sum(float(lap["duration_seconds"]) for lap in valid)
    return sum(float(lap["avg_power"]) * float(lap["duration_seconds"]) for lap in valid) / total_dur


def _find_closest_curve_entry(
    curve_bests: dict,
    target_duration: float,
) -> tuple[dict | None, int | None]:
    """Find the curve entry closest to target_duration in seconds.

    Returns (entry_dict, duration_seconds) or (None, None) when curve is empty.
    """
    if not curve_bests or target_duration <= 0:
        return None, None

    best_key = None
    best_diff = float("inf")
    for key in curve_bests:
        try:
            dur = int(key)
        except (ValueError, TypeError):
            continue
        diff = abs(dur - target_duration)
        if diff < best_diff:
            best_diff = diff
            best_key = key

    if best_key is None:
        return None, None

    entry = curve_bests[best_key]
    if not isinstance(entry, dict):
        return None, None

    return entry, int(best_key)


def _normalise_to_trend(qualifying: list[tuple[str, float]]) -> list[float]:
    """Normalise adjusted efficiency values to 0–100.

    Sorts by run_id is NOT applied — the caller already provides runs in
    chronological order.  The order of the qualifying list is preserved.

    When all values are identical, every entry scores 50.0 (midpoint of range).
    When a single value exists, it also scores 50.0.
    """
    values = [v for _, v in qualifying]
    min_v = min(values)
    max_v = max(values)

    if max_v == min_v:
        # All runs have identical adjusted efficiency; place everyone at midpoint
        return [50.0] * len(values)

    return [(v - min_v) / (max_v - min_v) * 100.0 for v in values]


def _compute_direction(trend: list[float], threshold: float) -> str:
    """Derive direction from the slope of the last three trend values.

    slope is computed as (last - third_from_last) / 2, treating the trend
    as evenly spaced (one unit apart).  When fewer than three values are
    available, the slope uses the first and last value divided by the span.

    direction is "improving" when slope > threshold, "declining" when
    slope < -threshold, and "flat" otherwise.
    """
    if len(trend) < 2:
        return "flat"

    if len(trend) >= 3:
        # Use last three values for the slope window
        slope = (trend[-1] - trend[-3]) / 2.0
    else:
        slope = trend[-1] - trend[0]

    if slope > threshold:
        return "improving"
    if slope < -threshold:
        return "declining"
    return "flat"
