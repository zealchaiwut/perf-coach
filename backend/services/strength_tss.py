"""Revamp strength TSS (P2-2): exercises × multiplier vs effort × time."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlanExercise, Workout, WorkoutExercise

STRENGTH_SET_TSS = 3.3
STRENGTH_METHODS = frozenset({"exercises", "effort_time"})
_STRENGTH_RE = re.compile(r"^(lift|strength|wod|crossfit|plyo)", re.IGNORECASE)


_EFFORT_SESSION_RE = re.compile(r"^(lift|strength|wod|crossfit|plyo|mobility)", re.IGNORECASE)


def is_strength_workout(workout: Workout) -> bool:
    return bool(_STRENGTH_RE.match((workout.workout_type or "").strip()))


def is_effort_tss_session(workout: Workout) -> bool:
    """Strength, plyo, or mobility — sessions whose TSS can follow session_effort."""
    return bool(_EFFORT_SESSION_RE.match((workout.workout_type or "").strip()))


def from_effort_time(*, duration_min: float, effort: int) -> dict[str, Any]:
    """TSS = duration_min/60 × (effort/10)² × 100, rounded integer."""
    if effort < 1 or effort > 10:
        return {"tss": None, "method": "effort_time", "reason": "effort must be 1–10"}
    if duration_min <= 0:
        return {"tss": None, "method": "effort_time", "reason": "duration required"}
    raw = (duration_min / 60.0) * ((effort / 10.0) ** 2) * 100.0
    return {"tss": int(round(raw)), "method": "effort_time"}


def _multipliers(session: Session, names: list[str]) -> dict[str, float]:
    if not names:
        return {}
    rows = (
        session.query(PlanExercise)
        .filter(PlanExercise.active.is_(True))
        .all()
    )
    by_lower = {r.name.strip().lower(): float(r.tss_weight) for r in rows}
    out: dict[str, float] = {}
    for n in names:
        key = n.strip().lower()
        out[key] = by_lower.get(key, 1.0)
    return out


def from_exercises(
    exercises: list[dict[str, Any]],
    *,
    multipliers: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """Per-exercise: set_count × STRENGTH_SET_TSS × library multiplier (1.0 custom)."""
    if not exercises:
        return {"tss": None, "method": "exercises", "per_exercise": [], "reason": "no exercises"}
    multipliers = multipliers or {}
    per: list[dict[str, Any]] = []
    total = 0.0
    for ex in exercises:
        name = (ex.get("name") or "").strip()
        sets = ex.get("sets") or []
        n_sets = len(sets) if isinstance(sets, list) else 0
        mult = multipliers.get(name.lower(), 1.0)
        tss = round(n_sets * STRENGTH_SET_TSS * mult, 1)
        per.append(
            {
                "name": name,
                "tss": tss,
                "set_count": n_sets,
                "multiplier": mult,
            }
        )
        total += tss
    return {
        "tss": round(total, 1),
        "method": "exercises",
        "per_exercise": per,
    }


def default_strength_method(exercises: Optional[list]) -> str:
    if exercises and len(exercises) > 0:
        return "exercises"
    return "effort_time"


def resolve_strength_method(workout: Workout, exercises: Optional[list]) -> str:
    stored = getattr(workout, "strength_tss_method", None)
    if stored in STRENGTH_METHODS:
        return stored
    return default_strength_method(exercises)


def canonical_from_workout_exercises(rows: list[WorkoutExercise]) -> list[dict[str, Any]]:
    """Best-effort canonical list from workout_exercises rows."""
    out: list[dict[str, Any]] = []
    for row in rows:
        sets_list: list[dict[str, Any]] = []
        raw_json = getattr(row, "sets_json", None)
        if raw_json:
            try:
                parsed = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            sets_list.append(dict(item))
            except (json.JSONDecodeError, TypeError):
                pass
        count = int(row.sets or 0) if row.sets else 0
        if not sets_list and count > 0:
            base: dict[str, Any] = {}
            if row.weight_kg is not None:
                base["kg"] = float(row.weight_kg)
            if row.reps is not None:
                base["reps"] = row.reps
            if base:
                sets_list = [dict(base) for _ in range(count)]
            else:
                sets_list = [{} for _ in range(count)]
        elif not sets_list and (row.reps or row.weight_kg):
            one: dict[str, Any] = {}
            if row.weight_kg is not None:
                one["kg"] = float(row.weight_kg)
            if row.reps is not None:
                one["reps"] = row.reps
            sets_list = [one]
        out.append({"name": row.name or "Exercise", "sets": sets_list})
    return out


def strength_tss_block(
    workout: Workout,
    *,
    session: Optional[Session] = None,
    exercises: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Compute both methods and return the active counted value."""
    if exercises is None and session is not None:
        rows = (
            session.query(WorkoutExercise)
            .filter(WorkoutExercise.workout_id == workout.id)
            .order_by(WorkoutExercise.display_order)
            .all()
        )
        exercises = canonical_from_workout_exercises(rows)
    exercises = exercises or []

    mult = _multipliers(session, [e["name"] for e in exercises]) if session else {}
    ex_block = from_exercises(exercises, multipliers=mult)
    duration_min = (workout.duration_seconds or 0) / 60.0 if workout.duration_seconds else 0.0
    effort = getattr(workout, "session_effort", None)
    eff_block = (
        from_effort_time(duration_min=duration_min, effort=int(effort))
        if effort is not None
        else {"tss": None, "method": "effort_time", "reason": "effort not set"}
    )

    method = resolve_strength_method(workout, exercises)
    chosen = ex_block if method == "exercises" else eff_block
    counted = chosen.get("tss")
    if method == "exercises" and counted is None:
        counted = eff_block.get("tss")
        method = "effort_time" if counted is not None else method
    elif method == "effort_time" and counted is None:
        counted = ex_block.get("tss")
        method = "exercises" if counted is not None else method

    return {
        "strength_tss_method": method,
        "tss_exercises": ex_block.get("tss"),
        "tss_effort_time": eff_block.get("tss"),
        "tss": counted,
        "method": method,
        "per_exercise": ex_block.get("per_exercise") or [],
        "tss_power": None,
        "tss_stryd": None,
    }


def apply_effort_time_tss(session: Optional[Session], workout: Workout) -> bool:
    """Persist effort×time TSS when this session uses that method.

    Returns True if ``workout.tss`` was written (including clearing it).
    Runs are skipped. Sessions with ``strength_tss_method == 'exercises'``
    keep their existing TSS.
    """
    if not is_effort_tss_session(workout):
        return False
    if getattr(workout, "tss_source", None) == "manual":
        return False

    exercises: list[dict[str, Any]] = []
    if session is not None and getattr(workout, "id", None):
        try:
            rows = (
                session.query(WorkoutExercise)
                .filter(WorkoutExercise.workout_id == workout.id)
                .order_by(WorkoutExercise.display_order)
                .all()
            )
            if isinstance(rows, list):
                exercises = canonical_from_workout_exercises(rows)
        except Exception:
            exercises = []

    if resolve_strength_method(workout, exercises) != "effort_time":
        return False

    duration_min = (workout.duration_seconds or 0) / 60.0 if workout.duration_seconds else 0.0
    effort = getattr(workout, "session_effort", None)
    if effort is None:
        workout.tss = None
        workout.tss_source = "calculated"
        workout.tss_method = "effort_time"
        return True

    result = from_effort_time(duration_min=duration_min, effort=int(effort))
    new_tss = result.get("tss")
    workout.tss = float(new_tss) if new_tss is not None else None
    workout.tss_source = "calculated"
    workout.tss_method = "effort_time"
    return True