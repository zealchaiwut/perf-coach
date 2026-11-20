"""Seven-day plan board payload (P3-5)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlannedSession
from backend.services.plan_match_payload import planned_item_status, planned_tss_estimate
from backend.services.training_month import _planned_kind
from backend.services.training_prefs import active_dict
from backend.services.training_load import estimate_historical_pace_and_tss
from backend.utils.time import today_bangkok
from backend.services.weekly_rollup import normalize_week_start


def effective_plan_source(row: PlannedSession) -> str:
    ps = (getattr(row, "plan_source", None) or "user").strip().lower()
    if ps in ("coach", "support", "user"):
        return ps
    return "support"


def _planned_board_item(session: Session, row: PlannedSession, today: date) -> dict[str, Any]:
    st = planned_item_status(row, today)
    src = effective_plan_source(row)
    return {
        "id": str(row.id),
        "planned_date": row.planned_date.isoformat(),
        "session_type": row.session_type,
        "kind": _planned_kind(row.session_type),
        "plan_source": src,
        "locked": src == "coach",
        "name": row.name or row.session_type.replace("_", " ").title(),
        "notes": row.notes,
        "status": st,
        "estimated_tss": planned_tss_estimate(session, row),
    }


def week_board(
    user_id: uuid.UUID,
    week_start: date,
    *,
    session: Session,
    today: Optional[date] = None,
) -> dict[str, Any]:
    today = today or today_bangkok()
    ws = normalize_week_start(week_start)
    we = ws + timedelta(days=6)
    prefs = active_dict(session, user_id)
    rest_days = sorted({int(d) for d in (prefs.get("payload") or {}).get("rest_days") or [] if 0 <= int(d) <= 6})

    rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= ws,
            PlannedSession.planned_date <= we,
            PlannedSession.status.notin_(("skipped",)),
        )
        .order_by(PlannedSession.planned_date, PlannedSession.created_at)
        .all()
    )
    by_date: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_date.setdefault(r.planned_date.isoformat(), []).append(_planned_board_item(session, r, today))

    days: list[dict[str, Any]] = []
    for i in range(7):
        d = ws + timedelta(days=i)
        iso = d.isoformat()
        is_rest = i in rest_days and not by_date.get(iso)
        days.append(
            {
                "date": iso,
                "weekday": i,
                "label": d.strftime("%a"),
                "is_preferred_rest": i in rest_days,
                "rest_placeholder": is_rest,
                "items": by_date.get(iso, []),
            }
        )

    estimate_baseline = estimate_historical_pace_and_tss(session, user_id)
    return {
        "week_start": ws.isoformat(),
        "week_end": we.isoformat(),
        "preferred_rest_days": rest_days,
        "days": days,
        "estimate_baseline": estimate_baseline is not None,
    }