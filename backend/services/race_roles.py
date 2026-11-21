"""Race roles for projection recalibration (revamp P4-10 amendment).

Only races with role ``pb`` or ``a_race`` recalibrate the projection;
``long_run`` and ``fun`` races are drawn as grey ticks and never move the line.

Race roles are owned by P6-4. Until that column lands this module reads
``race.role`` when present and otherwise derives a role from existing fields
(a single place to change once P6-4 ships):

    race_type == "checkpoint"  -> long_run
    priority  A                -> a_race
    priority  B                -> pb
    anything else (C)          -> fun
"""
from __future__ import annotations

from typing import Optional

ROLES = ("a_race", "pb", "long_run", "fun")
RECALIBRATING_ROLES = frozenset({"a_race", "pb"})


def race_role(race) -> str:
    role: Optional[str] = getattr(race, "role", None)
    if role in ROLES:
        return role
    if getattr(race, "race_type", None) == "checkpoint":
        return "long_run"
    priority = getattr(race, "priority", None)
    if priority == "A":
        return "a_race"
    if priority == "B":
        return "pb"
    return "fun"


def recalibrates(race) -> bool:
    return race_role(race) in RECALIBRATING_ROLES
