"""Daily coach message generation service (issue #1504 + daily SoT).

Generates a structured coaching message from specialist facts
(coach_facts.build_coach_facts) + LangGraph/plain LLM synthesizer, and
persists it per calendar date (``for_date``). ``for_week`` is denormalized.

Public API
----------
compose_deterministic_message(plan_state, projection_info, today) -> str
    Legacy 5-element text (kept for tests / fallback; Hermes uses get_coach_payload).

persist_daily_message / persist_weekly_message (alias)
get_latest_for_user / get_history_for_user / get_for_date
get_coach_payload_for_user — shared Home + Hermes shape
generate_for_user(user_id, db=None, today=None) -> dict
    facts → orch → persist nested snapshot {plan_state, facts, source, sections}.
"""

from __future__ import annotations

import math
import re as _re
from datetime import date, datetime, timezone
from typing import Any

from backend.utils.log import get_logger

_log = get_logger(__name__)

# Distance label map used in projection element
_DIST_LABEL: dict[str, str] = {
    "5k": "5k",
    "10k": "10k",
    "half": "HM",
    "marathon": "marathon",
}

# Approximate distance in km per race type (for projection fallback)
_DIST_KM: dict[str, float] = {
    "5k": 5.0,
    "10k": 10.0,
    "half": 21.0975,
    "marathon": 42.195,
}

