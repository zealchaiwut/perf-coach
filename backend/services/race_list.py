"""Race list for the Performance page (revamp P4-11).

Needs-result, upcoming and completed rows. Estimates come from the same
``estimate_race_finish`` call as the hero and the projection chain
(``race_hero.build_estimate_block``), so the A race row can never disagree with
the chain final. Recording a result goes through the existing
``POST /api/races/{id}/calibrate`` flow; this module only suggests.

Run matching (suggestion only): a synced run on the race's date or one day
either side, with a distance within 5% of the race distance.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from backend.services.checkpoint_detector import is_run_workout
from backend.services.perf_a_race import next_a_race
from backend.services.race_finish_estimate import estimate_race_finish
from backend.services.race_hero import build_estimate_block
from backend.services.race_roles import ROLE_LABELS, race_role, recalibrates, role_target_summary
from backend.utils.log import get_logger

_log = get_logger(__name__)

MATCH_DAY_WINDOW = 1
MATCH_DISTANCE_TOLERANCE = 0.05
UPCOMING_LIMIT = 8
COMPLETED_LIMIT = 6


def _wval(w, key):
    return w.get(key) if isinstance(w, dict) else getattr(w, key, None)


def match_run(race_date: date, race_distance_km: Optional[float], workouts: list) -> Optional[dict[str, Any]]:
    """Best synced run for a race: same local date +/- 1 day, distance within 5%.

    Closest distance wins; a tie goes to the run nearest the race date.
    Returns None when nothing qualifies (wrong day or wrong distance).
    """
    if not race_distance_km or race_distance_km <= 0:
        return None
    best = None
    best_key = None
    for w in workouts:
        wd = _wval(w, "workout_date")
        dist = _wval(w, "distance_km")
        secs = _wval(w, "duration_seconds")
        if wd is None or dist is None or secs is None or float(dist) <= 0:
            continue
        if not is_run_workout(_wval(w, "workout_type") or ""):
            continue
        day_gap = abs((wd - race_date).days)
        if day_gap > MATCH_DAY_WINDOW:
            continue
        rel = abs(float(dist) - float(race_distance_km)) / float(race_distance_km)
        if rel > MATCH_DISTANCE_TOLERANCE:
            continue
        key = (rel, day_gap)
        if best_key is None or key < best_key:
            best, best_key = w, key
    if best is None:
        return None
    return {
        "workout_id": str(_wval(best, "id")) if _wval(best, "id") is not None else None,
        "date": _wval(best, "workout_date").isoformat(),
        "distance_km": float(_wval(best, "distance_km")),
        "moving_seconds": int(_wval(best, "duration_seconds")),
        "name": _wval(best, "name"),
    }


def _pace(sec: Optional[int], km: Optional[float]) -> Optional[int]:
    if sec is None or not km:
        return None
    from backend.models import compute_goal_pace

    pace, _ = compute_goal_pace(sec, km)
    return pace


def _base(race) -> dict[str, Any]:
    role = race_role(race)
    distance = float(race.distance_km) if race.distance_km is not None else None
    goal = int(race.goal_time_seconds) if race.goal_time_seconds is not None else None
    return {
        "id": str(race.id),
        "name": race.name,
        "race_date": race.race_date.isoformat(),
        "distance_km": distance,
        "priority": race.priority,
        "race_type": race.race_type,
        "role": role,
        "role_label": ROLE_LABELS[role],
        "role_target": role_target_summary(race),
        "goal_sec": goal,
        "goal_pace_seconds_per_km": race.goal_pace_seconds_per_km if race.goal_pace_seconds_per_km else _pace(goal, distance),
    }


def _race_specific(session, user_id, race, today: date) -> dict[str, Any]:
    from backend.services.score_reader import get_race_scores

    try:
        rs = (get_race_scores(session, user_id, race, as_of=today) or {}).get("race_specific") or {}
    except Exception:
        _log.warning("race scores unavailable for %s", race.id, exc_info=True)
        rs = {}

    def chip(axis: str) -> dict[str, Any]:
        block = rs.get(axis) or {}
        return {"score": block.get("score"), "delta_28d": block.get("delta_28d")}

    return {"endurance": chip("endurance"), "speed": chip("speed")}


def debrief_by_race(session, user_id, race_ids: list) -> dict[str, dict[str, Any]]:
    """Newest linked decision per race (P4-13) — drives the Debrief chip."""
    if not race_ids:
        return {}
    from backend.models import Decision
    from backend.services.decision_lessons import parse_lessons

    rows = (
        session.query(Decision)
        .filter(Decision.user_id == user_id, Decision.race_id.in_(race_ids))
        .order_by(Decision.decided_on.desc(), Decision.created_at.desc())
        .all()
    )
    out: dict[str, dict[str, Any]] = {}
    for d in rows:
        key = str(d.race_id)
        if key not in out:
            out[key] = {
                "decision_id": str(d.id),
                "decided_on": d.decided_on.isoformat(),
                "lessons_count": len(parse_lessons(d.raw_text)),
                "link": f"/coach#decision-{d.id}",
            }
    return out


def needs_result_row(race, workouts: list) -> dict[str, Any]:
    row = _base(race)
    distance = row["distance_km"]
    suggestion = match_run(race.race_date, distance, workouts)
    row["suggested_actual"] = suggestion
    row["suggestion_reason"] = None if suggestion else "No synced run matched"
    return row


def completed_row(race, workouts: list) -> dict[str, Any]:
    row = _base(race)
    actual = int(race.actual_time_seconds) if race.actual_time_seconds is not None else None
    run = match_run(race.race_date, row["distance_km"], workouts)
    row.update(
        chip_time_sec=actual,
        moving_time_sec=run["moving_seconds"] if run else None,
        goal_minus_actual_sec=(row["goal_sec"] - actual) if (row["goal_sec"] is not None and actual is not None) else None,
        actual_pace_seconds_per_km=_pace(actual, row["distance_km"]),
    )
    return row


def upcoming_row(session, user_id, race, today: date, target_id) -> dict[str, Any]:
    row = _base(race)
    row["estimate"] = build_estimate_block(
        estimate_race_finish(user_id, race, today=today, db=session), row["distance_km"]
    )
    row["race_specific"] = _race_specific(session, user_id, race, today)
    row["is_target"] = target_id is not None and race.id == target_id
    row["recalibrates_here"] = recalibrates(race)
    row["days_to_race"] = (race.race_date - today).days
    return row


def build_race_list(session, user_id: uuid.UUID, today: date) -> dict[str, Any]:
    from backend.models import Race, Workout

    races = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.status != "abandoned")
        .order_by(Race.race_date.asc())
        .all()
    )
    needs = [r for r in races if r.status == "planned" and r.race_date < today and r.actual_time_seconds is None]
    upcoming = [r for r in races if r.status == "planned" and r.race_date >= today]
    done = [r for r in races if r.status == "done" and r.actual_time_seconds is not None]
    done = sorted(done, key=lambda r: r.race_date, reverse=True)[:COMPLETED_LIMIT]

    need_rows_races = needs + done
    runs: list = []
    if need_rows_races:
        lo = min(r.race_date for r in need_rows_races) - timedelta(days=MATCH_DAY_WINDOW)
        hi = max(r.race_date for r in need_rows_races) + timedelta(days=MATCH_DAY_WINDOW)
        runs = (
            session.query(Workout)
            .filter(
                Workout.user_id == user_id,
                Workout.workout_date >= lo,
                Workout.workout_date <= hi,
                Workout.distance_km.isnot(None),
                Workout.duration_seconds.isnot(None),
            )
            .all()
        )

    target = next_a_race(session, user_id, today)
    target_id = target.id if target is not None else None
    debriefs = debrief_by_race(session, user_id, [r.id for r in need_rows_races])
    needs_rows = [needs_result_row(r, runs) for r in needs]
    done_rows = [completed_row(r, runs) for r in done]
    for row in needs_rows + done_rows:
        row["debrief"] = debriefs.get(row["id"])
    return {
        "today": today.isoformat(),
        "needs_result": needs_rows,
        "upcoming": [upcoming_row(session, user_id, r, today, target_id) for r in upcoming[:UPCOMING_LIMIT]],
        "total_upcoming": len(upcoming),
        "completed": done_rows,
    }
