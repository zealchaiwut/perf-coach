"""Month board payload for revamp training log (P1-3)."""
from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlannedSession, UserPreferences, Workout
from backend.services.plan_match_payload import (
    is_missed_planned,
    plan_kept_ratio,
    planned_item_status,
    planned_source,
    planned_tss_estimate,
    session_kind_for_workout,
    who_label,
)
from backend.services.session_tss import session_tss
from backend.services.training_load import estimate_historical_pace_and_tss, estimate_planned_session_metrics
from backend.services.weekly_rollup import normalize_week_start, weekly_rollup
from backend.utils.time import today_bangkok


def month_bounds(month: date) -> tuple[date, date]:
    """First and last calendar day in ``month`` (any day → that month)."""
    first = month.replace(day=1)
    _, last_day = calendar.monthrange(first.year, first.month)
    last = first.replace(day=last_day)
    return first, last


def grid_range(month: date) -> tuple[date, date]:
    """Monday before/at month start through Sunday after month end."""
    first, last = month_bounds(month)
    grid_start = first - timedelta(days=first.weekday())
    grid_end = last + timedelta(days=(6 - last.weekday()))
    return grid_start, grid_end


def _planned_kind(session_type: str) -> str:
    st = (session_type or "").lower()
    if st == "run":
        return "run"
    if st == "rest":
        return "rest"
    return st if st in ("strength", "mobility", "plyo") else "support"


def _workout_item(
    session: Session,
    w: Workout,
    prefs: Optional[UserPreferences],
    match: Optional[dict],
) -> dict[str, Any]:
    tss = session_tss(w, prefs=prefs, session=session).get("tss")
    kind = session_kind_for_workout(w)
    if match:
        source = match.get("source") or "coach"
    else:
        source = "unplanned"
    status = "done"
    return {
        "id": str(w.id),
        "kind": kind,
        "source": source,
        "who": who_label(kind=kind, source=source, status=status),
        "name": w.name or "Session",
        "tss": round(float(tss), 1) if tss is not None else None,
        "distance_km": float(w.distance_km) if w.distance_km is not None else None,
        "duration_min": round(w.duration_seconds / 60, 1) if w.duration_seconds else None,
        "status": status,
        "workout_id": str(w.id),
        "planned_id": None,
    }


def _planned_item(session: Session, row: PlannedSession, today: date) -> dict[str, Any]:
    st = planned_item_status(row, today)
    kind = _planned_kind(row.session_type)
    src = planned_source(row.session_type)
    return {
        "id": f"plan:{row.id}",
        "kind": kind,
        "source": src,
        "who": who_label(kind=kind, source=src, status=st),
        "name": row.name or row.session_type.title(),
        "tss": planned_tss_estimate(session, row),
        "distance_km": None,
        "duration_min": None,
        "status": st,
        "workout_id": str(row.matched_workout_id) if row.matched_workout_id else None,
        "planned_id": str(row.id),
    }


def _week_target_meta(rollup: dict) -> dict:
    """Target bar helpers for the month WEEK column."""
    actual = float(rollup.get("tss_total") or 0)
    target = rollup.get("target_tss")
    planned = rollup.get("planned_tss")
    if target is None and planned:
        target = float(planned) + actual if rollup.get("partial") else float(planned)
    if target is None or target <= 0:
        return {"target_tss": None, "delta": None, "on_target": None, "bar_pct": None}
    delta = round(actual - target, 1)
    on_target = abs(delta) <= target * 0.05
    bar_pct = min(100, round((actual / target) * 100))
    return {
        "target_tss": round(float(target), 1),
        "delta": delta,
        "on_target": on_target,
        "bar_pct": bar_pct,
    }


