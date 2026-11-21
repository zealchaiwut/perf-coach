"""A-race hero and the after-the-race card (revamp P4-8).

Everything comes from existing readers:

- estimate and band: ``race_finish_estimate.estimate_race_finish`` (projection)
- race-specific End/Spd: ``score_reader.get_race_scores`` (P0-5)
- paces: ``models.compute_goal_pace`` (the one goal-pace derivation)
- goal / date / distance: ``races`` fields

The only arithmetic done here is subtraction: the gap to goal (goal minus the
slow end and goal minus the estimate), the countdown, and the range endpoints
``estimate -/+ band`` (printed exactly).
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from backend.models import compute_goal_pace
from backend.services.perf_a_race import next_a_race
from backend.services.race_finish_estimate import estimate_race_finish
from backend.services.score_reader import get_race_scores

RACE_SPECIFIC_EXPLANATION = (
    "These are the scores this course and distance need, not your overall ones."
)

AFTER_RACE_COPY = (
    "Once you record a race result, it replaces your current anchors: Endurance, Speed "
    "and the projection re-anchor on that effort. Record it on the race list to recalibrate."
)

READING_SLOW_END_BEATS = "even the slow end beats goal"
READING_ESTIMATE_BEATS = "estimate beats goal; the slow end misses it"
READING_BEHIND = "estimate is behind goal"
READING_NO_GOAL = "set a goal to see the gap"
READING_NO_ESTIMATE = "no estimate yet"


def gap_block(goal_sec: Optional[int], est_sec: Optional[int], band_sec: Optional[int]) -> dict[str, Any]:
    """Gap to goal — subtraction only. Positive = ahead of goal (goal minus value)."""
    slow_end = (est_sec + band_sec) if est_sec is not None and band_sec is not None else est_sec
    out: dict[str, Any] = {
        "goal_minus_estimate_sec": None,
        "goal_minus_slow_end_sec": None,
        "reading": READING_NO_GOAL if goal_sec is None else READING_NO_ESTIMATE,
    }
    if goal_sec is None or est_sec is None:
        return out
    out["goal_minus_estimate_sec"] = goal_sec - est_sec
    out["goal_minus_slow_end_sec"] = goal_sec - slow_end
    if goal_sec - slow_end >= 0:
        out["reading"] = READING_SLOW_END_BEATS
    elif goal_sec - est_sec >= 0:
        out["reading"] = READING_ESTIMATE_BEATS
    else:
        out["reading"] = READING_BEHIND
    return out


def _pace(sec: Optional[int], km: Optional[float]) -> Optional[int]:
    if sec is None or km is None:
        return None
    pace, _ = compute_goal_pace(sec, km)
    return pace


def build_estimate_block(est: dict[str, Any], distance_km: Optional[float]) -> dict[str, Any]:
    if est.get("unavailable") or est.get("est_sec") is None:
        return {"available": False, "reason": est.get("reason") or "unavailable"}
    est_sec = int(est["est_sec"])
    band = est.get("band_sec")
    band_sec = int(band) if band is not None else None
    return {
        "available": True,
        "est_sec": est_sec,
        "pace_seconds_per_km": _pace(est_sec, distance_km),
        "band_sec": band_sec,
        "uncertainty_min": est.get("uncertainty_min"),
        "range_low_sec": (est_sec - band_sec) if band_sec is not None else None,
        "range_high_sec": (est_sec + band_sec) if band_sec is not None else None,
        "source": est.get("source"),
    }


def build_race_block(race, today: date) -> dict[str, Any]:
    return {
        "id": str(race.id),
        "name": race.name,
        "race_date": race.race_date.isoformat(),
        "distance_km": float(race.distance_km) if race.distance_km is not None else None,
        "priority": race.priority,
        "race_type": race.race_type,
        "days_to_race": (race.race_date - today).days,
    }


def build_race_specific(scores: dict[str, Any]) -> dict[str, Any]:
    rs = (scores or {}).get("race_specific") or {}
    return {
        "endurance": (rs.get("endurance") or {}).get("score"),
        "speed": (rs.get("speed") or {}).get("score"),
        "explanation": RACE_SPECIFIC_EXPLANATION,
    }


def next_checkpoint(session, user_id: uuid.UUID, race, today: date):
    """Earliest upcoming checkpoint of the A race (or of any race when none is set)."""
    from backend.models import RaceCheckpoint as C

    q = session.query(C).filter(C.user_id == user_id, C.target_date >= today)
    if race is not None:
        q = q.filter(C.race_id == race.id)
    return q.order_by(C.target_date.asc()).first()


def build_after_race(session, user_id: uuid.UUID, race, today: date) -> dict[str, Any]:
    cp = next_checkpoint(session, user_id, race, today)
    block: dict[str, Any] = {"copy": AFTER_RACE_COPY, "next_checkpoint": None}
    if cp is None:
        return block
    distance = float(cp.target_distance_km) if cp.target_distance_km is not None else None
    estimate: dict[str, Any] = {"available": False, "reason": "checkpoint has no distance"}
    if distance is not None:
        from types import SimpleNamespace

        pseudo = SimpleNamespace(id=None, distance_km=distance, race_date=cp.target_date)
        estimate = build_estimate_block(
            estimate_race_finish(user_id, pseudo, today=today, db=session), distance
        )
    block["next_checkpoint"] = {
        "label": cp.label,
        "target_date": cp.target_date.isoformat(),
        "distance_km": distance,
        "estimate": estimate,
    }
    return block


def build_hero(session, user_id: uuid.UUID, today: date) -> dict[str, Any]:
    race = next_a_race(session, user_id, today)
    payload: dict[str, Any] = {
        "race": None,
        "goal": None,
        "estimate": None,
        "gap": None,
        "race_specific": None,
        "after_race": build_after_race(session, user_id, race, today),
    }
    if race is None:
        return payload
    distance = float(race.distance_km) if race.distance_km is not None else None
    goal_sec = int(race.goal_time_seconds) if race.goal_time_seconds is not None else None
    goal_pace = race.goal_pace_seconds_per_km
    if goal_pace is None:
        goal_pace = _pace(goal_sec, distance)
    estimate = build_estimate_block(estimate_race_finish(user_id, race, today=today, db=session), distance)
    payload.update(
        race=build_race_block(race, today),
        goal={"time_sec": goal_sec, "pace_seconds_per_km": goal_pace},
        estimate=estimate,
        gap=gap_block(goal_sec, estimate.get("est_sec"), estimate.get("band_sec")),
        race_specific=build_race_specific(get_race_scores(session, user_id, race, as_of=today)),
    )
    return payload
