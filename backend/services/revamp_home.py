"""Revamp Home — today hero, race-week plan panel, alert strip (P5-1)."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import Decision, PlannedSession, Race, UserPreferences, Workout
from backend.services.coach_block import checkin_state, fetch_coach_block, newest_due, review_lines
from backend.services.load_plan import ACWR_CEILING_MULT
from backend.services.perf_a_race import next_a_race
from backend.services.plan_match_payload import planned_tss_estimate
from backend.services.plan_matching import _planned_duration_seconds
from backend.services.plan_rules_engine import PlanSessionView, effective_plan_source_attr
from backend.services.revamp_load_plan import chronic_weekly_tss, revamp_week_load
from backend.services.race_finish_estimate import estimate_race_finish
from backend.services.revamp_week_board import week_board
from backend.services.sync_provider_status import build_providers, dot_state
from backend.services.training_load import estimate_historical_pace_and_tss, estimate_planned_session_metrics
from backend.services.weekly_rollup import normalize_week_start, weekly_rollup
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


def format_duration_hms(seconds: Optional[int]) -> Optional[str]:
    if seconds is None or seconds <= 0:
        return None
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_race_time(seconds: Optional[int]) -> Optional[str]:
    return format_duration_hms(seconds)


def _relative_workout_date(workout_date: date, today: date) -> str:
    delta = (today - workout_date).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    if delta < 7:
        return f"{delta} days ago"
    return workout_date.isoformat()


def _races_in_week(session: Session, user_id: uuid.UUID, ws: date, we: date) -> dict[str, Race]:
    rows = (
        session.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.race_date >= ws,
            Race.race_date <= we,
            Race.status == "planned",
        )
        .all()
    )
    return {r.race_date.isoformat(): r for r in rows}


def build_this_week(
    session: Session,
    user_id: uuid.UUID,
    today: date,
    board: dict[str, Any],
) -> dict[str, Any]:
    ws = normalize_week_start(today)
    wl = revamp_week_load(user_id, ws, session=session, today=today)
    rollup = weekly_rollup(user_id, ws, session=session, today=today)
    we = ws + timedelta(days=6)
    races = _races_in_week(session, user_id, ws, we)
    days_out: list[dict[str, Any]] = []
    for day in board.get("days") or []:
        iso = day["date"]
        d = date.fromisoformat(iso)
        race = races.get(iso)
        items_out: list[dict[str, Any]] = []
        if race is not None and not day.get("items"):
            items_out.append(
                {
                    "name": race.name,
                    "kind": "race",
                    "status": "planned",
                    "plan_source": "coach",
                    "estimated_tss": None,
                    "race_priority": (race.priority or "A").upper(),
                }
            )
        elif day.get("rest_placeholder") and not day.get("items"):
            items_out.append({"name": "Rest", "kind": "rest", "status": "planned", "plan_source": None, "estimated_tss": None})
        else:
            for it in day.get("items") or []:
                items_out.append(
                    {
                        "name": it.get("name"),
                        "kind": it.get("kind"),
                        "status": it.get("status"),
                        "plan_source": it.get("plan_source"),
                        "estimated_tss": it.get("estimated_tss"),
                        "notes": it.get("notes"),
                    }
                )
                if race is not None and (it.get("kind") or "") == "race":
                    items_out[-1]["race_priority"] = (race.priority or "A").upper()
        if race is not None and items_out and "race_priority" not in items_out[0]:
            for row in items_out:
                if (row.get("kind") or "") == "race" or race.name in (row.get("name") or ""):
                    row["race_priority"] = (race.priority or "A").upper()
        days_out.append(
            {
                "date": iso,
                "weekday": (day.get("label") or d.strftime("%a"))[:3].upper(),
                "day_of_month": d.day,
                "is_today": d == today,
                "is_race_day": race is not None,
                "items": items_out,
            }
        )
    load_bar = None
    subtitle = None
    if wl:
        target = float(wl.get("target_tss") or 0)
        logged = float(wl.get("logged_tss") or 0)
        planned = float(wl.get("planned_tss") or 0)
        base = target if target > 0 else 1.0
        load_bar = {
            "logged_pct": round(100 * logged / base, 1),
            "planned_pct": round(100 * planned / base, 1),
            "target_tss": wl.get("target_tss"),
            "logged_tss": wl.get("logged_tss"),
            "planned_tss": wl.get("planned_tss"),
        }
        phase = (wl.get("phase") or "build").replace("_", " ")
        subtitle = f"{phase.title()} · {logged + planned:.0f} / {target:.0f} TSS"
    return {
        "week_start": ws.isoformat(),
        "subtitle": subtitle,
        "load_bar": load_bar,
        "rollup_partial": bool(rollup.get("partial")),
        "days": days_out,
        "plan_href": "/v2/training/plan",
    }


def build_recent_sessions(session: Session, user_id: uuid.UUID, today: date, *, limit: int = 3) -> list[dict[str, Any]]:
    from backend.services.plan_match_payload import plan_match_map
    from backend.services.session_tss import session_tss
    from backend.services.plan_match_payload import session_kind_for_workout, who_label

    prefs = session.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    rows = (
        session.query(Workout)
        .filter(Workout.user_id == user_id)
        .order_by(Workout.workout_date.desc(), Workout.created_at.desc())
        .limit(limit)
        .all()
    )
    match_map = plan_match_map(session, [w.id for w in rows])
    out: list[dict[str, Any]] = []
    for w in rows:
        kind = session_kind_for_workout(w)
        match = match_map.get(str(w.id))
        source = (match or {}).get("source") or "unplanned"
        tss = session_tss(w, prefs=prefs, session=session).get("tss")
        out.append(
            {
                "id": str(w.id),
                "name": w.name or "Session",
                "kind": kind,
                "who": who_label(kind=kind, source=source, status="done"),
                "relative_date": _relative_workout_date(w.workout_date, today),
                "distance_km": float(w.distance_km) if w.distance_km is not None else None,
                "duration_min": round(w.duration_seconds / 60, 1) if w.duration_seconds else None,
                "tss": round(float(tss), 1) if tss is not None else None,
                "log_href": f"/v2/training/log?session={w.id}",
            }
        )
    return out


def build_focus_teaser(session: Session, user_id: uuid.UUID, today: date) -> dict[str, Any]:
    from backend.services import focus_ranking as fr
    from backend.services.radar_payload import build_radar

    race = next_a_race(session, user_id, today)
    km = float(race.distance_km) if race is not None and race.distance_km else None
    axes = build_radar(session, user_id, today)["axes"]
    ranked = fr.rank_axes(axes, km)
    focus = ranked.get("focus")
    advice = None
    axis = None
    score = None
    if focus:
        axis = focus.get("axis")
        score = focus.get("score")
        advice = (ranked.get("advice") or {}).get(axis) or fr.WORK_MAP.get(axis or "", {}).get("advice")
    return {
        "axis": axis,
        "score": score,
        "advice": advice,
        "href": "/v2/performance",
    }


def build_next_race_card(session: Session, user_id: uuid.UUID, today: date) -> dict[str, Any]:
    from backend.services.race_hero import build_hero

    hero = build_hero(session, user_id, today)
    race = hero.get("race")
    if race is None:
        return {"available": False}
    est = hero.get("estimate") or {}
    goal = hero.get("goal") or {}
    range_label = None
    if est.get("available") and est.get("range_low_sec") is not None and est.get("range_high_sec") is not None:

        def _short(sec: int) -> str:
            h, rem = divmod(int(sec), 3600)
            m, s = divmod(rem, 60)
            if h:
                return f"{h}:{m:02d}"
            return f"{m:02d}:{s:02d}"

        range_label = f"{_short(est['range_low_sec'])}–{_short(est['range_high_sec'])}"
    return {
        "available": True,
        "race": race,
        "goal_time_label": format_race_time(goal.get("time_sec")),
        "estimate_time_label": format_race_time(est.get("est_sec")) if est.get("available") else None,
        "range_label": range_label,
        "days_to_race": race.get("days_to_race"),
        "href": "/v2/performance",
    }


def build_coach_card(session: Session, user_id: uuid.UUID, today: date) -> dict[str, Any]:
    block = fetch_coach_block(session, user_id, today)
    return {
        "checkin": block.get("checkin"),
        "review_due": block.get("review_due"),
        "consult_endpoint": "/api/coach/consult",
        "paste_link": block.get("paste_link"),
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

    from backend.services.long_run_ladder import long_run_ladder_payload

    ladder = long_run_ladder_payload(session, user_id, today=today)

    return {
        "as_of": today.isoformat(),
        "greeting_name": name,
        "long_run_ladder": ladder,
        "hero": hero,
        "show_race_plan": show_race_plan,
        "race_plan": race_plan,
        "alerts": alerts,
        "sync_summary": {
            "strava": dot_state(providers.get("strava") or {}),
            "stryd": dot_state(providers.get("stryd") or {}),
        },
        "race_week": show_race_plan,
        "this_week": build_this_week(session, user_id, today, board),
        "next_race": build_next_race_card(session, user_id, today),
        "focus": build_focus_teaser(session, user_id, today),
        "recent_sessions": build_recent_sessions(session, user_id, today),
        "coach": build_coach_card(session, user_id, today),
    }