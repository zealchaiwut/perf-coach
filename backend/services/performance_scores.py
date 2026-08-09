"""Athlete performance score compute — worker-safe (no backend.main import)."""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta, timezone as _timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import PerformanceScoreHistory, Race, SummaryCache, User, UserPreferences, Workout, WorkoutSplit
from backend.services.duration_curve_best_effort import get_athlete_duration_curve
from backend.services.performance_constants import NEEDS_THRESHOLDS_REASON as _NEEDS_THRESHOLDS_REASON
from backend.services.workout_perf_helpers import classified_manual_laps_map, planned_duration_map

_performance_log = logging.getLogger(__name__)


def _latest_race_perf(session, user_id, as_of=None) -> dict | None:
    """Race VDOT-band perf point for the score re-anchor (proposal §4.3).

    Latest finished race (status='done' AND actual_time_seconds NOT NULL) by
    **race_date** — §4.3 anchors on the most recently *run* race, not the most
    recently edited row (ordering by updated_at let a back-filled older race
    steal the anchor from a newer one entered seconds earlier). updated_at is
    the tie-breaker for same-day races. Returns ``{"perf": float, "date":
    "YYYY-MM-DD"}`` on the universal VDOT band, or None when there is no usable
    race. When ``as_of`` is given, only races on/before that date are considered
    (for the as-of helper).
    """
    from backend.services.vdot import vdot_from_pace_duration, rescale_to_score

    q = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.status == "done",
            Race.actual_time_seconds.isnot(None),
            Race.distance_km.isnot(None),
        )
    )
    if as_of is not None:
        q = q.filter(Race.race_date <= as_of)
    race = q.order_by(Race.race_date.desc().nulls_last(), Race.updated_at.desc()).first()
    if race is None:
        return None
    try:
        dist_km = float(race.distance_km)
        secs = int(race.actual_time_seconds)
    except (TypeError, ValueError):
        return None
    if dist_km <= 0 or secs <= 0:
        return None
    velocity_m_per_min = (dist_km * 1000.0) / (secs / 60.0)
    duration_min = secs / 60.0
    perf = rescale_to_score(vdot_from_pace_duration(velocity_m_per_min, duration_min))
    return {"perf": perf, "date": race.race_date.isoformat() if race.race_date else None}


def _check_needs_thresholds(preferences) -> bool:
    """Return True when none of the three threshold values are set in preferences.

    Checks ftp_w, threshold_hr, and threshold_pace_seconds_per_km. Returns True
    when preferences is None or all three keys are absent or None.
    """
    if preferences is None:
        return True
    return not any(
        preferences.get(k) is not None
        for k in ("ftp_w", "threshold_hr", "threshold_pace_seconds_per_km")
    )


def _determine_performance_top_level_state(endurance_result, speed_result) -> str:
    """Return the top-level state string from both score results (issue #1020).

    Returns 'building_baseline' if either score signals it; returns 'scored'
    when both carry a numeric score field.  Caller is responsible for the
    'needs_thresholds' early-return and the 'error' try/except wrapping.
    """
    endurance_state = endurance_result.get("state") if isinstance(endurance_result, dict) else None
    speed_state = speed_result.get("state") if isinstance(speed_result, dict) else None

    if endurance_state == "building_baseline" or speed_state == "building_baseline":
        return "building_baseline"

    endurance_score = endurance_result.get("score") if isinstance(endurance_result, dict) else None
    speed_score = speed_result.get("score") if isinstance(speed_result, dict) else None
    if isinstance(endurance_score, (int, float)) and isinstance(speed_score, (int, float)):
        return "scored"

    # Unexpected shape (e.g. score: None from missing input) — treat as building_baseline
    return "building_baseline"


def _compute_perf_block_delta(today_score: float, block_start_score: float) -> float:
    """Return today_score − block_start_score (absolute scale, same formula version)."""
    return today_score - block_start_score


