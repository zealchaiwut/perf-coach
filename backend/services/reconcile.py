"""Reconcile source activities (Strava, Stryd) into unified workout rows."""
from __future__ import annotations

import uuid as _uuid
from datetime import date, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session as _Session


_TOLERANCE = timedelta(minutes=5)


def _find_in_memory(start_time, workouts: list, tolerance: timedelta):
    """In-memory match against pre-loaded workout list — no per-activity DB query."""
    if start_time is None:
        return None
    lower = start_time - tolerance
    upper = start_time + tolerance
    candidates = [w for w in workouts if w.start_time and lower <= w.start_time <= upper]
    if not candidates:
        return None
    return min(candidates, key=lambda w: abs((w.start_time - start_time).total_seconds()))


def _make_proxy(act, source_type: str, existing_workout=None) -> SimpleNamespace:
    """Build a SimpleNamespace compatible with compute_best_values."""
    ow = existing_workout
    return SimpleNamespace(
        manual_overrides=getattr(ow, "manual_overrides", None) if ow else None,
        strava_activity=act if source_type == "strava" else None,
        stryd_activity=act if source_type == "stryd" else None,
        distance_km=float(ow.distance_km) if ow and getattr(ow, "distance_km", None) is not None else None,
        duration_seconds=getattr(ow, "duration_seconds", None) if ow else None,
        avg_hr=getattr(ow, "avg_hr", None) if ow else None,
        avg_power_w=None,
        tss=getattr(ow, "tss", None) if ow else None,
        name=getattr(ow, "name", None) if ow else None,
    )


def _apply_best(workout, best: dict) -> None:
    if best.get("best_name"):
        workout.name = best["best_name"]
    if best.get("best_distance_km") is not None:
        workout.distance_km = best["best_distance_km"]
    if best.get("best_duration_seconds") is not None:
        workout.duration_seconds = best["best_duration_seconds"]
    if best.get("best_avg_hr") is not None:
        from backend.services.workout_merge import clean_hr

        hr = clean_hr(best["best_avg_hr"])
        if hr is not None:
            workout.avg_hr = hr
    if best.get("best_tss") is not None:
        workout.tss = best["best_tss"]


def _apply_stryd_metrics(workout, act) -> None:
    """Copy workout-level Stryd power/cadence/stride aggregates onto the workout."""
    fm = getattr(act, "form_metrics", None) or {}
    if getattr(act, "avg_power_w", None) is not None:
        workout.avg_power = int(act.avg_power_w)
    if fm.get("max_power_w") is not None:
        workout.max_power = int(fm["max_power_w"])
    if fm.get("np_w") is not None:
        workout.np = int(fm["np_w"])
    if fm.get("cadence_spm") is not None:
        workout.avg_cadence_spm = int(round(fm["cadence_spm"]))
    if fm.get("stride_length_m") is not None:
        workout.avg_stride_m = round(float(fm["stride_length_m"]), 2)


def _sync_splits(session, workout, act) -> None:
    """Replace a workout's splits from the Stryd activity's computed km-splits."""
    from backend.models import WorkoutSplit
    splits = getattr(act, "splits", None)
    if not isinstance(splits, list) or not splits or not isinstance(splits[0], dict):
        return
    session.query(WorkoutSplit).filter(WorkoutSplit.workout_id == workout.id).delete()
    session.flush()
    # Index by position (1-based) so it is always unique, regardless of the
    # source dict's own index field. Fields read defensively across split shapes.
    for i, s in enumerate(splits, start=1):
        session.add(WorkoutSplit(
            workout_id=workout.id,
            split_index=i,
            distance_km=s.get("distance_km") or 0,
            duration_seconds=s.get("duration_seconds") or 0,
            avg_hr=s.get("avg_hr"),
            avg_power=s.get("avg_power") if s.get("avg_power") is not None else s.get("avg_power_w"),
            cadence_spm=s.get("cadence_spm"),
            stride_length_m=s.get("stride_length_m"),
        ))


def _ingest_streams(session, all_acts, existing_workouts) -> None:
    """Write activity_streams rows for every workout that has stream data.

    Called after session.flush() so all workouts have UUIDs.  Failures on
    individual activities are logged and skipped — they must not abort the
    surrounding reconcile transaction.

    Also computes and persists Normalized Power from the power_w channel when
    present, using compute_normalized_power (pure; no DB access inside that fn).
    """
    from backend.services.activity_streams import (
        extract_strava_streams,
        extract_stryd_streams,
        write_activity_stream,
    )
    from backend.services.normalized_power import compute_normalized_power
    import logging
    _log = logging.getLogger(__name__)

    for source_type, act in all_acts:
        try:
            if source_type == "strava":
                streams_payload = getattr(act, "streams_payload", None)
                if not streams_payload:
                    continue
                row_data, reason = extract_strava_streams(streams_payload, source="strava")
            else:
                streams_payload = getattr(act, "streams_payload", None)
                if not streams_payload:
                    continue
                row_data, reason = extract_stryd_streams(streams_payload, source="stryd")

            if reason:
                _log.debug("streams skipped", extra={"source": source_type, "reason": reason})
                continue

            # Find the workout that corresponds to this activity
            workout = _find_workout_for_activity(act, source_type, existing_workouts)
            if workout is None or workout.id is None:
                continue

            write_activity_stream(workout.id, row_data, session)

            # Compute NP from the power stream and persist on the workout.
            # sample_interval_seconds comes from row_data (never hardcoded here).
            power_samples = row_data.get("power_w")
            if power_samples:
                sample_interval = row_data.get("sample_interval_seconds", 1)
                np_val, _ = compute_normalized_power(power_samples, sample_interval)
                if np_val is not None:
                    workout.np = np_val

        except Exception as exc:
            _log.warning(
                "activity_streams ingest failed",
                extra={"source": source_type, "activity_id": getattr(act, "id", None), "error": str(exc)},
            )


