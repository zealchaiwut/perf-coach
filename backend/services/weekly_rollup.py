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
from backend.models import PlannedSession, Race, Workout
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


def _remaining_planned_row(p: Any, week_start: date, week_end: date) -> bool:
    if p.planned_date < week_start or p.planned_date > week_end:
        return False
    if getattr(p, "matched_workout_id", None) is not None:
        return False
    if (p.status or "") in ("missed", "skipped"):
        return False
    if p.session_type == "mobility":
        return False
    return True


def _estimate_planned_tss_remaining(
    session: Session,
    user_id: uuid.UUID,
    week_start: date,
    week_end: date,
    today: date,
    *,
    planned_rows: Optional[list] = None,
    baseline: Optional[dict[str, Any]] = None,
) -> float:
    from backend.services.training_load import (
        estimate_historical_pace_and_tss,
        estimate_planned_session_metrics,
    )

    if baseline is None:
        baseline = estimate_historical_pace_and_tss(str(user_id), session)
    if planned_rows is None:
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
    else:
        rows = [p for p in planned_rows if _remaining_planned_row(p, week_start, week_end)]
    total = 0.0
    for p in rows:
        if p.planned_date < today:
            continue
        est = estimate_planned_session_metrics(baseline, p.session_type, p.structure)
        if est.get("estimated_tss"):
            total += float(est["estimated_tss"])
    return round(total, 2)


def _target_or_chronic(plan_target: Any, chronic: Any) -> Any:
    """A-race load-plan target when present, else chronic (Plan generic week)."""
    if plan_target is not None:
        return plan_target
    return chronic


def _assemble_week(
    *,
    ws: date,
    we: date,
    today: date,
    workouts: list,
    planned_rows: list,
    planned_tss_training: float,
    race_items: list[dict[str, Any]],
    target_tss_val: Any,
    phase_label: Any,
) -> dict[str, Any]:
    in_week = [w for w in workouts if ws <= session_local_date(w) <= we]
    tss_total = 0.0
    tss_run = 0.0
    tss_strength = 0.0
    tss_support_other = 0.0
    distance_km = 0.0
    duration_seconds = 0.0

    for w in in_week:
        val = float(w.tss) if w.tss is not None else None
        if val is not None:
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

    week_planned = [p for p in planned_rows if ws <= p.planned_date <= we]
    counts = {"done": len(in_week), "planned": 0, "missed": 0, "skipped": 0}
    for p in week_planned:
        st = (p.status or "").lower()
        if st == "planned":
            counts["planned"] += 1
        elif st == "skipped":
            counts["skipped"] += 1
        elif st in _MISSED:
            counts["missed"] += 1
        elif st in _DONE_PLANNED:
            pass

    race_planned_tss = sum(int(r["tss"] or 0) for r in race_items if r.get("tss") is not None)
    planned_tss = round(planned_tss_training + race_planned_tss, 2)
    runs = sum(1 for w in in_week if _tss_bucket(w.workout_type, distance_km=w.distance_km) == "run")
    strength = sum(
        1 for w in in_week if _tss_bucket(w.workout_type, distance_km=w.distance_km) == "strength"
    )
    partial = ws <= today <= we
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
        "planned_tss_training": planned_tss_training,
        "race_planned_tss": race_planned_tss,
        "race_items": race_items,
        "target_tss": round(float(target_tss_val), 1) if target_tss_val is not None else None,
        "phase": phase_label,
        "partial": partial,
        "tss_delta_prev": None,
    }