def _fetch_perf_block_delta(
    session,
    user_id,
    today,
    window_days: int,
    current_score: float,
    current_formula_version: str,
    score_type: str,
):
    """Query performance_score_history for the row at block_start_date.

    Returns the block delta (float) when a matching-version row exists at
    today - window_days, or None when history doesn't reach back that far or
    the formula version differs (version-mixing guard).

    score_type: 'endurance' | 'speed' — which column to read from the row.
    """
    from backend.models import PerformanceScoreHistory
    block_start = today - _timedelta(days=window_days)
    row = (
        session.query(PerformanceScoreHistory)
        .filter(
            PerformanceScoreHistory.user_id == user_id,
            PerformanceScoreHistory.score_date <= block_start,
            PerformanceScoreHistory.formula_version == current_formula_version,
        )
        .order_by(
            PerformanceScoreHistory.score_date.desc(),
            PerformanceScoreHistory.created_at.desc(),
        )
        .first()
    )
    if row is None:
        return None
    # Version-mixing guard: reject rows produced by a different formula version
    # even if they somehow passed the query filter (e.g. in tests with mock sessions).
    if getattr(row, "formula_version", None) != current_formula_version:
        return None
    block_start_score = getattr(row, score_type, None)
    if block_start_score is None:
        return None
    return _compute_perf_block_delta(current_score, block_start_score)


