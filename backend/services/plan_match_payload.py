"""Plan match payloads for revamp log surfaces (P1-6)."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlannedSession, Workout
from backend.services.plan_matching import _planned_duration_seconds
from backend.services.training_load import estimate_historical_pace_and_tss, estimate_planned_session_metrics

_MISSED = frozenset({"missed", "missed_auto", "missed_manual", "needs_review"})
_SKIPPED = frozenset({"skipped"})
_MATCHED_DONE = frozenset({"done_auto", "done_manual"})


def planned_source(session_type: str) -> str:
    st = (session_type or "").lower()
    return "coach" if st == "run" else "support"


def effective_plan_source_for_row(row) -> str:
    """Prefer persisted plan_source; fall back to type heuristic until backfill."""
    ps = getattr(row, "plan_source", None)
    if ps and str(ps).strip().lower() in ("coach", "support", "user"):
        return str(ps).strip().lower()
    return planned_source(getattr(row, "session_type", ""))


def plan_match_for_workout(session: Session, workout_id: uuid.UUID) -> Optional[dict[str, Any]]:
    row = (
        session.query(PlannedSession)
        .filter(PlannedSession.matched_workout_id == workout_id)
        .order_by(PlannedSession.planned_date.desc())
        .first()
    )
    if row is None:
        return None
    planned_tss = planned_tss_estimate(session, row)
    return {
        "planned_id": str(row.id),
        "planned_name": row.name,
        "planned_tss": planned_tss,
        "source": planned_source(row.session_type),
    }


def plan_match_map(session: Session, workout_ids: list[uuid.UUID]) -> dict[str, Optional[dict[str, Any]]]:
    if not workout_ids:
        return {}
    rows = (
        session.query(PlannedSession)
        .filter(PlannedSession.matched_workout_id.in_(workout_ids))
        .all()
    )
    by_wid: dict[uuid.UUID, PlannedSession] = {}
    for r in rows:
        if r.matched_workout_id and r.matched_workout_id not in by_wid:
            by_wid[r.matched_workout_id] = r
    out: dict[str, Optional[dict[str, Any]]] = {}
    for wid in workout_ids:
        row = by_wid.get(wid)
        if row is None:
            out[str(wid)] = None
            continue
        out[str(wid)] = {
            "planned_id": str(row.id),
            "planned_name": row.name,
            "planned_tss": planned_tss_estimate(session, row),
            "source": planned_source(row.session_type),
        }
    return out


def planned_tss_estimate(session: Session, row: PlannedSession) -> Optional[float]:
    baseline = estimate_historical_pace_and_tss(str(row.user_id), session)
    est = estimate_planned_session_metrics(baseline, row.session_type, row.structure)
    val = est.get("estimated_tss")
    return round(float(val), 1) if val is not None else None


def plan_kept_ratio(matched: int, missed: int) -> Optional[float]:
    denom = matched + missed
    if denom <= 0:
        return None
    return round(matched / denom, 3)


def planned_item_status(row: PlannedSession, today) -> str:
    """Missed only after the Bangkok calendar day ends (planned_date < today)."""
    st = (row.status or "planned").lower()
    if st in _SKIPPED:
        return "skipped"
    if row.matched_workout_id is not None or st in _MATCHED_DONE:
        return "done"
    if row.planned_date >= today:
        return "planned"
    if st in _MISSED or row.planned_date < today:
        return "missed"
    return "planned"


def is_missed_planned(row: PlannedSession, today) -> bool:
    """True only when planned_date is a Bangkok calendar day strictly before today."""
    if row.planned_date >= today:
        return False
    return planned_item_status(row, today) == "missed"


def who_label(*, kind: str, source: str, status: str) -> str:
    """Mock-style card header (TrainingLog preview)."""
    st = (status or "").lower()
    if st == "missed":
        return "MISSED"
    if kind == "rest":
        return "REST"
    if kind == "race":
        return "RACE" if source in ("unplanned", "coach") else "B RACE"
    if source == "unplanned":
        if kind in ("strength", "plyo"):
            return "STRENGTH · UNPLANNED" if kind == "strength" else "PLYO · UNPLANNED"
        return "RUN" if kind.startswith("run") or kind == "quality_run" else kind.upper()
    if source == "coach":
        return "COACH · LOCKED" if st == "planned" else "COACH"
    if source == "support":
        return "SUPPORT"
    return kind.replace("_", " ").upper()


def session_kind_for_workout(workout: Workout) -> str:
    wt = (workout.workout_type or "").lower()
    rs = (workout.run_subtype or "").lower()
    if "race" in wt or rs == "race":
        return "race"
    if wt == "run" or "run" in wt:
        if rs in ("interval", "tempo"):
            return "quality_run"
        return "run"
    if "strength" in wt or "lift" in wt:
        return "strength"
    if "plyo" in wt:
        return "plyo"
    if "mobility" in wt:
        return "mobility"
    if "drill" in wt:
        return "drills"
    return "run" if (workout.distance_km or 0) > 0 else "strength"