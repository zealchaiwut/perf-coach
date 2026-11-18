"""Canonical weekly volume rollup (revamp P0-4).

All week totals (chart, plan, log, export) must call weekly_rollup / weekly_rollups.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import PlannedSession, UserPreferences, Workout
from backend.services.session_tss import session_tss
from backend.utils.time import today_bangkok, to_bangkok

_RUN_RE = re.compile(r"^run(ning)?$|^race$|^(bike|ride|cycl)", re.IGNORECASE)
_STRENGTH_RE = re.compile(r"^(lift|strength|wod|crossfit|plyo)", re.IGNORECASE)
_DONE_PLANNED = frozenset({"done_auto", "done_manual"})
_MISSED = frozenset({"missed", "missed_auto", "missed_manual", "needs_review"})


def bangkok_week_start(d: date) -> date:
    """Monday containing calendar date ``d`` (Bangkok week semantics)."""
    return d - timedelta(days=d.weekday())


def normalize_week_start(week_start: date) -> date:
    """Accept any date in the week; return that week's Monday."""
    return bangkok_week_start(week_start)


def session_local_date(workout: Workout) -> date:
    """Local (Bangkok) calendar date for week membership."""
    st = getattr(workout, "start_time", None)
    if st is not None:
        try:
            return to_bangkok(st).date()
        except (ValueError, TypeError):
            pass
    return workout.workout_date


def _tss_bucket(workout_type: Optional[str], *, distance_km) -> str:
    wt = (workout_type or "").strip()
    if _RUN_RE.match(wt):
        return "run"
    if _STRENGTH_RE.match(wt):
        return "strength"
    if distance_km is not None and float(distance_km or 0) > 0:
        return "run"
    return "support"


def _estimate_planned_tss_remaining(
    session: Session,
    user_id: uuid.UUID,
    week_start: date,
    week_end: date,
    today: date,
) -> float:
    from backend.services.training_load import (
        estimate_historical_pace_and_tss,
        estimate_planned_session_metrics,
    )

    baseline = estimate_historical_pace_and_tss(str(user_id), session)
    rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= week_start,
            PlannedSession.planned_date <= week_end,
            PlannedSession.matched_workout_id.is_(None),
            PlannedSession.status.notin_(("missed", "skipped")),
            PlannedSession.session_type != "mobility",
        )
        .all()
    )
    total = 0.0
    for p in rows:
        if p.planned_date < today:
            continue
        est = estimate_planned_session_metrics(baseline, p.session_type, p.structure)
        if est.get("estimated_tss"):
            total += float(est["estimated_tss"])
    return round(total, 2)


def weekly_rollup(
    user_id: uuid.UUID | str,
    week_start: date,
    *,
    session: Optional[Session] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Return one week's canonical totals for ``week_start`` (any day → Monday)."""
    uid = uuid.UUID(str(user_id))
    ws = normalize_week_start(week_start)
    we = ws + timedelta(days=6)
    today = today or today_bangkok()
    partial = ws <= today <= we

    own = session is None
    if own:
        session = Session(engine)

    try:
        prefs = session.query(UserPreferences).filter(UserPreferences.user_id == uid).first()
        # Buffer workout_date so Sunday-late / Monday-early start_time rows are included.
        buffer_start = ws - timedelta(days=1)
        buffer_end = we + timedelta(days=1)
        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= buffer_start,
                Workout.workout_date <= buffer_end,
            )
            .all()
        )
        in_week = [w for w in workouts if ws <= session_local_date(w) <= we]

        tss_total = 0.0
        tss_run = 0.0
        tss_strength = 0.0
        tss_support_other = 0.0
        distance_km = 0.0
        duration_seconds = 0.0

        for w in in_week:
            counted = session_tss(w, prefs=prefs).get("tss")
            if counted is not None:
                val = float(counted)
                tss_total += val
                bucket = _tss_bucket(w.workout_type, distance_km=w.distance_km)
                if bucket == "run":
                    tss_run += val
                elif bucket == "strength":
                    tss_strength += val
                else:
                    tss_support_other += val
            if w.distance_km is not None:
                distance_km += float(w.distance_km)
            if w.duration_seconds is not None:
                duration_seconds += float(w.duration_seconds)

        planned_rows = (
            session.query(PlannedSession)
            .filter(
                PlannedSession.user_id == uid,
                PlannedSession.planned_date >= ws,
                PlannedSession.planned_date <= we,
            )
            .all()
        )
        counts = {"done": len(in_week), "planned": 0, "missed": 0, "skipped": 0}
        for p in planned_rows:
            st = (p.status or "").lower()
            if st == "planned":
                counts["planned"] += 1
            elif st == "skipped":
                counts["skipped"] += 1
            elif st in _MISSED:
                counts["missed"] += 1
            elif st in _DONE_PLANNED:
                pass  # fulfillment reflected in workout count

        planned_tss = _estimate_planned_tss_remaining(session, uid, ws, we, today)
        runs = sum(1 for w in in_week if _tss_bucket(w.workout_type, distance_km=w.distance_km) == "run")
        strength = sum(
            1 for w in in_week if _tss_bucket(w.workout_type, distance_km=w.distance_km) == "strength"
        )

        return {
            "week_start": ws.isoformat(),
            "week_end": we.isoformat(),
            "tss_total": round(tss_total, 2),
            "tss_run": round(tss_run, 2),
            "tss_strength": round(tss_strength, 2),
            "tss_support_other": round(tss_support_other, 2),
            "distance_km": round(distance_km, 2),
            "hours": round(duration_seconds / 3600.0, 2) if duration_seconds else 0.0,
            "session_count": len(in_week),
            "runs": runs,
            "strength": strength,
            "counts": counts,
            "planned_tss": planned_tss,
            "target_tss": None,
            "partial": partial,
        }
    finally:
        if own:
            session.close()


def weekly_rollups(
    user_id: uuid.UUID | str,
    from_week: date,
    to_week: date,
    *,
    session: Optional[Session] = None,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Inclusive range of Monday week starts."""
    start = normalize_week_start(from_week)
    end = normalize_week_start(to_week)
    if start > end:
        start, end = end, start
    today = today or today_bangkok()
    out: list[dict[str, Any]] = []
    ws = start
    own = session is None
    if own:
        session = Session(engine)
    try:
        while ws <= end:
            out.append(
                weekly_rollup(user_id, ws, session=session, today=today)
            )
            ws += timedelta(weeks=1)
        return out
    finally:
        if own:
            session.close()


def rollup_for_export(week: dict[str, Any]) -> dict[str, Any]:
    """Shape for coach export ``training.weekly_rollups``."""
    return {
        "week_start": week["week_start"],
        "sessions": week["session_count"],
        "tss": week["tss_total"],
        "distance_km": week["distance_km"],
        "hours": week["hours"],
        "runs": week.get("runs", 0),
        "strength": week.get("strength", 0),
        "partial": week["partial"],
    }