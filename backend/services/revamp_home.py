"""Revamp Home — today hero, race-week plan panel, alert strip (P5-1)."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import Decision, PlannedSession, Race
from backend.services.coach_block import checkin_state, newest_due, review_lines
from backend.services.load_plan import ACWR_CEILING_MULT
from backend.services.perf_a_race import next_a_race
from backend.services.plan_match_payload import planned_tss_estimate
from backend.services.plan_matching import _planned_duration_seconds
from backend.services.plan_rules_engine import PlanSessionView, effective_plan_source_attr
from backend.services.revamp_load_plan import chronic_weekly_tss
from backend.services.race_finish_estimate import estimate_race_finish
from backend.services.revamp_week_board import week_board
from backend.services.sync_provider_status import build_providers, dot_state
from backend.services.training_load import estimate_historical_pace_and_tss, estimate_planned_session_metrics
from backend.services.weekly_rollup import normalize_week_start
from backend.utils.time import today_bangkok

FUEL_DEFAULT = "Gels every 30 min from 40"
RACE_REMINDER_COPY = "Nothing new on race day. Same gels, same timing, same shoes."
FIRST_10K_PACE_BUFFER_SEC = 10
SYNC_STALE_HOURS = 48

_EFFORT_LABELS = {
    1: "Recovery",
    2: "Easy",
    3: "Easy",
    4: "Steady",
    5: "Moderate",
    6: "Threshold",
    7: "Hard",
    8: "Hard",
    9: "Hard",
    10: "Max",
}


def format_pace_seconds_per_km(sec: Optional[int]) -> Optional[str]:
    if sec is None or sec <= 0:
        return None
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d} /km"


def _effort_label(structure: Optional[dict]) -> str:
    if not isinstance(structure, dict):
        return "—"
    raw = structure.get("effort") or structure.get("target_effort") or structure.get("zone")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().title()
    try:
        return _EFFORT_LABELS.get(int(raw), "Moderate")
    except (TypeError, ValueError):
        return "Moderate"


def _duration_minutes(session_type: str, structure: Optional[dict]) -> Optional[int]:
    sec = _planned_duration_seconds(structure)
    if sec:
        return max(1, int(round(sec / 60)))
    from backend.services.training_load import _planned_duration_minutes

    dm = _planned_duration_minutes(session_type, structure)
    return int(round(dm)) if dm else None


def _session_tiles(session: Session, row: PlannedSession) -> dict[str, Any]:
    baseline = estimate_historical_pace_and_tss(row.user_id, session)
    est = estimate_planned_session_metrics(baseline, row.session_type, row.structure)
    return {
        "target_tss": planned_tss_display(session, row, est),
        "duration_min": _duration_minutes(row.session_type or "", row.structure if isinstance(row.structure, dict) else None),
        "effort": _effort_label(row.structure if isinstance(row.structure, dict) else None),
    }


def planned_tss_display(session: Session, row: PlannedSession, est: Optional[dict] = None) -> Optional[float]:
    val = planned_tss_estimate(session, row)
    if val is not None:
        return val
    if est and est.get("estimated_tss") is not None:
        return float(est["estimated_tss"])
    return None


def _source_subtitle(plan_source: str) -> str:
    if plan_source == "coach":
        return "From your coach"
    if plan_source == "support":
        return "Your support session"
    return "Planned in the app"


def _sync_freshness_hours(last_success_at: Optional[str], now: datetime) -> Optional[float]:
    if not last_success_at:
        return None
    try:
        last = datetime.fromisoformat(last_success_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last.astimezone(timezone.utc)).total_seconds() / 3600.0


def sync_alert(provider_rows: dict[str, Any], *, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """True when any connected provider is in error or last sync is >= 48h old."""
    now = now or datetime.now(timezone.utc)
    stale_sources: list[str] = []
    for source in ("strava", "stryd"):
        p = provider_rows.get(source) or {}
        if not p.get("connected"):
            continue
        if p.get("last_error"):
            return {
                "rule_id": "sync_error",
                "message": f"{source.title()} sync failed — open Integrations to retry.",
                "href": "/settings?tab=integrations",
            }
        age_h = _sync_freshness_hours(p.get("last_success_at"), now)
        if age_h is None or age_h > SYNC_STALE_HOURS:
            stale_sources.append(source.title())
    if stale_sources:
        return {
            "rule_id": "sync_stale",
            "message": f"Last sync {' and '.join(stale_sources)} older than {SYNC_STALE_HOURS} hours.",
            "href": "/settings?tab=integrations",
        }
    return None


def sync_alert_boundary(provider_rows: dict[str, Any], *, now: datetime) -> Optional[dict[str, Any]]:
    """Same as sync_alert but treats exactly 48h as fresh (strict boundary for tests)."""
    for source in ("strava", "stryd"):
        p = provider_rows.get(source) or {}
        if not p.get("connected"):
            continue
        if p.get("last_error"):
            return sync_alert(provider_rows, now=now)
        age_h = _sync_freshness_hours(p.get("last_success_at"), now)
        if age_h is None or age_h > SYNC_STALE_HOURS:
            return sync_alert(provider_rows, now=now)
    return None


_GEL_LINE = re.compile(r"(gel|fuel)", re.I)


def _fuel_timing_line(session: Session, user_id: uuid.UUID, race: Race) -> str:
    """Race fuel line from today's or race-day plan notes, else default."""
    rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date == race.race_date,
        )
        .all()
    )
    for row in rows:
        for text in (row.notes, row.name):
            if text and _GEL_LINE.search(text):
                return text.strip()
        struct = row.structure if isinstance(row.structure, dict) else {}
        for key in ("fuel_note", "fuel", "notes"):
            val = struct.get(key)
            if isinstance(val, str) and _GEL_LINE.search(val):
                return val.strip()
    return FUEL_DEFAULT


