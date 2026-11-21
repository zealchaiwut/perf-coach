"""Planned-session editor context (revamp P3-8)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlanExercise, PlannedSession
from backend.services.plan_pattern_fill import _load_exercise_pool
from backend.services.plan_rules_engine import evaluate, summarize
from backend.services.revamp_load_plan import revamp_week_load
from backend.services.strength_tss import from_effort_time
from backend.services.weekly_rollup import normalize_week_start, week_target_and_phase
from backend.utils.time import today_bangkok

RACE_WEEK_SAFE_GROUPS = frozenset(
    {"warmup", "mobility", "drills", "cooldown", "bodyweight", "isometric", "accessories"}
)


def _session_tss_estimate(session_type: str, structure: Optional[dict]) -> float:
    structure = structure if isinstance(structure, dict) else {}
    if structure.get("target_tss") is not None:
        try:
            return float(structure["target_tss"])
        except (TypeError, ValueError):
            pass
    dur = structure.get("duration_minutes") or structure.get("duration_min")
    eff = structure.get("effort") or structure.get("target_effort") or 5
    try:
        dur_f = float(dur) if dur is not None else 30.0
        eff_i = int(eff)
    except (TypeError, ValueError):
        dur_f, eff_i = 30.0, 5
    if session_type in ("strength", "plyo", "mobility", "drills"):
        return float(from_effort_time(duration_min=dur_f, effort=eff_i).get("tss") or 0)
    return float(structure.get("estimated_tss") or 0)


def _day_planned_tss(session: Session, user_id: uuid.UUID, planned_date: date, *, exclude_id: Optional[uuid.UUID] = None) -> float:
    from backend.services.training_load import estimate_historical_pace_and_tss, estimate_planned_session_metrics

    baseline = estimate_historical_pace_and_tss(session, user_id)
    rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date == planned_date,
            PlannedSession.status.notin_(("missed", "skipped")),
        )
        .all()
    )
    total = 0.0
    for p in rows:
        if exclude_id and p.id == exclude_id:
            continue
        est = estimate_planned_session_metrics(baseline, p.session_type, p.structure)
        total += float(est.get("estimated_tss") or 0)
    return round(total, 1)


def _library_delta_tss(ex: dict) -> float:
    sets = int(ex.get("default_sets") or 3)
    weight = float(ex.get("tss_weight") or 1.0)
    return round(sets * weight * 2.5, 1)


def library_for_planned_editor(
    session: Session,
    user_id: uuid.UUID,
    *,
    planned_date: date,
    session_type: str,
    draft_structure: Optional[dict],
    week_start: Optional[date] = None,
    session_id: Optional[uuid.UUID] = None,
) -> list[dict[str, Any]]:
    today = today_bangkok()
    ws = normalize_week_start(week_start or planned_date)
    meta = week_target_and_phase(user_id, ws, session=session, today=today) or {}
    race_week = (meta.get("phase") or "") == "race_week"
    pool = _load_exercise_pool(session)
    out: list[dict[str, Any]] = []
    for ex in pool:
        groups = ex.get("groups") or []
        if isinstance(groups, str):
            groups = [groups]
        safe = any(g in RACE_WEEK_SAFE_GROUPS for g in groups)
        delta = _library_delta_tss(ex)
        structure = dict(draft_structure or {})
        exercises = list(structure.get("exercises") or [])
        exercises.append(
            {
                "name": ex.get("name"),
                "sets": ex.get("default_sets") or 3,
                "reps": ex.get("default_reps") or "10",
            }
        )
        structure["exercises"] = exercises
        change = {
            "action": "create" if session_id is None else "edit",
            "session_id": str(session_id) if session_id else None,
            "planned_date": planned_date.isoformat(),
            "session_type": session_type,
            "structure": structure,
            "source": "support",
            "estimated_tss": _session_tss_estimate(session_type, structure) + delta,
        }
        hits = evaluate(user_id, change, session)
        blocked = any(h.get("level") == "block" for h in hits)
        block_reason = next((h.get("message") for h in hits if h.get("level") == "block"), None)
        out.append(
            {
                "name": ex.get("name"),
                "groups": groups,
                "race_week_safe": safe,
                "week_delta_tss": delta,
                "blocked": blocked,
                "block_reason": block_reason,
            }
        )
    out.sort(key=lambda r: (0 if race_week and r["race_week_safe"] else 1, r["name"] or ""))
    return out


def planned_editor_context(
    session: Session,
    user_id: uuid.UUID,
    *,
    planned_date: date,
    session_id: Optional[uuid.UUID] = None,
    week_start: Optional[date] = None,
    draft: Optional[dict] = None,
) -> dict[str, Any]:
    today = today_bangkok()
    ws = normalize_week_start(week_start or planned_date)
    row = None
    if session_id:
        row = (
            session.query(PlannedSession)
            .filter(PlannedSession.id == session_id, PlannedSession.user_id == user_id)
            .one_or_none()
        )
    session_type = (draft or {}).get("session_type") or (row.session_type if row else "mobility")
    structure = (draft or {}).get("structure") or (row.structure if row else {}) or {}
    name = (draft or {}).get("name") or (row.name if row else "New session")
    source = (row.plan_source if row else "support") or "support"
    sess_tss = _session_tss_estimate(session_type, structure)
    day_tss = _day_planned_tss(session, user_id, planned_date, exclude_id=session_id)
    meta = week_target_and_phase(user_id, ws, session=session, today=today) or {}
    wl = revamp_week_load(user_id, ws, session=session, today=today) or {}
    week_planned = float(wl.get("planned_tss") or wl.get("planned_tss_training") or 0)
    week_target = wl.get("target_tss") or meta.get("target_tss")
    headroom = None
    if week_target is not None:
        headroom = round(float(week_target) - week_planned, 1)

    change = {
        "action": "create" if row is None else "edit",
        "session_id": str(session_id) if session_id else None,
        "planned_date": planned_date.isoformat(),
        "session_type": session_type,
        "structure": structure,
        "source": source,
        "estimated_tss": sess_tss,
    }
    rules = evaluate(user_id, change, session)
    library = library_for_planned_editor(
        session,
        user_id,
        planned_date=planned_date,
        session_type=session_type,
        draft_structure=structure,
        week_start=ws,
        session_id=session_id,
    )
    return {
        "mode": "planned",
        "planned_date": planned_date.isoformat(),
        "week_start": ws.isoformat(),
        "session_id": str(session_id) if session_id else None,
        "name": name,
        "session_type": session_type,
        "plan_source": source,
        "structure": structure,
        "tiles": {
            "session_tss": sess_tss,
            "day_tss": round(day_tss + sess_tss, 1),
            "week_planned": week_planned,
            "week_target": week_target,
            "headroom": headroom,
        },
        "rules": {"level": summarize(rules), "results": rules},
        "library": library,
        "race_week": (meta.get("phase") or "") == "race_week",
    }