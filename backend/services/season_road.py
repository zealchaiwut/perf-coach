"""Season road page payload (revamp P6-6 / #1880).

One view of the block between consecutive A races: hero on the target A race,
track status, a date-ordered timeline, and race rows with role results.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from backend.services.perf_a_race import next_a_race
from backend.services.projection_view import goal_state
from backend.services.race_finish_estimate import estimate_race_finish
from backend.services.race_hero import build_estimate_block
from backend.services.race_list import (
    _base,
    _gap_chip,
    _pace,
    format_distance_km,
    format_race_date,
    match_run,
)
from backend.services.race_roles import ROLE_LABELS, compute_role_result, race_role, role_target_summary
def goal_interval_sec(race) -> tuple[Optional[int], Optional[int]]:
    lo = getattr(race, "goal_band_low_seconds", None)
    hi = getattr(race, "goal_band_high_seconds", None)
    if lo is not None and hi is not None:
        return int(lo), int(hi)
    g = race.goal_time_seconds
    if g is not None:
        return int(g), int(g)
    return None, None


def projection_interval_sec(est_sec: Optional[int], band_sec: Optional[int]) -> tuple[Optional[int], Optional[int]]:
    if est_sec is None:
        return None, None
    if band_sec is None:
        return est_sec, est_sec
    return est_sec - int(band_sec), est_sec + int(band_sec)


def bands_overlap(a_lo: int, a_hi: int, b_lo: int, b_hi: int) -> bool:
    return max(a_lo, b_lo) <= min(a_hi, b_hi)


def track_status(
    race,
    estimate: dict[str, Any],
    readiness_done: int,
    *,
    readiness_total: int = 5,
) -> dict[str, Any]:
    """On track / building / at risk per #1880."""
    g_lo, g_hi = goal_interval_sec(race)
    est = estimate.get("est_sec")
    band = estimate.get("band_sec")
    p_lo, p_hi = projection_interval_sec(est, band)
    if g_lo is None or g_hi is None or est is None:
        return {"status": "unknown", "label": "Unknown"}
    if p_lo is not None and p_hi is not None and bands_overlap(g_lo, g_hi, p_lo, p_hi):
        return {"status": "on_track", "label": "On track"}
    slower = p_hi is not None and p_hi > g_hi
    if not slower:
        return {"status": "on_track", "label": "On track"}
    if readiness_done < 4:
        return {"status": "building", "label": "Building"}
    return {"status": "at_risk", "label": "At risk"}


def _x_frac(d: date, start: date, end: date) -> float:
    span = (end - start).days
    if span <= 0:
        return 1.0
    return round(max(0.0, min(1.0, (d - start).days / span)), 4)


def _prev_a_race(races: list, next_a) -> Optional[Any]:
    a_races = sorted(
        [r for r in races if race_role(r) == "a_race" and r.race_date < next_a.race_date],
        key=lambda r: r.race_date,
    )
    for r in reversed(a_races):
        if r.status == "done":
            return r
    return a_races[-1] if a_races else None


def _block_races(races: list, start: date, end: date) -> list:
    return sorted(
        [r for r in races if start <= r.race_date <= end and r.status != "abandoned"],
        key=lambda r: (r.race_date, str(r.id)),
    )


def _hms(sec: Optional[int]) -> Optional[str]:
    if sec is None:
        return None
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _status_chip(race, today: date, role_result, actual_sec, goal_sec) -> dict[str, Any]:
    days = (race.race_date - today).days
    if days > 0:
        text = f"in {days} day" if days == 1 else f"in {days} days"
        return {"tone": "neutral", "text": text, "title": text, "aria_label": text}
    if actual_sec is not None and goal_sec is not None:
        chip = _gap_chip(int(goal_sec) - int(actual_sec), vs_goal=True)
        if chip:
            return chip
    if race_role(race) == "long_run" and role_result:
        st = role_result.get("status")
        if st == "pass":
            return {"tone": "good", "text": "pass", "title": "pass", "aria_label": "pass"}
        if st == "fail":
            return {"tone": "bad", "text": "missed", "title": "missed", "aria_label": "missed"}
    if actual_sec is None:
        return {
            "tone": "warn",
            "text": "needs a result",
            "title": "needs a result",
            "aria_label": "needs a result",
        }
    return {"tone": "neutral", "text": "done", "title": "done", "aria_label": "done"}


def _result_display(race, today: date, km) -> dict[str, Any]:
    actual = race.actual_time_seconds
    if actual is not None:
        pace = _pace(int(actual), km)
        return {
            "kind": "result",
            "time_sec": int(actual),
            "time_hms": _hms(int(actual)),
            "pace_seconds_per_km": pace,
            "pace_label": _hms(pace) if pace is not None else None,
        }
    if race.race_date < today:
        return {"kind": "record"}
    return {"kind": "empty"}