def race_plan_panel(session: Session, user_id: uuid.UUID, race: Race, today: date) -> dict[str, Any]:
    est = estimate_race_finish(user_id, race, today=today, db=session)
    distance = float(race.distance_km) if race.distance_km else None
    est_sec = est.get("est_sec")
    pace_spk = None
    if est_sec and distance:
        pace_spk = int(round(est_sec / distance))
    cap_spk = pace_spk + FIRST_10K_PACE_BUFFER_SEC if pace_spk is not None else None
    return {
        "race_id": str(race.id),
        "race_name": race.name,
        "days_to_race": (race.race_date - today).days,
        "fuel_timing": _fuel_timing_line(session, user_id, race),
        "target_pace_seconds_per_km": pace_spk,
        "target_pace_label": format_pace_seconds_per_km(pace_spk),
        "first_10k_cap_seconds_per_km": cap_spk,
        "first_10k_cap_label": format_pace_seconds_per_km(cap_spk),
        "reminder_copy": RACE_REMINDER_COPY,
    }


def _today_day(board: dict[str, Any], today: date) -> Optional[dict[str, Any]]:
    iso = today.isoformat()
    for day in board.get("days") or []:
        if day.get("date") == iso:
            return day
    return None


def build_today_hero(
    session: Session,
    user_id: uuid.UUID,
    today: date,
    *,
    board: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    board = board or week_board(user_id, normalize_week_start(today), session=session, today=today)
    day = _today_day(board, today)
    if day is None:
        return {"state": "empty", "session": None, "plan_link": "/v2/training/plan"}

    items = list(day.get("items") or [])
    if day.get("rest_placeholder") and not items:
        return {"state": "rest", "session": None, "plan_link": "/v2/training/plan"}

    if not items:
        return {
            "state": "empty",
            "session": None,
            "plan_link": "/v2/training/plan",
            "empty_copy": "Nothing on the plan for today.",
        }

    primary = items[0]
    # load full row for structure / mark-done
    ps_id = primary.get("id")
    row = session.get(PlannedSession, uuid.UUID(ps_id)) if ps_id else None
    status = primary.get("status") or "planned"
    src = primary.get("plan_source") or "support"
    kind = (primary.get("kind") or "").lower()
    is_run = kind.startswith("run") or (row and (row.session_type or "").lower() == "run")
    mark_done = bool(row) and not is_run and src in ("support", "user") and status == "planned"

    session_block = {
        "id": ps_id,
        "name": primary.get("name"),
        "notes": primary.get("notes"),
        "plan_source": src,
        "status": status,
        "kind": kind,
        "source_subtitle": _source_subtitle(src),
        "tiles": _session_tiles(session, row) if row else {},
        "mark_done_allowed": mark_done,
        "run_auto_complete_note": "Ticks itself when Strava syncs" if is_run else None,
    }
    state = "done" if status == "done" else "planned"
    if status == "planned" and len(items) > 1 and all(i.get("status") == "done" for i in items[1:]):
        pass
    return {
        "state": state,
        "session": session_block,
        "plan_link": "/v2/training/plan",
        "extra_items_count": max(0, len(items) - 1),
    }


def week_planned_over_ceiling(session: Session, user_id: uuid.UUID, today: date) -> Optional[dict[str, Any]]:
    ws = normalize_week_start(today)
    we = ws + timedelta(days=6)
    baseline = estimate_historical_pace_and_tss(user_id, session)
    rows = (
        session.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= ws,
            PlannedSession.planned_date <= we,
            PlannedSession.status.notin_(("missed", "skipped")),
        )
        .all()
    )
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
    week_tss = sum(v.estimated_tss for v in views)
    if week_tss <= ceiling:
        return None
    return {
        "rule_id": "week_planned_ceiling",
        "message": f"Week planned load {week_tss:.0f} TSS exceeds the ceiling ({ceiling:.0f}).",
        "href": "/v2/training/plan",
        "week_planned_tss": round(week_tss, 1),
        "ceiling_tss": ceiling,
    }


