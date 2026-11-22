"""Long-run ladder — weekly longest run vs plan (revamp P6-8 / #1882)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlannedSession, Race, Workout
from backend.services.checkpoint_detector import is_run_workout
from backend.services.perf_a_race import next_a_race
from backend.services.plan_matching import _planned_duration_seconds
from backend.services.race_list import match_run
from backend.services.race_roles import race_role
from backend.services.weekly_rollup import bangkok_week_start, normalize_week_start, session_local_date
from backend.utils.time import today_bangkok

DEFAULT_NEED_SECONDS = 3 * 3600 + 30 * 60
QUALIFYING_COUNT_TARGET = 2
UNDER_TARGET_GAP_SECONDS = 20 * 60
DEFAULT_BLOCK_WEEKS = 20
ROLE_BAR_COLORS = {
    "a_race": "#e4ff52",
    "pb": "#fca5a5",
    "long_run": "#93c5fd",
    "fun": "#ddd6fe",
}


def format_duration_hm(seconds: Optional[int]) -> Optional[str]:
    if seconds is None or seconds <= 0:
        return None
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}:{m:02d}"


def _is_planned_long_run(ps: PlannedSession) -> bool:
    if (ps.session_type or "").lower() != "run":
        return False
    structure = ps.structure if isinstance(ps.structure, dict) else {}
    sub = (structure.get("subtype") or structure.get("run_subtype") or "").lower()
    name = (ps.name or "").lower()
    return sub in ("long_run", "longrun", "long") or "long" in name


def planned_long_run_target_seconds(row: PlannedSession) -> Optional[int]:
    if not _is_planned_long_run(row):
        return None
    structure = row.structure if isinstance(row.structure, dict) else {}
    sec = _planned_duration_seconds(structure)
    if sec:
        return sec
    dm = structure.get("duration_minutes")
    if dm is not None:
        try:
            return int(round(float(dm) * 60))
        except (TypeError, ValueError):
            pass
    return None


def _week_target(planned: list[PlannedSession], fallback_seconds: Optional[int]) -> Optional[int]:
    best: Optional[int] = None
    for ps in planned:
        sec = planned_long_run_target_seconds(ps)
        if sec is not None:
            best = sec if best is None else max(best, sec)
    if best is not None:
        return best
    return fallback_seconds


def _run_durations_for_week(
    workouts: list[Workout],
    races: list[Race],
    week_start: date,
    week_end: date,
) -> list[tuple[int, Optional[str]]]:
    runs = [
        w
        for w in workouts
        if week_start <= session_local_date(w) <= week_end
        and is_run_workout(w.workout_type or "")
        and w.duration_seconds is not None
        and int(w.duration_seconds) > 0
    ]
    race_role_for_week: Optional[str] = None
    week_races = [r for r in races if week_start <= r.race_date <= week_end]
    if week_races:
        week_races.sort(key=lambda r: (r.race_date, str(r.id)))
        race_role_for_week = race_role(week_races[-1])

    used_ids: set[uuid.UUID] = set()
    durations: list[tuple[int, Optional[str]]] = []

    for race in week_races:
        main = match_run(race.race_date, float(race.distance_km) if race.distance_km else None, runs)
        main_w = None
        if main and main.get("workout_id"):
            try:
                wid = uuid.UUID(main["workout_id"])
            except (ValueError, TypeError):
                wid = None
            if wid is not None:
                main_w = next((w for w in runs if w.id == wid), None)
        if main_w is None:
            continue
        total = int(main_w.duration_seconds or 0)
        addon_id = getattr(race, "addon_workout_id", None)
        used_ids.add(main_w.id)
        if addon_id is not None:
            addon = next((w for w in runs if w.id == addon_id), None)
            if addon is not None:
                total += int(addon.duration_seconds or 0)
                used_ids.add(addon.id)
        if total > 0:
            durations.append((total, race_role(race)))

    for w in runs:
        if w.id in used_ids:
            continue
        durations.append((int(w.duration_seconds), race_role_for_week or None))

    return durations


def week_actual_max_seconds(
    workouts: list[Workout],
    races: list[Race],
    week_start: date,
    week_end: date,
) -> tuple[Optional[int], Optional[str]]:
    options = _run_durations_for_week(workouts, races, week_start, week_end)
    if not options:
        return None, None
    best = max(options, key=lambda x: x[0])
    return best[0], best[1]


def red_state_triggered(completed_weeks: list[dict[str, Any]]) -> bool:
    streak = 0
    for row in completed_weeks:
        actual = row.get("actual_seconds")
        target = row.get("target_seconds")
        if actual is None or target is None:
            streak = 0
            continue
        if actual < target - UNDER_TARGET_GAP_SECONDS:
            streak += 1
            if streak >= 2:
                return True
        else:
            streak = 0
    return False


def _previous_a_race(session: Session, user_id: uuid.UUID, target: Race) -> Optional[Race]:
    rows = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.race_date < target.race_date)
        .order_by(Race.race_date.desc())
        .all()
    )
    for r in rows:
        if race_role(r) == "a_race" or getattr(r, "priority", None) == "A":
            return r
    return None


def _peak_long_run_seconds(
    workouts: list[Workout],
    races: list[Race],
    from_week: date,
    to_week: date,
) -> Optional[int]:
    peak: Optional[int] = None
    ws = normalize_week_start(from_week)
    end = normalize_week_start(to_week)
    while ws <= end:
        we = ws + timedelta(days=6)
        val, _ = week_actual_max_seconds(workouts, races, ws, we)
        if val is not None:
            peak = val if peak is None else max(peak, val)
        ws += timedelta(weeks=1)
    return peak


def long_run_ladder_payload(
    session: Session,
    user_id: uuid.UUID,
    *,
    today: Optional[date] = None,
) -> dict[str, Any]:
    today = today or today_bangkok()
    target_a = next_a_race(session, user_id, today)
    if target_a is None:
        return {"available": False, "reason": "no_a_race"}

    prev_a = _previous_a_race(session, user_id, target_a)
    block_start = (
        prev_a.race_date + timedelta(days=1)
        if prev_a is not None
        else target_a.race_date - timedelta(weeks=DEFAULT_BLOCK_WEEKS)
    )

    from_week = bangkok_week_start(block_start)
    to_week = bangkok_week_start(target_a.race_date)
    buffer_start = from_week - timedelta(days=2)
    buffer_end = to_week + timedelta(days=13)

    workouts = (
        session.query(Workout)
        .filter(Workout.user_id == user_id, Workout.workout_date >= buffer_start, Workout.workout_date <= buffer_end)
        .all()
    )
    races = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.race_date >= buffer_start, Race.race_date <= buffer_end)
        .all()
    )
    planned_rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= from_week,
            PlannedSession.planned_date <= to_week + timedelta(days=6),
        )
        .all()
    )
    planned_by_week: dict[date, list[PlannedSession]] = {}
    for ps in planned_rows:
        planned_by_week.setdefault(bangkok_week_start(ps.planned_date), []).append(ps)

    need_seconds = int(getattr(target_a, "long_run_need_seconds", None) or DEFAULT_NEED_SECONDS)
    fallback_target = getattr(target_a, "long_run_manual_target_seconds", None)
    fallback_target = int(fallback_target) if fallback_target else need_seconds

    weeks_out: list[dict[str, Any]] = []
    ws = from_week
    max_actual = need_seconds
    qualifying_count = 0

    while ws <= to_week:
        we = ws + timedelta(days=6)
        actual, bar_role = week_actual_max_seconds(workouts, races, ws, we)
        if actual is not None:
            max_actual = max(max_actual, actual)
            if actual >= need_seconds:
                qualifying_count += 1
        target = _week_target(planned_by_week.get(ws, []), fallback_target)
        weeks_out.append(
            {
                "week_start": ws.isoformat(),
                "week_end": we.isoformat(),
                "actual_seconds": actual,
                "actual_label": format_duration_hm(actual),
                "target_seconds": target,
                "target_label": format_duration_hm(target),
                "state": (
                    "current"
                    if ws <= today <= we
                    else ("future" if ws > today else "done")
                ),
                "race_role": bar_role,
                "bar_color": ROLE_BAR_COLORS.get(bar_role or "", None),
            }
        )
        ws += timedelta(weeks=1)

    red = red_state_triggered([w for w in weeks_out if w["state"] == "done"])

    prior_peak: Optional[int] = None
    prior_peak_label: Optional[str] = None
    if prev_a is not None:
        ref_end = bangkok_week_start(prev_a.race_date) - timedelta(weeks=1)
        ref_start = ref_end - timedelta(weeks=11)
        prior_peak = _peak_long_run_seconds(workouts, races, ref_start, ref_end)
        prior_peak_label = format_duration_hm(prior_peak)

    return {
        "available": True,
        "a_race_id": str(target_a.id),
        "a_race_name": target_a.name,
        "a_race_date": target_a.race_date.isoformat(),
        "need_seconds": need_seconds,
        "need_label": format_duration_hm(need_seconds),
        "prior_a_peak_seconds": prior_peak,
        "prior_a_peak_label": prior_peak_label,
        "qualifying_count": qualifying_count,
        "qualifying_count_target": QUALIFYING_COUNT_TARGET,
        "red_state": red,
        "scale_max_seconds": max(max_actual, need_seconds, prior_peak or 0, 1),
        "weeks": weeks_out,
    }
