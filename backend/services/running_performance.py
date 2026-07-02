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
      intensity (equivalent_pace = lap_pace × (avg_hr / threshold_hr) ** k, with
      a calibration exponent k>1 since pace–HR is non-linear), fed through VDOT
      at a threshold-effort duration, × decoupling durability factor → perf_i.
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
# endurance_hr_extrapolation_exponent: pace–HR is non-linear, so a pure-linear
#   HR scaling (exponent 1.0) systematically under-extrapolates easy runs and
#   pins Endurance near the band floor (the §6 calibration target). An exponent
#   of 1.5 pushes an easy aerobic run's equivalent threshold pace toward the
#   athlete's real threshold neighborhood without overstating it, while a
#   genuinely detrained run (higher HR for the same pace) still reads lower.
#   equivalent_pace = lap_pace × (avg_hr / threshold_hr) ** exponent.
# speed_sparse_effort_threshold / speed_sparse_band_multiplier: confidence band.
PERFORMANCE_CONFIG: dict = {
    "trailing_window_days": 90,
    "threshold_effort_minutes": 30.0,
    "endurance_hr_extrapolation_exponent": 1.5,
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

        # HR-extrapolate the aerobic lap to threshold intensity. Pace–HR is
        # non-linear, so a linear scaling under-extrapolates easy runs; apply a
        # calibration exponent (proposal §6): equivalent_pace =
        # lap_pace × (avg_hr / threshold_hr) ** exponent.
        hr_ratio = avg_hr / float(threshold_hr)
        if hr_ratio <= 0:
            continue
        exponent = PERFORMANCE_CONFIG["endurance_hr_extrapolation_exponent"]
        equivalent_pace = lap_pace * (hr_ratio ** exponent)  # s/km at threshold intensity
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
    """Speed score on the VDOT band from the best sustained hard effort.

    The effort's pace + duration → VDOT → rescale. Effort pace is resolved per
    run by ``_speed_effort_pace_duration`` (hard laps → power/pace-basis
    speed_signal fallback), so intervals whose real reps live in the Stryd
    streams (not the 1 km auto-splits) still score.
    """
    zc = _resolve_zone_constants(zone_constants)

    if preferences is None:
        return {"score": None, "reason": "missing: preferences not provided"}
    if not isinstance(preferences, dict):
        return {"score": None, "reason": "missing: preferences must be a dict"}

    runs = runs or []
    bands = zc["speed_bands"]
    threshold_pace = preferences.get("threshold_pace_seconds_per_km")

    qualifying_meta: list[dict] = []
    per_run_perf: dict[str, float] = {}

    for run in runs:
        run_id = run.get("run_id", "")
        effort_pace, effort_dur_s = _speed_effort_pace_duration(run, bands, threshold_pace)
        if effort_pace is None or not effort_dur_s or effort_dur_s <= 0:
            continue

        velocity = 1000.0 / (effort_pace / 60.0)  # m/min
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

    # Distinct dates, oldest first — one trend value per date. Also evaluate at
    # TODAY when the last point is in the past AND today is still within the
    # trailing window of that last point, so the CURRENT score reflects
    # decay-to-now (detraining lowers the displayed score with no new run). We
    # skip this for purely-historical data (last run already outside the window
    # relative to today) — there the trend ends at the last real point.
    window_days = PERFORMANCE_CONFIG["trailing_window_days"]
    trend_dates = sorted({d for d, _ in points})
    today = date.today()
    if trend_dates and trend_dates[-1] < today and (today - trend_dates[-1]).days <= window_days:
        trend_dates.append(today)
    trend = [_score_at(points, t, race_perf) for t in trend_dates]

    raw_score = trend[-1]
    direction = _compute_direction(trend, zc["direction_slope_threshold"])
    score = max(0.0, min(100.0, raw_score * body_modifier))

    # Per-date contribution: how much this date's effort(s) moved the score
    # (score(date) − score(previous trend date)), on the same displayed scale.
    # Free — the trend already holds score(t) per date. Keyed by ISO date so a
    # feeding session can look up its own contribution (its *_delta).
    contributions: dict[str, float] = {}
    prev_val = None
    for t, v in zip(trend_dates, trend):
        disp = max(0.0, min(100.0, v * body_modifier))
        if prev_val is not None:
            contributions[t.isoformat()] = round(disp - prev_val, 2)
        prev_val = disp

    result: dict[str, Any] = {
        "score": round(score, 2),
        "direction": direction,
        "trend": [round(v, 2) for v in trend],
        "trend_dates": [t.isoformat() for t in trend_dates],
        "contributions": contributions,
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


def _speed_effort_pace_duration(run: dict, bands: list[str], threshold_pace) -> tuple[float | None, float | None]:
    """Resolve the best hard-effort (pace_s_per_km, duration_s) for a run.

    Precedence:
      1. Qualifying hard/interval laps present → their real pace + total duration.
      2. Else a persisted ``speed_signal`` (the real reps live in the Stryd
         streams, not the 1 km auto-splits):
         - pace basis:  effort_pace = threshold_pace / signal.
         - power basis: convert power→pace via the run's own pace–power relation:
             effort_pace ≈ avg_run_pace × (avg_run_power / effort_power),
             effort_power = signal × ftp is proportional to avg_run_power × signal
             ÷ (avg_run_power/ftp) — but we only need the RATIO, so use
             effort_pace = avg_run_pace / (signal / (avg_run_power / ftp)).
           Falls back to threshold_pace/signal-as-pace-proxy when the run lacks
           the power/pace data needed for the relation.
         - hr basis: no reliable pace mapping → skip (returns None).
       Effort duration = ``speed_signal_window_seconds`` when present, else a
       nominal 5 min (a typical hard-effort window).
    """
    laps = _qualifying_laps(run.get("laps") or [], bands)
    lap_pace, lap_dur = _lap_pace_and_duration(laps)
    if lap_pace is not None and lap_dur and lap_dur > 0:
        return lap_pace, lap_dur

    signal = run.get("speed_signal")
    if not isinstance(signal, (int, float)) or isinstance(signal, bool) or signal <= 0:
        return None, None

    basis = (run.get("speed_signal_basis") or "").lower()
    window_s = run.get("speed_signal_window_seconds")
    duration_s = float(window_s) if isinstance(window_s, (int, float)) and window_s and window_s > 0 else 300.0

    if basis == "pace":
        if threshold_pace and threshold_pace > 0:
            # signal = threshold_pace / lap_pace → lap_pace = threshold_pace / signal
            return float(threshold_pace) / float(signal), duration_s
        return None, None

    if basis == "power":
        # Run-level pace–power relation → convert the effort's power ratio to a
        # pace. avg_run_pace corresponds to avg_run_power; running power scales
        # ~linearly with speed, so effort_pace ≈ avg_run_pace × avg_run_power / effort_power.
        dist = run.get("distance_km")
        dur = run.get("duration_seconds")
        avg_power = run.get("avg_power")
        ftp = run.get("ftp_w")
        if (isinstance(dist, (int, float)) and dist and dist > 0
                and isinstance(dur, (int, float)) and dur and dur > 0
                and isinstance(avg_power, (int, float)) and avg_power and avg_power > 0
                and isinstance(ftp, (int, float)) and ftp and ftp > 0):
            avg_run_pace = float(dur) / float(dist)         # s/km
            effort_power = float(signal) * float(ftp)        # W
            if effort_power > 0:
                effort_pace = avg_run_pace * float(avg_power) / effort_power
                if effort_pace > 0:
                    return effort_pace, duration_s
        # Fallback: treat the intensity ratio against threshold pace.
        if threshold_pace and threshold_pace > 0:
            return float(threshold_pace) / float(signal), duration_s
        return None, None

    # heart_rate basis or unknown → no reliable pace mapping.
    return None, None


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
