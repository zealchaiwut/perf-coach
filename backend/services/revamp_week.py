"""Combined Plan-tab payload: one session, one shared context (#1927)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import PlannedSession, Race
from backend.services.radar_cache import DERIVED_RADAR_KEY
from backend.services.revamp_load_plan import (
    generic_road_chart,
    generic_week_load,
    revamp_week_load,
    road_to_chart,
)
from backend.services.revamp_plan_settings import plan_context
from backend.services.revamp_week_board import week_board
from backend.services.weekly_rollup import normalize_week_start
from backend.utils.time import today_bangkok

ALLOWED_SECTIONS = (
    "board",
    "week_load",
    "road",
    "warnings",
    "rail",
    "upcoming_races",
)

RACE_WEEK_NOTE = (
    "Weekly training target excludes race-day load; race TSS is counted separately."
)
EMPTY_WARNINGS = {
    "layout_error": None,
    "clashes": [],
    "race_week_note": RACE_WEEK_NOTE,
}


class UnknownSectionError(ValueError):
    def __init__(self, unknown: list[str]):
        self.unknown = unknown
        self.allowed = list(ALLOWED_SECTIONS)
        super().__init__(f"unknown section(s): {', '.join(unknown)}")


def parse_sections(raw: Optional[str]) -> list[str]:
    if raw is None or not str(raw).strip():
        return list(ALLOWED_SECTIONS)
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    unknown = [p for p in parts if p not in ALLOWED_SECTIONS]
    if unknown:
        raise UnknownSectionError(unknown)
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return seen


def peek_focus_label(session: Session, user_id: uuid.UUID, as_of: date) -> Optional[str]:
    """Radar cache only — never computes the radar (#1927)."""
    from backend.services.derived_cache import derived_signature
    from backend.services.summary_cache_store import summary_cache_get

    sig = derived_signature(session, user_id, as_of)
    cached = summary_cache_get(user_id, DERIVED_RADAR_KEY, sig)
    if not isinstance(cached, dict):
        return None
    for axis in cached.get("axes") or []:
        if axis.get("focus"):
            return axis.get("label") or axis.get("axis")
    return None


def upcoming_races_section(session: Session, user_id: uuid.UUID, today: date) -> list[dict[str, Any]]:
    rows = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.status == "planned",
            Race.race_date >= today,
        )
        .order_by(Race.race_date)
        .limit(2)
        .all()
    )
    return [
        {"name": r.name, "race_date": r.race_date.isoformat(), "priority": r.priority}
        for r in rows
    ]


def _skip_warnings(session: Session, user_id: uuid.UUID, today: date, ctx: Optional[dict[str, Any]]) -> bool:
    if ctx is not None:
        return False
    recent = (
        session.query(Race.id)
        .filter(
            Race.user_id == user_id,
            Race.race_date >= today - timedelta(days=14),
            Race.status.in_(("planned", "done")),
        )
        .first()
    )
    return recent is None


def rail_section(
    session: Session,
    user_id: uuid.UUID,
    today: date,
    *,
    focus_label: Optional[str],
) -> dict[str, Any]:
    rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= today,
            PlannedSession.status.notin_(("skipped", "missed", "missed_auto", "missed_manual")),
        )
        .order_by(PlannedSession.planned_date, PlannedSession.created_at)
        .limit(24)
        .all()
    )
    next_up: list[dict[str, Any]] = []
    coach_imported = False
    for row in rows:
        src = (row.plan_source or "user").lower()
        if src == "coach":
            coach_imported = True
        if len(next_up) < 3:
            next_up.append(
                {
                    "name": row.name or "Session",
                    "date": row.planned_date.isoformat(),
                    "kind": row.session_type,
                    "plan_source": row.plan_source or "user",
                }
            )
    return {
        "next_up": next_up,
        "coach_imported": coach_imported,
        "focus_label": focus_label,
    }


def build_revamp_week(
    session: Session,
    user_id: uuid.UUID,
    *,
    week_start: date,
    sections: Optional[list[str]] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    today = today or today_bangkok()
    ws = normalize_week_start(week_start)
    wanted = list(sections or ALLOWED_SECTIONS)
    uid = uuid.UUID(str(user_id))
    ctx = plan_context(session, uid, today=today)
    chronic = None if ctx is None else ctx.get("chronic_baseline")
    out: dict[str, Any] = {"week_start": ws.isoformat()}

    if "board" in wanted:
        out["board"] = week_board(uid, ws, session=session, today=today)
    if "week_load" in wanted:
        load = revamp_week_load(uid, ws, session=session, today=today, ctx=ctx)
        if load is None:
            load = generic_week_load(uid, ws, session=session, today=today, chronic=chronic)
        out["week_load"] = load
    if "road" in wanted:
        road = road_to_chart(uid, session=session, today=today, ctx=ctx)
        if road is None:
            road = generic_road_chart(uid, session=session, today=today, chronic=chronic)
        out["road"] = road
    if "warnings" in wanted:
        if _skip_warnings(session, uid, today, ctx):
            out["warnings"] = dict(EMPTY_WARNINGS)
        else:
            from backend.services.plan_warnings import revamp_warnings_payload

            out["warnings"] = revamp_warnings_payload(session, uid, today=today, ctx=ctx)
    if "rail" in wanted:
        focus = peek_focus_label(session, uid, today)
        out["rail"] = rail_section(session, uid, today, focus_label=focus)
    if "upcoming_races" in wanted:
        out["upcoming_races"] = upcoming_races_section(session, uid, today)
    return out
