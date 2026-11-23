"""Race-day planned TSS for weekly rollups (revamp P3-2)."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import Race, Workout
from backend.services.race_finish_estimate import estimate_race_finish
from backend.services.session_tss import session_tss

# Standard-distance anchors for IF interpolation (km → IF).
_IF_ANCHORS: list[tuple[float, float]] = [
    (5.0, 0.95),
    (10.0, 0.92),
    (21.1, 0.88),
    (42.2, 0.84),
]


def _round_nearest_5(value: float) -> int:
    return int(round(value / 5.0) * 5)


def intensity_factor_for_distance(distance_km: float, override: Optional[float] = None) -> float:
    if override is not None and float(override) > 0:
        return float(override)
    d = float(distance_km)
    if d <= _IF_ANCHORS[0][0]:
        return _IF_ANCHORS[0][1]
    if d >= _IF_ANCHORS[-1][0]:
        return _IF_ANCHORS[-1][1]
    for i in range(len(_IF_ANCHORS) - 1):
        lo_km, lo_if = _IF_ANCHORS[i]
        hi_km, hi_if = _IF_ANCHORS[i + 1]
        if lo_km <= d <= hi_km:
            frac = (d - lo_km) / (hi_km - lo_km)
            return lo_if + frac * (hi_if - lo_if)
    return 0.84


def _duration_minutes(session: Session, race: Race) -> Optional[float]:
    if race.status == "done" and race.actual_time_seconds:
        return race.actual_time_seconds / 60.0
    if race.goal_time_seconds:
        return race.goal_time_seconds / 60.0
    est = estimate_race_finish(race.user_id, race, db=session)
    if est and not est.get("unavailable") and est.get("est_sec"):
        return est["est_sec"] / 60.0
    return None


def compute_race_day_tss(
    session: Session,
    race: Race,
) -> dict[str, Any]:
    """Estimate race TSS from duration × IF² × 100, rounded to nearest 5."""
    if race.distance_km is None or float(race.distance_km) <= 0:
        return {"tss": None, "reason": "distance required"}
    override = getattr(race, "tss_if_override", None)
    if override is not None:
        override = float(override)
    if_val = intensity_factor_for_distance(float(race.distance_km), override)
    dur_min = _duration_minutes(session, race)
    if dur_min is None or dur_min <= 0:
        return {"tss": None, "reason": "duration unknown", "if": if_val}
    raw = (dur_min / 60.0) * (if_val**2) * 100.0
    tss = _round_nearest_5(raw)
    return {
        "tss": tss,
        "tss_raw": round(raw, 1),
        "duration_minutes": round(dur_min, 1),
        "if": round(if_val, 3),
        "source": "estimate",
    }


def logged_race_tss(session: Session, user_id, race: Race, *, workouts=None) -> Optional[float]:
    """Actual session TSS for a completed race day."""
    if workouts is not None:
        rows = [w for w in workouts if getattr(w, "workout_date", None) == race.race_date]
    else:
        rows = (
            session.query(Workout)
            .filter(
                Workout.user_id == user_id,
                Workout.workout_date == race.race_date,
            )
            .all()
        )
    best = None
    for w in rows:
        wt = (w.workout_type or "").lower()
        if "race" in wt or race.name.lower() in (w.name or "").lower():
            val = session_tss(w, session=session).get("tss")
            if val is not None:
                best = float(val)
                break
    if best is None and rows:
        val = session_tss(rows[0], session=session).get("tss")
        if val is not None:
            best = float(val)
    return best


def races_in_week(
    session: Session,
    user_id,
    week_start,
    week_end,
) -> list[Race]:
    return (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.race_date >= week_start,
            Race.race_date <= week_end,
            Race.status.in_(("planned", "done")),
        )
        .order_by(Race.race_date)
        .all()
    )


def race_week_payload(
    session: Session,
    user_id,
    week_start,
    week_end,
    *,
    races: Optional[list[Race]] = None,
    workouts: Optional[list[Workout]] = None,
) -> list[dict[str, Any]]:
    """Race items kept separate from training planned TSS.

    Prefetch ``races`` / ``workouts`` on the range path so each table is
    queried once; compute_race_day_tss → estimate_race_finish still hits
    the DB when duration is unknown (unavoidable per-race, rare).
    """
    if races is None:
        race_rows = races_in_week(session, user_id, week_start, week_end)
    else:
        race_rows = [
            r
            for r in races
            if week_start <= r.race_date <= week_end and r.status in ("planned", "done")
        ]
        race_rows.sort(key=lambda r: r.race_date)
    out: list[dict[str, Any]] = []
    for race in race_rows:
        if race.status == "done":
            actual = logged_race_tss(session, user_id, race, workouts=workouts)
            if actual is None:
                est = compute_race_day_tss(session, race)
                tss = est.get("tss")
                source = "estimate"
            else:
                tss = int(round(actual))
                source = "logged"
            out.append(
                {
                    "race_id": str(race.id),
                    "name": race.name,
                    "race_date": str(race.race_date),
                    "priority": race.priority,
                    "tss": tss,
                    "tss_source": source,
                    "kind": "race",
                }
            )
        else:
            est = compute_race_day_tss(session, race)
            out.append(
                {
                    "race_id": str(race.id),
                    "name": race.name,
                    "race_date": str(race.race_date),
                    "priority": race.priority,
                    "tss": est.get("tss"),
                    "tss_source": "estimate",
                    "if": est.get("if"),
                    "duration_minutes": est.get("duration_minutes"),
                    "kind": "race",
                }
            )
    return out