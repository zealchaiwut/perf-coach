"""Weekly / monthly training-summary payloads — worker-safe (no backend.main).

Dashboard GETs read ``summary_cache``; this module is the write path used by
the worker precompute job and by a first-ever GET that has no cached row.
"""
from __future__ import annotations

import calendar as _calendar
import uuid as _uuid
from datetime import date as _date, timedelta as _timedelta

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import AppConfig, Race, User, UserPreferences, WeightEntry, Workout
from backend.services.guardrail import get_guardrail_result
from backend.services.summary_cache_store import (
    summary_cache_put,
    summary_signature,
)
from backend.services.training_load import (
    get_snapshot_series,
    get_weekly_volume,
    readiness_label,
)
from backend.services.workout_perf_helpers import (
    classified_manual_laps_map,
    planned_duration_map,
    splits_by_workout_map,
)
from backend.utils.log import get_logger
from backend.utils.time import today_bangkok

_log = get_logger(__name__)

_MONTHLY_SUMMARY_SAFE_LEAN_DOWN_KEY = "monthly_summary.safe_lean_down_pct_per_week"
_MONTHLY_SUMMARY_FORM_RECOVERY_THRESHOLD = 0.0
_MONTHLY_SUMMARY_SCORE_DELTA_THRESHOLD = 0.05

WEEKLY_CACHE_VERSION = "v2"


def weekly_cache_key(week_start: _date) -> str:
    return "weekly:" + week_start.isoformat()


def monthly_cache_key(month_start: _date) -> str:
    return "monthly:" + month_start.isoformat()


def _generate_weekly_note(
    session_count: int,
    distance_km,
    total_tss,
    form_tsb_change,
    workout_types: list,
) -> str:
    if session_count == 0:
        return ""

    parts = []
    type_counts: dict = {}
    for wt in workout_types:
        key = (wt or "").lower()
        type_counts[key] = type_counts.get(key, 0) + 1

    if type_counts.get("run", 0) > 0:
        run_count = type_counts["run"]
        parts.append(f"{run_count} run{'s' if run_count > 1 else ''}")

    if type_counts.get("strength", 0) > 0 or type_counts.get("lift", 0) > 0:
        parts.append("strength work")

    if distance_km and distance_km > 0:
        parts.append(f"{distance_km:.1f} km covered")

    if total_tss and total_tss > 0:
        parts.append(f"{total_tss:.0f} TSS")

    if isinstance(form_tsb_change, (int, float)):
        if form_tsb_change > 1:
            parts.append("form improving")
        elif form_tsb_change < -1:
            parts.append("building load")

    return ", ".join(parts) if parts else f"{session_count} session{'s' if session_count > 1 else ''} logged"