def _row(
    session,
    user_id: uuid.UUID,
    race,
    today: date,
    runs: list,
) -> dict[str, Any]:
    from backend.models import Workout

    row = _base(race)
    main = None
    addon = None
    suggestion = match_run(race.race_date, row["distance_km"], runs)
    if suggestion and suggestion.get("workout_id"):
        try:
            main = session.get(Workout, uuid.UUID(suggestion["workout_id"]))
        except (ValueError, AttributeError):
            main = None
    if race.addon_workout_id is not None:
        addon = session.get(Workout, race.addon_workout_id)
    rr = compute_role_result(race, main, addon)
    actual = int(race.actual_time_seconds) if race.actual_time_seconds is not None else None
    goal = row.get("goal_sec")
    row["role_result"] = rr
    row["counts_as"] = role_target_summary(race)
    row["result"] = _result_display(race, today, row.get("distance_km"))
    row["status_chip"] = _status_chip(race, today, rr, actual, goal)
    if actual is not None:
        row["chip_time_sec"] = actual
    row["days_to_race"] = (race.race_date - today).days
    row["recalibrates"] = race_role(race) in ("a_race", "pb")
    return row


def build_season_road(session, user_id: uuid.UUID, today: date) -> dict[str, Any]:
    from backend.models import Race, Workout
    from backend.services.a_race_readiness_checklist import build_checklist

    target = next_a_race(session, user_id, today)
    empty: dict[str, Any] = {
        "available": False,
        "today": today.isoformat(),
        "reason": "No upcoming A race",
        "hero": None,
        "timeline": None,
        "rows": [],
        "earlier_rows": [],
    }
    if target is None:
        return empty

    all_races = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.status != "abandoned")
        .order_by(Race.race_date.asc())
        .all()
    )
    prev_a = _prev_a_race(all_races, target)
    start = prev_a.race_date if prev_a is not None else min(target.race_date, today)
    end = target.race_date
    block = _block_races(all_races, start, end)

    lo_run = min(start, today) - timedelta(days=2)
    hi_run = max(end, today) + timedelta(days=2)
    runs = (
        session.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= lo_run,
            Workout.workout_date <= hi_run,
            Workout.distance_km.isnot(None),
            Workout.duration_seconds.isnot(None),
        )
        .all()
    )

    distance = float(target.distance_km) if target.distance_km else None
    estimate = build_estimate_block(
        estimate_race_finish(user_id, target, today=today, db=session),
        distance,
    )
    checklist = build_checklist(session, user_id, today)
    summary = checklist.get("summary") or {}
    readiness_done = int(summary.get("done") or 0)
    readiness_total = int(summary.get("total") or 5)
    status = track_status(target, estimate, readiness_done, readiness_total=readiness_total)
    goal = goal_state(session, user_id, target)

    hero = {
        "race": {
            "id": str(target.id),
            "name": target.name,
            "race_date": target.race_date.isoformat(),
            "race_date_label": format_race_date(target.race_date),
            "distance_km": distance,
            "distance_label": format_distance_km(distance),
            "priority": target.priority,
            "role": race_role(target),
            "role_label": ROLE_LABELS.get(race_role(target), "A race"),
            "days_to_race": (target.race_date - today).days,
        },
        "goal": goal,
        "estimate": estimate,
        "track_status": status,
        "readiness": {
            "done": readiness_done,
            "total": readiness_total,
            "count_label": f"{readiness_done} of {readiness_total}",
        },
    }

    nodes = []
    for r in block:
        actual = r.actual_time_seconds
        goal = r.goal_time_seconds
        chip = _status_chip(r, today, None, actual, goal)
        nodes.append(
            {
                "id": str(r.id),
                "name": r.name,
                "race_date": r.race_date.isoformat(),
                "date_label": format_race_date(r.race_date),
                "distance_km": float(r.distance_km) if r.distance_km is not None else None,
                "distance_label": format_distance_km(
                    float(r.distance_km) if r.distance_km is not None else None
                ),
                "priority": r.priority,
                "role": race_role(r),
                "role_label": ROLE_LABELS.get(race_role(r), race_role(r)),
                "x": _x_frac(r.race_date, start, end),
                "is_today": False,
                "is_target_a": r.id == target.id,
                "status_tone": chip.get("tone") if actual is not None else "upcoming",
            }
        )
    from backend.services.projection_view import _assign_tag_lanes

    _assign_tag_lanes(nodes, min_dx=0.10)
    timeline = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "start_label": format_race_date(start),
        "end_label": format_race_date(end),
        "today": today.isoformat(),
        "today_x": _x_frac(today, start, end),
        "prev_a_race_id": str(prev_a.id) if prev_a is not None else None,
        "target_a_race_id": str(target.id),
        "nodes": nodes,
    }

    rows = [_row(session, user_id, r, today, runs) for r in block]
    rows = sorted(rows, key=lambda row: row["race_date"])

    from backend.services.projection_view import _chart_window_start

    try:
        chart_start = _chart_window_start(session, user_id, target, today)
    except Exception:
        chart_start = today - timedelta(days=84)
    season_start = min(chart_start, target.race_date - timedelta(days=183))
    earlier_races = [
        r for r in all_races
        if season_start <= r.race_date < start
        and (r.status == "done" or r.actual_time_seconds is not None)
    ]
    earlier_races.sort(key=lambda r: r.race_date, reverse=True)
    earlier_rows = [_row(session, user_id, r, today, runs) for r in earlier_races]

    return {
        "available": True,
        "today": today.isoformat(),
        "hero": hero,
        "timeline": timeline,
        "rows": rows,
        "earlier_rows": earlier_rows,
    }