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

from datetime import date, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# EWMA scoring configuration (issue #1051)
# ---------------------------------------------------------------------------
# All smoothing parameters live here so they can be tuned without touching
# business logic. Inline comments explain each parameter's effect.
#
# endurance_ewma_alpha: base decay factor for the endurance EWMA.
#   Higher value = faster response to recent sessions; lower = more historical
#   inertia. Effective alpha per step is scaled by the run's duration weight.
#
# speed_ewma_alpha: base decay factor for the speed EWMA.
#   Speed signals are noisier (short hard efforts), so a slightly higher alpha
#   lets recent quality efforts update the score faster.
#
# endurance_reference_duration_seconds: run length that earns full EWMA weight.
#   Shorter runs receive proportionally less weight; longer are capped at 1.0.
#   Default: 3600 s (1 hour).
#
# speed_reference_signal: speed-signal ratio that earns full EWMA weight.
#   Signals above this value are capped at 1.0. Default: 1.30 (a solid hard
#   effort well above threshold).
#
# trailing_window_days: only sessions within this many days of the most recent
#   run in the input list contribute to the EWMA. Older sessions are ignored.
PERFORMANCE_CONFIG: dict = {
    "endurance_ewma_alpha": 0.2,
    "speed_ewma_alpha": 0.3,
    "endurance_reference_duration_seconds": 3600,
    "speed_reference_signal": 1.30,
    "trailing_window_days": 90,
}


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

    # Collect per-run adjusted efficiency and metadata for each qualifying run.
    # A run qualifies when it contains at least one easy/steady lap with usable data.
    qualifying_meta: list[dict] = []  # {run_id, adjusted, duration_seconds, workout_date}
    per_run_efficiency: dict[str, float] = {}

    for run in runs:
        run_id = run.get("run_id", "")
        laps = _qualifying_laps(run.get("laps") or [], bands)
        if not laps:
            continue

        eff, reason = _efficiency_from_laps(laps)
        if eff is None:
            continue  # insufficient data for this run

        # Durability adjustment: multiply efficiency by durability_factor.
        # A run with low decoupling is more durable and earns a higher signal.
        decoupling_pct = run.get("decoupling_pct")
        if isinstance(decoupling_pct, (int, float)) and not isinstance(decoupling_pct, bool):
            clamped = max(0.0, min(float(decoupling_pct), 50.0))
            durability_factor = 1.0 - clamped / 50.0
        else:
            durability_factor = 1.0

        adjusted = eff * durability_factor
        per_run_efficiency[run_id] = round(eff, 6)
        qualifying_meta.append({
            "run_id": run_id,
            "adjusted": adjusted,
            "duration_seconds": run.get("duration_seconds") or 0,
            "workout_date": run.get("workout_date") or "",
        })

    # Restrict to the trailing window (sessions outside are ignored; forward-carry
    # is implicit: the EWMA holds its last value until a new qualifying session arrives).
    window_days = PERFORMANCE_CONFIG["trailing_window_days"]
    qualifying_meta = _filter_trailing_window(qualifying_meta, window_days)

    min_runs = zc["min_qualifying_runs"]
    if len(qualifying_meta) < min_runs:
        found = len(qualifying_meta)
        return {
            "state": "building_baseline",
            "reason": (
                f"Need at least {min_runs} qualifying easy/steady runs; "
                f"{found} found."
            ),
        }

    # Normalize adjusted efficiency values to [0, 100] within the window.
    raw_values = [m["adjusted"] for m in qualifying_meta]
    normalised = _normalise_values(raw_values)

    # Build duration weights: longer runs earn proportionally more influence.
    ref_dur = PERFORMANCE_CONFIG["endurance_reference_duration_seconds"]
    duration_weights = [
        min(1.0, (m["duration_seconds"] or 0) / ref_dur) if ref_dur > 0 else 1.0
        for m in qualifying_meta
    ]
    # Guard: if all weights are 0 (all durations unknown), default to equal weight.
    if all(w == 0.0 for w in duration_weights):
        duration_weights = [1.0] * len(duration_weights)

    # Apply the duration-weighted EWMA over the normalised signals.
    base_alpha = PERFORMANCE_CONFIG["endurance_ewma_alpha"]
    ewma_series = _compute_ewma_series(normalised, duration_weights, base_alpha)

    score = ewma_series[-1]
    direction = _compute_direction(ewma_series, zc["direction_slope_threshold"])

    return {
        "score": round(score, 2),
        "direction": direction,
        "trend": [round(v, 2) for v in ewma_series],
        "qualifying_session_count": len(qualifying_meta),
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

    # Determine scoring path. When runs carry pre-computed speed_signal values
    # (persisted by issue #1048), use them directly as per-run signals. When no
    # run has a speed_signal, fall back to the lap-based efficiency path so that
    # existing test suites (which construct run dicts without speed_signal) keep
    # passing and athletes without a backfill still get scores.
    has_any_speed_signal = any(
        run.get("speed_signal") is not None for run in runs
    )

    qualifying_meta: list[dict] = []  # {run_id, signal, effort_weight, workout_date}
    per_run_efficiency: dict[str, float] = {}
    curve_best_used: dict | None = None

    if has_any_speed_signal:
        # Signal-based path: use the stored speed_signal as the per-run signal.
        # Weight each update by effort quality (how far above threshold the effort was).
        ref_signal = PERFORMANCE_CONFIG["speed_reference_signal"]
        for run in runs:
            run_id = run.get("run_id", "")
            sig = run.get("speed_signal")
            if sig is None:
                continue  # no qualifying effort on this run; carries forward implicitly
            effort_weight = min(1.0, float(sig) / ref_signal) if ref_signal > 0 else 1.0
            per_run_efficiency[run_id] = round(float(sig), 6)
            qualifying_meta.append({
                "run_id": run_id,
                "signal": float(sig),
                "effort_weight": effort_weight,
                "workout_date": run.get("workout_date") or "",
            })
    else:
        # Lap-based fallback: compute per-run efficiency from hard/interval laps.
        # Preserves full backward compatibility including duration-curve adjustment.
        for run in runs:
            run_id = run.get("run_id", "")
            laps = _qualifying_laps(run.get("laps") or [], bands)
            if not laps:
                continue

            eff, reason = _efficiency_from_laps(laps)
            if eff is None:
                continue

            adjusted = eff
            if curve_bests:
                avg_duration = _avg_lap_duration(laps)
                best_entry, best_duration = _find_closest_curve_entry(curve_bests, avg_duration)
                if best_entry is not None:
                    best_value = best_entry.get("best_value")
                    avg_power = _avg_lap_power(laps)
                    if best_value and best_value > 0 and avg_power and avg_power > 0:
                        proximity = min(1.0, avg_power / best_value)
                        adjusted = eff * (0.5 + 0.5 * proximity)
                        if curve_best_used is None:
                            curve_best_used = {
                                "duration_seconds": best_duration,
                                "best_value": best_value,
                            }

            per_run_efficiency[run_id] = round(eff, 6)
            # In the fallback path all runs receive equal effort weight.
            qualifying_meta.append({
                "run_id": run_id,
                "signal": adjusted,
                "effort_weight": 1.0,
                "workout_date": run.get("workout_date") or "",
            })

    # Restrict to the trailing window.
    window_days = PERFORMANCE_CONFIG["trailing_window_days"]
    qualifying_meta = _filter_trailing_window(qualifying_meta, window_days)

    min_runs = zc["min_qualifying_runs"]
    if len(qualifying_meta) < min_runs:
        found = len(qualifying_meta)
        return {
            "state": "building_baseline",
            "reason": (
                f"Need at least {min_runs} qualifying hard/interval runs; "
                f"{found} found."
            ),
        }

    # Normalize signals to [0, 100] within the trailing window.
    raw_signals = [m["signal"] for m in qualifying_meta]
    normalised = _normalise_values(raw_signals)

    effort_weights = [m["effort_weight"] for m in qualifying_meta]
    if all(w == 0.0 for w in effort_weights):
        effort_weights = [1.0] * len(effort_weights)

    base_alpha = PERFORMANCE_CONFIG["speed_ewma_alpha"]
    ewma_series = _compute_ewma_series(normalised, effort_weights, base_alpha)

    score = ewma_series[-1]
    direction = _compute_direction(ewma_series, zc["direction_slope_threshold"])

    return {
        "score": round(score, 2),
        "direction": direction,
        "trend": [round(v, 2) for v in ewma_series],
        "qualifying_session_count": len(qualifying_meta),
        "debug": {
            "perRunEfficiency": per_run_efficiency,
            "durationCurveBestUsed": curve_best_used,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _date_from_str(date_str: str) -> date | None:
    """Parse YYYY-MM-DD string to a date object; return None on failure."""
    try:
        return date.fromisoformat(date_str[:10]) if date_str else None
    except (ValueError, TypeError):
        return None


def _filter_trailing_window(items: list[dict], window_days: int) -> list[dict]:
    """Return only items whose workout_date is within window_days of the most recent.

    Items without a parseable date are excluded to avoid stale data skewing the
    window boundary. If no items have parseable dates, all items are returned.
    """
    dated = [(item, _date_from_str(item.get("workout_date", ""))) for item in items]
    valid_dates = [d for _, d in dated if d is not None]
    if not valid_dates:
        return items

    latest = max(valid_dates)
    cutoff = latest - timedelta(days=window_days)
    return [item for item, d in dated if d is not None and d >= cutoff]


def _normalise_values(values: list[float]) -> list[float]:
    """Normalise a list of floats to [0, 100].

    When all values are equal (or there is only one value), every entry maps
    to 50.0 (midpoint of the range).
    """
    if not values:
        return []
    min_v = min(values)
    max_v = max(values)
    if max_v == min_v:
        return [50.0] * len(values)
    return [(v - min_v) / (max_v - min_v) * 100.0 for v in values]


def _compute_ewma_series(
    signals: list[float],
    weights: list[float],
    base_alpha: float,
) -> list[float]:
    """Apply a weighted EWMA to a sequence of normalised signal values (0–100).

    For each step:
        effective_alpha = base_alpha * weight   (weight clamped to [0, 1])
        ewma_new = effective_alpha * signal + (1 - effective_alpha) * ewma_prev

    The first signal bootstraps the series (no prior value to blend against).
    Returns an EWMA value for every input signal in the same order.
    """
    ewma_history: list[float] = []
    ewma: float | None = None
    for signal, weight in zip(signals, weights):
        clamped_weight = max(0.0, min(1.0, weight))
        effective_alpha = base_alpha * clamped_weight
        if ewma is None:
            ewma = signal  # bootstrap: first qualifying session initialises the series
        else:
            ewma = effective_alpha * signal + (1.0 - effective_alpha) * ewma
        ewma_history.append(ewma)
    return ewma_history


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


def get_contributing_run_ids(
    runs: list[dict] | None,
    preferences: dict[str, Any] | None,
    zone_constants: dict[str, Any] | None,
    mode: str = "endurance",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return up to `limit` most recent qualifying run IDs with contribution values.

    Runs are assumed to be in chronological order (oldest first).  The function
    applies the same qualifying logic as compute_endurance_score / compute_speed_score
    so the contribution values match the normalised trend values in those results.

    Parameters
    ----------
    runs : list[dict] or None
        Same structure as accepted by compute_endurance_score.
    preferences : dict or None
        User preferences.  None → empty list returned.
    zone_constants : dict or None
        Zone band config from make_zone_constants().
    mode : "endurance" | "speed"
        Selects which band set to use for qualifying-lap filtering.
    limit : int
        Maximum number of sessions to return (most recent first).

    Returns
    -------
    list[dict]
        Each dict has exactly two keys: run_id (str) and contribution (float 0-100).
        Empty list when no qualifying sessions exist or prerequisites are missing.
    """
    zc = _resolve_zone_constants(zone_constants)
    if not runs or preferences is None:
        return []

    bands = zc["endurance_bands"] if mode == "endurance" else zc["speed_bands"]

    qualifying: list[tuple[str, float]] = []

    for run in runs:
        run_id = run.get("run_id", "")
        laps = _qualifying_laps(run.get("laps") or [], bands)
        if not laps:
            continue

        eff, _ = _efficiency_from_laps(laps)
        if eff is None:
            continue

        if mode == "endurance":
            decoupling_pct = run.get("decoupling_pct")
            if isinstance(decoupling_pct, (int, float)) and not isinstance(decoupling_pct, bool):
                clamped = max(0.0, min(float(decoupling_pct), 50.0))
                adjusted = eff * (1.0 - clamped / 50.0)
            else:
                adjusted = eff
        else:
            adjusted = eff

        qualifying.append((run_id, adjusted))

    if not qualifying:
        return []

    # Normalise to 0-100 (same formula as _normalise_to_trend)
    values = [v for _, v in qualifying]
    min_v = min(values)
    max_v = max(values)
    if max_v == min_v:
        contributions = [50.0] * len(values)
    else:
        contributions = [(v - min_v) / (max_v - min_v) * 100.0 for v in values]

    # Take the `limit` most recent (qualifying is already chronological)
    recent_qualifying = qualifying[-limit:]
    recent_contributions = contributions[-limit:]

    return [
        {"run_id": run_id, "contribution": round(contrib, 2)}
        for (run_id, _), contrib in zip(recent_qualifying, recent_contributions)
    ]


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
