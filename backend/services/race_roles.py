"""Race roles, targets, add-on runs and role results (revamp P6-4)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from backend.services.checkpoint_detector import is_run_workout

ROLES = ("a_race", "pb", "long_run", "fun")
RECALIBRATING_ROLES = frozenset({"a_race", "pb"})
ADDON_WINDOW_MINUTES = 60
ADDON_DISTANCE_TOLERANCE_KM = 0.5
POWER_CAP_TOLERANCE = 1.03
PB_LIMIT_PER_BLOCK = 2

ROLE_LABELS = {"a_race": "A race", "pb": "PB attempt", "long_run": "Long run", "fun": "Fun run"}
ROLE_TARGETS = {
    "a_race": "Target: the goal time",
    "pb": "Target: a personal best",
    "long_run": "Target: a steady effort",
    "fun": "Target: enjoy it",
}


def _derive_role_from_legacy(race) -> str:
    if getattr(race, "race_type", None) == "checkpoint":
        return "long_run"
    priority = getattr(race, "priority", None)
    if priority == "A":
        return "a_race"
    if priority == "B":
        return "pb"
    return "fun"


def race_role(race) -> str:
    role: Optional[str] = getattr(race, "role", None)
    if role in ROLES:
        return role
    return _derive_role_from_legacy(race)


def recalibrates(race) -> bool:
    return race_role(race) in RECALIBRATING_ROLES


def role_target_summary(race) -> str:
    role = race_role(race)
    if role == "pb" and race.goal_time_seconds:
        return f"Target: {race.goal_time_seconds // 60} min"
    if role == "long_run":
        parts = []
        if race.power_cap_w:
            parts.append(f"cap {race.power_cap_w} W")
        if race.addon_distance_km is not None:
            parts.append(f"+{float(race.addon_distance_km):g} km add-on")
        if parts:
            return "Target: " + ", ".join(parts)
    if role == "a_race" and race.goal_band_low_seconds and race.goal_band_high_seconds:
        lo, hi = race.goal_band_low_seconds, race.goal_band_high_seconds
        return f"Target: {lo // 60}-{hi // 60} min band"
    return ROLE_TARGETS[role]


def _a_race_dates(races) -> list[date]:
    return sorted({r.race_date for r in races if race_role(r) == "a_race"})


def races_in_a_block(races, race_date: date) -> list:
    """Races between consecutive A races: day after previous A through day before next A."""
    a_dates = _a_race_dates(races)
    if not a_dates:
        return []
    prev_a = max((d for d in a_dates if d < race_date), default=None)
    next_a = min((d for d in a_dates if d > race_date), default=None)
    if prev_a is None or next_a is None:
        return []
    start = prev_a + timedelta(days=1)
    end = next_a
    return [r for r in races if start <= r.race_date < end]


def pb_limit_warning(races, race) -> Optional[str]:
    if race_role(race) != "pb":
        return None
    block = races_in_a_block(races, race.race_date)
    pb_races = sorted(
        [r for r in block if race_role(r) == "pb"],
        key=lambda r: (r.race_date, str(getattr(r, "id", ""))),
    )
    rank = next((i + 1 for i, r in enumerate(pb_races) if getattr(r, "id", None) == getattr(race, "id", object())), None)
    if rank is None:
        rank = sum(1 for r in pb_races if r.race_date <= race.race_date)
    if rank > PB_LIMIT_PER_BLOCK:
        return (
            f"Warning: PB #{rank} in this A-race block "
            f"(recommended limit is {PB_LIMIT_PER_BLOCK})."
        )
    return None


def _wval(obj, key):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _workout_end(workout) -> Optional[Any]:
    start = _wval(workout, "start_time")
    dur = _wval(workout, "duration_seconds")
    if start is None or dur is None:
        return None
    return start + timedelta(seconds=int(dur))


def find_addon_workout(race, main_workout, workouts) -> Optional[Any]:
    """First synced run starting within 60 min after the race ends, same calendar day."""
    if main_workout is None:
        return None
    race_end = _workout_end(main_workout)
    if race_end is None:
        return None
    window_end = race_end + timedelta(minutes=ADDON_WINDOW_MINUTES)
    main_id = _wval(main_workout, "id")
    best = None
    best_start = None
    for w in workouts:
        if _wval(w, "id") == main_id:
            continue
        if not is_run_workout(_wval(w, "workout_type") or ""):
            continue
        if _wval(w, "workout_date") != race.race_date:
            continue
        start = _wval(w, "start_time")
        if start is None:
            continue
        if start < race_end or start > window_end:
            continue
        if best_start is None or start < best_start:
            best, best_start = w, start
    return best


def try_auto_link_addon(race, main_workout, workouts) -> Optional[Any]:
    """Return the workout to link, or None. Does not mutate the race."""
    if race.addon_workout_id is not None:
        return None
    return find_addon_workout(race, main_workout, workouts)


def compute_role_result(
    race,
    main_workout=None,
    addon_workout=None,
) -> Optional[dict[str, Any]]:
    role = race_role(race)
    if role == "fun":
        return None

    actual = race.actual_time_seconds

    if role == "pb":
        goal = race.goal_time_seconds
        if actual is None or goal is None:
            return {"role": role, "status": "unknown"}
        passed = actual <= goal
        return {"role": role, "status": "pass" if passed else "fail", "chip_seconds": actual, "goal_seconds": goal}

    if role == "a_race":
        lo = race.goal_band_low_seconds
        hi = race.goal_band_high_seconds
        if actual is None or lo is None or hi is None:
            return {"role": role, "status": "unknown"}
        if lo <= actual <= hi:
            status = "pass"
        elif actual < lo:
            status = "fast"
        else:
            status = "slow"
        return {
            "role": role,
            "status": status,
            "chip_seconds": actual,
            "band_low_seconds": lo,
            "band_high_seconds": hi,
        }

    if role == "long_run":
        cap = race.power_cap_w
        target_addon = float(race.addon_distance_km) if race.addon_distance_km is not None else 0.0
        if main_workout is None:
            return {"role": role, "status": "unknown"}
        avg_power = _wval(main_workout, "avg_power")
        if cap is None or avg_power is None:
            power_ok = None
        else:
            power_ok = float(avg_power) <= cap * POWER_CAP_TOLERANCE
        addon_km = 0.0
        if addon_workout is not None:
            d = _wval(addon_workout, "distance_km")
            addon_km = float(d) if d is not None else 0.0
        if target_addon <= 0:
            addon_ok = True
        elif addon_workout is None:
            addon_ok = False
        else:
            addon_ok = abs(addon_km - target_addon) <= ADDON_DISTANCE_TOLERANCE_KM
        if power_ok is None:
            return {"role": role, "status": "unknown"}
        passed = bool(power_ok and addon_ok)
        return {
            "role": role,
            "status": "pass" if passed else "fail",
            "avg_power_w": int(avg_power) if avg_power is not None else None,
            "power_cap_w": cap,
            "addon_distance_km": addon_km,
            "addon_target_km": target_addon,
        }

    return None