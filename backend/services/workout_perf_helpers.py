"""Shared workout query helpers for performance scoring (worker-safe)."""
from __future__ import annotations

from types import SimpleNamespace

from backend.models import PlannedSession, StrydActivity, WorkoutSplit


def classified_manual_laps_map(session, run_workouts, prefs_dict) -> dict:
    """{workout_id: [classified manual-lap dicts]} for workouts whose Stryd
    activity carries lap-button laps (stryd_activities.manual_laps)."""
    from backend.services.lap_classify import classify_laps as _cl

    pks = {wk.stryd_activity_pk for wk in run_workouts if getattr(wk, "stryd_activity_pk", None)}
    if not pks:
        return {}
    rows = (
        session.query(StrydActivity.id, StrydActivity.manual_laps)
        .filter(StrydActivity.id.in_(pks))
        .all()
    )
    by_pk = {rid: ml for rid, ml in rows if ml}
    out: dict = {}
    for wk in run_workouts:
        ml = by_pk.get(getattr(wk, "stryd_activity_pk", None))
        if not ml:
            continue
        shims = [
            SimpleNamespace(
                avg_power=lap.get("avg_power"),
                avg_hr=lap.get("avg_hr"),
                duration_seconds=lap.get("duration_seconds"),
                distance_km=lap.get("distance_km"),
            )
            for lap in ml
        ]
        out[wk.id] = [
            {
                "band": c.get("band"),
                "avg_power": lap.get("avg_power"),
                "avg_hr": lap.get("avg_hr"),
                "distance_km": float(lap["distance_km"]) if lap.get("distance_km") is not None else None,
                "duration_seconds": lap.get("duration_seconds"),
            }
            for lap, c in zip(ml, _cl(shims, prefs_dict or {}))
        ]
    return out


def planned_duration_map(session, workout_ids: list) -> dict:
    """Map workout_id → planned_duration_seconds from matched PlannedSession rows."""
    if not workout_ids:
        return {}
    from backend.services.plan_matching import _planned_duration_seconds as _pds

    rows = (
        session.query(PlannedSession)
        .filter(PlannedSession.matched_workout_id.in_(workout_ids))
        .all()
    )
    out = {}
    for r in rows:
        if r.matched_workout_id is None:
            continue
        dur = _pds(r.structure)
        if dur is not None:
            out[r.matched_workout_id] = dur
    return out


def splits_by_workout_map(session, workout_ids: list) -> dict:
    """Batch-load WorkoutSplit rows for many workouts in one query.

    Same pattern as issue #1578's cold-cache performance path — callers must
    not N+1 ``filter(workout_id == …)`` per run on the 512MB web dyno.
    Returns ``{workout_id: [WorkoutSplit, …]}`` ordered by split_index.
    """
    if not workout_ids:
        return {}
    rows = (
        session.query(WorkoutSplit)
        .filter(WorkoutSplit.workout_id.in_(workout_ids))
        .order_by(WorkoutSplit.workout_id, WorkoutSplit.split_index)
        .all()
    )
    out: dict = {}
    for s in rows:
        out.setdefault(s.workout_id, []).append(s)
    return out