def _upsert_perf_score_history(
    session,
    user_id,
    score_date,
    endurance,
    speed,
    formula_version: str,
) -> None:
    """Upsert today's endurance/speed scores into performance_score_history.

    Idempotent: recomputing scores on the same day updates the row rather
    than inserting a duplicate (unique constraint on user_id+score_date+formula_version).
    Only called for the 'scored' state so null-score rows are never persisted.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.models import PerformanceScoreHistory
    try:
        stmt = pg_insert(PerformanceScoreHistory).values(
            user_id=user_id,
            score_date=score_date,
            endurance=float(endurance) if endurance is not None else None,
            speed=float(speed) if speed is not None else None,
            formula_version=formula_version,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_performance_score_history_user_date_version",
            set_={"endurance": stmt.excluded.endurance, "speed": stmt.excluded.speed},
        )
        session.execute(stmt)
        session.commit()
    except Exception:
        _performance_log.warning(
            "Failed to upsert performance_score_history for user %s on %s",
            user_id,
            score_date,
            exc_info=True,
        )
        session.rollback()


def _get_perf_history_sparkline(session, user_id, today, window_days: int, formula_version: str):
    """Return (dates, endurance_values, speed_values) from performance_score_history.

    Reads rows for [today - window_days, today] with the current formula_version,
    ordered oldest-first. Returns ([], [], []) when no rows exist (caller falls back
    to in-request trend computation).
    """
    from backend.models import PerformanceScoreHistory
    cutoff = today - _timedelta(days=window_days)
    rows = (
        session.query(PerformanceScoreHistory)
        .filter(
            PerformanceScoreHistory.user_id == user_id,
            PerformanceScoreHistory.score_date >= cutoff,
            PerformanceScoreHistory.score_date <= today,
            PerformanceScoreHistory.formula_version == formula_version,
        )
        .order_by(PerformanceScoreHistory.score_date.asc())
        .all()
    )
    dates = [r.score_date.isoformat() for r in rows]
    endurance_vals = [r.endurance for r in rows]
    speed_vals = [r.speed for r in rows]
    return dates, endurance_vals, speed_vals


def _build_performance_response(
    state: str,
    endurance,
    speed,
    generated_at: str,
    reason: str | None = None,
) -> dict:
    """Assemble the canonical top-level performance response dict (issue #1020).

    Always includes state, endurance, speed, and generated_at.  The optional
    reason field is only included for state='error'.
    """
    body: dict = {
        "state": state,
        "endurance": endurance,
        "speed": speed,
        "generated_at": generated_at,
    }
    if reason is not None:
        body["reason"] = reason
    return body


def _build_performance_log_entry(
    preferences,
    runs,
    endurance,
    speed,
):
    """Assemble a structured log dict for the performance endpoint.

    All field access is guarded — this function must never raise even when
    preferences is None, runs is empty, or score dicts are missing keys.
    """
    user_preferences_found = preferences is not None

    if preferences is not None:
        ftp_w_present = bool(preferences.get("ftp_w") is not None)
        threshold_hr_present = bool(preferences.get("threshold_hr") is not None)
        threshold_pace_present = bool(preferences.get("threshold_pace_seconds_per_km") is not None)
    else:
        ftp_w_present = None
        threshold_hr_present = None
        threshold_pace_present = None

    runs_assembled_count = len(runs) if runs else 0
    laps_with_band_count = 0
    total_laps_count = 0
    for run in (runs or []):
        laps = run.get("laps") or [] if isinstance(run, dict) else []
        total_laps_count += len(laps)
        laps_with_band_count += sum(1 for lap in laps if lap.get("band") is not None)

    def _score_shape(result):
        if not isinstance(result, dict):
            return "null"
        if result.get("state") == "needs_thresholds":
            return "needs_thresholds"
        if result.get("state") == "building_baseline":
            return "building_baseline"
        score = result.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            return "numeric"
        reason = result.get("reason") or ""
        if isinstance(reason, str) and reason.startswith("missing:"):
            return "missing-input"
        return "null"

    return {
        "event": "performance_score_computed",
        "user_preferences_found": user_preferences_found,
        "ftp_w_present": ftp_w_present,
        "threshold_hr_present": threshold_hr_present,
        "threshold_pace_seconds_per_km_present": threshold_pace_present,
        "runs_assembled_count": runs_assembled_count,
        "laps_with_band_count": laps_with_band_count,
        "total_laps_count": total_laps_count,
        "endurance_result_shape": _score_shape(endurance),
        "speed_result_shape": _score_shape(speed),
    }


def _build_performance_diagnostic(preferences, runs):
    """Return the 8 flat diagnostic keys required by issue #1018.

    Unconditionally safe — never raises even when preferences is None or runs is empty.
    Called at INFO level on every request to GET /api/athletes/{id}/performance so
    the values are always visible in UAT logs without requiring DEBUG log level.
    """
    _runs = runs or []

    runs_considered = len(_runs)
    runs_with_laps = sum(1 for r in _runs if r.get("laps"))
    laps_total = sum(len(r.get("laps") or []) for r in _runs)
    laps_with_band = sum(
        1 for r in _runs
        for lap in (r.get("laps") or [])
        if lap.get("band") is not None
    )

    if preferences is not None:
        thresholds_present = any(
            preferences.get(k) is not None
            for k in ("ftp_w", "threshold_hr", "threshold_pace_seconds_per_km")
        )
        ftp_present = preferences.get("ftp_w") is not None
        threshold_hr_present = preferences.get("threshold_hr") is not None
        threshold_pace_present = preferences.get("threshold_pace_seconds_per_km") is not None
    else:
        thresholds_present = False
        ftp_present = False
        threshold_hr_present = False
        threshold_pace_present = False

    return {
        "runs_considered": runs_considered,
        "runs_with_laps": runs_with_laps,
        "laps_total": laps_total,
        "laps_with_band": laps_with_band,
        "thresholds_present": thresholds_present,
        "ftp_present": ftp_present,
        "threshold_hr_present": threshold_hr_present,
        "threshold_pace_present": threshold_pace_present,
    }



def get_performance_payload(user_id: _uuid.UUID, *, generated_at: str | None = None) -> dict:
    """Return endurance and speed performance scores for an athlete (issue #1020).

    Every response includes exactly these top-level keys: state, endurance, speed,
    generated_at.  The state field is always one of: scored, needs_thresholds,
    building_baseline, error.

    HTTP 200 for scored, needs_thresholds, and building_baseline.
    HTTP 500 for unexpected server-side failures (state='error').
    HTTP 404 when the athlete ID does not exist — body uses _build_performance_response
    so the canonical shape (including state key) is always present (issue #1027).
    """
    if generated_at is None:
        generated_at = _datetime.now(_timezone.utc).isoformat()

    uid = user_id
    from backend.services.running_performance import compute_endurance_score, compute_speed_score
    from backend.services.zone_constants import make_zone_constants
    from backend.services.lap_classify import classify_laps

    try:
        from backend.services.aerobic_decoupling import compute_decoupling
    except ImportError:
        compute_decoupling = None

    try:
        with Session(engine) as session:
            athlete = session.get(User, uid)
            if athlete is None:
                return _build_performance_response(
                        state="error",
                        endurance=None,
                        speed=None,
                        generated_at=generated_at,
                        reason="athlete not found",
                    )

            # Load user preferences; None means preferences row absent
            prefs_row = (
                session.query(UserPreferences)
                .filter(UserPreferences.user_id == uid)
                .first()
            )
            if prefs_row is not None:
                preferences = {
                    "ftp_w": prefs_row.ftp_w,
                    "threshold_hr": prefs_row.threshold_hr,
                    "threshold_pace_seconds_per_km": prefs_row.threshold_pace_seconds_per_km,
                    # aerobic_decoupling_threshold added by migration d915ffcb4c0c
                    "aerobic_decoupling_threshold": getattr(prefs_row, "aerobic_decoupling_threshold", None),
                    "duration_curve_bests": None,
                }
            else:
                preferences = None

            # Load duration-curve bests so speed score can reference them
            curve_data = get_athlete_duration_curve(uid, session)
            if preferences is not None:
                preferences["duration_curve_bests"] = curve_data or {}

            # Performance-score cache (issue: cacheable scores, same model as the
            # weekly/monthly summaries). Recompute only when a new workout is
            # synced (signature changes) or a threshold/preference input the
            # score depends on changes — not on every page load.
            _perf_sig = _performance_signature(session, uid, prefs_row)
            _perf_cached = _summary_cache_get(uid, "performance", _perf_sig)
            if _perf_cached is not None:
                _performance_log.info("performance cache hit for %s", uid)
                return _perf_cached

            # Load run workouts within the scoring window (issue #1578: cap
            # history to bound in-request memory on cache miss).
            _history_cutoff = _datetime.now(_timezone.utc).date() - _timedelta(days=_RUN_HISTORY_CAP_DAYS)
            run_workouts = (
                session.query(Workout)
                .filter(
                    Workout.user_id == uid,
                    Workout.workout_type == "run",
                    Workout.workout_date >= _history_cutoff,
                )
                .order_by(Workout.workout_date.asc(), Workout.start_time.asc().nulls_last())
                .all()
            )

            prefs_dict = preferences or {}
            _ml_map_perf = classified_manual_laps_map(session, run_workouts, prefs_dict)

            # Batch-load all splits for the qualifying runs in one query
            # (issue #1578: replaces N sequential per-workout queries → 1 query).
            _run_ids = [w.id for w in run_workouts]
            _pdc_map_perf = planned_duration_map(session, _run_ids)
            if _run_ids:
                _all_splits = (
                    session.query(WorkoutSplit)
                    .filter(WorkoutSplit.workout_id.in_(_run_ids))
                    .order_by(WorkoutSplit.workout_id, WorkoutSplit.split_index)
                    .all()
                )
            else:
                _all_splits = []
            _splits_by_workout: dict = {}
            for _s in _all_splits:
                _splits_by_workout.setdefault(_s.workout_id, []).append(_s)

            runs = []
            for workout in run_workouts:
                splits = _splits_by_workout.get(workout.id, [])

                # Classify lap intensity bands using user thresholds
                classifications = classify_laps(splits, prefs_dict)

                # Build lap dicts with classification bands
                laps = []
                for split, cls in zip(splits, classifications):
                    laps.append({
                        "band": cls.get("band"),
                        "avg_power": split.avg_power,
                        "avg_hr": split.avg_hr,
                        "distance_km": float(split.distance_km) if split.distance_km is not None else None,
                        "duration_seconds": split.duration_seconds,
                    })

                # Compute aerobic decoupling for this run (back-half vs front-half
                # efficiency) using plain dicts so compute_decoupling stays pure
                decoupling_pct = None
                if compute_decoupling is not None:
                    split_dicts = [
                        {
                            "split_index": s.split_index,
                            "duration_seconds": s.duration_seconds,
                            "avg_hr": s.avg_hr,
                            "avg_power": s.avg_power,
                            "distance_km": float(s.distance_km) if s.distance_km is not None else None,
                        }
                        for s in splits
                    ]
                    decoupling_result, _ = compute_decoupling(
                        {"workout_type": workout.workout_type},
                        split_dicts,
                        prefs_dict.get("aerobic_decoupling_threshold"),
                    )
                    decoupling_pct = (
                        decoupling_result.get("decoupling_pct")
                        if decoupling_result
                        else None
                    )

                runs.append({
                    "run_id": str(workout.id),
                    "workout_date": workout.workout_date.isoformat() if workout.workout_date else "",
                    "laps": laps,
                    "decoupling_pct": decoupling_pct,
                    "avg_power": workout.avg_power,
                    "avg_hr": workout.avg_hr,
                    "distance_km": float(workout.distance_km) if workout.distance_km is not None else None,
                    "duration_seconds": workout.duration_seconds,
                    # Pre-computed speed signal (issue #1048): the best hard-effort
                    # intensity ratio + its basis/window, used by compute_speed_score
                    # to derive the effort pace when the reps aren't in the splits.
                    "speed_signal": workout.speed_signal,
                    "speed_signal_basis": workout.speed_signal_basis,
                    "speed_signal_window_seconds": workout.speed_signal_window_seconds,
                    # Stryd lap-button reps — precedence 0 in the speed-effort
                    # extraction (short reps are invisible in 1 km auto-splits).
                    "manual_laps": _ml_map_perf.get(workout.id, []),
                    "ftp_w": (prefs_dict or {}).get("ftp_w"),
                    "planned_duration_seconds": _pdc_map_perf.get(workout.id),
                })

        # All DB access is finished above.  The pure functions below perform no I/O.

        # AC #1018: unconditional INFO-level diagnostic log — fires on every request so
        # UAT logs always contain the 8 flat keys needed to diagnose scoring failures.
        _performance_log.info(
            "performance diagnostic",
            extra=_build_performance_diagnostic(preferences=preferences, runs=runs),
        )

        # AC #912 / #1020: check for missing thresholds; return top-level state field.
        if _check_needs_thresholds(preferences):
            _needs_thresholds_obj = {
                "state": "needs_thresholds",
                "reason": _NEEDS_THRESHOLDS_REASON,
            }
            if _performance_log.isEnabledFor(logging.INFO):
                log_entry = _build_performance_log_entry(
                    preferences=preferences,
                    runs=runs,
                    endurance=_needs_thresholds_obj,
                    speed=_needs_thresholds_obj,
                )
                _performance_log.info("performance score request", extra=log_entry)
            return _build_performance_response(
                    state="needs_thresholds",
                    endurance=None,
                    speed=None,
                    generated_at=generated_at,
                )

        zone_constants = make_zone_constants()
        # Race VDOT-band perf point (pool point + decayed floor) — score re-anchor.
        with Session(engine) as _race_session:
            _race_perf = _latest_race_perf(_race_session, uid)
        from backend.services.body_modifier import get_body_modifier_for_user as _get_bm
        _bm = _get_bm(uid)
        endurance = compute_endurance_score(runs, preferences, zone_constants, race_perf=_race_perf, body_modifier=_bm)
        speed = compute_speed_score(runs, preferences, zone_constants, race_perf=_race_perf, body_modifier=_bm)

        if _performance_log.isEnabledFor(logging.INFO):
            log_entry = _build_performance_log_entry(
                preferences=preferences,
                runs=runs,
                endurance=endurance,
                speed=speed,
            )
            _performance_log.info("performance score request", extra=log_entry)

        # Endurance requires threshold_hr (HR extrapolation); surface its
        # needs_thresholds sub-state as the top-level state.
        if isinstance(endurance, dict) and endurance.get("state") == "needs_thresholds":
            return _build_performance_response(
                    state="needs_thresholds",
                    endurance=None,
                    speed=None,
                    generated_at=generated_at,
                )

        top_state = _determine_performance_top_level_state(endurance, speed)

        if top_state == "building_baseline":
            return _build_performance_response(
                    state="building_baseline",
                    endurance=None,
                    speed=None,
                    generated_at=generated_at,
                )

        # ── Persist scores + compute history-based block delta (issue #1365) ──
        today_date = _datetime.now(_timezone.utc).date()
        end_score = endurance.get("score") if isinstance(endurance, dict) else None
        spd_score = speed.get("score") if isinstance(speed, dict) else None
        from backend.services.running_performance import BREAKDOWN_WINDOW_DAYS as _BW_DAYS
        with Session(engine) as _hist_session:
            # Write-through: upsert today's scores so history grows each compute.
            if end_score is not None or spd_score is not None:
                _upsert_perf_score_history(
                    session=_hist_session,
                    user_id=uid,
                    score_date=today_date,
                    endurance=end_score,
                    speed=spd_score,
                    formula_version=_PERF_FORMULA_VERSION,
                )
            # Block delta: today − score at block_start (same formula_version only).
            end_block_delta = None
            spd_block_delta = None
            if end_score is not None:
                end_block_delta = _fetch_perf_block_delta(
                    session=_hist_session,
                    user_id=uid,
                    today=today_date,
                    window_days=_BW_DAYS,
                    current_score=end_score,
                    current_formula_version=_PERF_FORMULA_VERSION,
                    score_type="endurance",
                )
            if spd_score is not None:
                spd_block_delta = _fetch_perf_block_delta(
                    session=_hist_session,
                    user_id=uid,
                    today=today_date,
                    window_days=_BW_DAYS,
                    current_score=spd_score,
                    current_formula_version=_PERF_FORMULA_VERSION,
                    score_type="speed",
                )
            # History sparkline: persisted series for the last BREAKDOWN_WINDOW_DAYS.
            hist_dates, hist_end, hist_spd = _get_perf_history_sparkline(
                session=_hist_session,
                user_id=uid,
                today=today_date,
                window_days=_BW_DAYS,
                formula_version=_PERF_FORMULA_VERSION,
            )

        # Inject block_delta and history_trend into the score dicts (copies).
        if isinstance(endurance, dict):
            endurance = dict(endurance)
            endurance["block_delta"] = round(end_block_delta, 2) if end_block_delta is not None else None
            if hist_dates:
                endurance["history_trend"] = hist_end
                endurance["history_trend_dates"] = hist_dates
        if isinstance(speed, dict):
            speed = dict(speed)
            speed["block_delta"] = round(spd_block_delta, 2) if spd_block_delta is not None else None
            if hist_dates:
                speed["history_trend"] = hist_spd
                speed["history_trend_dates"] = hist_dates

        _scored_payload = _build_performance_response(
            state="scored",
            endurance=endurance,
            speed=speed,
            generated_at=generated_at,
        )
        # Cache the computed scored payload; the signature invalidates it when a
        # sync inserts/updates workouts or a relevant threshold changes.
        _summary_cache_put(uid, "performance", _perf_sig, _scored_payload)
        _performance_log.info("performance cache miss (computed) for %s", uid)
        return _scored_payload

    except Exception:
        _performance_log.exception("unexpected error in performance endpoint")
        return _build_performance_response(
                state="error",
                endurance=None,
                speed=None,
                generated_at=generated_at,
                reason="unexpected server error",
            )
# In-process cache for the log-tab summaries: recompute only when new workouts
# arrive (a sync) or the period rolls over — otherwise reuse the last result
# (summary was recomputed every load). Signature-invalidation like the plan
# cache; in-memory (re-warms after a restart, which is fine — idempotent).
_SUMMARY_CACHE: dict = {}


def _l1_cacheable(key: str) -> bool:
    """Whether ``key`` is safe to hold in the unbounded in-process L1 dict.

    Fixed keys ("performance", "weekly") are bounded by the number of active
    users — fine. "monthly:<iso-date>" keys are not: every distinct month a
    user has ever viewed adds a permanent entry for the life of the process,
    since only a restart clears L1. Those keys still get the durable L2 table
    (``summary_cache``), just not the in-process dict — a slightly slower
    cache hit (one query) instead of unbounded process memory growth.
    """
    return not key.startswith("monthly:")


def _summary_signature(session, user_id) -> str:
    row = (
        session.query(
            func.max(Workout.created_at),
            func.count(Workout.id),
            func.max(Workout.updated_at),
        )
        .filter(Workout.user_id == user_id)
        .one()
    )
    # Include MAX(updated_at) so an in-place edit (e.g. marking a run as an
    # interval) — which changes updated_at but not created_at/count — still
    # busts the cache and refreshes the derived scores/feeds.
    return "%s|%s|%s" % (row[0], row[1], row[2])


def _summary_cache_get(user_id, key, sig):
    """Two-level cache read: in-memory L1, then durable Neon L2.

    L1 (``_SUMMARY_CACHE``) is the fast per-process path — but only for
    ``_l1_cacheable`` keys (see that function). On an L1 miss (e.g. the first
    request after a restart wiped L1, or an unbounded-cardinality key that
    never touches L1 at all) fall back to the ``summary_cache`` table: if a
    row exists whose stored signature matches, hydrate L1 (when cacheable)
    and return it — no recompute. Any DB error degrades gracefully to a miss
    (recompute).
    """
    cacheable = _l1_cacheable(key)
    if cacheable:
        ent = _SUMMARY_CACHE.get((str(user_id), key))
        if ent and ent[0] == sig:
            return ent[1]

    # L2: durable Neon-backed cache. A restart clears L1 but not this table.
    try:
        with Session(engine) as _s:
            row = (
                _s.query(SummaryCache.signature, SummaryCache.payload)
                .filter(
                    SummaryCache.user_id == user_id,
                    SummaryCache.cache_key == key,
                )
                .first()
            )
        if row is not None and row[0] == sig:
            payload = row[1]
            if cacheable:
                _SUMMARY_CACHE[(str(user_id), key)] = (sig, payload)  # hydrate L1
            return payload
    except Exception:
        _performance_log.exception("summary_cache L2 read failed for %s/%s", user_id, key)
    return None


def _summary_cache_put(user_id, key, sig, payload):
    """Two-level cache write: set L1 (if bounded), then UPSERT the durable L2 row.

    A DB failure on the L2 write must not break the request — L1 still serves
    within the process (when the key is L1-cacheable); the durable row simply
    refreshes on the next compute.
    """
    if _l1_cacheable(key):
        _SUMMARY_CACHE[(str(user_id), key)] = (sig, payload)
    try:
        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        stmt = _pg_insert(SummaryCache.__table__).values(
            user_id=user_id,
            cache_key=key,
            signature=sig,
            payload=payload,
            updated_at=_datetime.now(_timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "cache_key"],
            set_={
                "signature": stmt.excluded.signature,
                "payload": stmt.excluded.payload,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        with Session(engine) as _s:
            _s.execute(stmt)
            _s.commit()
    except Exception:
        _performance_log.exception("summary_cache L2 write failed for %s/%s", user_id, key)


# Bump whenever the score FORMULA changes so BOTH caches bust on deploy: the
# durable Neon summary_cache for /performance AND the plan bundle (race
# estimates read the scores, so a score-model change must invalidate the
# bundle too — learned the hard way when vdot-v11 shipped invisibly to the
# race cards).
# v2 = VDOT re-anchor; v3 = recreational band recalibration + HR exponent;
# v4 = one-score-everywhere + feed contributions; v5 = races in signature;
# v6 = run_contributions + model + consistency bonus + improve hint;
# v7 = power-fallback guards; v8 = implausible-lap filter; v9 = breakdown
# block; v10 = race_floor_now + floor_binding; v11 = manual-lap reps;
# v12 = aborted-session guard (MIN_ENDURANCE_QUALIFYING_SESSION_SECONDS);
# v13 = endurance calibration: exponent 1.5→2.5, durability /50→/100 (#1331).
_PERF_FORMULA_VERSION = "vdot-v13"

# History window cap for the cold-cache run load (issue #1578).
# trailing_window_days=90: only runs within 90d of the most-recent run affect
# scores. Adding a 310d buffer handles users who last ran up to 400 days ago;
# beyond that all runs are outside the scoring window and the endpoint returns
# building_baseline regardless.  Peak memory on a 512 MB dyno with this cap:
# ≤ ~400 runs × ~2 KB/run dict ≈ 0.8 MB for the runs list, well under the OOM
# threshold observed in the 2026-07-22 incident (PR #1576 follow-up #1578).
_RUN_HISTORY_CAP_DAYS = 400


def _performance_signature(session, user_id, prefs_row) -> str:
    """Cache signature for the Endurance/Speed performance scores.

    Combines the workout-set signature (MAX(created_at) + count for the athlete —
    a sync that inserts/updates any workout bumps created_at) with the race-set
    signature (MAX(updated_at) + count — the race anchor/floor feeds the scores,
    so adding or editing a race must recompute them) and the threshold/preference
    inputs the score compute depends on (FTP, threshold HR, threshold pace,
    aerobic-decoupling threshold). Any of these changing recomputes the scores;
    otherwise repeat loads reuse the cached payload.
    """
    # Formula-version token: _PERF_FORMULA_VERSION (module level, shared with
    # the plan-bundle signature).
    base = _summary_signature(session, user_id)
    race_row = (
        session.query(func.max(Race.updated_at), func.count(Race.id))
        .filter(Race.user_id == user_id)
        .one()
    )
    races_part = "%s|%s" % (race_row[0], race_row[1])
    if prefs_row is not None:
        prefs_part = "%s|%s|%s|%s" % (
            getattr(prefs_row, "ftp_w", None),
            getattr(prefs_row, "threshold_hr", None),
            getattr(prefs_row, "threshold_pace_seconds_per_km", None),
            getattr(prefs_row, "aerobic_decoupling_threshold", None),
        )
    else:
        prefs_part = "no-prefs"
    return base + "|" + races_part + "|" + prefs_part + "|" + _PERF_FORMULA_VERSION
