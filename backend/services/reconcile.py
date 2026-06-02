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
        workout.avg_hr = best["best_avg_hr"]
    if best.get("best_tss") is not None:
        workout.tss = best["best_tss"]


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

            sync_jobs.increment(uid, current=1)

        session.commit()