def compute_weekly_summary(user_id, week_start: _date) -> dict:
    """Build and persist the weekly summary payload for ``week_start`` (Monday)."""
    from backend.services.body_modifier import get_body_modifier_for_user
    from backend.services.lap_classify import classify_laps
    from backend.services.running_performance import compute_endurance_score, compute_speed_score
    from backend.services.zone_constants import make_zone_constants

    try:
        from backend.services.aerobic_decoupling import compute_decoupling
    except ImportError:
        compute_decoupling = None

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    we = week_start + _timedelta(days=6)
    today = today_bangkok()
    load_end = min(we, today)

    with Session(engine) as session:
        athlete = session.get(User, uid)
        if athlete is None:
            raise ValueError("athlete not found")

        sig = (
            summary_signature(session, uid)
            + "|"
            + week_start.isoformat()
            + "|"
            + WEEKLY_CACHE_VERSION
        )

        volume = get_weekly_volume(str(uid), week_start, we)
        session_count = volume["session_count"]
        distance_km = volume["distance_km"]
        total_tss = volume["total_tss"]
        workout_types = volume["workout_types"]

        prior_ws = week_start - _timedelta(days=7)
        prior_we = prior_ws + _timedelta(days=6)
        prior_volume = get_weekly_volume(str(uid), prior_ws, prior_we)
        distance_change_km = round(distance_km - prior_volume["distance_km"], 2)
        total_tss_change = round(total_tss - prior_volume["total_tss"], 1)
        session_count_change = session_count - prior_volume["session_count"]
        duration_seconds_change = volume["duration_seconds"] - prior_volume["duration_seconds"]

        warmup_start = week_start - _timedelta(days=180)
        load_series = get_snapshot_series(str(uid), warmup_start, load_end)

        def _tsb_at(target_date):
            for row in reversed(load_series):
                if row["date"] <= target_date:
                    return row["tsb"]
            return 0.0

        tsb_start = _tsb_at(week_start)
        tsb_end = _tsb_at(load_end)
        form_tsb_change = round(tsb_end - tsb_start, 2)
        readiness_next_week = readiness_label(tsb_end) if load_series else None

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
                "aerobic_decoupling_threshold": getattr(
                    prefs_row, "aerobic_decoupling_threshold", None
                ),
                "duration_curve_bests": None,
            }
        else:
            preferences = None

        run_workouts = (
            session.query(Workout)
            .filter(Workout.user_id == uid, Workout.workout_type == "run")
            .order_by(Workout.workout_date.asc(), Workout.start_time.asc().nulls_last())
            .all()
        )

        prefs_dict = preferences or {}
        zone_constants = make_zone_constants()
        ml_map = classified_manual_laps_map(session, run_workouts, prefs_dict)
        pdc_map = planned_duration_map(session, [w.id for w in run_workouts])
        splits_map = splits_by_workout_map(session, [w.id for w in run_workouts])
        body_modifier = get_body_modifier_for_user(uid)

        def _build_run_list(max_date):
            runs = []
            for workout in run_workouts:
                if workout.workout_date > max_date:
                    continue
                splits = splits_map.get(workout.id, [])
                classifications = classify_laps(splits, prefs_dict)
                laps = []
                for split, cls in zip(splits, classifications):
                    laps.append({
                        "band": cls.get("band"),
                        "avg_power": split.avg_power,
                        "avg_hr": split.avg_hr,
                        "distance_km": float(split.distance_km) if split.distance_km is not None else None,
                        "duration_seconds": split.duration_seconds,
                    })

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
                    try:
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
                    except Exception:
                        decoupling_pct = None

                runs.append({
                    "run_id": str(workout.id),
                    "workout_date": workout.workout_date.isoformat() if workout.workout_date else "",
                    "laps": laps,
                    "decoupling_pct": decoupling_pct,
                    "avg_power": workout.avg_power,
                    "avg_hr": workout.avg_hr,
                    "distance_km": float(workout.distance_km) if workout.distance_km is not None else None,
                    "duration_seconds": workout.duration_seconds,
                    "speed_signal": workout.speed_signal,
                    "manual_laps": ml_map.get(workout.id, []),
                    "planned_duration_seconds": pdc_map.get(workout.id),
                })
            return runs

        def _extract_score(result):
            if not isinstance(result, dict):
                return None
            score = result.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                return score
            return None

        runs_at_start = _build_run_list(week_start)
        endurance_start = _extract_score(
            compute_endurance_score(runs_at_start, preferences, zone_constants, body_modifier=body_modifier)
        )
        speed_start = _extract_score(
            compute_speed_score(runs_at_start, preferences, zone_constants, body_modifier=body_modifier)
        )

        runs_at_end = _build_run_list(load_end)
        endurance_end = _extract_score(
            compute_endurance_score(runs_at_end, preferences, zone_constants, body_modifier=body_modifier)
        )
        speed_end = _extract_score(
            compute_speed_score(runs_at_end, preferences, zone_constants, body_modifier=body_modifier)
        )

        if endurance_start is not None and endurance_end is not None:
            endurance_score_change = round(endurance_end - endurance_start, 2)
        else:
            endurance_score_change = 0.0

        if speed_start is not None and speed_end is not None:
            speed_score_change = round(speed_end - speed_start, 2)
        else:
            speed_score_change = 0.0

        weight_entries = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.entry_date >= week_start,
                WeightEntry.entry_date <= we,
            )
            .order_by(WeightEntry.entry_date.asc())
            .all()
        )

        if len(weight_entries) >= 2:
            weight_change_kg = round(
                float(weight_entries[-1].weight_kg) - float(weight_entries[0].weight_kg),
                2,
            )
        else:
            weight_change_kg = None

    note = _generate_weekly_note(
        session_count=session_count,
        distance_km=distance_km,
        total_tss=total_tss,
        form_tsb_change=form_tsb_change,
        workout_types=workout_types,
    )
    guardrail = get_guardrail_result(uid)

    payload = {
        "week_start": week_start.isoformat(),
        "week_end": we.isoformat(),
        "distance_km": distance_km,
        "total_tss": total_tss,
        "session_count": session_count,
        "duration_seconds": volume["duration_seconds"],
        "distance_change_km": distance_change_km,
        "total_tss_change": total_tss_change,
        "session_count_change": session_count_change,
        "duration_seconds_change": duration_seconds_change,
        "endurance_score_change": endurance_score_change,
        "speed_score_change": speed_score_change,
        "weight_change_kg": weight_change_kg,
        "form_tsb_change": form_tsb_change,
        "note": note,
        "readiness_next_week": readiness_next_week,
        "guardrail_state": guardrail["guardrail_state"],
        "guardrail_message": guardrail["guardrail_message"],
    }
    key = weekly_cache_key(week_start)
    summary_cache_put(uid, key, sig, payload)
    # Backward-compat key the existing GET tests and older rows used.
    summary_cache_put(uid, "weekly", sig, payload)
    return payload