# Representative target CTL per distance (mirrors coach_plan._TARGET_CTL)
_TARGET_CTL: dict[str, float] = {
    "5k": 50.0,
    "10k": 60.0,
    "half": 70.0,
    "marathon": 85.0,
}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _iso_week(d: date) -> str:
    """Return ISO week string 'YYYY-Www' for date d."""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _format_hms(seconds: int) -> str:
    """Format seconds as H:MM or H:MM:SS."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if s == 0:
        return f"{h}:{m:02d}"
    return f"{h}:{m:02d}:{s:02d}"


def _estimate_current_trend(
    current_ctl: float,
    race_distance: str,
    target_time_seconds: int,
) -> int:
    """Estimate current finish time from CTL ratio vs target CTL.

    Uses a square-root scaling so that a 10% CTL deficit → ~5% slower time.
    Returns target_time_seconds unchanged when data is insufficient.
    """
    target_ctl = _TARGET_CTL.get(race_distance, 70.0)
    if target_ctl <= 0 or current_ctl <= 0:
        return target_time_seconds
    ratio = target_ctl / current_ctl  # >1 means we're below target CTL → slower
    ratio = max(0.5, min(2.0, ratio))
    return int(round(target_time_seconds * (ratio ** 0.5)))


def _uncertainty_minutes(weeks_to_race: float) -> int:
    """Uncertainty band in minutes, growing with horizon (sqrt model)."""
    return max(1, int(round(0.7 * math.sqrt(max(0, weeks_to_race)))))


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ── Core composition ───────────────────────────────────────────────────────────

def compose_deterministic_message(
    plan_state: dict,
    projection_info: dict,
    today: date,
) -> str:
    """Compose the 5-element weekly coaching message from engine outputs.

    All numeric values are taken from plan_state and projection_info — no
    values are invented here.

    Parameters
    ----------
    plan_state:
        Output of coach_plan.build_plan_state().
    projection_info:
        Dict with keys: full_compliance_time_seconds (int), target_date (date),
        current_trend_time_seconds (int), uncertainty_minutes (int),
        distance_label (str).
    today:
        Reference date (used for phase-date display).

    Returns
    -------
    str — the composed weekly message (plain text, no markdown).
    """
    parts: list[str] = []

    # ── (a) Now directive ─────────────────────────────────────────────────────
    load = (plan_state.get("levers") or {}).get("load") or {}
    load_state = load.get("state", "unavailable")

    if load_state == "locked":
        reason = load.get("reason", "")
        unlock_date = load.get("unlock_date")
        if unlock_date and isinstance(unlock_date, date):
            unlock_str = unlock_date.strftime("%d %b")
        else:
            unlock_str = "soon"
        parts.append(
            f"Now: {reason}; ACWR converges ~{unlock_str} — "
            "CTL rises because you hold, not because you add."
        )
    elif load_state == "available":
        parts.append(
            "Now: Load lever available — safe to begin a progressive ramp this week."
        )
    else:
        parts.append("Now: Training load data unavailable — log workouts to enable guidance.")

    # ── (b) Sequenced next steps with dates ───────────────────────────────────
    timeline = plan_state.get("timeline") or []
    if timeline:
        step_lines: list[str] = []
        for phase in timeline:
            start = phase.get("start_date")
            directive = phase.get("directive", "")
            if isinstance(start, date):
                step_lines.append(f"  • {start.strftime('%-d %b')}: {directive}")
            else:
                step_lines.append(f"  • {directive}")
        parts.append("Next steps:\n" + "\n".join(step_lines))
    else:
        parts.append("Next steps: Set a race goal to unlock sequenced training phases.")

    # ── (c) Interaction constraint one-liner ──────────────────────────────────
    constraints = plan_state.get("constraints") or []
    if constraints:
        constraint_text = constraints[0]
        if not constraint_text.endswith("."):
            constraint_text += "."
        constraint_text = constraint_text[0].upper() + constraint_text[1:]
        parts.append(f"Constraint: {constraint_text}")
    else:
        parts.append("Constraint: No active interaction constraints this week.")

    # ── (d) Lever ranking sentence ────────────────────────────────────────────
    ranking = plan_state.get("lever_ranking") or {}
    rationale = ranking.get("rationale", "")
    if rationale:
        parts.append(f"Levers: {rationale}")
    else:
        parts.append("Levers: Insufficient data to rank levers.")

    # ── (e) Motivation projection ─────────────────────────────────────────────
    if projection_info:
        full_time_sec = projection_info.get("full_compliance_time_seconds", 0)
        trend_time_sec = projection_info.get("current_trend_time_seconds", 0)
        uncertainty = projection_info.get("uncertainty_minutes", 0)
        target_dt = projection_info.get("target_date")
        dist_label = projection_info.get("distance_label", "race")

        full_str = _format_hms(full_time_sec)
        trend_str = _format_hms(trend_time_sec)

        if isinstance(target_dt, date):
            target_month = target_dt.strftime("%b")
        else:
            target_month = "race day"

        parts.append(
            f"Projection: Full compliance → ~{full_str} {dist_label} by {target_month}; "
            f"currently trending ~{trend_str} ± {uncertainty} min."
        )
    else:
        parts.append("Projection: Set a race goal and log workouts to enable outcome projection.")

    return "\n\n".join(parts)


# ── LLM narrative layer ────────────────────────────────────────────────────────
#
# Restored after Priority 2 parked it (D4). The operator's rule moved from
# "no LLM in the app" to "minimal LLM" — see CLAUDE.md — and the daily coach
# message is one of the two surfaces judged to earn a provider call. The other
# is Ask-AI single-session.
#
# The deterministic message remains the source of truth for every NUMBER. The
# LLM only rewrites the prose around them, and any failure — disabled provider,
# network error, malformed response, a number that changed — falls back to the
# deterministic text silently. The athlete always gets a message.

_NUMERAL_RE = _re.compile(r"\d+(?:[.:]\d+)*")


def _numbers_preserved(original: str, rephrased: str) -> bool:
    """True iff the rephrase kept every numeral from the deterministic text.

    The prompt says to preserve numbers verbatim; this is what makes that a
    guarantee rather than a request. A rephrase that drops a TSS figure or
    invents a finish time is rejected outright — the whole reason the coach
    message is trusted is that its numbers come from the engines, and a warm
    sentence is not worth a wrong one.

    Multiset comparison, not set: "315 TSS across 5 sessions" losing one of two
    identical figures should still fail.
    """
    return sorted(_NUMERAL_RE.findall(original)) == sorted(_NUMERAL_RE.findall(rephrased))


def _call_llm_narrative(deterministic_text: str, plan_state: dict) -> str | None:
    """Ask the LLM to add warmth to the deterministic message.

    All numbers must be preserved verbatim. Returns None on any failure
    (disabled LLM, API error, bad response, numeral drift). Never raises.
    """
    from backend.services.llm import complete_structured, llm_enabled

    if not llm_enabled():
        return None

    system = (
        "You are a supportive performance coach writing a weekly update for an athlete. "
        "Rephrase the structured message below to sound encouraging and human, "
        "but you MUST preserve ALL numeric values, dates, and time estimates exactly as given. "
        "Do not invent, change, or omit any number, date, or time. "
        "Keep all five sections (Now, Next steps, Constraint, Levers, Projection) in order. "
        "Plain text only — no markdown, no bullet symbols beyond what is already present."
    )
    user = f"Rephrase this weekly coaching update:\n\n{deterministic_text}"

    schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
        },
        "required": ["message"],
        "additionalProperties": False,
    }

    result = complete_structured(
        system=system,
        user=user,
        schema_name="weekly_coach_message",
        json_schema=schema,
        model_tier="fast",
        max_tokens=800,
    )
    if result is None:
        return None
    text = result.get("message", "")
    if not text:
        return None
    if not _numbers_preserved(deterministic_text, text):
        _log.warning(
            "LLM narrative changed a number — discarding the rephrase",
            extra={"surface": "weekly_coach_message"},
        )
        return None
    return text


def _build_message(
    plan_state: dict,
    projection_info: dict,
    today: date,
) -> str:
    """Build the weekly message — tries LLM, falls back to deterministic."""
    deterministic = compose_deterministic_message(plan_state, projection_info, today)
    try:
        llm_result = _call_llm_narrative(deterministic, plan_state)
    except Exception as exc:
        _log.warning("LLM narrative failed, using deterministic fallback", extra={"error": str(exc)})
        llm_result = None

    return llm_result if llm_result else deterministic


# ── Persistence ────────────────────────────────────────────────────────────────

def _serialize_plan_state(plan_state: dict) -> dict:
    """Convert date objects in plan_state to ISO strings for JSONB storage."""
    import json

    def _convert(obj: Any) -> Any:
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(i) for i in obj]
        return obj

    return _convert(plan_state)


def persist_daily_message(
    user_id,
    for_date: date,
    text: str,
    plan_state_snapshot: dict | None,
    db,
    for_week: str | None = None,
) -> "WeeklyCoachMessage":
    """Upsert a daily message record on (user_id, for_date)."""
    from backend.models import WeeklyCoachMessage

    week = for_week or _iso_week(for_date)
    snapshot = _serialize_plan_state(plan_state_snapshot) if plan_state_snapshot else None
    now = datetime.now(tz=timezone.utc)

    existing = (
        db.query(WeeklyCoachMessage)
        .filter_by(user_id=user_id, for_date=for_date)
        .first()
    )
    if existing is not None:
        existing.text = text
        existing.for_week = week
        existing.generated_at = now
        existing.plan_state_snapshot = snapshot
        db.flush()
        return existing

    record = WeeklyCoachMessage(
        user_id=user_id,
        for_week=week,
        for_date=for_date,
        text=text,
        generated_at=now,
        plan_state_snapshot=snapshot,
    )
    db.add(record)
    db.flush()
    return record


def persist_weekly_message(
    user_id,
    for_week: str,
    text: str,
    plan_state_snapshot: dict | None,
    db,
    for_date: date | None = None,
) -> "WeeklyCoachMessage":
    """Compat wrapper — prefers for_date when provided, else derives from week Monday."""
    if for_date is None:
        # ISO week → Monday of that week (synthetic keys fall back to a stable date)
        year_s, week_s = for_week.split("-W")
        try:
            for_date = date.fromisocalendar(int(year_s), int(week_s), 1)
        except ValueError:
            from datetime import timedelta
            for_date = date(int(year_s), 1, 1) + timedelta(days=max(0, int(week_s) - 1) * 7)
    return persist_daily_message(
        user_id=user_id,
        for_date=for_date,
        text=text,
        plan_state_snapshot=plan_state_snapshot,
        db=db,
        for_week=for_week,
    )


def _message_to_dict(record: "WeeklyCoachMessage") -> dict:
    for_date = getattr(record, "for_date", None)
    return {
        "id": str(record.id) if record.id else None,
        "for_week": record.for_week,
        "for_date": for_date.isoformat() if for_date else None,
        "generated_at": record.generated_at.isoformat() if record.generated_at else None,
        "text": record.text,
        "plan_state_snapshot": record.plan_state_snapshot,
    }


def get_for_date(user_id, for_date: date, db) -> dict | None:
    """Return the message for a specific date, or None."""
    from backend.models import WeeklyCoachMessage

    record = (
        db.query(WeeklyCoachMessage)
        .filter_by(user_id=user_id, for_date=for_date)
        .first()
    )
    return _message_to_dict(record) if record is not None else None


def get_latest_for_user(user_id, db, as_of: date | None = None) -> dict | None:
    """Return the newest message with for_date ≤ as_of (default: any latest)."""
    from backend.models import WeeklyCoachMessage

    q = db.query(WeeklyCoachMessage).filter_by(user_id=user_id)
    if as_of is not None:
        q = q.filter(WeeklyCoachMessage.for_date <= as_of)
        record = q.order_by(WeeklyCoachMessage.for_date.desc()).first()
    else:
        record = q.order_by(WeeklyCoachMessage.generated_at.desc()).first()
    return _message_to_dict(record) if record is not None else None


def get_history_for_user(user_id, limit: int, db) -> list[dict]:
    """Return up to `limit` messages for user_id, newest-first."""
    from backend.models import WeeklyCoachMessage

    rows = (
        db.query(WeeklyCoachMessage)
        .filter_by(user_id=user_id)
        .order_by(WeeklyCoachMessage.for_date.desc(), WeeklyCoachMessage.generated_at.desc())
        .limit(limit)
        .all()
    )
    return [_message_to_dict(r) for r in rows]


def get_coach_payload_for_user(
    user_id,
    today: date | None = None,
    db=None,
) -> dict | None:
    """Shared Home + Hermes coach payload (sections + nudge + text).

    Prefer the persisted daily row for ``today`` (or latest ≤ today). If missing,
    build facts + deterministic narrative offline — never the legacy
    compose_deterministic_message Hermes path.
    """
    _own_session = db is None
    if _own_session:
        from sqlalchemy.orm import Session as _Session
        from backend.db import engine
        db = _Session(engine)

    today = today or date.today()
    try:
        msg = get_latest_for_user(user_id, db, as_of=today)
        if msg:
            snap = msg.get("plan_state_snapshot") or {}
            sections = (snap.get("sections") or {}) if isinstance(snap, dict) else {}
            facts = (snap.get("facts") or {}) if isinstance(snap, dict) else {}
            nudge = facts.get("nudge") if isinstance(facts, dict) else None
            chosen = facts.get("chosen_preset") if isinstance(facts, dict) else None
            if not isinstance(nudge, dict):
                nudge = None
            if sections or msg.get("text"):
                brief = snap.get("brief") if isinstance(snap, dict) else None
                if not brief:
                    try:
                        from backend.models import DailyBrief
                        from datetime import date as _date

                        bd = msg.get("for_date")
                        if isinstance(bd, str):
                            bd = _date.fromisoformat(bd[:10])
                        row = (
                            db.query(DailyBrief)
                            .filter(
                                DailyBrief.user_id == user_id,
                                DailyBrief.brief_date == (bd or today),
                            )
                            .first()
                        )
                        if row and isinstance(row.payload, dict):
                            brief = row.payload
                    except Exception:
                        brief = None
                return {
                    "as_of": msg.get("for_date") or today.isoformat(),
                    "source": (snap.get("source") if isinstance(snap, dict) else None) or "persisted",
                    "sections": {
                        "now": sections.get("now") or "",
                        "focus": sections.get("focus") or "",
                        "dream": sections.get("dream") or "",
                        "reflection": sections.get("reflection") or "",
                    },
                    "nudge": nudge,
                    "chosen_preset": chosen,
                    "text": msg.get("text") or "",
                    "brief": brief,
                    "message": msg,
                }

        # Offline fallback: facts + brief v4 → legacy Markdown for Hermes
        from backend.services.coach_facts import build_coach_facts
        from backend.services.coach_brief import compose_coach_brief, brief_to_text, get_or_build_brief
        from backend.services.coach_sections import parse_sections_from_text

        # Prefer stored v4 brief when present
        stored = get_or_build_brief(db, user_id, today, force=False)
        if stored:
            text = brief_to_text(stored)
            try:
                sections = parse_sections_from_text(text)
            except Exception:
                sections = {"now": text, "focus": "", "dream": "", "reflection": ""}
            facts = build_coach_facts(user_id, today=today, db=db) or {}
            return {
                "as_of": today.isoformat(),
                "source": stored.get("source") or "fallback",
                "sections": sections,
                "nudge": facts.get("nudge"),
                "chosen_preset": facts.get("chosen_preset"),
                "text": text,
                "brief": stored,
                "message": None,
            }

        facts = build_coach_facts(user_id, today=today, db=db)
        if facts is None:
            return None
        brief = compose_coach_brief(facts)
        text = brief_to_text(brief)
        try:
            sections = parse_sections_from_text(text)
        except Exception:
            sections = {"now": text, "focus": "", "dream": "", "reflection": ""}
        return {
            "as_of": today.isoformat(),
            "source": "fallback",
            "sections": sections,
            "nudge": facts.get("nudge"),
            "chosen_preset": facts.get("chosen_preset"),
            "text": text,
            "brief": brief,
            "message": None,
        }
    finally:
        if _own_session:
            db.close()


# ── Orchestration ──────────────────────────────────────────────────────────────

def _distance_label_from_km(km: float | None) -> str:
    if km is None:
        return "half"
    if km >= 40:
        return "marathon"
    if km >= 20:
        return "half"
    if km >= 9:
        return "10k"
    return "5k"


def _goal_from_a_race(user_id, db) -> Any | None:
    """Build a PerformanceGoal-shaped object from the user's A-race (Plan SoT)."""
    from types import SimpleNamespace

    from backend.models import Race

    a_race = (
        db.query(Race)
        .filter(
            Race.user_id == user_id,
            Race.priority == "A",
            Race.status.in_(("planned", "active")),
        )
        .order_by(Race.race_date.asc().nullslast())
        .first()
    )
    if a_race is None:
        return None
    dist_km = float(a_race.distance_km) if a_race.distance_km is not None else None
    target = int(a_race.goal_time_seconds) if a_race.goal_time_seconds else 0
    return SimpleNamespace(
        race_distance=_distance_label_from_km(dist_km),
        target_time=target,
        race_date=a_race.race_date,
        name=a_race.name,
        distance_km=dist_km,
        source="a_race",
        id=getattr(a_race, "id", None),
    )


