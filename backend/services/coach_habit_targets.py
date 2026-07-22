"""Coach-tracked habit targets — stretch (daily) + Zone 2 (weekly).

Stable identity via ``auto_fill_source``:
- ``workout.zone2_minutes`` — weekly Z2 minutes, autofilled from workouts
- ``coach.stretch_daily`` — daily stretch minutes (manual log; key is identity only)

Plan/coach read targets from these habits instead of training-preferences fields
or Settings ``weekly_zone2_target_min``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.models import Habit, UserPreferences

ZONE2_SOURCE = "workout.zone2_minutes"
STRETCH_SOURCE = "coach.stretch_daily"

_DEFAULT_ZONE2_MIN = 150
_DEFAULT_STRETCH_MIN = 10


def _zone2_seed_target(db: Session, user_id) -> int:
    """Prefer legacy Settings value, else training-prefs payload, else default."""
    prefs = (
        db.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .one_or_none()
    )
    if prefs is not None and prefs.weekly_zone2_target_min is not None:
        return int(prefs.weekly_zone2_target_min)
    try:
        from backend.services.training_prefs import active_dict
        from backend.services.pref_catalog import get_field

        info = active_dict(db, user_id)
        val = get_field(info.get("payload") or {}, "zone2_weekly_min")
        if val is not None and int(val) > 0:
            return int(val)
    except Exception:
        pass
    return _DEFAULT_ZONE2_MIN


def _stretch_seed_target(db: Session, user_id) -> int:
    try:
        from backend.services.training_prefs import active_dict
        from backend.services.pref_catalog import get_field

        info = active_dict(db, user_id)
        val = get_field(info.get("payload") or {}, "stretch_daily_min")
        if val is not None and int(val) > 0:
            return int(val)
    except Exception:
        pass
    return _DEFAULT_STRETCH_MIN


def _find_by_source(db: Session, user_id, source: str) -> Habit | None:
    return (
        db.query(Habit)
        .filter(
            Habit.user_id == user_id,
            Habit.auto_fill_source == source,
            Habit.is_archived.is_(False),
        )
        .order_by(Habit.sort_order.asc())
        .first()
    )


def ensure_coach_tracked_habits(db: Session, user_id) -> dict[str, Habit]:
    """Idempotently create Zone 2 + Daily stretch habits. Returns both rows."""
    out: dict[str, Habit] = {}

    z2 = _find_by_source(db, user_id, ZONE2_SOURCE)
    if z2 is None:
        target = _zone2_seed_target(db, user_id)
        z2 = Habit(
            user_id=user_id,
            name="Zone 2",
            habit_type="duration",
            schedule_type="weekly",
            target_value=target,
            weekly_target=target,
            unit="min",
            tracking_type="weekly_minutes",
            auto_fill_source=ZONE2_SOURCE,
            section="training",
            icon="ti-heart-rate-monitor",
            active=True,
            is_archived=False,
        )
        db.add(z2)
        db.flush()
    out["zone2"] = z2

    stretch = _find_by_source(db, user_id, STRETCH_SOURCE)
    if stretch is None:
        target = _stretch_seed_target(db, user_id)
        stretch = Habit(
            user_id=user_id,
            name="Daily stretch",
            habit_type="duration",
            schedule_type="daily",
            target_value=target,
            unit="min",
            tracking_type="daily_checkmark",
            auto_fill_source=STRETCH_SOURCE,
            section="training",
            icon="ti-stretching",
            active=True,
            is_archived=False,
        )
        db.add(stretch)
        db.flush()
    out["stretch"] = stretch
    return out


def _int_target(habit: Habit | None, *, weekly: bool) -> int:
    if habit is None:
        return 0
    if weekly:
        if habit.weekly_target is not None:
            return int(float(habit.weekly_target))
        if habit.target_value is not None:
            return int(float(habit.target_value))
        return 0
    if habit.target_value is not None:
        return int(float(habit.target_value))
    if habit.weekly_target is not None:
        return int(float(habit.weekly_target))
    return 0


def habit_targets_for_coach(db: Session, user_id, *, ensure: bool = True) -> dict[str, Any]:
    """Return stretch_daily_min + zone2_weekly_min for plan/coach facts."""
    if ensure:
        rows = ensure_coach_tracked_habits(db, user_id)
        stretch = rows["stretch"]
        zone2 = rows["zone2"]
    else:
        stretch = _find_by_source(db, user_id, STRETCH_SOURCE)
        zone2 = _find_by_source(db, user_id, ZONE2_SOURCE)
    return {
        "stretch_daily_min": _int_target(stretch, weekly=False),
        "zone2_weekly_min": _int_target(zone2, weekly=True),
        "stretch_habit_id": str(stretch.id) if stretch else None,
        "zone2_habit_id": str(zone2.id) if zone2 else None,
    }
