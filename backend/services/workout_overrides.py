"""Persist manual edits on synced workouts so reconcile keeps them."""
from __future__ import annotations

from typing import Any


def set_override(workout, key: str, value: Any) -> None:
    """Record that the athlete set ``key`` manually (SQLAlchemy JSONB change detection)."""
    workout.manual_overrides = {**(workout.manual_overrides or {}), key: value}


def clear_override(workout, key: str) -> None:
    base = dict(workout.manual_overrides or {})
    if key in base:
        del base[key]
        workout.manual_overrides = base or None