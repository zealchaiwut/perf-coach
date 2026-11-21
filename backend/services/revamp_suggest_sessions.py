"""Deterministic week fill to training target (revamp P3-10)."""
from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlannedSession, WorkoutTemplate
from backend.services.plan_match_payload import planned_tss_estimate
from backend.services.plan_rules_engine import (
    PlanSessionView,
    effective_plan_source_attr,
    evaluate_plan_change,
    summarize,
)
from backend.services.training_load import estimate_historical_pace_and_tss, estimate_planned_session_metrics
from backend.utils.time import today_bangkok as _today_bangkok
from backend.services.weekly_rollup import normalize_week_start, weekly_rollup

GAP_MIN_SUGGEST_TSS = 5.0
REVAMP_SUGGEST_DAY_TSS_CAP = 48.0

# Built-in defaults until P4/P5 sources land.
BUILTIN_CANDIDATES: list[dict[str, Any]] = [
    {
        "candidate_id": "builtin:mobility",
        "name": "Mobility block",
        "session_type": "mobility",
        "structure": {"duration_minutes": 20, "target_tss": 12, "suggested": True},
        "estimated_tss": 12.0,
        "race_week_safe": True,
    },
    {
        "candidate_id": "builtin:drills",
        "name": "Drills",
        "session_type": "mobility",
        "structure": {"duration_minutes": 15, "target_tss": 10, "suggested": True},
        "estimated_tss": 10.0,
        "race_week_safe": True,
    },
]

_RACE_WEEK_SAFE_GROUPS = frozenset({"warmup", "cooldown", "bodyweight", "mobility", "isometric"})


@dataclass
class _Ctx:
    user_id: uuid.UUID
    week_start: date
    today: date
    target_tss: float
    week_gap: float
    phase: Optional[str]
    rest_days: list[int]
    max_consecutive: int
    acwr_ceiling: float
    races: list[dict[str, Any]]
    exercise_groups: dict[str, set[str]]
    sessions: list[PlanSessionView]


def _session_views(session: Session, user_id: uuid.UUID, ws: date, we: date) -> list[PlanSessionView]:
    baseline = estimate_historical_pace_and_tss(user_id, session)
    rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= ws,
            PlannedSession.planned_date <= we,
            PlannedSession.status.notin_(("skipped",)),
        )
        .all()
    )
    out: list[PlanSessionView] = []
    for p in rows:
        est = estimate_planned_session_metrics(baseline, p.session_type, p.structure)
        out.append(
            PlanSessionView(
                id=p.id,
                planned_date=p.planned_date,
                session_type=p.session_type,
                structure=p.structure if isinstance(p.structure, dict) else None,
                source=effective_plan_source_attr(p),
                estimated_tss=float(est.get("estimated_tss") or 0),
            )
        )
    return out


def _day_planned_tss(views: list[PlanSessionView], d: date) -> float:
    return sum(s.estimated_tss for s in views if s.planned_date == d)


def _week_planned_tss(views: list[PlanSessionView], ws: date) -> float:
    we = ws + timedelta(days=6)
    return sum(s.estimated_tss for s in views if ws <= s.planned_date <= we)


