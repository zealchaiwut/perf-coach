"""Planning rules engine (P3-9): pure evaluate() + DB-backed context loader.

Returns structured rule hits for board moves and the planned session editor.
Levels: ok (implicit), warn, block.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal, Optional

from sqlalchemy.orm import Session

from backend.services.coach_export import _max_consecutive_training_days
from backend.services.load_plan import ACWR_CEILING_MULT
from backend.services.plan_suggestions import _MAX_CONSECUTIVE_TRAINING_DAYS
from backend.services.revamp_load_plan import chronic_weekly_tss, week_target_and_phase
from backend.services.training_prefs import active_dict
from backend.services.weekly_rollup import normalize_week_start
from backend.utils.time import today_bangkok

RuleLevel = Literal["ok", "warn", "block"]

# Single constants block — per-user overrides arrive in P5-9.
RULE_THRESHOLDS: dict[str, float | int] = {
    "race_proximity_lifting_days": 10,
    "race_proximity_plyo_days": 7,
    "weekly_target_warn_pct": 0.05,
    "race_week_support_cap_tss": 15,
}

_GROUP_HEAVY = "heavy_compound"
_GROUP_BODYWEIGHT = "bodyweight"
_GROUP_PLYO = "plyo"


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    level: RuleLevel
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"rule_id": self.rule_id, "level": self.level, "message": self.message}


@dataclass
class PlanSessionView:
    id: Optional[uuid.UUID]
    planned_date: date
    session_type: str
    structure: Optional[dict]
    source: Optional[str]
    estimated_tss: float

    @property
    def is_training(self) -> bool:
        return (self.session_type or "").strip().lower() not in ("rest", "")

    @property
    def is_coach(self) -> bool:
        return (self.source or "").lower() == "coach"


def effective_plan_source_attr(row) -> str:
    from backend.services.plan_match_payload import effective_plan_source_for_row

    return effective_plan_source_for_row(row)


def _session_source(structure: Optional[dict], explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    if not isinstance(structure, dict):
        return None
    for key in ("source", "_source", "plan_source"):
        v = structure.get(key)
        if v:
            return str(v)
    return None


def _exercise_names(structure: Optional[dict]) -> list[str]:
    if not structure or not isinstance(structure, dict):
        return []
    names: list[str] = []
    for ex in structure.get("exercises") or []:
        if isinstance(ex, dict) and ex.get("name"):
            names.append(str(ex["name"]).strip().lower())
    return names


def _groups_for_session(
    view: PlanSessionView,
    exercise_groups: dict[str, set[str]],
) -> set[str]:
    st = (view.session_type or "").lower()
    groups: set[str] = set()
    if st == "plyo":
        groups.add(_GROUP_PLYO)
    for name in _exercise_names(view.structure):
        groups.update(exercise_groups.get(name, set()))
    return groups


def _training_streak_length(dates: set[date], focus: date) -> int:
    if focus not in dates:
        return 0
    start = focus
    while start - timedelta(days=1) in dates:
        start -= timedelta(days=1)
    end = focus
    while end + timedelta(days=1) in dates:
        end += timedelta(days=1)
    return (end - start).days + 1


def _apply_change(
    sessions: list[PlanSessionView],
    change: dict[str, Any],
) -> list[PlanSessionView]:
    """Return a new session list with the hypothetical change applied."""
    action = (change.get("action") or "move").lower()
    sid = change.get("session_id")
    target_date = change.get("planned_date")
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)

    out = list(sessions)
    if action in ("delete",):
        if sid:
            suid = uuid.UUID(str(sid))
            out = [s for s in out if s.id != suid]
        return out

    if action in ("create",):
        out.append(
            PlanSessionView(
                id=None,
                planned_date=target_date,
                session_type=str(change.get("session_type") or "run"),
                structure=change.get("structure"),
                source=_session_source(change.get("structure"), change.get("source")),
                estimated_tss=float(change.get("estimated_tss") or 0),
            )
        )
        return out

    # update / move
    suid = uuid.UUID(str(sid)) if sid else None
    patched: list[PlanSessionView] = []
    for s in out:
        if suid and s.id == suid:
            patched.append(
                PlanSessionView(
                    id=s.id,
                    planned_date=target_date or s.planned_date,
                    session_type=str(change.get("session_type") or s.session_type),
                    structure=change.get("structure") if "structure" in change else s.structure,
                    source=_session_source(
                        change.get("structure") if "structure" in change else s.structure,
                        change.get("source") if "source" in change else s.source,
                    ),
                    estimated_tss=float(
                        change.get("estimated_tss")
                        if change.get("estimated_tss") is not None
                        else s.estimated_tss
                    ),
                )
            )
        else:
            patched.append(s)
    if suid is None and action == "create":
        pass
    elif suid is None:
        patched.append(
            PlanSessionView(
                id=None,
                planned_date=target_date,
                session_type=str(change.get("session_type") or "run"),
                structure=change.get("structure"),
                source=_session_source(change.get("structure"), change.get("source")),
                estimated_tss=float(change.get("estimated_tss") or 0),
            )
        )
    return patched


def _resolve_focus(projected: list[PlanSessionView], change: dict[str, Any]) -> Optional[PlanSessionView]:
    target_date = change.get("planned_date")
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    sid = change.get("session_id")
    if sid:
        suid = uuid.UUID(str(sid))
        for s in projected:
            if s.id == suid:
                return s
    action = (change.get("action") or "").lower()
    if action == "create" and target_date:
        for s in reversed(projected):
            if s.planned_date == target_date and s.id is None:
                return s
    if target_date:
        for s in reversed(projected):
            if s.planned_date == target_date and s.is_training:
                return s
    return None


def evaluate_plan_change(
    *,
    sessions: list[PlanSessionView],
    change: dict[str, Any],
    preferred_rest_days: list[int],
    max_consecutive_cap: int,
    week_target_tss: Optional[float],
    acwr_ceiling: float,
    races: list[dict[str, Any]],
    phase: Optional[str],
    exercise_groups: dict[str, set[str]],
) -> list[RuleHit]:
    """Pure rule evaluation against an in-memory week (+ context)."""
    hits: list[RuleHit] = []
    projected = _apply_change(sessions, change)
    target_date = change.get("planned_date")
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)

    changed = _resolve_focus(projected, change)
    rest_set = {int(d) for d in preferred_rest_days if 0 <= int(d) <= 6}

    # ── rest_day ──
    if changed and target_date and target_date.weekday() in rest_set:
        coach_on_day = any(
            s.planned_date == target_date and s.is_coach and s.is_training for s in projected
        )
        level: RuleLevel = "block" if coach_on_day else "warn"
        hits.append(
            RuleHit(
                "rest_day",
                level,
                "Preferred rest day — training here needs a deliberate choice."
                + (" A coach session is already on this day." if coach_on_day else ""),
            )
        )

    # ── max_consecutive ──
    train_dates = {s.planned_date for s in projected if s.is_training}
    if changed and target_date:
        streak = _training_streak_length(train_dates, target_date)
        if streak > max_consecutive_cap:
            hits.append(
                RuleHit(
                    "max_consecutive",
                    "block",
                    f"Would exceed {max_consecutive_cap} consecutive training days ({streak} in a row).",
                )
            )
        elif streak == max_consecutive_cap:
            hits.append(
                RuleHit(
                    "max_consecutive",
                    "warn",
                    f"Hits the {max_consecutive_cap}-day training streak limit.",
                )
            )

    # ── weekly_ceiling / target ──
    if target_date:
        ws = normalize_week_start(target_date)
        week_end = ws + timedelta(days=6)
        week_tss = sum(s.estimated_tss for s in projected if ws <= s.planned_date <= week_end)
        if week_tss > acwr_ceiling:
            hits.append(
                RuleHit(
                    "weekly_ceiling",
                    "block",
                    f"Week planned load {week_tss:.0f} TSS exceeds the ACWR ceiling ({acwr_ceiling:.0f}).",
                )
            )
        elif week_target_tss is not None and week_tss > week_target_tss * (1 + RULE_THRESHOLDS["weekly_target_warn_pct"]):
            hits.append(
                RuleHit(
                    "weekly_ceiling",
                    "warn",
                    f"Week planned load {week_tss:.0f} TSS is more than 5% above target ({week_target_tss:.0f}).",
                )
            )

    if not changed or not target_date:
        return hits

    sess_groups = _groups_for_session(changed, exercise_groups)
    st = (changed.session_type or "").lower()

    for race in races:
        rdate = race["race_date"]
        if isinstance(rdate, str):
            rdate = date.fromisoformat(rdate)
        days_before = (rdate - target_date).days
        if days_before < 0:
            continue
        is_a = (race.get("priority") or "A").upper() == "A"
        if is_a and days_before <= int(RULE_THRESHOLDS["race_proximity_lifting_days"]):
            if _GROUP_HEAVY in sess_groups:
                hits.append(
                    RuleHit(
                        "race_proximity_lifting",
                        "block",
                        f"Heavy lifting within {days_before} days of A race {race.get('name')}.",
                    )
                )
        if days_before <= int(RULE_THRESHOLDS["race_proximity_plyo_days"]):
            if st == "plyo" or _GROUP_PLYO in sess_groups:
                hits.append(
                    RuleHit(
                        "race_proximity_plyo",
                        "block",
                        f"Plyo within {days_before} days of race {race.get('name')}.",
                    )
                )
        if days_before == 1 and changed.is_training:
            bad_day_before = st in ("run", "plyo") or (
                st == "strength" and (not sess_groups or bool(sess_groups - {_GROUP_BODYWEIGHT}))
            )
            if bad_day_before:
                hits.append(
                    RuleHit(
                        "day_before_race",
                        "block",
                        f"Only bodyweight work the day before {race.get('name')}.",
                    )
                )

    # ── race_week_support_cap ──
    if phase == "race_week" and target_date and changed and not changed.is_coach:
        runs_on_day = [s for s in projected if s.planned_date == target_date and s.session_type == "run"]
        if runs_on_day:
            support_tss = sum(
                s.estimated_tss for s in projected if s.planned_date == target_date and not s.is_coach
            )
            if support_tss > float(RULE_THRESHOLDS["race_week_support_cap_tss"]):
                hits.append(
                    RuleHit(
                        "race_week_support_cap",
                        "warn",
                        f"Support sessions add {support_tss:.0f} TSS on a race-week run day (cap {RULE_THRESHOLDS['race_week_support_cap_tss']}).",
                    )
                )

    return hits


def _load_exercise_groups(session: Session) -> dict[str, set[str]]:
    from backend.models import PlanExercise

    out: dict[str, set[str]] = {}
    for row in session.query(PlanExercise).filter(PlanExercise.active.is_(True)).all():
        name = (row.name or "").strip().lower()
        if not name:
            continue
        groups = row.groups if isinstance(row.groups, list) else []
        out[name] = {str(g) for g in groups}
    return out


def evaluate(user_id: uuid.UUID, change: dict[str, Any], session: Session) -> list[dict[str, str]]:
    """Load user context and evaluate a single planning change."""
    from backend.models import PlannedSession, Race

    today = today_bangkok()
    prefs = active_dict(session, user_id)
    payload = prefs.get("payload") or {}
    rest_days = list(payload.get("rest_days") or [])
    max_cap = _max_consecutive_training_days(rest_days)
    if max_cap is None:
        max_cap = _MAX_CONSECUTIVE_TRAINING_DAYS

    target_date = change.get("planned_date")
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    if not target_date:
        raise ValueError("planned_date required")

    span_start = target_date - timedelta(days=14)
    span_end = target_date + timedelta(days=14)
    rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= span_start,
            PlannedSession.planned_date <= span_end,
            PlannedSession.status.notin_(("missed", "skipped")),
        )
        .all()
    )

    from backend.services.training_load import (
        estimate_historical_pace_and_tss,
        estimate_planned_session_metrics,
    )

    baseline = estimate_historical_pace_and_tss(user_id, session)
    views: list[PlanSessionView] = []
    for p in rows:
        est = estimate_planned_session_metrics(baseline, p.session_type, p.structure)
        views.append(
            PlanSessionView(
                id=p.id,
                planned_date=p.planned_date,
                session_type=p.session_type,
                structure=p.structure if isinstance(p.structure, dict) else None,
                source=effective_plan_source_attr(p),
                estimated_tss=float(est.get("estimated_tss") or 0),
            )
        )

    chronic = chronic_weekly_tss(session, user_id, today)
    ceiling = round(ACWR_CEILING_MULT * chronic, 1)
    ws = normalize_week_start(target_date)
    meta = week_target_and_phase(user_id, ws, session=session, chronic_baseline=chronic, today=today) or {}
    target_tss = meta.get("target_tss")
    phase = meta.get("phase")

    races_raw = (
        session.query(Race)
        .filter(Race.user_id == user_id, Race.status == "planned", Race.race_date >= today - timedelta(days=1))
        .order_by(Race.race_date)
        .all()
    )
    races = [
        {
            "name": r.name,
            "race_date": r.race_date.isoformat(),
            "priority": r.priority,
        }
        for r in races_raw
    ]

    hits = evaluate_plan_change(
        sessions=views,
        change=change,
        preferred_rest_days=rest_days,
        max_consecutive_cap=int(max_cap),
        week_target_tss=float(target_tss) if target_tss is not None else None,
        acwr_ceiling=ceiling,
        races=races,
        phase=phase,
        exercise_groups=_load_exercise_groups(session),
    )
    return [h.as_dict() for h in hits]


def summarize(hits: list[dict[str, str]]) -> RuleLevel:
    if any(h.get("level") == "block" for h in hits):
        return "block"
    if any(h.get("level") == "warn" for h in hits):
        return "warn"
    return "ok"