def _monthly_score_delta(workouts: list) -> tuple:
    signals_with_data = [
        (w.endurance_signal, w.speed_signal)
        for w in workouts
        if w.endurance_signal is not None or w.speed_signal is not None
    ]
    if len(signals_with_data) < 2:
        return None, None

    mid = len(signals_with_data) // 2
    first_half = signals_with_data[:mid]
    second_half = signals_with_data[mid:]

    def _avg(items, idx):
        vals = [x[idx] for x in items if x[idx] is not None]
        return sum(vals) / len(vals) if vals else None

    e_start = _avg(first_half, 0)
    e_end = _avg(second_half, 0)
    s_start = _avg(first_half, 1)
    s_end = _avg(second_half, 1)

    e_delta = round(e_end - e_start, 3) if (e_start is not None and e_end is not None) else None
    s_delta = round(s_end - s_start, 3) if (s_start is not None and s_end is not None) else None
    return e_delta, s_delta


def _compute_supercompensation_state(
    endurance_delta,
    speed_delta,
    form_recovered: bool,
    threshold: float = _MONTHLY_SUMMARY_SCORE_DELTA_THRESHOLD,
) -> str:
    scores_rose = (
        (endurance_delta is not None and endurance_delta > threshold)
        or (speed_delta is not None and speed_delta > threshold)
    )
    if scores_rose and form_recovered:
        return "working"
    if not form_recovered:
        return "digging"
    return "flat"


def _compute_call_to_action(
    supercompensation_state: str,
    weight_rate_pct_per_week,
    safe_lean_down_rate: float,
) -> str:
    if (
        weight_rate_pct_per_week is not None
        and abs(weight_rate_pct_per_week) > safe_lean_down_rate
        and weight_rate_pct_per_week < 0
    ):
        return "Ease the deficit and hold load"
    if supercompensation_state == "working":
        return "Advance plyo to single-leg phase"
    if supercompensation_state == "digging":
        return "Reduce volume and prioritize sleep"
    return "Maintain load and monitor recovery"


def _app_config(key: str, default: str) -> str:
    with Session(engine) as session:
        row = session.get(AppConfig, key)
        return row.value if row else default


class NoMonthlySessions(Exception):
    """No workouts in the requested month — GET maps this to HTTP 424."""


