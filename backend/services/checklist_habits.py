"""Checklist-specific habits (sleep target) — sprint 135 / WC-07."""
from __future__ import annotations

import uuid as _uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import Habit

SLEEP_SOURCE = "sleep.hours_min"
SLEEP_TARGET_HOURS = 7.5


def _find_sleep(db: Session, user_id) -> Habit | None:
    return (
        db.query(Habit)
        .filter(
            Habit.user_id == user_id,
            Habit.is_archived.is_(False),
            Habit.auto_fill_source == SLEEP_SOURCE,
        )
        .first()
    )


def ensure_sleep_habit(db: Session, user_id) -> Habit | None:
    """Idempotently create the Sleep ≥ target checklist habit."""
    existing = _find_sleep(db, user_id)
    if existing is not None:
        if getattr(existing, "checklist_role", "core") == "off":
            return existing
        existing.section = "training"
        existing.is_focus = True
        return existing

    candidate = Habit(
        id=_uuid.uuid4(),
        user_id=user_id,
        name="Sleep ≥ target",
        habit_type="binary",
        schedule_type="daily",
        tracking_type="daily_checkmark",
        target_value=SLEEP_TARGET_HOURS,
        unit="h",
        auto_fill_source=SLEEP_SOURCE,
        icon="ti-moon",
        sort_order=3,
        display_order=3,
        section="training",
        active=True,
        is_archived=False,
        is_focus=True,
        checklist_role="core",
    )
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        return candidate
    except IntegrityError:
        return _find_sleep(db, user_id)