def _load_inputs_for_user(user_id, db, today: date) -> tuple[Any, Any, Any, Any]:
    """Load (goal, snapshot, weight_status, log_consistency) from DB.

    Goal source of truth for coach: **A-race** on the Plan tab. Falls back to
    an active ``PerformanceGoal`` only when no A-race is set.
    Returns (None, None, None, None) when neither exists.
    """
    from datetime import timedelta

    from sqlalchemy import desc

    from backend.models import TrainingLoadSnapshot, WeightEntry, PerformanceGoal

    goal = _goal_from_a_race(user_id, db)
    if goal is None:
        goal = (
            db.query(PerformanceGoal)
            .filter_by(user_id=user_id, active=True)
            .first()
        )
    if goal is None:
        return None, None, None, None

    snapshot = (
        db.query(TrainingLoadSnapshot)
        .filter(
            TrainingLoadSnapshot.user_id == user_id,
            TrainingLoadSnapshot.snapshot_date <= today,
        )
        .order_by(desc(TrainingLoadSnapshot.snapshot_date))
        .first()
    )

    # Weight status: gap between current and goal weight
    window_start = today - timedelta(days=14)
    weight_rows = (
        db.query(WeightEntry)
        .filter(
            WeightEntry.user_id == user_id,
            WeightEntry.entry_date >= window_start,
            WeightEntry.entry_date <= today,
        )
        .all()
    )
    logged_days = len({r.entry_date for r in weight_rows})
    log_consistency = {"logged_days": logged_days, "total_days": 14}

    # Simple weight status: try weight_plan service, fall back to None-safe dict
    try:
        from backend.services.weight_plan import compute_weight_status
        weight_status_full = compute_weight_status(db, user_id, today)
        current_kg = weight_status_full.get("current_kg")
        target_kg = weight_status_full.get("target_kg")
        gap_kg = (
            round(current_kg - target_kg, 1)
            if current_kg is not None and target_kg is not None
            else 0.0
        )
        weight_status = {
            "current_kg": current_kg,
            "goal_kg": target_kg,
            "gap_kg": max(0.0, gap_kg),
        }
    except Exception:
        weight_status = {"current_kg": None, "goal_kg": None, "gap_kg": 0.0}

    return goal, snapshot, weight_status, log_consistency


