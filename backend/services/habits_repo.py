"""Habit and habit-log repository — all DB access for the habits v2 CRUD surface."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from backend.models import Habit, HabitLog

HABIT_TYPE_VALUES: frozenset[str] = frozenset(("binary", "count", "duration"))
SCHEDULE_TYPE_VALUES: frozenset[str] = frozenset(
    ("daily", "weekly", "times_per_week"))
SECTION_VALUES: frozenset[str] = frozenset(("training", "general"))

# tracking_type -> habit_type (#1604 — tracking_type is the survivor column;
# habit_type is derived from it rather than independently settable). Mirrors
# the pairings the app's own seeders already use: goal_habits.py's three
# daily_checkmark habits are all binary, coach_habit_targets.py's Zone 2 habit
# is weekly_minutes/duration.
_TRACKING_TYPE_TO_HABIT_TYPE: dict[str, str] = {
    "daily_checkmark": "binary",
    "weekly_minutes": "duration",
    "weekly_count": "count",
    "weekly_quantity": "count",
}


def derive_habit_type(tracking_type: Optional[str]) -> Optional[str]:
    """Return the habit_type implied by tracking_type, or None if unknown/absent."""
    if tracking_type is None:
        return None
    return _TRACKING_TYPE_TO_HABIT_TYPE.get(tracking_type)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def get_habit(
    session: Session,
    habit_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[Habit]:
    """Return the habit if it exists and belongs to user_id; else None."""
    h = session.get(Habit, habit_id)
    if h is None or h.user_id != user_id:
        return None
    return h


def list_habits(
    session: Session,
    user_id: uuid.UUID,
    active: Optional[bool] = None,
) -> list[Habit]:
    """Return habits for user_id; optionally filter by active flag."""
    q = session.query(Habit).filter(Habit.user_id == user_id)
    if active is not None:
        q = q.filter(Habit.active == active)
    return q.order_by(Habit.display_order).all()


def create_habit(
    session: Session,
    user_id: uuid.UUID,
    data: dict,
) -> Habit:
    """Insert a new habit and return the refreshed row."""
    habit = Habit(user_id=user_id)
    habit.name = data["name"].strip()
    habit.active = True
    habit.is_archived = False

    # v2 fields — only set when explicitly provided so server_defaults apply otherwise
    if data.get("schedule_type") is not None:
        habit.schedule_type = data["schedule_type"]
    if data.get("target_value") is not None:
        habit.target_value = data["target_value"]
    if data.get("unit") is not None:
        habit.unit = data["unit"]
    if data.get("schedule_target") is not None:
        habit.schedule_target = data["schedule_target"]

    # habit_type (#1604): derived from tracking_type when tracking_type is
    # given — tracking_type is the survivor column and carries the real
    # behavior, so it wins over any habit_type also passed in the same
    # request. The real frontend (frontend/js/habits.js) only ever sends
    # tracking_type; before this, a caller that omitted habit_type (i.e.
    # every real habit created through the UI) silently got the column's
    # server default of 'binary' regardless of its actual tracking type.
    # When tracking_type is absent (the older, still-tested v2-only creation
    # path: habit_type + schedule_type, no tracking_type — see
    # tests/test_825_ac_verification.py's AC10), there is nothing to derive
    # from, so an explicitly supplied habit_type is honored as before.
    tracking_type = data.get("tracking_type")
    if tracking_type is not None:
        habit.tracking_type = tracking_type
        derived_habit_type = derive_habit_type(tracking_type)
        if derived_habit_type is not None:
            habit.habit_type = derived_habit_type
    elif data.get("habit_type") is not None:
        habit.habit_type = data["habit_type"]

    # legacy fields
    if data.get("weekly_target") is not None:
        habit.weekly_target = data["weekly_target"]
    if data.get("description") is not None:
        habit.description = data["description"]
    if data.get("icon") is not None:
        habit.icon = data["icon"]
    if data.get("color") is not None:
        habit.color = data["color"]
    if data.get("auto_fill_source") is not None:
        habit.auto_fill_source = data["auto_fill_source"]

    if data.get("section") is not None:
        habit.section = data["section"]

    # auto-assign sort_order unless caller provided it
    provided_order = data.get("sort_order")
    if provided_order is None:
        max_order = (
            session.query(sa_func.max(Habit.sort_order))
            .filter(Habit.user_id == user_id)
            .scalar()
        )
        habit.sort_order = (max_order or 0) + 1
    else:
        habit.sort_order = provided_order

    session.add(habit)
    session.commit()
    session.refresh(habit)
    return habit


def update_habit(
    session: Session,
    habit_id: uuid.UUID,
    user_id: uuid.UUID,
    data: dict,
) -> Optional[Habit]:
    """Apply partial updates; return None if the habit is not found."""
    h = get_habit(session, habit_id, user_id)
    if h is None:
        return None

    # v2 fields
    if "habit_type" in data and data["habit_type"] is not None:
        h.habit_type = data["habit_type"]
    if "schedule_type" in data and data["schedule_type"] is not None:
        h.schedule_type = data["schedule_type"]
    if "target_value" in data and data["target_value"] is not None:
        h.target_value = data["target_value"]
    if "active" in data and data["active"] is not None:
        h.active = data["active"]
    if "display_order" in data and data["display_order"] is not None:
        h.display_order = data["display_order"]

    # shared / legacy fields
    if "name" in data and data["name"] is not None:
        h.name = data["name"].strip()
    if "unit" in data and data["unit"] is not None:
        h.unit = data["unit"]
    if "schedule_target" in data and data["schedule_target"] is not None:
        h.schedule_target = data["schedule_target"]
    if "description" in data and data["description"] is not None:
        h.description = data["description"]
    if "weekly_target" in data and data["weekly_target"] is not None:
        h.weekly_target = data["weekly_target"]
    if "icon" in data and data["icon"] is not None:
        h.icon = data["icon"]
    if "color" in data and data["color"] is not None:
        h.color = data["color"]
    if "auto_fill_source" in data and data["auto_fill_source"] is not None:
        h.auto_fill_source = data["auto_fill_source"]
    if "sort_order" in data and data["sort_order"] is not None:
        h.sort_order = data["sort_order"]
    if "is_archived" in data and data["is_archived"] is not None:
        h.is_archived = data["is_archived"]
    if "section" in data and data["section"] is not None:
        h.section = data["section"]

    h.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(h)
    return h


def archive_habit(
    session: Session,
    habit_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[Habit]:
    """Soft-delete: set active=False and is_archived=True; return updated row."""
    h = get_habit(session, habit_id, user_id)
    if h is None:
        return None
    h.active = False
    h.is_archived = True
    h.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(h)
    return h


def upsert_habit_log(
    session: Session,
    habit_id: uuid.UUID,
    user_id: uuid.UUID,
    log_date: date,
    value: float,
    note: Optional[str] = None,
) -> tuple[HabitLog, bool]:
    """Upsert a habit log for (habit_id, log_date).

    Returns (log, was_inserted) — was_inserted=True on first write.
    """
    existing = (
        session.query(HabitLog)
        .filter(HabitLog.habit_id == habit_id, HabitLog.log_date == log_date)
        .first()
    )
    if existing is not None:
        existing.value = value
        if note is not None:
            existing.note = note
        existing.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(existing)
        return existing, False

    log = HabitLog(
        habit_id=habit_id,
        user_id=user_id,
        log_date=log_date,
        value=value,
        note=note,
        log_week_start=_week_start(log_date),
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    return log, True


def get_habit_logs(
    session: Session,
    habit_id: uuid.UUID,
    user_id: uuid.UUID,
    from_date: date,
    to_date: date,
) -> list[HabitLog]:
    """Return logs for habit_id/user_id in [from_date, to_date], ordered by log_date."""
    return (
        session.query(HabitLog)
        .filter(
            HabitLog.habit_id == habit_id,
            HabitLog.user_id == user_id,
            HabitLog.log_date >= from_date,
            HabitLog.log_date <= to_date,
        )
        .order_by(HabitLog.log_date)
        .all()
    )
