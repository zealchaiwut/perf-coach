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

import logging
from datetime import date, timedelta
from typing import Any

from backend.services.vdot import (
    vdot_from_pace_duration,
    rescale_to_score,
    decay_points,
    TOP_K,
    GRACE_WEEKS,
    DECAY_PER_WEEK,
    CONSISTENCY_BONUS_PER_RUN,
    CONSISTENCY_WINDOW_DAYS,
    CONSISTENCY_BONUS_CAP,
)

_log = logging.getLogger(__name__)

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

# Reference effort duration for the SPEED improve hint ("run X:XX /km held
# ~8 min") — a typical sustained hard/interval effort length; endurance's
# hint uses threshold_effort_minutes above (the same duration its perf
# points are extrapolated to).
IMPROVE_SPEED_REF_MINUTES: float = 8.0
# The improve hint targets this many points above the current score —
# "Endurance 36 → 40" scale, near enough to be actionable.
IMPROVE_TARGET_STEP: int = 4
# Score-change decomposition window and the summation-invariant tolerance
# (score_then + decay + efforts + consistency must equal score_now within
# this; beyond it the breakdown is withheld rather than rendered wrong).
BREAKDOWN_WINDOW_DAYS: int = 28
BREAKDOWN_RESIDUAL_TOLERANCE: float = 0.05


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

    ``body_modifier``: **multiplier** centered at 1.0 (valid range 0.85–1.05).
        1.0 is neutral; > 1.0 improves the score (lighter, better power-to-weight);
        < 1.0 reduces it (excessive deficit or low EA).
        Derive from body-composition data via::

            1.0 + compute_body_modifier(weekly_pct_bw_rate, ea_proxy)['modifier']

        Do **not** pass the raw ``'modifier'`` delta directly — that value is in
        [-0.15, +0.05] and would multiply the score by ~0.02, effectively zeroing it.
        Raises ``ValueError`` if ``body_modifier`` is outside [0.5, 2.0].

    ``race_perf`` (optional): ``{"perf": float, "date": "YYYY-MM-DD"}`` — a race
    VDOT-band point that enters the pool and enforces a decayed floor.
    """
    if not (0.5 <= body_modifier <= 2.0):
        raise ValueError(
            f"body_modifier={body_modifier!r} is outside the valid multiplier range "
            "[0.5, 2.0]. It must be a multiplier centered at 1.0 (e.g. 0.85–1.05). "
            "If you have a raw delta from compute_body_modifier(), convert it first: "
            "1.0 + result['modifier']."
        )
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
        # Endurance perf points are HR-extrapolated to a threshold-length
        # effort — the improve hint speaks the same reference duration.
        improve_ref_minutes=PERFORMANCE_CONFIG["threshold_effort_minutes"],
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

    ``body_modifier``: **multiplier** centered at 1.0 (valid range 0.85–1.05).
        1.0 is neutral; > 1.0 improves the score; < 1.0 reduces it.
        Derive from body-composition data via::

            1.0 + compute_body_modifier(weekly_pct_bw_rate, ea_proxy)['modifier']

        Do **not** pass the raw ``'modifier'`` delta directly — that value is in
        [-0.15, +0.05] and would nearly zero the score.
        Raises ``ValueError`` if ``body_modifier`` is outside [0.5, 2.0].
    """
    if not (0.5 <= body_modifier <= 2.0):
        raise ValueError(
            f"body_modifier={body_modifier!r} is outside the valid multiplier range "
            "[0.5, 2.0]. It must be a multiplier centered at 1.0 (e.g. 0.85–1.05). "
            "If you have a raw delta from compute_body_modifier(), convert it first: "
            "1.0 + result['modifier']."
        )
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
        improve_ref_minutes=IMPROVE_SPEED_REF_MINUTES,
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
    improve_ref_minutes: float = 30.0,
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
    # tagged_points keeps each point's run_id so a single run can be removed
    # from the pool for the marginal-contribution computation below.
    tagged_points: list[tuple[date, float, str | None]] = []
    for m in qualifying_meta:
        d = _date_from_str(m["workout_date"])
        if d is not None:
            tagged_points.append((d, float(m["perf"]), m.get("run_id") or None))
    race_point = _race_point(race_perf)
    if race_point is not None:
        tagged_points.append((race_point[0], race_point[1], None))
    points: list[tuple[date, float]] = [(d, p) for d, p, _ in tagged_points]

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

    # Per-date contribution (LEGACY, kept for back-compat): score(date) −
    # score(previous trend date). Includes pure time-decay drift between
    # dates, so a maintenance run reads slightly negative — prefer
    # run_contributions below for per-session badges.
    contributions: dict[str, float] = {}
    prev_val = None
    for t, v in zip(trend_dates, trend):
        disp = max(0.0, min(100.0, v * body_modifier))
        if prev_val is not None:
            contributions[t.isoformat()] = round(disp - prev_val, 2)
        prev_val = disp

    # Per-RUN marginal contribution to the CURRENT score, keyed by run_id:
    # score at the final trend date (today, or the last point when history is
    # stale) WITH the run minus WITHOUT it, on the displayed scale. This
    # isolates the run's own effect on the score being shown — a maintenance
    # run below the decayed top-3 shows exactly 0.0 instead of being blamed
    # for the decay drift that accrued since the previous session; an effort
    # holding up the top-3 (or the race floor) shows its real lift; a run
    # that has decayed out of relevance shows 0.0. This is THE single source
    # for every per-session delta badge (Performance-tab feed AND the
    # workout-detail panel) — do not derive a second one elsewhere.
    def _display(v: float) -> float:
        return max(0.0, min(100.0, v * body_modifier))

    t_eval = trend_dates[-1]
    score_with_all = _display(_score_at(points, t_eval, race_perf))
    run_contributions: dict[str, float] = {}
    for d, perf, rid in tagged_points:
        if rid is None:
            continue  # race anchor point, not a run
        without = [(pd, pp) for pd, pp, prid in tagged_points if prid != rid]
        without_run = _score_at(without, t_eval, race_perf) if without else 0.0
        run_contributions[rid] = round(score_with_all - _display(without_run), 2)

    # "How do I get from 36 to 40?" — invert the model: the perf a single
    # NEW effort (today) must score so the decayed top-3 mean (plus the
    # consistency bonus it also adds) reaches the target, then translate
    # that perf back through VDOT into a concrete pace at the score type's
    # reference effort duration. None when a pace can't be formed.
    improve_hint: dict[str, Any] | None = None
    try:
        from backend.services.vdot import VDOT_FLOOR, VDOT_CEIL
        from backend.services.race_finish_estimator import (
            _velocity_for_vdot_at_duration as _vel_for_vdot,
        )

        target_score = min(100, int(round(score)) + IMPROVE_TARGET_STEP)
        decayed_now = []
        recent_now = 0
        for d, perf, _rid in tagged_points:
            if d > t_eval:
                continue
            days = (t_eval - d).days
            decayed_now.append(max(0.0, perf - decay_points(days)))
            if days <= CONSISTENCY_WINDOW_DAYS:
                recent_now += 1
        decayed_now.sort(reverse=True)
        d1 = decayed_now[0] if decayed_now else 0.0
        d2 = decayed_now[1] if len(decayed_now) > 1 else 0.0
        bonus_new = min(CONSISTENCY_BONUS_CAP, (recent_now + 1) * CONSISTENCY_BONUS_PER_RUN)
        needed_mean = target_score / body_modifier - bonus_new
        required_perf = max(0.0, min(100.0, TOP_K * needed_mean - d1 - d2))
        required_vdot = VDOT_FLOOR + required_perf / 100.0 * (VDOT_CEIL - VDOT_FLOOR)
        _v = _vel_for_vdot(required_vdot, improve_ref_minutes)
        if _v is not None and _v > 0:
            improve_hint = {
                "target_score": target_score,
                "required_perf": round(required_perf, 1),
                "required_vdot": round(required_vdot, 1),
                "pace_seconds_per_km": int(round(1000.0 / (_v / 60.0))),
                "effort_minutes": improve_ref_minutes,
            }
    except Exception:  # pragma: no cover — hint is best-effort decoration
        _log.warning("improve_hint computation failed", exc_info=True)

    # ── Change decomposition (score-breakdown card) ──────────────────────
    # Explain score_now − score_then over BREAKDOWN_WINDOW_DAYS as decay +
    # efforts + consistency, via three recomputes against fixed pools (never
    # per-run attribution):
    #   A = points dated ≤ then;  B = the full pool
    #   M(P,t) = anchor mean (decayed top-K + race floor), C(P,t) = bonus
    #   score_then   = M(A,then) + C(A,then)
    #   decay        = M(A,now) − M(A,then)      (the OLD pool aging)
    #   efforts      = M(B,now) − M(A,now)       (window's new points, at now)
    #   consistency  = C(B,now) − C(A,then)
    # The sum telescopes to M(B,now)+C(B,now) = score_now EXACTLY on the
    # unclamped display scale; the residual check below catches the one case
    # the identity can break (the 0/100 display clamp binding).
    breakdown: dict[str, Any] | None = None
    try:
        then = t_eval - timedelta(days=BREAKDOWN_WINDOW_DAYS)
        pool_a = [(d, pp) for d, pp in points if d <= then]
        m_a_then = _anchor_mean_at(pool_a, then, race_perf) * body_modifier
        c_a_then = _bonus_at(pool_a, then) * body_modifier
        m_a_now = _anchor_mean_at(pool_a, t_eval, race_perf) * body_modifier
        m_b_now = _anchor_mean_at(points, t_eval, race_perf) * body_modifier
        c_b_now = _bonus_at(points, t_eval) * body_modifier

        b_score_then = m_a_then + c_a_then
        b_decay = m_a_now - m_a_then
        b_efforts = m_b_now - m_a_now
        b_consistency = c_b_now - c_a_then
        b_sum = b_score_then + b_decay + b_efforts + b_consistency
        residual = score - b_sum  # vs the CLAMPED displayed score

        # Anchor rows: the TOP_K decayed points defining today's mean.
        decorated = []
        for d, pp, rid in tagged_points:
            if d > t_eval:
                continue
            age_days = (t_eval - d).days
            dec = min(pp, decay_points(age_days))
            decorated.append({
                "run_id": rid,  # None = the race anchor point
                "date": d.isoformat(),
                "raw_score": round(pp * body_modifier, 2),
                "age_weeks": round(age_days / 7.0, 1),
                "decay_applied": round(-dec * body_modifier, 2),
                "current_contribution": round((pp - dec) * body_modifier, 2),
                "is_stale": age_days / 7.0 > GRACE_WEEKS,
            })
        decorated.sort(key=lambda r: -r["current_contribution"])
        anchors = decorated[:TOP_K]
        weakest = anchors[-1]["current_contribution"] if anchors else 0.0
        # The race point (run_id None) may BE an anchor but is never listed
        # as a displaceable non-anchor run.
        non_anchors = [
            {
                "run_id": r["run_id"],
                "date": r["date"],
                "raw_score": r["raw_score"],
                "age_weeks": r["age_weeks"],
                "gap_to_weakest_anchor": round(r["current_contribution"] - weakest, 2),
            }
            for r in decorated[TOP_K:]
            if r["run_id"] is not None
            and _date_from_str(r["date"]) is not None and _date_from_str(r["date"]) > then
        ]
        # Footer arithmetic: score = max(avg of K, race floor) + consistency.
        # Surface BOTH terms (floor may be None when no recent race) plus
        # which one won, so the UI renders the same formula on every card.
        mean_top = (
            sum(a["current_contribution"] for a in anchors) / len(anchors) if anchors else 0.0
        )
        rp_now = _race_point(race_perf)
        race_floor_val = None
        if rp_now is not None and rp_now[0] <= t_eval:
            race_floor_val = max(
                0.0, (rp_now[1] - decay_points((t_eval - rp_now[0]).days)) * body_modifier
            )
        floor_binding = m_b_now > mean_top + 0.01

        breakdown = {
            "window_days": BREAKDOWN_WINDOW_DAYS,
            "score_then": round(b_score_then, 2),
            "score_now": round(score, 2),
            "delta": round(score - b_score_then, 2),
            "decay": round(b_decay, 2),
            "efforts": round(b_efforts, 2),
            "consistency": round(b_consistency, 2),
            "residual": round(residual, 4),
            "anchors": anchors,
            "non_anchors": non_anchors,
            "weakest_anchor_now": round(weakest, 2),
            "consistency_bonus_now": round(c_b_now, 2),
            "anchor_mean_now": round(mean_top, 2),
            "race_floor_now": round(race_floor_val, 2) if race_floor_val is not None else None,
            "floor_binding": floor_binding,
        }
        if abs(residual) > BREAKDOWN_RESIDUAL_TOLERANCE:
            # A decomposition that doesn't sum is worse than none — it looks
            # authoritative and is wrong. Don't render it.
            _log.error(
                "score breakdown residual %.4f exceeds tolerance (display clamp?)",
                residual,
            )
            breakdown = {"error": "residual", "residual": round(residual, 4)}
    except Exception:  # pragma: no cover — breakdown is derived decoration
        _log.warning("score breakdown computation failed", exc_info=True)
        breakdown = None

    result: dict[str, Any] = {
        "score": round(score, 2),
        "direction": direction,
        "trend": [round(v, 2) for v in trend],
        "trend_dates": [t.isoformat() for t in trend_dates],
        "contributions": contributions,
        "run_contributions": run_contributions,
        "qualifying_session_count": len(qualifying_meta),
        "improve_hint": improve_hint,
        "breakdown": breakdown,
        # How the score moves, for the UI to state instead of hardcode:
        # top-K anchor decay + the consistency bonus (vdot.py constants).
        "model": {
            "top_k": TOP_K,
            "grace_weeks": GRACE_WEEKS,
            "decay_per_week": DECAY_PER_WEEK,
            "consistency_bonus_per_run": CONSISTENCY_BONUS_PER_RUN,
            "consistency_window_days": CONSISTENCY_WINDOW_DAYS,
            "consistency_bonus_cap": CONSISTENCY_BONUS_CAP,
        },
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


def _anchor_mean_at(points: list[tuple[date, float]], t: date, race_perf: dict | None) -> float:
    """Anchor component of score(t): mean of the TOP_K largest decayed perf
    points with date ≤ t, floored by the decayed race anchor. NO consistency
    bonus — see _bonus_at; _score_at composes the two. Kept separate so the
    change decomposition can attribute decay/efforts/consistency exactly."""
    decayed = []
    for d, perf in points:
        if d > t:
            continue
        decayed.append(max(0.0, perf - decay_points((t - d).days)))
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


def _bonus_at(points: list[tuple[date, float]], t: date) -> float:
    """Consistency component of score(t) — see vdot.py constants."""
    recent = sum(1 for d, _ in points if d <= t and (t - d).days <= CONSISTENCY_WINDOW_DAYS)
    return min(CONSISTENCY_BONUS_CAP, recent * CONSISTENCY_BONUS_PER_RUN)


def _score_at(points: list[tuple[date, float]], t: date, race_perf: dict | None) -> float:
    """score(t) = anchor mean (decayed top-K, race-floored) + consistency
    bonus. See _anchor_mean_at / _bonus_at."""
    if not any(d <= t for d, _ in points):
        return 0.0
    return _anchor_mean_at(points, t, race_perf) + _bonus_at(points, t)


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
    n_bad = sum(1 for _, d in dated if d is None)
    if n_bad:
        _log.warning(
            "dropping %d run(s) from trailing window: unparseable workout_date",
            n_bad,
        )
    latest = max(valid_dates)
    cutoff = latest - timedelta(days=window_days)
    return [item for item, d in dated if d is not None and d >= cutoff]


# No human sustains a pace faster than this (150 s/km = 2:30/km; the world
# mile record averages ~148 s/km). A lap claiming to beat it is sensor/sync
# garbage — seen live: a corrupted file with three "1 km in ~81 s" laps that
# classified as hard efforts and pinned the Speed score at a perfect 100.
_MIN_PLAUSIBLE_PACE_S_PER_KM: float = 150.0


def _lap_pace_plausible(lap: dict) -> bool:
    dur = lap.get("duration_seconds")
    dist = lap.get("distance_km")
    if (isinstance(dur, (int, float)) and not isinstance(dur, bool) and dur > 0
            and isinstance(dist, (int, float)) and not isinstance(dist, bool) and dist > 0):
        return (float(dur) / float(dist)) >= _MIN_PLAUSIBLE_PACE_S_PER_KM
    return True  # no pace derivable — other validators handle it


def _qualifying_laps(laps: list[dict], bands: list[str]) -> list[dict]:
    return [lap for lap in laps if lap.get("band") in bands and _lap_pace_plausible(lap)]


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


# Minimum speed_signal window that may define a run's speed effort via the
# power-basis fallback — sub-2-minute surges say nothing about sustainable
# speed (see the guard note inside _speed_effort_pace_duration).
_MIN_POWER_FALLBACK_WINDOW_S: float = 120.0


def _fastest_real_lap_pace(laps: list[dict]) -> float | None:
    """Fastest ACTUAL pace (s/km) across all laps with usable distance +
    duration, any band — the hard bound on what pace the run demonstrated."""
    paces = []
    for lap in laps:
        dur = lap.get("duration_seconds")
        dist = lap.get("distance_km")
        if (isinstance(dur, (int, float)) and not isinstance(dur, bool) and dur > 0
                and isinstance(dist, (int, float)) and not isinstance(dist, bool) and dist > 0):
            pace = float(dur) / float(dist)
            if pace >= _MIN_PLAUSIBLE_PACE_S_PER_KM:
                paces.append(pace)
    return min(paces) if paces else None


def _speed_effort_pace_duration(run: dict, bands: list[str], threshold_pace) -> tuple[float | None, float | None]:
    """Resolve the best hard-effort (pace_s_per_km, duration_s) for a run.

    Precedence:
      0. Qualifying MANUAL laps (Stryd lap-button reps) → their real pace +
         total duration — reps are invisible inside 1 km auto-splits.
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
    # MANUAL laps first (Stryd lap-button reps, run["manual_laps"], already
    # band-classified by the caller): short reps are invisible inside 1 km
    # auto-splits — a 2-min rep at 4:30/km dilutes to a ~6:15/km split and
    # never classifies hard. When the athlete marked reps, those ARE the
    # speed demonstration; sum the qualifying ones (same plausibility filter).
    manual = _qualifying_laps(run.get("manual_laps") or [], bands)
    m_pace, m_dur = _lap_pace_and_duration(manual)
    if m_pace is not None and m_dur and m_dur > 0:
        return m_pace, m_dur

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
        #
        # GUARDED (2026-07-10): this conversion assumes flat ground. On an
        # incline the power spike is real but the flat-equivalent PACE it
        # implies was never run — seen live: a 6% uphill interval session
        # (best real lap 6:16/km) fabricated a 4:14/km "sustained effort"
        # from a 112-second 1.3× power window and scored perf 62.6; another
        # easy run scored a perfect 100.0 the same way. Two guards:
        #   1. windows shorter than _MIN_POWER_FALLBACK_WINDOW_S can't
        #      define the run's speed effort at all;
        #   2. the fabricated pace can never be FASTER than the fastest
        #      pace the run actually demonstrated (best real lap, else the
        #      run average) — the speed score anchors demonstrated pace,
        #      and an uphill power surge demonstrates no flat pace.
        if duration_s < _MIN_POWER_FALLBACK_WINDOW_S:
            return None, None
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
                    fastest_real = _fastest_real_lap_pace(run.get("laps") or [])
                    if fastest_real is None:
                        fastest_real = avg_run_pace
                    effort_pace = max(effort_pace, fastest_real)
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