def _build_projection_info(goal: Any, snapshot: Any, today: date) -> dict:
    """Derive projection_info dict from goal and latest training load snapshot."""
    if goal is None:
        return {}

    race_distance = getattr(goal, "race_distance", None) or "half"
    target_time_sec = int(getattr(goal, "target_time", 0) or 0)
    race_date = getattr(goal, "race_date", None)
    if isinstance(race_date, str):
        from datetime import date as _date
        race_date = _date.fromisoformat(race_date)

    current_ctl = float(getattr(snapshot, "ctl", 0) or 0) if snapshot else 0.0
    trend_time_sec = _estimate_current_trend(current_ctl, race_distance, target_time_sec)

    weeks_to_race = 0.0
    if race_date:
        weeks_to_race = max(0.0, (race_date - today).days / 7.0)

    return {
        "full_compliance_time_seconds": target_time_sec,
        "target_date": race_date,
        "current_trend_time_seconds": trend_time_sec,
        "uncertainty_minutes": _uncertainty_minutes(weeks_to_race),
        "distance_label": _DIST_LABEL.get(race_distance, race_distance),
    }


def generate_for_user(user_id, db=None, today: date | None = None) -> dict | None:
    """Generate and persist the daily coaching message for user_id.

    Pipeline: build_coach_facts → coach narrative orch (LangGraph / plain) →
    persist Markdown text. Nested snapshot stores plan_state, facts, source,
    and sections so Home / Hermes can render without re-parsing.

    Returns the persisted message as a dict, or None when no active goal exists.
    """
    _own_session = db is None
    if _own_session:
        from sqlalchemy.orm import Session as _Session
        from backend.db import engine
        db = _Session(engine)

    today = today or date.today()

    try:
        from backend.services.coach_brief import build_brief_deterministic
        from backend.services.coach_facts import build_coach_facts

        facts = build_coach_facts(user_id, today=today, db=db)
        if facts is None:
            _log.info(
                "No active goal for user — skipping daily coach message",
                extra={"user_id": str(user_id)},
            )
            return None

        result = build_brief_deterministic(
            facts,
            db=db,
            user_id=user_id,
            brief_date=today,
        )
        text = result.get("text") or ""
        for_week = _iso_week(today)

        # Nest richer payload inside the free-form JSON snapshot column.
        plan_state = facts.get("plan_state") or {}
        snapshot = {
            "plan_state": plan_state,
            "facts": {k: v for k, v in facts.items() if k != "plan_state"},
            "source": result.get("source") or "fallback",
            "sections": result.get("sections") or {},
            "brief": result.get("brief"),
            "orch": result.get("orch"),
            "attempts": result.get("attempts"),
        }

        record = persist_daily_message(
            user_id=user_id,
            for_date=today,
            for_week=for_week,
            text=text,
            plan_state_snapshot=snapshot,
            db=db,
        )
        db.commit()

        return _message_to_dict(record)

    except Exception as exc:
        _log.error("Failed to generate daily coach message", extra={"user_id": str(user_id), "error": str(exc)})
        if _own_session:
            try:
                db.rollback()
            except Exception:
                pass
        raise
    finally:
        if _own_session:
            db.close()