def compute_monthly_summary(user_id, month_start: _date) -> dict:
    """Build and persist the monthly summary payload. Raises NoMonthlySessions."""
    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    last_day = _calendar.monthrange(month_start.year, month_start.month)[1]
    month_end = month_start.replace(day=last_day)
    today = today_bangkok()

    with Session(engine) as session:
        athlete = session.get(User, uid)
        if athlete is None:
            raise ValueError("athlete not found")

        mkey = monthly_cache_key(month_start)
        msig = summary_signature(session, uid)

        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= month_start,
                Workout.workout_date <= month_end,
            )
            .order_by(Workout.workout_date)
            .all()
        )
        if not workouts:
            raise NoMonthlySessions(month_start)

        weight_entries = (
            session.query(WeightEntry)
            .filter(
                WeightEntry.user_id == uid,
                WeightEntry.entry_date >= month_start,
                WeightEntry.entry_date <= month_end,
            )
            .order_by(WeightEntry.entry_date)
            .all()
        )
        races = (
            session.query(Race)
            .filter(
                Race.user_id == uid,
                Race.race_type == "checkpoint",
                Race.race_date > today,
            )
            .order_by(Race.race_date)
            .all()
        )

        session_count = len(workouts)

        def _safe_sum(items, attr):
            vals = []
            for item in items:
                v = getattr(item, attr, None)
                if v is not None:
                    try:
                        vals.append(float(v))
                    except (TypeError, ValueError):
                        pass
            return round(sum(vals), 3) if vals else 0.0

        distance_km = _safe_sum(workouts, "distance_km")
        total_tss = _safe_sum(workouts, "tss")
        duration_seconds = _safe_sum(workouts, "duration_seconds")
        endurance_score_change, speed_score_change = _monthly_score_delta(workouts)

        weight_change_kg = None
        weight_rate_percent_per_week = None
        if len(weight_entries) >= 2:
            first_w = float(weight_entries[0].weight_kg)
            last_w = float(weight_entries[-1].weight_kg)
            weight_change_kg = round(last_w - first_w, 3)
            span_days = (weight_entries[-1].entry_date - weight_entries[0].entry_date).days
            if span_days > 0 and first_w > 0:
                weeks = span_days / 7.0
                rate_pct = (weight_change_kg / first_w) * 100.0 / weeks
                weight_rate_percent_per_week = round(rate_pct, 3)

        month_entries = get_snapshot_series(str(uid), month_start, min(month_end, today))
        if month_entries:
            ctl_at_start = month_entries[0]["ctl"]
            ctl_at_end = month_entries[-1]["ctl"]
            tsb_at_end = month_entries[-1]["tsb"]
        else:
            ctl_at_start = 0.0
            ctl_at_end = 0.0
            tsb_at_end = 0.0

        fitness_ctl_change = round(ctl_at_end - ctl_at_start, 2)
        form_recovered = tsb_at_end >= _MONTHLY_SUMMARY_FORM_RECOVERY_THRESHOLD
        supercompensation_state = _compute_supercompensation_state(
            endurance_score_change, speed_score_change, form_recovered
        )
        raw_safe_rate = _app_config(_MONTHLY_SUMMARY_SAFE_LEAN_DOWN_KEY, "1.0")
        try:
            safe_lean_down_rate = float(raw_safe_rate)
        except (TypeError, ValueError):
            safe_lean_down_rate = 1.0
        call_to_action = _compute_call_to_action(
            supercompensation_state, weight_rate_percent_per_week, safe_lean_down_rate
        )

        next_checkpoint = None
        upcoming = [r for r in races if r.race_date > today and r.race_type == "checkpoint"]
        if upcoming:
            nearest = min(upcoming, key=lambda r: r.race_date)
            next_checkpoint = {
                "name": nearest.name,
                "date": nearest.race_date.isoformat(),
            }

        guardrail = get_guardrail_result(uid)

        payload = {
            "month_start": month_start.isoformat(),
            "month_end": month_end.isoformat(),
            "distance_km": distance_km,
            "total_tss": total_tss,
            "session_count": session_count,
            "duration_seconds": duration_seconds,
            "endurance_score_change": endurance_score_change,
            "speed_score_change": speed_score_change,
            "weight_change_kg": weight_change_kg,
            "weight_rate_percent_per_week": weight_rate_percent_per_week,
            "fitness_ctl_change": fitness_ctl_change,
            "form_recovered": form_recovered,
            "supercompensation_state": supercompensation_state,
            "call_to_action": call_to_action,
            "next_checkpoint": next_checkpoint,
            "guardrail_state": guardrail["guardrail_state"],
            "guardrail_message": guardrail["guardrail_message"],
        }
        summary_cache_put(uid, mkey, msig, payload)
        return payload