def _attach_tss_delta_prev(weeks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set tss_delta_prev vs the previous row in ``weeks`` (range order)."""
    prev_tss = None
    for week in weeks:
        if prev_tss is None:
            week["tss_delta_prev"] = None
        else:
            week["tss_delta_prev"] = round(float(week.get("tss_total") or 0) - prev_tss, 2)
        prev_tss = float(week.get("tss_total") or 0)
    return weeks



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

    own = session is None
    if own:
        session = Session(engine)

    try:
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
        planned_rows = (
            session.query(PlannedSession)
            .filter(
                PlannedSession.user_id == uid,
                PlannedSession.planned_date >= ws,
                PlannedSession.planned_date <= we,
            )
            .all()
        )
        planned_rows = [p for p in planned_rows if ws <= p.planned_date <= we]
        planned_tss_training = _estimate_planned_tss_remaining(session, uid, ws, we, today)
        from backend.services.race_day_tss import race_week_payload

        race_items = race_week_payload(
            session, uid, ws, we, allow_finish_estimate=False
        )
        phase_label = None
        target_tss_val = None
        chronic = None
        try:
            from backend.services.revamp_load_plan import chronic_weekly_tss, week_target_and_phase

            chronic = chronic_weekly_tss(session, uid, today)
            meta = week_target_and_phase(
                uid, ws, session=session, chronic_baseline=chronic, today=today
            )
            if meta:
                target_tss_val = meta.get("target_tss")
                phase_label = meta.get("phase")
        except Exception:
            pass
        target_tss_val = _target_or_chronic(target_tss_val, chronic)

        return _assemble_week(
            ws=ws,
            we=we,
            today=today,
            workouts=workouts,
            planned_rows=planned_rows,
            planned_tss_training=planned_tss_training,
            race_items=race_items,
            target_tss_val=target_tss_val,
            phase_label=phase_label,
        )
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
    plan_ctx: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Inclusive range of Monday week starts. One query per table for the span."""
    start = normalize_week_start(from_week)
    end = normalize_week_start(to_week)
    if start > end:
        start, end = end, start
    today = today or today_bangkok()
    mondays: list[date] = []
    ws = start
    while ws <= end:
        mondays.append(ws)
        ws += timedelta(weeks=1)
    we_last = end + timedelta(days=6)
    uid = uuid.UUID(str(user_id))
    own = session is None
    if own:
        session = Session(engine)
    try:
        lookback = today - timedelta(days=90)
        buffer_start = min(start - timedelta(days=1), lookback)
        buffer_end = we_last + timedelta(days=1)
        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == uid,
                Workout.workout_date >= buffer_start,
                Workout.workout_date <= buffer_end,
            )
            .all()
        )
        planned_rows = (
            session.query(PlannedSession)
            .filter(
                PlannedSession.user_id == uid,
                PlannedSession.planned_date >= start,
                PlannedSession.planned_date <= we_last,
            )
            .all()
        )
        from backend.models import LoadPlanWeekSnapshot, Race
        from backend.services.race_day_tss import race_week_payload
        from backend.services.training_load import estimate_historical_pace_and_tss

        races = (
            session.query(Race)
            .filter(
                Race.user_id == uid,
                Race.status.in_(("planned", "done")),
            )
            .order_by(Race.race_date)
            .all()
        )
        baseline = estimate_historical_pace_and_tss(str(uid), session, workouts=workouts)

        chronic = None if plan_ctx is None else plan_ctx.get("chronic_baseline")
        ctx = plan_ctx
        settings = None if plan_ctx is None else plan_ctx.get("settings")
        snap_map: dict[date, Any] = {}
        current_ws = normalize_week_start(today)
        has_race = bool(ctx and ctx.get("race"))
        try:
            from backend.services.revamp_load_plan import (
                chronic_weekly_tss,
                week_target_and_phase,
            )

            if ctx is None:
                from backend.services.revamp_plan_settings import (
                    get_row,
                    merged_phase_settings,
                    resolve_a_race,
                    resolve_block_start,
                )

                chronic = chronic_weekly_tss(session, uid, today)
                row = get_row(session, uid)
                a_race_id = getattr(row, "a_race_id", None) if row is not None else None
                race = resolve_a_race(session, uid, today, a_race_id=a_race_id)
                settings = merged_phase_settings(row)
                if race is not None:
                    block_start = resolve_block_start(
                        race.race_date,
                        settings,
                        block_start_override=getattr(row, "block_start", None) if row else None,
                    )
                    ctx = {
                        "race": race,
                        "block_start": block_start,
                        "settings": settings,
                        "chronic_baseline": chronic,
                        "row": row,
                    }
            elif chronic is None:
                chronic = chronic_weekly_tss(session, uid, today)
            has_race = bool(ctx and ctx.get("race"))
            if has_race:
                snaps = (
                    session.query(LoadPlanWeekSnapshot)
                    .filter(
                        LoadPlanWeekSnapshot.user_id == uid,
                        LoadPlanWeekSnapshot.week_start.in_(mondays),
                    )
                    .all()
                )
                snap_map = {s.week_start: s for s in snaps}
                settings = settings or ctx.get("settings")
                if chronic is None:
                    chronic = ctx.get("chronic_baseline")
        except Exception:
            ctx = None
            has_race = False

        out: list[dict[str, Any]] = []
        for week_monday in mondays:
            week_end = week_monday + timedelta(days=6)
            planned_tss_training = _estimate_planned_tss_remaining(
                session,
                uid,
                week_monday,
                week_end,
                today,
                planned_rows=planned_rows,
                baseline=baseline,
            )
            race_items = race_week_payload(
                session,
                uid,
                week_monday,
                week_end,
                races=races,
                workouts=workouts,
                allow_finish_estimate=False,
            )
            target_tss_val = None
            phase_label = None
            if has_race:
                try:
                    snap = snap_map.get(week_monday) if week_monday <= current_ws else None
                    meta = week_target_and_phase(
                        uid,
                        week_monday,
                        session=session,
                        chronic_baseline=chronic,
                        settings=settings,
                        today=today,
                        ctx=ctx,
                        snapshot=snap,
                    )
                    if meta:
                        target_tss_val = meta.get("target_tss")
                        phase_label = meta.get("phase")
                except Exception:
                    pass
            target_tss_val = _target_or_chronic(target_tss_val, chronic)
            out.append(
                _assemble_week(
                    ws=week_monday,
                    we=week_end,
                    today=today,
                    workouts=workouts,
                    planned_rows=planned_rows,
                    planned_tss_training=planned_tss_training,
                    race_items=race_items,
                    target_tss_val=target_tss_val,
                    phase_label=phase_label,
                )
            )
        return _attach_tss_delta_prev(out)
    finally:
        if own:
            session.close()


def next_race_brief(session: Session, user_id, today: date) -> Optional[dict[str, Any]]:
    """Compact next planned race for Log subtitle; None when none upcoming."""
    row = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.status == "planned",
            Race.race_date >= today,
        )
        .order_by(Race.race_date.asc())
        .first()
    )
    if row is None:
        return None
    race_date = row.race_date.isoformat() if getattr(row, "race_date", None) else None
    return {
        "name": row.name,
        "race_date": race_date,
        "priority": row.priority,
    }


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