def training_month(
    session: Session,
    user_id: uuid.UUID,
    month: date,
    *,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Build month grid weeks Mon–Sun with P0-4 rollups per row."""
    today = today or today_bangkok()
    uid = uuid.UUID(str(user_id))
    first, last = month_bounds(month)
    grid_start, grid_end = grid_range(month)

    prefs = session.query(UserPreferences).filter(UserPreferences.user_id == uid).first()
    workouts = (
        session.query(Workout)
        .filter(
            Workout.user_id == uid,
            Workout.workout_date >= grid_start,
            Workout.workout_date <= grid_end,
        )
        .all()
    )
    by_date: dict[str, list[Workout]] = {}
    wid_list = []
    for w in workouts:
        key = str(w.workout_date)
        by_date.setdefault(key, []).append(w)
        wid_list.append(w.id)

    from backend.services.plan_match_payload import plan_match_map

    match_map = plan_match_map(session, wid_list)

    planned_rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == uid,
            PlannedSession.planned_date >= grid_start,
            PlannedSession.planned_date <= grid_end,
        )
        .all()
    )
    planned_by_date: dict[str, list[PlannedSession]] = {}
    matched_ids = {w.id for w in workouts}
    for p in planned_rows:
        if p.matched_workout_id and p.matched_workout_id in matched_ids:
            continue
        st = planned_item_status(p, today)
        if st == "skipped":
            continue
        if st == "done":
            continue
        key = str(p.planned_date)
        planned_by_date.setdefault(key, []).append(p)

    weeks: list[dict[str, Any]] = []
    matched_count = 0
    missed_count = 0
    month_tss = 0.0
    month_km = 0.0
    month_sessions = 0

    cursor = grid_start
    while cursor <= grid_end:
        week_start = normalize_week_start(cursor)
        week_days: list[dict[str, Any]] = []
        for offset in range(7):
            d = week_start + timedelta(days=offset)
            key = d.isoformat()
            items: list[dict[str, Any]] = []
            for w in by_date.get(key, []):
                items.append(_workout_item(session, w, prefs, match_map.get(str(w.id))))
                if match_map.get(str(w.id)):
                    matched_count += 1
                tss = session_tss(w, prefs=prefs, session=session).get("tss")
                if tss:
                    month_tss += float(tss)
                if w.distance_km:
                    month_km += float(w.distance_km)
                month_sessions += 1
            for p in planned_by_date.get(key, []):
                item = _planned_item(session, p, today)
                items.append(item)
                if is_missed_planned(p, today):
                    missed_count += 1
            if not items and any(
                pr.planned_date == d and (pr.session_type or "").lower() == "rest"
                for pr in planned_rows
                if planned_item_status(pr, today) == "planned"
            ):
                items.append(
                    {
                        "id": f"rest:{key}",
                        "kind": "rest",
                        "source": "coach",
                        "name": "Rest day",
                        "tss": None,
                        "distance_km": None,
                        "duration_min": None,
                        "status": "planned",
                        "workout_id": None,
                        "planned_id": None,
                    }
                )
            week_days.append(
                {
                    "date": key,
                    "in_month": first <= d <= last,
                    "is_today": d == today,
                    "items": items,
                }
            )
        rollup = weekly_rollup(uid, week_start, session=session, today=today)
        weeks.append({
            "week_start": week_start.isoformat(),
            "days": week_days,
            "rollup": rollup,
            "target_meta": _week_target_meta(rollup),
        })
        cursor = week_start + timedelta(days=7)

    plan_kept = plan_kept_ratio(matched_count, missed_count)
    return {
        "month": first.strftime("%Y-%m"),
        "grid_start": grid_start.isoformat(),
        "grid_end": grid_end.isoformat(),
        "weeks": weeks,
        "summary": {
            "tss_total": round(month_tss, 1),
            "distance_km": round(month_km, 1),
            "session_count": month_sessions,
            "plan_kept": plan_kept,
            "plan_kept_label": (
                f"{matched_count} of {matched_count + missed_count}"
                if matched_count + missed_count > 0
                else None
            ),
        },
    }