def build_alerts(
    *,
    provider_rows: dict[str, Any],
    review_due: Optional[Decision],
    checkin: dict[str, Any],
    ceiling_hit: Optional[dict[str, Any]],
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sync = sync_alert(provider_rows, now=now)
    if sync:
        out.append(sync)
    if checkin.get("state") == "due":
        out.append(
            {
                "rule_id": "weekly_checkin",
                "message": "Weekly coach check-in is due.",
                "href": checkin.get("link") or "/coach",
            }
        )
    if review_due is not None:
        lines = review_lines(review_due.raw_text)
        snippet = lines[0] if lines else "A past decision needs your review."
        out.append(
            {
                "rule_id": "review_due",
                "message": snippet,
                "href": "/v2/performance#coach",
                "decision_id": str(review_due.id),
            }
        )
    if ceiling_hit:
        out.append({k: ceiling_hit[k] for k in ("rule_id", "message", "href")})
    return out


def home_payload(session: Session, user_id: uuid.UUID, *, today: Optional[date] = None) -> dict[str, Any]:
    today = today or today_bangkok()
    board = week_board(user_id, normalize_week_start(today), session=session, today=today)
    hero = build_today_hero(session, user_id, today, board=board)
    race = next_a_race(session, user_id, today)
    show_race_plan = False
    race_plan = None
    if race is not None:
        days = (race.race_date - today).days
        if 0 <= days <= 7:
            show_race_plan = True
            race_plan = race_plan_panel(session, user_id, race, today)

    providers = build_providers(session, user_id)
    decisions = (
        session.query(Decision)
        .filter(Decision.user_id == user_id)
        .order_by(Decision.decided_on.desc(), Decision.created_at.desc())
        .all()
    )
    due = newest_due(decisions, today)
    checkin = checkin_state(decisions, today)
    ceiling_hit = week_planned_over_ceiling(session, user_id, today)
    alerts = build_alerts(
        provider_rows=providers,
        review_due=due,
        checkin=checkin,
        ceiling_hit=ceiling_hit,
    )

    from backend.models import User

    user_row = session.get(User, user_id)
    name = (user_row.name if user_row else None) or None

    return {
        "as_of": today.isoformat(),
        "greeting_name": name,
        "hero": hero,
        "show_race_plan": show_race_plan,
        "race_plan": race_plan,
        "alerts": alerts,
        "sync_summary": {
            "strava": dot_state(providers.get("strava") or {}),
            "stryd": dot_state(providers.get("stryd") or {}),
        },
        "race_week": show_race_plan,
    }