"""GET /api/mobile/bundle — one payload the phone caches for up to 14 days (PWA P0-3)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import (
    LoadPlanWeekSnapshot,
    PlanExercise,
    PlannedSession,
    Race,
    SessionVersion,
    UserPreferences,
    WeightEntry,
    Workout,
    WorkoutExercise,
)
from backend.services.axis_strength import fetch_trend_mass, get_anchor_lifts, get_strength
from backend.services.plan_match_payload import planned_tss_estimate
from backend.services.session_exercises import enrich_generated_exercises
from backend.services.session_tss import session_tss
from backend.services.sync_provider_status import build_providers
from backend.services.weekly_rollup import bangkok_week_start, weekly_rollup
from backend.services.weight_ewma import compute_ewma
from backend.utils.time import today_bangkok

LIBRARY_CAP = 180


def _iso(d) -> Optional[str]:
    if d is None:
        return None
    if hasattr(d, "isoformat"):
        return d.isoformat()
    return str(d)


def _json_ready(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    return value


def bundle_etag(payload: dict[str, Any]) -> str:
    stable = {k: v for k, v in payload.items() if k != "server_time"}
    blob = json.dumps(stable, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _exercises_from_structure(structure) -> list[dict[str, Any]]:
    if not isinstance(structure, dict):
        return []
    raw = structure.get("exercises") or []
    if not isinstance(raw, list):
        return []
    out = []
    for ex in raw:
        if isinstance(ex, dict):
            out.append(dict(ex))
    if out and not any(e.get("section_format") for e in out):
        out = enrich_generated_exercises(out)
    return out


def _latest_version_id(session: Session, workout_id) -> Optional[str]:
    if workout_id is None:
        return None
    row = (
        session.query(SessionVersion.id)
        .filter(SessionVersion.workout_id == workout_id)
        .order_by(SessionVersion.saved_at.desc())
        .first()
    )
    return str(row[0]) if row else None


def _last_numbers(session: Session, user_id, names: set[str]) -> dict[str, Any]:
    if not names:
        return {}
    lowered = {n.strip().lower() for n in names if n}
    rows = (
        session.query(Workout.workout_date, WorkoutExercise)
        .join(WorkoutExercise, WorkoutExercise.workout_id == Workout.id)
        .filter(Workout.user_id == user_id)
        .order_by(Workout.workout_date.desc())
        .limit(800)
        .all()
    )
    out: dict[str, Any] = {}
    for d, ex in rows:
        key = (ex.name or "").strip().lower()
        if key not in lowered or key in out:
            continue
        sets = None
        if ex.sets_json:
            try:
                sets = json.loads(ex.sets_json) if isinstance(ex.sets_json, str) else ex.sets_json
            except (TypeError, ValueError):
                sets = None
        out[ex.name] = {
            "date": _iso(d),
            "kg": float(ex.weight_kg) if ex.weight_kg is not None else None,
            "reps": ex.reps,
            "sets": sets,
            "rpe": ex.rpe,
        }
        if len(out) >= len(lowered):
            break
    return out


def _library(session: Session) -> list[dict[str, Any]]:
    rows = (
        session.query(PlanExercise)
        .filter(PlanExercise.active.is_(True))
        .order_by(PlanExercise.name.asc())
        .limit(LIBRARY_CAP)
        .all()
    )
    out = []
    for r in rows:
        muscles = r.body_parts if isinstance(r.body_parts, list) else []
        if muscles and isinstance(muscles[0], dict):
            muscles = [m.get("part") or m.get("name") for m in muscles if isinstance(m, dict)]
        out.append(
            {
                "id": str(r.id),
                "name": r.name,
                "muscles": muscles,
                "equipment": r.groups if isinstance(r.groups, list) else [],
                "aliases": [],
            }
        )
    return out


def _swap_history(session: Session, user_id) -> dict[str, Any]:
    from backend.models import SessionTemplateOverride

    rows = (
        session.query(SessionTemplateOverride)
        .filter(SessionTemplateOverride.user_id == user_id)
        .all()
    )
    out: dict[str, Any] = {}
    for r in rows:
        ov = r.override or {}
        name = ov.get("replacement")
        if not name:
            continue
        out[r.exercise_key] = {"usual": name, "replacement": name, "count": 1}
    return out


def _recent_runs(session: Session, user_id, today: date) -> list[dict[str, Any]]:
    rows = (
        session.query(Workout)
        .filter(Workout.user_id == user_id, Workout.workout_type == "run", Workout.workout_date <= today)
        .order_by(Workout.workout_date.desc())
        .limit(3)
        .all()
    )
    out = []
    for w in rows:
        tss = session_tss(w, session=session)
        dur = w.duration_seconds
        dist = float(w.distance_km) if w.distance_km is not None else None
        pace = None
        if dur and dist and dist > 0:
            pace = int(round(dur / dist))
        out.append(
            {
                "id": str(w.id),
                "name": w.name,
                "date": _iso(w.workout_date),
                "duration_seconds": dur,
                "distance_km": dist,
                "pace_sec_per_km": pace,
                "tss": tss.get("tss"),
            }
        )
    return out


def build_zone2_week(
    today: date,
    logged: dict,
    planned: dict,
    target: int | None,
    hr_ceiling: int | None,
) -> dict[str, Any]:
    """Bangkok-week Zone 2 card. Planned minutes never count in the total."""
    start = bangkok_week_start(today)
    labels = "MTWTFSS"
    days = []
    total = 0
    for i in range(7):
        d = start + timedelta(days=i)
        logged_min = int(logged.get(d) or 0)
        planned_min = int(planned.get(d) or 0) if d > today else 0
        if d <= today:
            total += logged_min
        days.append(
            {
                "date": _iso(d),
                "label": labels[i],
                "logged_min": logged_min,
                "planned_min": planned_min,
            }
        )
    return {
        "days": days,
        "total": total,
        "target": int(target) if target is not None else 150,
        "hr_ceiling": hr_ceiling,
    }


def _planned_easy_minutes(p: PlannedSession) -> int:
    st = (p.session_type or "").lower()
    if st not in ("run", "running"):
        return 0
    structure = p.structure if isinstance(p.structure, dict) else {}
    hints = structure.get("structure_hints") if isinstance(structure.get("structure_hints"), dict) else {}
    subtype = str(structure.get("subtype") or hints.get("subtype") or "").lower()
    name = (p.name or "").lower()
    easy = subtype in ("easy", "easy_run", "z2") or "easy" in name or "zone 2" in name or "z2" in name
    if not easy:
        return 0
    dur = structure.get("duration_minutes") or structure.get("duration_min") or 0
    try:
        return max(0, int(dur))
    except (TypeError, ValueError):
        return 0


def _zone2_week(session: Session, user_id, today: date) -> dict[str, Any]:
    start = bangkok_week_start(today)
    end = start + timedelta(days=6)
    workouts = (
        session.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= start,
            Workout.workout_date <= today,
        )
        .all()
    )
    logged: dict[date, int] = {}
    for w in workouts:
        mins = int(w.easy_minutes or 0)
        if mins:
            logged[w.workout_date] = logged.get(w.workout_date, 0) + mins
    planned_rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date > today,
            PlannedSession.planned_date <= end,
        )
        .all()
    )
    planned: dict[date, int] = {}
    for p in planned_rows:
        mins = _planned_easy_minutes(p)
        if mins:
            planned[p.planned_date] = planned.get(p.planned_date, 0) + mins
    prefs = session.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    target = prefs.weekly_zone2_target_min if prefs is not None else None
    hr = prefs.zone2_hr_max if prefs is not None else None
    if target is None:
        target = 150
    return build_zone2_week(today, logged, planned, target, hr)


def _body(session: Session, user_id, today: date) -> dict[str, Any]:
    trend, _days = fetch_trend_mass(session, user_id, today)
    last = (
        session.query(WeightEntry)
        .filter(WeightEntry.user_id == user_id, WeightEntry.entry_date <= today)
        .order_by(WeightEntry.entry_date.desc(), WeightEntry.created_at.desc())
        .first()
    )
    lookback = today - timedelta(days=56)
    entries = (
        session.query(WeightEntry)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date >= lookback,
            WeightEntry.entry_date <= today,
        )
        .order_by(WeightEntry.entry_date.asc())
        .all()
    )
    series = [{"date": r.entry_date, "weight_kg": float(r.weight_kg)} for r in entries if r.weight_kg is not None]
    smoothed = compute_ewma(series) if series else []
    change_28d = None
    if smoothed and len(smoothed) >= 2:
        older = None
        cutoff = today - timedelta(days=28)
        for i, row in enumerate(series):
            if row["date"] <= cutoff:
                older = smoothed[i]
        if older is not None:
            change_28d = round(smoothed[-1] - older, 2)
    return {
        "trend_kg": round(float(trend), 2) if trend is not None else None,
        "change_28d_kg": change_28d,
        "last_weigh_in": (
            {"date": _iso(last.entry_date), "kg": float(last.weight_kg)} if last is not None else None
        ),
        "weigh_ins": [
            {"date": _iso(r.entry_date), "kg": float(r.weight_kg), "trend_kg": smoothed[i] if i < len(smoothed) else None}
            for i, r in enumerate(entries)
            if r.weight_kg is not None
        ],
        "zone2_week": _zone2_week(session, user_id, today),
    }


def _today_meta(session: Session, user_id, today: date) -> dict[str, Any]:
    snap = (
        session.query(LoadPlanWeekSnapshot)
        .filter(LoadPlanWeekSnapshot.user_id == user_id, LoadPlanWeekSnapshot.week_start <= today)
        .order_by(LoadPlanWeekSnapshot.week_start.desc())
        .first()
    )
    race = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.priority == "A", Race.race_date >= today)
        .order_by(Race.race_date.asc())
        .first()
    )
    providers = build_providers(session, user_id)
    return {
        "date": _iso(today),
        "plan_phase": snap.phase if snap else None,
        "block_name": race.name if race else None,
        "sync": {
            "strava": (providers.get("strava") or {}).get("state"),
            "stryd": (providers.get("stryd") or {}).get("state"),
        },
    }


def build_bundle(
    session: Session,
    user_id,
    *,
    days: int = 7,
    today: Optional[date] = None,
) -> dict[str, Any]:
    today = today or today_bangkok()
    days = max(1, min(14, int(days)))
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    end = today + timedelta(days=days - 1)
    planned = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == uid,
            PlannedSession.planned_date >= today,
            PlannedSession.planned_date <= end,
        )
        .order_by(PlannedSession.planned_date.asc())
        .all()
    )
    sessions_out = []
    names: set[str] = set()
    for p in planned:
        exercises = _exercises_from_structure(p.structure)
        for ex in exercises:
            if ex.get("name"):
                names.add(ex["name"])
        est = planned_tss_estimate(session, p)
        structure = p.structure if isinstance(p.structure, dict) else {}
        duration = structure.get("duration_minutes") or structure.get("duration_min")
        sessions_out.append(
            {
                "id": str(p.id),
                "date": _iso(p.planned_date),
                "name": p.name,
                "session_type": p.session_type,
                "status": p.status,
                "plan_source": p.plan_source,
                "template_key": structure.get("pattern_name") or p.name,
                "pattern_name": structure.get("pattern_name"),
                "exercises": exercises,
                "estimated_tss": est,
                "duration_minutes": duration,
                "version_id": _latest_version_id(session, p.matched_workout_id),
                "matched_workout_id": str(p.matched_workout_id) if p.matched_workout_id else None,
            }
        )

    from backend.services.data_version import get_data_version

    payload = {
        "today": _today_meta(session, uid, today),
        "sessions": sessions_out,
        "last_numbers": _last_numbers(session, uid, names),
        "anchors": get_anchor_lifts(session, uid),
        "library": _library(session),
        "swap_history": _swap_history(session, uid),
        "recent_runs": _recent_runs(session, uid, today),
        "body": _body(session, uid, today),
        "server_time": datetime.now(timezone.utc).isoformat(),
        "bundle_version": get_data_version(session, uid),
        "days": days,
    }
    return _json_ready(payload)


def numbers_for_parity(session: Session, user_id, today: date) -> dict[str, Any]:
    """Subset of bundle numbers compared against existing readers in tests."""
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    trend, _ = fetch_trend_mass(session, uid, today)
    from backend.services.weekly_rollup import normalize_week_start

    roll = weekly_rollup(uid, normalize_week_start(today), session=session, today=today)
    strength = get_strength(session, uid, today)
    return {
        "trend_kg": round(float(trend), 2) if trend is not None else None,
        "week_tss": roll.get("tss_total"),
        "strength_score": (strength or {}).get("score"),
    }
