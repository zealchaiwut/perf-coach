"""Endurance and Speed running performance scores — VDOT re-anchor.

compute_endurance_score and compute_speed_score are pure functions. They accept
pre-assembled run data, user preferences, zone constants, and an optional race
perf point, then return a score object on the **universal VDOT band** (0–100).

Design (docs/calculations/score-reanchor-proposal.md §4, DECIDED 2026-07-02):

- Per-run performance is an ABSOLUTE VDOT-derived value, not a window-relative
  min/max normalization:
    Speed: the run's best sustained hard effort → its pace + duration →
      vdot_from_pace_duration → rescale_to_score → perf_i.
    Endurance: an aerobic lap set's pace, HR-extrapolated to threshold
      intensity (equivalent_speed = lap_speed / (avg_hr / threshold_hr)), fed
      through VDOT at a threshold-effort duration, × decoupling durability
      factor → perf_i.
- Aggregate = decayed top-3 mean:
    decayed_i = max(0, perf_i − decay_points(days_since_i))
    score(t)  = mean of the 3 largest decayed_i over runs (date ≤ t) in window.
  Outlier-resistant (one blip can't set the score) and an aborted/slow session
  (low perf_i) can never LOWER it.
- Decay: 2-week grace, then 1.5 pts/week (vdot.decay_points).
- Race floor: latest finished race is a perf point in the pool AND a decayed
  floor score(t) ≥ perf_race − decay_points(days_since_race).
- trend[] = score(t) recomputed per date (step-like, no smoothing); trend_dates
  is the parallel date list. direction from the last-3 slope.

Response shapes are preserved exactly (score / direction / trend /
qualifying_session_count / confidence_band (speed) / debug) plus the
building_baseline / needs_thresholds / missing states.

SPEED_SIGNAL BASIS NOTE: workouts.speed_signal is an intensity *ratio*
(effort/threshold), basis one of "power" | "pace" | "heart_rate" — NOT a pace.
We therefore derive the effort's real pace directly from the run's hard/interval
laps (distance / duration), which is basis-independent and avoids a fragile
power→pace conversion. speed_signal is used only to confirm a run had a
qualifying hard effort.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.services.vdot import (
    vdot_from_pace_duration,
    rescale_to_score,
    decay_points,
    TOP_K,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# trailing_window_days: qualifying cutoff; decay operates inside it.
# threshold_effort_minutes: the effort duration used when extrapolating an
#   endurance lap to threshold intensity (a ~threshold-effort reference so the
#   %VO2max term is that of a sustained threshold run, not the easy-run length).
# speed_sparse_effort_threshold / speed_sparse_band_multiplier: confidence band.
PERFORMANCE_CONFIG: dict = {
    "trailing_window_days": 90,
    "threshold_effort_minutes": 30.0,
    "speed_sparse_effort_threshold": 5,
    "speed_sparse_band_multiplier": 1.5,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_endurance_score(
    runs: list[dict] | None,
    preferences: dict[str, Any] | None,
    zone_constants: dict[str, Any] | None,
    body_modifier: float = 1.0,
    race_perf: dict | None = None,
) -> dict[str, Any]:
    """Endurance score on the VDOT band from easy/steady aerobic runs.

    Requires ``threshold_hr`` in preferences (HR extrapolation) → missing
    returns the ``needs_thresholds`` state. See module docstring for the method.

    ``race_perf`` (optional): ``{"perf": float, "date": "YYYY-MM-DD"}`` — a race
    VDOT-band point that enters the pool and enforces a decayed floor.
    """
    zc = _resolve_zone_constants(zone_constants)

    if preferences is None:
        return {"score": None, "reason": "missing: preferences not provided"}
    if not isinstance(preferences, dict):
        return {"score": None, "reason": "missing: preferences must be a dict"}

    threshold_hr = preferences.get("threshold_hr")
    if not isinstance(threshold_hr, (int, float)) or isinstance(threshold_hr, bool) or threshold_hr <= 0:
        return {"state": "needs_thresholds", "reason": "Endurance score needs threshold_hr."}

    runs = runs or []
    bands = zc["endurance_bands"]
    threshold_effort_min = PERFORMANCE_CONFIG["threshold_effort_minutes"]

    qualifying_meta: list[dict] = []
    per_run_perf: dict[str, float] = {}

    for run in runs:
        run_id = run.get("run_id", "")
        laps = _qualifying_laps(run.get("laps") or [], bands)
        lap_pace, _dur = _lap_pace_and_duration(laps)
        avg_hr = _weighted_lap_hr(laps)
        if lap_pace is None or avg_hr is None or avg_hr <= 0:
            continue

        # HR-extrapolate the aerobic lap to threshold intensity:
        #   equivalent_speed = lap_speed / (avg_hr / threshold_hr)
        #   → equivalent_pace = lap_pace × (avg_hr / threshold_hr)
        hr_ratio = avg_hr / float(threshold_hr)
        if hr_ratio <= 0:
            continue
        equivalent_pace = lap_pace * hr_ratio  # s/km at threshold intensity
        velocity = 1000.0 / (equivalent_pace / 60.0)  # m/min
        vdot = vdot_from_pace_duration(velocity, threshold_effort_min)
        perf = rescale_to_score(vdot)

        # Durability factor from decoupling (unchanged).
        decoupling_pct = run.get("decoupling_pct")
        if isinstance(decoupling_pct, (int, float)) and not isinstance(decoupling_pct, bool):
            clamped = max(0.0, min(float(decoupling_pct), 50.0))
            durability_factor = 1.0 - clamped / 50.0
        else:
            durability_factor = 1.0

        perf = perf * durability_factor
        per_run_perf[run_id] = round(perf, 4)
        qualifying_meta.append({
            "run_id": run_id,
            "perf": perf,
            "workout_date": run.get("workout_date") or "",
        })

    return _aggregate_and_shape(
        qualifying_meta, per_run_perf, zc, body_modifier, race_perf,
        include_confidence_band=False,
        baseline_reason_noun="easy/steady",
    )


def compute_speed_score(
    runs: list[dict] | None,
    preferences: dict[str, Any] | None,
    zone_constants: dict[str, Any] | None,
    body_modifier: float = 1.0,
    race_perf: dict | None = None,
) -> dict[str, Any]:
    """Speed score on the VDOT band from hard/interval efforts.

    The run's best sustained hard effort → its pace + duration → VDOT →
    rescale. Basis-independent: pace comes from the run's own hard laps.
    """
    zc = _resolve_zone_constants(zone_constants)

    if preferences is None:
        return {"score": None, "reason": "missing: preferences not provided"}
    if not isinstance(preferences, dict):
        return {"score": None, "reason": "missing: preferences must be a dict"}

    runs = runs or []
    bands = zc["speed_bands"]

    qualifying_meta: list[dict] = []
    per_run_perf: dict[str, float] = {}

    for run in runs:
        run_id = run.get("run_id", "")
        laps = _qualifying_laps(run.get("laps") or [], bands)
        lap_pace, effort_dur_s = _lap_pace_and_duration(laps)
        if lap_pace is None or not effort_dur_s or effort_dur_s <= 0:
            continue

        velocity = 1000.0 / (lap_pace / 60.0)  # m/min
        effort_min = effort_dur_s / 60.0
        vdot = vdot_from_pace_duration(velocity, effort_min)
        perf = rescale_to_score(vdot)
        per_run_perf[run_id] = round(perf, 4)
        qualifying_meta.append({
            "run_id": run_id,
            "perf": perf,
            "workout_date": run.get("workout_date") or "",
        })

    return _aggregate_and_shape(
        qualifying_meta, per_run_perf, zc, body_modifier, race_perf,
        include_confidence_band=True,
        baseline_reason_noun="hard/interval",
    )


# ---------------------------------------------------------------------------
# Aggregate: decayed top-3 mean + race floor + trend
# ---------------------------------------------------------------------------

def _aggregate_and_shape(
    qualifying_meta: list[dict],
    per_run_perf: dict[str, float],
    zc: dict,
    body_modifier: float,
    race_perf: dict | None,
    include_confidence_band: bool,
    baseline_reason_noun: str,
) -> dict[str, Any]:
    """Shared: window filter → decayed top-3 mean → floor → trend/direction."""
    window_days = PERFORMANCE_CONFIG["trailing_window_days"]
    qualifying_meta = _filter_trailing_window(qualifying_meta, window_days)

    min_runs = zc["min_qualifying_runs"]
    if len(qualifying_meta) < min_runs:
        found = len(qualifying_meta)
        return {
            "state": "building_baseline",
            "reason": (
                f"Need at least {min_runs} qualifying {baseline_reason_noun} runs; "
                f"{found} found."
            ),
        }

    # Points pool: qualifying runs (+ race as an ordinary point at its date).
    points: list[tuple[date, float]] = []
    for m in qualifying_meta:
        d = _date_from_str(m["workout_date"])
        if d is not None:
            points.append((d, float(m["perf"])))
    race_point = _race_point(race_perf)
    if race_point is not None:
        points.append(race_point)

    if len(points) < min_runs:
        return {
            "state": "building_baseline",
            "reason": (
                f"Need at least {min_runs} dated qualifying {baseline_reason_noun} runs; "
                f"{len(points)} found."
            ),
        }

    # Distinct dates, oldest first — one trend value per date.
    trend_dates = sorted({d for d, _ in points})
    trend = [_score_at(points, t, race_perf) for t in trend_dates]

    raw_score = trend[-1]
    direction = _compute_direction(trend, zc["direction_slope_threshold"])
    score = max(0.0, min(100.0, raw_score * body_modifier))

    result: dict[str, Any] = {
        "score": round(score, 2),
        "direction": direction,
        "trend": [round(v, 2) for v in trend],
        "trend_dates": [t.isoformat() for t in trend_dates],
        "qualifying_session_count": len(qualifying_meta),
        "debug": {"perRunEfficiency": per_run_perf},
    }

    if include_confidence_band:
        count = len(qualifying_meta)
        sparse_threshold = PERFORMANCE_CONFIG.get("speed_sparse_effort_threshold", 5)
        result["low_data_warning"] = count < sparse_threshold
        result["confidence_band"] = _compute_confidence_band(
            score, count, sparse_threshold, base_band_width=10.0
        )
        result["debug"]["durationCurveBestUsed"] = None

    return result


def _score_at(points: list[tuple[date, float]], t: date, race_perf: dict | None) -> float:
    """score(t) = mean of the 3 largest decayed perf points with date ≤ t,
    floored by a decayed race anchor.
    """
    decayed = []
    for d, perf in points:
        if d > t:
            continue
        days = (t - d).days
        decayed.append(max(0.0, perf - decay_points(days)))
    if not decayed:
        return 0.0
    decayed.sort(reverse=True)
    top = decayed[:TOP_K]
    score = sum(top) / len(top)

    # Race floor: score(t) ≥ perf_race − decay_points(days_since_race).
    rp = _race_point(race_perf)
    if rp is not None:
        rdate, rperf = rp
        if rdate <= t:
            floor = max(0.0, rperf - decay_points((t - rdate).days))
            score = max(score, floor)
    return score


def _race_point(race_perf: dict | None) -> tuple[date, float] | None:
    if not isinstance(race_perf, dict):
        return None
    perf = race_perf.get("perf")
    d = _date_from_str(race_perf.get("date", ""))
    if d is None or not isinstance(perf, (int, float)) or isinstance(perf, bool):
        return None
    return d, float(perf)


# ---------------------------------------------------------------------------
# Lap / pace helpers
# ---------------------------------------------------------------------------

def _date_from_str(date_str: str) -> date | None:
    try:
        return date.fromisoformat(date_str[:10]) if date_str else None
    except (ValueError, TypeError):
        return None


def _filter_trailing_window(items: list[dict], window_days: int) -> list[dict]:
    """Only items within window_days of the most recent dated item."""
    dated = [(item, _date_from_str(item.get("workout_date", ""))) for item in items]
    valid_dates = [d for _, d in dated if d is not None]
    if not valid_dates:
        return items
    latest = max(valid_dates)
    cutoff = latest - timedelta(days=window_days)
    return [item for item, d in dated if d is not None and d >= cutoff]


def _qualifying_laps(laps: list[dict], bands: list[str]) -> list[dict]:
    return [lap for lap in laps if lap.get("band") in bands]


def _lap_pace_and_duration(laps: list[dict]) -> tuple[float | None, float | None]:
    """Duration-weighted pace (s/km) and total effort duration (s) over laps.

    Uses distance + duration only (basis-independent). Returns (None, None)
    when there is no usable distance/duration.
    """
    valid = [
        lap for lap in laps
        if isinstance(lap.get("duration_seconds"), (int, float))
        and not isinstance(lap.get("duration_seconds"), bool)
        and lap["duration_seconds"] > 0
        and isinstance(lap.get("distance_km"), (int, float))
        and not isinstance(lap.get("distance_km"), bool)
        and lap["distance_km"] > 0
    ]
    if not valid:
        return None, None
    total_dur = sum(float(lap["duration_seconds"]) for lap in valid)
    total_dist = sum(float(lap["distance_km"]) for lap in valid)
    if total_dist <= 0 or total_dur <= 0:
        return None, None
    pace_s_per_km = total_dur / total_dist
    return pace_s_per_km, total_dur


def _weighted_lap_hr(laps: list[dict]) -> float | None:
    """Duration-weighted avg HR over laps that have positive HR + duration."""
    valid = [
        lap for lap in laps
        if isinstance(lap.get("avg_hr"), (int, float))
        and not isinstance(lap.get("avg_hr"), bool)
        and lap["avg_hr"] > 0
        and isinstance(lap.get("duration_seconds"), (int, float))
        and not isinstance(lap.get("duration_seconds"), bool)
        and lap["duration_seconds"] > 0
    ]
    if not valid:
        return None
    total_dur = sum(float(lap["duration_seconds"]) for lap in valid)
    return sum(float(lap["avg_hr"]) * float(lap["duration_seconds"]) for lap in valid) / total_dur


def _resolve_zone_constants(zone_constants: dict | None) -> dict:
    from backend.services.zone_constants import make_zone_constants
    if zone_constants is None:
        return make_zone_constants()
    return zone_constants


def _compute_direction(trend: list[float], threshold: float) -> str:
    """Direction from the slope of the last three trend values (unchanged rule)."""
    if len(trend) < 2:
        return "flat"
    if len(trend) >= 3:
        slope = (trend[-1] - trend[-3]) / 2.0
    else:
        slope = trend[-1] - trend[0]
    if slope > threshold:
        return "improving"
    if slope < -threshold:
        return "declining"
    return "flat"


def _compute_confidence_band(
    score: float,
    qualifying_count: int,
    sparse_threshold: int,
    base_band_width: float = 10.0,
) -> dict:
    """Uncertainty interval around a score; widened when data is sparse."""
    sparse_multiplier = PERFORMANCE_CONFIG.get("speed_sparse_band_multiplier", 1.5)
    is_sparse = qualifying_count < sparse_threshold
    effective_width = base_band_width * (sparse_multiplier if is_sparse else 1.0)
    lower = max(0.0, score - effective_width)
    upper = min(100.0, score + effective_width)
    return {"lower": round(lower, 2), "upper": round(upper, 2)}
