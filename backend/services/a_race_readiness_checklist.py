"""A-race readiness checklist (revamp P6-7, #1881)."""
from __future__ import annotations

import math
import uuid
from datetime import date, timedelta
from typing import Any, Optional

from backend.models import Race, Workout
from backend.services.checkpoint_detector import is_run_workout
from backend.services.perf_a_race import next_a_race
from backend.services.race_roles import race_role

_UNSET = object()

LONG_RUN_TARGET_SEC = 3 * 3600 + 30 * 60
LONG_RUN_ITEM_TARGET = 2
FUEL_REHEARSAL_TARGET = 4
FUEL_RUN_MIN_SEC = 90 * 60
RACE_SHOE_MIN_KM = 30.0
WEEKS_BEFORE_WINDOW_START = 10
WEEKS_BEFORE_WINDOW_END = 3
PB_LOOKBACK_WEEKS = 6


def _item(
    key: str,
    label: str,
    *,
    state: str,
    done: int,
    target: int,
    source: str,
    manual: bool = False,
    detail: Optional[str] = None,
    note: Optional[str] = None,
    action: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "state": state,
        "done": done,
        "target": target,
        "count_label": f"{done} / {target}",
        "source": source,
        "manual": manual,
        "detail": detail,
        "note": note,
        "action": action,
    }


def _state_from_counts(done: int, target: int) -> str:
    if done >= target:
        return "done"
    if done > 0:
        return "in_progress"
    return "not_started"


def _run_workouts(session, user_id: uuid.UUID, start: date, end: date) -> list[Workout]:
    rows = (
        session.query(Workout)
        .filter(Workout.user_id == user_id, Workout.workout_date >= start, Workout.workout_date <= end)
        .all()
    )
    return [w for w in rows if is_run_workout(w.workout_type or "")]


def _race_shoe_ids(session, user_id: uuid.UUID) -> frozenset[uuid.UUID]:
    try:
        from backend.models import AthleteShoe
    except ImportError:
        return frozenset()
    rows = (
        session.query(AthleteShoe)
        .filter(AthleteShoe.user_id == user_id, AthleteShoe.is_race_shoe.is_(True), AthleteShoe.retired.is_(False))
        .all()
    )
    return frozenset(r.id for r in rows)


def _used_race_shoe(workout: Workout, race_shoe_ids: frozenset[uuid.UUID]) -> bool:
    overrides = workout.manual_overrides if isinstance(workout.manual_overrides, dict) else {}
    if overrides.get("race_shoe"):
        return True
    shoe_id = getattr(workout, "shoe_id", None)
    if shoe_id is None:
        return False
    try:
        sid = shoe_id if isinstance(shoe_id, uuid.UUID) else uuid.UUID(str(shoe_id))
    except (ValueError, AttributeError, TypeError):
        return False
    return sid in race_shoe_ids


def _fuel_run_ok(workout: Workout) -> bool:
    dur = workout.duration_seconds or 0
    if dur < FUEL_RUN_MIN_SEC:
        return False
    gels = getattr(workout, "gel_count", None)
    fluid = getattr(workout, "fluid_level", None)
    if gels is None or fluid is None:
        return False
    need = max(1, math.ceil(dur / (40 * 60)))
    return int(gels) >= need and str(fluid).lower() in ("ok", "high")


def item_long_runs(session, user_id: uuid.UUID, race_date: date) -> dict[str, Any]:
    start = race_date - timedelta(weeks=WEEKS_BEFORE_WINDOW_START)
    end = race_date - timedelta(weeks=WEEKS_BEFORE_WINDOW_END)
    count = sum(
        1 for w in _run_workouts(session, user_id, start, end) if (w.duration_seconds or 0) >= LONG_RUN_TARGET_SEC
    )
    done = min(count, LONG_RUN_ITEM_TARGET)
    return _item(
        "long_runs_330",
        "Two runs of 3:30 or longer (10-3 weeks out)",
        state=_state_from_counts(count, LONG_RUN_ITEM_TARGET),
        done=done,
        target=LONG_RUN_ITEM_TARGET,
        source="workouts.duration_seconds",
        detail=f"{done} of {LONG_RUN_ITEM_TARGET} long runs done",
    )


