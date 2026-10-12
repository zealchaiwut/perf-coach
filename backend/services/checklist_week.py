"""Weekly checklist read model (WC-14) — no table; composes existing rows."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.models import Habit, HabitLog, PlannedSession
from backend.utils.time import today_bangkok

_DONE_STATUSES = frozenset({"done_auto", "done_manual"})
_MISSED_STATUSES = frozenset({"missed", "missed_auto", "missed_manual"})


def _session_state(ps: PlannedSession, today: date) -> str:
    st = (ps.status or "planned").lower()
    if st == "skipped":
        return "skipped"
    if st in _DONE_STATUSES:
        return "done"
    if st in _MISSED_STATUSES:
        return "missed"
    if ps.planned_date < today and ps.session_type != "mobility":
        return "missed"
    return "pending"


def _session_role(ps: PlannedSession, prefs_payload: dict | None = None) -> str:
    if ps.session_type == "mobility":
        from backend.services.pref_catalog import get_field

        role = get_field(prefs_payload or {}, "mobility_checklist_role") or "optional"
        if role in ("core", "optional"):
            return role
        return "optional"
    return "core"


def _habit_done_for_day(habit: Habit, d: date, logs_by_habit: dict) -> bool:
    for log in logs_by_habit.get(habit.id, []):
        if log.log_date == d and float(log.value or 0) > 0:
            return True
    return False


def _long_run_days(sessions_by_date: dict[date, list[PlannedSession]]) -> set[date]:
    out: set[date] = set()
    for d, rows in sessions_by_date.items():
        for ps in rows:
            if ps.session_type == "run":
                sub = (ps.structure or {}).get("subtype") if isinstance(ps.structure, dict) else None
                name = (ps.name or "").lower()
                if sub == "long_run" or "long" in name:
                    out.add(d)
    return out


def _structure_summary(structure: Any) -> dict[str, Any]:
    s = structure if isinstance(structure, dict) else {}
    exercises = s.get("exercises") or []
    blocks = s.get("blocks") or []
    duration = s.get("duration_minutes")
    if duration is None and blocks:
        tot = 0.0
        for b in blocks:
            if not isinstance(b, dict):
                continue
            d = float(b.get("duration_min") or 0)
            r = max(1, int(b.get("repeat") or 1))
            tot += d * r + float(b.get("rest_min") or 0) * max(0, r - 1)
        if tot:
            duration = int(round(tot))
    return {
        "duration_minutes": int(duration) if duration is not None else None,
        "exercise_count": len(exercises),
        "block_count": len(blocks),
    }


def _ribbon_for_day(
    sessions: list[PlannedSession],
    score: dict[str, int],
) -> dict[str, Any]:
    primary = None
    for ps in sessions:
        if (ps.session_type or "").lower() not in ("rest", "mobility"):
            primary = ps
            break
    if primary is None:
        for ps in sessions:
            if (ps.session_type or "").lower() != "rest":
                primary = ps
                break
    if primary is None:
        return {
            "label": "Rest",
            "session_type": "rest",
            "session_id": None,
            "core_done": score.get("core_done", 0),
            "core_total": score.get("core_total", 0),
        }
    return {
        "label": primary.name or (primary.session_type or "session").replace("_", " ").title(),
        "session_type": primary.session_type,
        "session_id": str(primary.id),
        "core_done": score.get("core_done", 0),
        "core_total": score.get("core_total", 0),
    }


def _race_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "name": row.name,
        "race_date": row.race_date.isoformat() if row.race_date else None,
        "goal_time_seconds": row.goal_time_seconds,
        "distance_km": float(row.distance_km) if row.distance_km is not None else None,
        "priority": row.priority,
        "type": row.type,
    }


def _fuel_detail_for_day(user_id: UUID, d: date, db: Session) -> dict[str, Any] | None:
    try:
        from backend.services.fuel import get_today_payload

        fp = get_today_payload(user_id, d, db=db)
    except Exception:
        return None
    if not fp:
        return None
    targets = fp.get("targets") or {}
    return {
        "day_type": fp.get("day_type"),
        "week_phase": fp.get("week_phase"),
        "week_phase_reason": fp.get("week_phase_reason"),
        "targets": targets,
        "deficit_applied": fp.get("deficit_applied"),
        "effective_deficit_kcal": fp.get("effective_deficit_kcal"),
        "auto_periodize": fp.get("auto_periodize"),
        "food_portions": fp.get("food_portions"),
    }


def build_checklist_week(
    db: Session,
    user_id: UUID,
    week_start: date,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Compose checklist payload for one ISO week (Monday start)."""
    from backend.services.checklist_habits import ensure_sleep_habit
    from backend.services.fuel import get_week_payload
    from backend.services.habit_autofill import recompute_autofill_for_week
    from backend.services.plan_build_status import plan_build_status
    from backend.services.pref_catalog import get_field
    from backend.services.training_prefs import active_dict

    today = today or today_bangkok()
    week_end = week_start + timedelta(days=6)

    ensure_sleep_habit(db, user_id)
    try:
        recompute_autofill_for_week(user_id, week_start)
    except Exception:
        pass

    prefs_payload = active_dict(db, user_id).get("payload") or {}
    checklist_enabled = bool(get_field(prefs_payload, "weekly_checklist_enabled"))

    habits = (
        db.query(Habit)
        .filter(
            Habit.user_id == user_id,
            Habit.is_archived.is_(False),
            Habit.checklist_role != "off",
        )
        .order_by(Habit.sort_order)
        .all()
    )
    habits = [
        h for h in habits
        if (h.auto_fill_source or "") != "coach.stretch_daily"
    ]

    logs = (
        db.query(HabitLog)
        .filter(HabitLog.user_id == user_id, HabitLog.log_week_start == week_start)
        .all()
    )
    logs_by_habit: dict = {}
    for log in logs:
        logs_by_habit.setdefault(log.habit_id, []).append(log)

    planned = (
        db.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= week_start,
            PlannedSession.planned_date <= week_end,
        )
        .order_by(PlannedSession.planned_date)
        .all()
    )
    by_date: dict[date, list[PlannedSession]] = {}
    for ps in planned:
        by_date.setdefault(ps.planned_date, []).append(ps)

    fuel_week = get_week_payload(user_id, week_start, db=db)
    fuel_by_date = {d["date"]: d for d in (fuel_week.get("days") or [])}
    long_run_days = _long_run_days(by_date)

    a_race = None
    b_race = None
    try:
        from backend.models import Race

        row = (
            db.query(Race)
            .filter(
                Race.user_id == user_id,
                Race.priority == "A",
                Race.status.in_(("planned", "active")),
            )
            .order_by(Race.race_date.asc().nullslast())
            .first()
        )
        a_race = _race_dict(row)
        brow = (
            db.query(Race)
            .filter(
                Race.user_id == user_id,
                Race.race_date >= week_start,
                Race.race_date <= week_end,
                Race.status.in_(("planned", "active")),
                Race.priority != "A",
            )
            .order_by(Race.race_date.asc())
            .first()
        )
        b_race = _race_dict(brow)
    except Exception:
        pass

    days_out: list[dict] = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        day_sessions = by_date.get(d, [])
        items: list[dict] = []
        core_total = core_done = 0

        for ps in day_sessions:
            if ps.session_type == "rest":
                continue
            role = _session_role(ps, prefs_payload)
            state = _session_state(ps, today)
            if role == "core" and state not in ("skipped",):
                core_total += 1
                if state == "done":
                    core_done += 1
            tick = None
            if ps.session_type == "mobility":
                tick = {
                    "method": "POST",
                    "url": f"/api/planned-sessions/{ps.id}/mark-done",
                    "skip_url": f"/api/planned-sessions/{ps.id}/skip",
                }
            elif state == "pending":
                tick = {
                    "method": "POST",
                    "url": f"/api/planned-sessions/{ps.id}/mark-done",
                }
            items.append({
                "id": str(ps.id),
                "kind": "planned_session",
                "source": "planned_sessions",
                "session_type": ps.session_type,
                "role": role,
                "state": state,
                "label": ps.name or ps.session_type.replace("_", " ").title(),
                "link": f"/log?tab=plan&session={ps.id}",
                "tick": tick,
                "structure_summary": _structure_summary(ps.structure),
            })

        for h in habits:
            role = getattr(h, "checklist_role", None) or "core"
            if role == "off":
                continue
            src = h.auto_fill_source or ""
            if src == "long_run.fuelled" and d not in long_run_days:
                continue
            if h.tracking_type == "daily_checkmark":
                done = _habit_done_for_day(h, d, logs_by_habit)
                state = "done" if done else ("pending" if d <= today else "upcoming")
                if role == "core" and d <= today:
                    core_total += 1
                    if done:
                        core_done += 1
                items.append({
                    "id": str(h.id),
                    "kind": "habit",
                    "source": "habits",
                    "role": role,
                    "state": state,
                    "label": h.name,
                    "link": "/habits",
                    "auto_fill_source": h.auto_fill_source,
                    "tick": {
                        "method": "POST",
                        "url": f"/api/habits/{h.id}/log",
                        "body": {"log_date": d.isoformat(), "value": 1},
                    } if not done and h.auto_fill_source is None else None,
                })
            elif i == 0:
                week_logs = logs_by_habit.get(h.id, [])
                total = sum(float(x.value or 0) for x in week_logs)
                target = float(h.target_value or 0)
                done = target > 0 and total >= target
                state = "done" if done else "pending"
                items.append({
                    "id": str(h.id),
                    "kind": "habit",
                    "source": "habits",
                    "role": role,
                    "state": state,
                    "label": h.name,
                    "link": "/habits",
                    "auto_fill_source": h.auto_fill_source,
                    "tick": None,
                    "weekly_progress": {"value": total, "target": target},
                })

        fuel_enabled = get_field(prefs_payload, "checklist_fuel_enabled")
        if fuel_enabled is not False:
            fuel = fuel_by_date.get(d.isoformat()) or {}
            items.append({
                "id": f"fuel-{d.isoformat()}",
                "kind": "fuel",
                "source": "fuel",
                "role": "optional",
                "state": "shown",
                "label": f"Fuel · {fuel.get('day_type', 'rest')}",
                "link": None,
                "tick": None,
                "fuel": {
                    "day_type": fuel.get("day_type"),
                    "budget": fuel.get("budget"),
                    "burn": fuel.get("burn"),
                },
            })

        score = {"core_done": core_done, "core_total": core_total}
        days_out.append({
            "date": d.isoformat(),
            "day_offset": i,
            "score": score,
            "ribbon": _ribbon_for_day(day_sessions, score),
            "fuel_detail": _fuel_detail_for_day(user_id, d, db),
            "items": items,
        })

    what_moves: list[dict] = []
    try:
        from backend.services.habit_evidence import build_user_evidence

        for ev in (build_user_evidence(db, user_id, today, weeks=4) or [])[:5]:
            what_moves.append({
                "habit": ev.get("habit"),
                "sentence": ev.get("sentence"),
                "better": ev.get("better"),
            })
    except Exception:
        pass

    cur_mon = today - timedelta(days=today.weekday())
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_number": week_start.isocalendar()[1],
        "is_current_week": week_start == cur_mon,
        "checklist_enabled": checklist_enabled,
        "build_status": plan_build_status(db, user_id, week_start=week_start),
        "a_race": a_race,
        "races_header": {"a_race": a_race, "b_race": b_race},
        "fuel_week": {
            "week_phase": fuel_week.get("week_phase"),
            "week_phase_reason": fuel_week.get("week_phase_reason"),
        },
        "days": days_out,
        "what_moves_estimate": what_moves,
    }