def _load_candidates(session: Session, user_id: uuid.UUID, *, race_week: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # P4-7 performance queue — not wired yet.
    templates = (
        session.query(WorkoutTemplate)
        .filter(WorkoutTemplate.user_id == user_id)
        .order_by(WorkoutTemplate.name)
        .all()
    )
    baseline = estimate_historical_pace_and_tss(user_id, session)
    for t in templates:
        st = "strength"
        ex = t.exercises if isinstance(t.exercises, list) else []
        if ex and any("plyo" in str(e.get("name", "")).lower() for e in ex if isinstance(e, dict)):
            st = "plyo"
        structure = {"exercises": ex, "suggested": True}
        est = estimate_planned_session_metrics(baseline, st, structure).get("estimated_tss") or 20
        safe = st in ("mobility", "stretch") or not ex
        out.append(
            {
                "candidate_id": f"template:{t.id}",
                "name": t.name,
                "session_type": st,
                "structure": structure,
                "estimated_tss": float(est),
                "race_week_safe": safe,
            }
        )
    builtins = deepcopy(BUILTIN_CANDIDATES)
    if race_week:
        builtins.sort(key=lambda c: (0 if c.get("race_week_safe") else 1))
        out.sort(key=lambda c: (0 if c.get("race_week_safe") else 1))
    out.extend(builtins)
    return out


def _build_ctx(session: Session, user_id: uuid.UUID, week_start: date, today: date) -> Optional[_Ctx]:
    ws = normalize_week_start(week_start)
    we = ws + timedelta(days=6)
    rollup = weekly_rollup(user_id, ws, session=session, today=today)
    target = rollup.get("target_tss")
    if target is None:
        return None
    planned = float(rollup.get("planned_tss") or 0)
    gap = float(target) - planned
    if gap <= GAP_MIN_SUGGEST_TSS:
        return None

    from backend.services.revamp_load_plan import chronic_weekly_tss
    from backend.services.load_plan import ACWR_CEILING_MULT
    from backend.services.coach_export import _max_consecutive_training_days
    from backend.services.plan_rules_engine import _load_exercise_groups
    from backend.services.training_prefs import active_dict
    from backend.models import Race

    prefs = active_dict(session, user_id)
    rest_days = list((prefs.get("payload") or {}).get("rest_days") or [])
    max_cap = _max_consecutive_training_days(rest_days) or 3
    chronic = chronic_weekly_tss(session, user_id, today)
    ceiling = round(ACWR_CEILING_MULT * chronic, 1)
    races = [
        {"name": r.name, "race_date": r.race_date.isoformat(), "priority": r.priority}
        for r in session.query(Race)
        .filter(Race.user_id == user_id, Race.status == "planned", Race.race_date >= today - timedelta(days=1))
        .order_by(Race.race_date)
        .all()
    ]
    views = _session_views(session, user_id, ws, we)
    return _Ctx(
        user_id=user_id,
        week_start=ws,
        today=today,
        target_tss=float(target),
        week_gap=gap,
        phase=rollup.get("phase"),
        rest_days=rest_days,
        max_consecutive=int(max_cap),
        acwr_ceiling=ceiling,
        races=races,
        exercise_groups=_load_exercise_groups(session),
        sessions=views,
    )


def _allowed_days(ctx: _Ctx) -> list[date]:
    ws = ctx.week_start
    days = [ws + timedelta(days=i) for i in range(7)]
    return [d for d in days if d >= ctx.today]


def _pick_day(ctx: _Ctx, views: list[PlanSessionView], cand: dict[str, Any]) -> Optional[date]:
    best: Optional[tuple[float, date]] = None
    for d in _allowed_days(ctx):
        day_tss = _day_planned_tss(views, d)
        headroom_day = REVAMP_SUGGEST_DAY_TSS_CAP - day_tss
        if headroom_day < float(cand["estimated_tss"]):
            continue
        week_after = _week_planned_tss(views, ctx.week_start) + float(cand["estimated_tss"])
        if week_after > ctx.target_tss:
            continue
        change = {
            "action": "create",
            "planned_date": d.isoformat(),
            "session_type": cand["session_type"],
            "structure": cand["structure"],
            "source": "support",
            "estimated_tss": float(cand["estimated_tss"]),
        }
        hits = evaluate_plan_change(
            sessions=views,
            change=change,
            preferred_rest_days=ctx.rest_days,
            max_consecutive_cap=ctx.max_consecutive,
            week_target_tss=ctx.target_tss,
            acwr_ceiling=ctx.acwr_ceiling,
            races=ctx.races,
            phase=ctx.phase,
            exercise_groups=ctx.exercise_groups,
        )
        if summarize([h.as_dict() for h in hits]) == "block":
            continue
        remaining = ctx.target_tss - _week_planned_tss(views, ctx.week_start)
        score = min(headroom_day, remaining)
        if best is None or score > best[0]:
            best = (score, d)
    return best[1] if best else None


def suggest_week_fill(
    session: Session,
    user_id: uuid.UUID,
    *,
    week_start: date,
    today: Optional[date] = None,
) -> dict[str, Any]:
    today = today or _today_bangkok()
    ctx = _build_ctx(session, user_id, week_start, today)
    if ctx is None:
        rollup = weekly_rollup(user_id, normalize_week_start(week_start), session=session, today=today)
        target = rollup.get("target_tss")
        planned = float(rollup.get("planned_tss") or 0) if rollup else 0
        gap = (float(target) - planned) if target is not None else 0
        return {
            "week_start": normalize_week_start(week_start).isoformat(),
            "gap_tss": round(gap, 1),
            "proposed": [],
            "message": "Week is on target or within 5 TSS — nothing to suggest.",
        }

    race_week = (ctx.phase or "") == "race_week"
    candidates = _load_candidates(session, user_id, race_week=race_week)
    views = list(ctx.sessions)
    proposed: list[dict[str, Any]] = []
    remaining_gap = ctx.week_gap

    for cand in candidates:
        if remaining_gap <= GAP_MIN_SUGGEST_TSS:
            break
        if float(cand["estimated_tss"]) > remaining_gap + 0.01:
            continue
        day = _pick_day(ctx, views, cand)
        if day is None:
            continue
        item = {
            "planned_date": day.isoformat(),
            "session_type": cand["session_type"],
            "name": cand["name"],
            "structure": cand["structure"],
            "estimated_tss": round(float(cand["estimated_tss"]), 1),
            "candidate_id": cand["candidate_id"],
            "label": "suggested",
        }
        proposed.append(item)
        views.append(
            PlanSessionView(
                id=None,
                planned_date=day,
                session_type=cand["session_type"],
                structure=cand["structure"],
                source="support",
                estimated_tss=float(cand["estimated_tss"]),
            )
        )
        remaining_gap = ctx.target_tss - _week_planned_tss(views, ctx.week_start)

    message = None
    if not proposed and ctx.week_gap > GAP_MIN_SUGGEST_TSS:
        message = "No session fits the remaining gap under day cap and planning rules this week."

    return {
        "week_start": ctx.week_start.isoformat(),
        "target_tss": round(ctx.target_tss, 1),
        "gap_tss": round(ctx.week_gap, 1),
        "proposed": proposed,
        "message": message,
    }


def apply_week_suggestions(
    session: Session,
    user_id: uuid.UUID,
    proposed: list[dict[str, Any]],
) -> dict[str, Any]:
    created = 0
    for item in proposed:
        row = PlannedSession(
            user_id=user_id,
            planned_date=date.fromisoformat(item["planned_date"][:10]),
            session_type=item["session_type"],
            name=item.get("name"),
            structure=item.get("structure"),
            plan_source="support",
            status="planned",
            notes="Suggested fill (P3-10)",
        )
        session.add(row)
        created += 1
    return {"created": created}