def item_race_shoe(session, user_id: uuid.UUID, race_date: date) -> dict[str, Any]:
    start = race_date - timedelta(weeks=WEEKS_BEFORE_WINDOW_START)
    shoes = _race_shoe_ids(session, user_id)
    found = any(
        float(w.distance_km or 0) >= RACE_SHOE_MIN_KM and _used_race_shoe(w, shoes)
        for w in _run_workouts(session, user_id, start, race_date - timedelta(days=1))
    )
    return _item(
        "race_shoe_30k",
        "Race shoes on a run of 30 km or more",
        state="done" if found else "not_started",
        done=1 if found else 0,
        target=1,
        source="workouts.shoe_id or manual_overrides.race_shoe (P6-14)",
        detail="Log the shoe on one 30 km+ run",
    )


def item_fuel_rehearsal(session, user_id: uuid.UUID, race_date: date) -> dict[str, Any]:
    start = race_date - timedelta(weeks=WEEKS_BEFORE_WINDOW_START)
    count = sum(
        1 for w in _run_workouts(session, user_id, start, race_date - timedelta(days=1)) if _fuel_run_ok(w)
    )
    return _item(
        "fuel_rehearsal",
        "Fuel rehearsed on 90 min+ runs (gel + fluid)",
        state=_state_from_counts(count, FUEL_REHEARSAL_TARGET),
        done=min(count, FUEL_REHEARSAL_TARGET),
        target=FUEL_REHEARSAL_TARGET,
        source="workouts.gel_count, fluid_level (P6-14)",
        detail=f"Log gels and fluid on {FUEL_REHEARSAL_TARGET} runs over 90 min",
    )


def item_pb_block(session, user_id: uuid.UUID, race_date: date) -> dict[str, Any]:
    start = race_date - timedelta(weeks=PB_LOOKBACK_WEEKS)
    rows = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.race_date >= start,
            Race.race_date < race_date,
            Race.status == "done",
            Race.actual_time_seconds.isnot(None),
        )
        .all()
    )
    count = sum(1 for r in rows if race_role(r) == "pb")
    return _item(
        "pb_result",
        "A PB result in the 6 weeks before the A race",
        state="done" if count else "not_started",
        done=1 if count else 0,
        target=1,
        source="races with role pb",
        detail="Run a PB-attempt race in the 6 weeks before",
    )


def item_cp_fresh(session, user_id: uuid.UUID, today: date) -> dict[str, Any]:
    from backend.services.cp_staleness import get_cp_status

    cp = get_cp_status(session, user_id, today)
    stale = bool(cp.get("stale"))
    fresh = not stale and cp.get("status") != "no_cp"
    return _item(
        "cp_fresh",
        "CP not stale",
        state="done" if fresh else ("in_progress" if cp.get("status") == "no_cp" else "not_started"),
        done=1 if fresh else 0,
        target=1,
        source="cp_staleness (#1877)",
        action="update_cp",
        detail="Update CP with a recent hard effort",
    )


def item_toilet_plan(race: Race) -> dict[str, Any]:
    notes = (getattr(race, "notes", None) or "").strip()
    done = bool(getattr(race, "toilet_plan_done", False)) and bool(notes)
    return _item(
        "toilet_plan",
        "Race-morning toilet plan",
        state="done" if done else "not_started",
        done=1 if done else 0,
        target=1,
        source="manual on A race",
        manual=True,
        detail="Write your race-morning plan",
        note=notes[:120] if notes else None,
    )


def build_checklist(
    session,
    user_id: uuid.UUID,
    today: date,
    *,
    race: Any = _UNSET,
) -> dict[str, Any]:
    if race is _UNSET:
        race = next_a_race(session, user_id, today)
    if race is None:
        return {
            "race_id": None,
            "available": False,
            "reason": "no_a_race",
            "summary": {"done": 0, "total": 6, "count_label": "0 / 6"},
            "items": [],
        }
    items = [
        item_long_runs(session, user_id, race.race_date),
        item_race_shoe(session, user_id, race.race_date),
        item_fuel_rehearsal(session, user_id, race.race_date),
        item_pb_block(session, user_id, race.race_date),
        item_cp_fresh(session, user_id, today),
        item_toilet_plan(race),
    ]
    done = sum(1 for it in items if it["state"] == "done")
    return {
        "race_id": str(race.id),
        "available": True,
        "summary": {"done": done, "total": len(items), "count_label": f"{done} / {len(items)}"},
        "items": items,
    }