def _find_workout_for_activity(act, source_type: str, existing_workouts: list):
    """Return the workout matched to this activity, or None."""
    pk = act.id
    if source_type == "strava":
        for w in existing_workouts:
            if getattr(w, "strava_activity_pk", None) == pk:
                return w
    else:
        for w in existing_workouts:
            if getattr(w, "stryd_activity_pk", None) == pk:
                return w
    return None


def _merge_source(current: str | None, new_source: str) -> str:
    if not current or current == new_source:
        return new_source
    if current == "manual":
        return current
    # Both strava and stryd present
    return "strava,stryd"


def reconcile_workouts(job_id, user_id) -> None:
    """Merge strava_activities (and stryd_activities) into workouts.

    Phase transitions: sets 'reconciling'. Caller is responsible for mark_success.
    """
    from backend.db import engine
    from backend.models import Workout, StravaActivity, StrydActivity
    from backend.services import sync_jobs
    from backend.services.workout_merge import compute_best_values

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    sync_jobs.set_phase(uid, "reconciling")

    with _Session(engine) as session:
        strava_acts = (
            session.query(StravaActivity)
            .filter(StravaActivity.user_id == uid)
            .all()
        )

        try:
            stryd_acts = (
                session.query(StrydActivity)
                .filter(StrydActivity.user_id == uid)
                .all()
            )
        except Exception:
            stryd_acts = []

        all_acts = [("strava", a) for a in strava_acts] + [("stryd", a) for a in stryd_acts]

        # Single bulk load of all existing workouts — no per-activity query
        existing_workouts: list = session.query(Workout).filter(Workout.user_id == uid).all()

        sync_jobs.reset_progress(uid, total=len(all_acts))

        stryd_pairs = []
        for source_type, act in all_acts:
            matched = _find_in_memory(act.start_time, existing_workouts, _TOLERANCE)
            proxy = _make_proxy(act, source_type, matched)
            best = compute_best_values(proxy)

            if matched:
                if source_type == "strava":
                    matched.strava_activity_pk = act.id
                    matched.source = _merge_source(matched.source, "strava")
                else:
                    matched.stryd_activity_pk = act.id
                    matched.source = _merge_source(matched.source, "stryd")
                _apply_best(matched, best)
                target = matched
            else:
                wdate = act.start_time.astimezone(timezone.utc).date() if act.start_time else date.today()
                wtype = getattr(act, "activity_type", None) or "Run"
                w = Workout(
                    user_id=uid,
                    workout_date=wdate,
                    name=best["best_name"] or getattr(act, "name", None) or "Untitled",
                    workout_type=wtype,
                    source=source_type,
                    start_time=act.start_time,
                )
                if source_type == "strava":
                    w.strava_activity_pk = act.id
                else:
                    w.stryd_activity_pk = act.id
                _apply_best(w, best)
                session.add(w)
                existing_workouts.append(w)
                target = w

            if source_type == "stryd":
                _apply_stryd_metrics(target, act)
                stryd_pairs.append((target, act))

            sync_jobs.increment(uid, current=1)

        # Flush so newly-created workouts have ids, then (re)build their splits
        # and ingest activity streams into activity_streams.
        session.flush()
        for workout, act in stryd_pairs:
            _sync_splits(session, workout, act)

        _ingest_streams(session, all_acts, existing_workouts)

        session.commit()

    # Derive TSS (fallback) + Zone-2 minutes for runs from the now-current splits.
    compute_run_metrics(user_id)


def compute_run_metrics(user_id) -> None:
    """Per-run: fill zone2_minutes (time in the user's Zone-2 HR band) from the
    km-splits, and TSS via tss.py when a run has none (no Stryd stress).

    Thresholds + Zone-2 band come from user_preferences (defaults applied here)."""
    from backend.db import engine
    from backend.models import UserPreferences, Workout, WorkoutSplit
    from backend.services.tss import estimate_tss_for_workout
    from types import SimpleNamespace

    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))
    with _Session(engine) as session:
        prefs = session.query(UserPreferences).filter(UserPreferences.user_id == uid).first()
        z_min = (prefs.zone2_hr_min if prefs and prefs.zone2_hr_min is not None else 130)
        z_max = (prefs.zone2_hr_max if prefs and prefs.zone2_hr_max is not None else 155)

        runs = (
            session.query(Workout)
            .filter(Workout.user_id == uid, Workout.workout_type.ilike("run"))
            .all()
        )
        run_ids = [w.id for w in runs]
        splits_by: dict = {}
        if run_ids:
            for s in session.query(WorkoutSplit).filter(WorkoutSplit.workout_id.in_(run_ids)).all():
                splits_by.setdefault(s.workout_id, []).append(s)

        for w in runs:
            sp = splits_by.get(w.id, [])
            if sp:
                z2s = sum((s.duration_seconds or 0) for s in sp
                          if s.avg_hr is not None and z_min <= s.avg_hr <= z_max)
                w.zone2_minutes = round(z2s / 60)
            elif w.avg_hr is not None and w.duration_seconds and z_min <= w.avg_hr <= z_max:
                w.zone2_minutes = round(w.duration_seconds / 60)

            if w.tss is None and w.duration_seconds:
                proxy = SimpleNamespace(
                    duration_seconds=w.duration_seconds,
                    avg_power_w=w.avg_power,
                    avg_hr=w.avg_hr,
                    distance_km=float(w.distance_km) if w.distance_km is not None else None,
                    avg_pace_seconds_per_km=None,
                )
                tss, src = estimate_tss_for_workout(proxy, uid, session)
                w.tss = tss
                w.tss_source = src

        session.commit()
