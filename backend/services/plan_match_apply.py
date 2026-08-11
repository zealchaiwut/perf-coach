"""Apply planned-session content onto a matched workout.

Plan→workout match used to be link-only (``matched_workout_id``). Strava
strength activities arrive with ``tss=NULL`` and no ``workout_exercises``, so
the Log / weekly Lift TSS / muscle-load paths stayed at zero even after a
manual match to a planned session that already had ``target_tss`` and an
exercise list.

On match (manual or auto) we:

1. Stamp ``workouts.tss`` from the plan when the workout has no TSS yet
   (``tss_source='manual'`` — athlete-confirmed via match).
2. Copy planned exercises into ``workout_exercises`` when the workout has none.
3. Recompute strength muscle load for that calendar day.

Never overwrites an existing workout TSS or existing exercise rows.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

_log = logging.getLogger(__name__)

_TSS_SOURCE = "manual"  # allowed by ck_workouts_tss_source_values; athlete-confirmed via match

_DONE_STATES = frozenset({"done", "completed", "complete"})
_SKIP_STATES = frozenset({"skipped", "skip"})
_INT_RE = re.compile(r"-?\d+")


def _as_dict(structure: Any) -> Optional[dict]:
    if isinstance(structure, dict):
        return structure
    return None


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v > 0 else None
    if isinstance(v, float):
        return int(v) if v > 0 else None
    m = _INT_RE.search(str(v))
    if not m:
        return None
    n = int(m.group(0))
    return n if n > 0 else None


def _parse_weight_kg(ex: dict) -> Optional[float]:
    for key in ("weight_kg", "weight", "load_kg"):
        n = _num(ex.get(key))
        if n is not None and n >= 0:
            return n
    load = ex.get("load")
    n = _num(load)
    if n is not None and n >= 0:
        return n
    return None


def resolve_planned_tss(structure: Any) -> Optional[float]:
    """Best TSS to stamp on a matched workout from the planned session.

    Prefer ``target_tss`` (the athlete's planned pin, e.g. 50) over the sum of
    per-exercise ``spend_tss`` (often a partial fill).
    """
    s = _as_dict(structure)
    if not s:
        return None
    target = _num(s.get("target_tss"))
    if target is not None and target >= 0:
        return round(target, 1)

    from backend.services.session_pins import structure_actual_spend

    spend = structure_actual_spend(s)
    if spend and spend.get("actual_tss") is not None:
        return float(spend["actual_tss"])

    exercises = s.get("exercises")
    if not isinstance(exercises, list):
        return None
    total = 0.0
    saw = False
    for ex in exercises:
        if not isinstance(ex, dict):
            continue
        st = str(ex.get("state") or "done").lower()
        if st in _SKIP_STATES:
            continue
        n = _num(ex.get("spend_tss"))
        if n is None:
            continue
        total += n
        saw = True
    return round(total, 1) if saw else None


def _exercise_rows_from_structure(structure: Any) -> list[dict]:
    s = _as_dict(structure)
    if not s:
        return []
    exercises = s.get("exercises")
    if not isinstance(exercises, list):
        return []
    out: list[dict] = []
    for ex in exercises:
        if not isinstance(ex, dict):
            continue
        name = str(ex.get("name") or "").strip()
        if not name:
            continue
        st = str(ex.get("state") or "done").lower()
        if st in _SKIP_STATES:
            continue
        out.append(
            {
                "block": (str(ex.get("block")).strip() if ex.get("block") else None) or None,
                "name": name[:200],
                "sets": _parse_int(ex.get("sets")),
                "reps": _parse_int(ex.get("reps")),
                "weight_kg": _parse_weight_kg(ex),
                "duration": (str(ex.get("duration")).strip() if ex.get("duration") else None) or None,
                "rpe": _parse_int(ex.get("rpe")),
            }
        )
    return out


def apply_planned_session_to_workout(session, planned, workout) -> dict:
    """Copy plan TSS/exercises onto ``workout`` when those fields are empty.

    ``session`` is an open SQLAlchemy Session; caller commits. Returns a small
    stats dict for tests / logging.
    """
    from backend.models import WorkoutExercise

    stats = {"tss_applied": False, "exercises_added": 0, "tss": None}

    if workout is None or planned is None:
        return stats

    structure = getattr(planned, "structure", None)

    if getattr(workout, "tss", None) is None:
        tss = resolve_planned_tss(structure)
        if tss is not None and tss >= 0:
            workout.tss = tss
            workout.tss_source = _TSS_SOURCE
            stats["tss_applied"] = True
            stats["tss"] = tss

    existing = (
        session.query(WorkoutExercise)
        .filter(WorkoutExercise.workout_id == workout.id)
        .count()
    )
    if existing == 0:
        rows = _exercise_rows_from_structure(structure)
        for i, row in enumerate(rows):
            session.add(
                WorkoutExercise(
                    workout_id=workout.id,
                    display_order=i,
                    block=row["block"],
                    name=row["name"],
                    sets=row["sets"],
                    reps=row["reps"],
                    weight_kg=row["weight_kg"],
                    duration=row["duration"],
                    rpe=row["rpe"],
                )
            )
            stats["exercises_added"] += 1

    return stats


def after_match_side_effects(user_id, workout, *, stats: Optional[dict] = None) -> None:
    """Muscle-load + training-load refresh after a match apply. Never raises."""
    if workout is None:
        return
    try:
        from backend.services.muscle_load import recompute_strength_load_for_date

        if (getattr(workout, "workout_type", None) or "").lower() in (
            "strength",
            "lift",
            "plyo",
            "wod",
        ) or (stats and stats.get("exercises_added")):
            recompute_strength_load_for_date(user_id, workout.workout_date)
    except Exception as exc:
        _log.warning(
            "plan_match_apply: muscle_load recompute failed for %s: %s",
            getattr(workout, "id", None),
            exc,
            exc_info=True,
        )
    try:
        from backend.services.worker_client import (
            delegate_precompute,
            precompute_on_write_enabled,
        )
        from backend.services.training_load import daily_update

        if precompute_on_write_enabled():
            res = delegate_precompute(str(user_id), dates=[workout.workout_date])
            if res.get("queued"):
                return
        daily_update(str(user_id), workout.workout_date)
    except Exception as exc:
        _log.warning(
            "plan_match_apply: load warm failed for %s: %s",
            getattr(workout, "id", None),
            exc,
            exc_info=True,
        )
