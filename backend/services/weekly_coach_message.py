"""Weekly coach message generation service (issue #1504).

Generates a structured weekly coaching message from engine outputs
(coach_plan.build_plan_state() + projection) and persists it per ISO week.

Public API
----------
compose_deterministic_message(plan_state, projection_info, today) -> str
    Pure function.  Returns the 5-element text message from engine data.
    No LLM calls; no DB access.

_build_message(plan_state, projection_info, today) -> str
    Tries the LLM narrative layer first; falls back to deterministic silently.

_call_llm_narrative(deterministic_text, plan_state) -> str | None
    Calls the LLM to rephrase with warmth.  Returns None on any failure.

persist_weekly_message(user_id, for_week, text, plan_state_snapshot, db) -> WeeklyCoachMessage
    Upserts a record — replaces the existing row for the same (user, week).

get_latest_for_user(user_id, db) -> dict | None
    Returns the most-recently-generated message for the user.

get_history_for_user(user_id, limit, db) -> list[dict]
    Returns up to `limit` messages newest-first.

generate_for_user(user_id, db=None, today=None) -> dict
    Orchestrates: load data → build_plan_state → project → compose → persist.
    Returns the persisted message as a dict.

_iso_week(d) -> str
    Returns 'YYYY-Www' ISO week string for a given date.
"""

from __future__ import annotations

import math
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

def _call_llm_narrative(deterministic_text: str, plan_state: dict) -> str | None:
    """Ask the LLM to add warmth to the deterministic message.

    All numbers must be preserved verbatim.  Returns None on any failure
    (disabled LLM, API error, bad response).  Never raises.
    """
    from backend.services.llm import llm_enabled, complete_structured

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
    return text if text else None


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


def persist_weekly_message(
    user_id,
    for_week: str,
    text: str,
    plan_state_snapshot: dict | None,
    db,
) -> "WeeklyCoachMessage":
    """Upsert a weekly message record.

    If a record already exists for (user_id, for_week) it is updated in place
    (generated_at refreshed, text replaced) — enforcing idempotency per ISO week.
    """
    from backend.models import WeeklyCoachMessage

    snapshot = _serialize_plan_state(plan_state_snapshot) if plan_state_snapshot else None
    now = datetime.now(tz=timezone.utc)

    existing = (
        db.query(WeeklyCoachMessage)
        .filter_by(user_id=user_id, for_week=for_week)
        .first()
    )
    if existing is not None:
        existing.text = text
        existing.generated_at = now
        existing.plan_state_snapshot = snapshot
        db.flush()
        return existing

    record = WeeklyCoachMessage(
        user_id=user_id,
        for_week=for_week,
        text=text,
        generated_at=now,
        plan_state_snapshot=snapshot,
    )
    db.add(record)
    db.flush()
    return record


def _message_to_dict(record: "WeeklyCoachMessage") -> dict:
    return {
        "id": str(record.id) if record.id else None,
        "for_week": record.for_week,
        "generated_at": record.generated_at.isoformat() if record.generated_at else None,
        "text": record.text,
        "plan_state_snapshot": record.plan_state_snapshot,
    }


def get_latest_for_user(user_id, db) -> dict | None:
    """Return the most recently generated message for user_id, or None."""
    from backend.models import WeeklyCoachMessage

    record = (
        db.query(WeeklyCoachMessage)
        .filter_by(user_id=user_id)
        .order_by(WeeklyCoachMessage.generated_at.desc())
        .first()
    )
    return _message_to_dict(record) if record is not None else None


def get_history_for_user(user_id, limit: int, db) -> list[dict]:
    """Return up to `limit` messages for user_id, newest-first."""
    from backend.models import WeeklyCoachMessage

    rows = (
        db.query(WeeklyCoachMessage)
        .filter_by(user_id=user_id)
        .order_by(WeeklyCoachMessage.generated_at.desc())
        .limit(limit)
        .all()
    )
    return [_message_to_dict(r) for r in rows]


# ── Orchestration ──────────────────────────────────────────────────────────────

def _load_inputs_for_user(user_id, db, today: date) -> tuple[Any, Any, Any, Any]:
    """Load (goal, snapshot, weight_status, log_consistency) from DB.

    Returns (None, None, None, None) when no active goal exists.
    """
    from datetime import timedelta

    from sqlalchemy import desc

    from backend.models import PerformanceGoal, TrainingLoadSnapshot, WeightEntry

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
    """Generate and persist the weekly coaching message for user_id.

    Returns the persisted message as a dict, or None when no active goal exists.
    """
    from backend.services.coach_plan import build_plan_state

    _own_session = db is None
    if _own_session:
        from sqlalchemy.orm import Session as _Session
        from backend.db import engine
        db = _Session(engine)

    today = today or date.today()

    try:
        goal, snapshot, weight_status, log_consistency = _load_inputs_for_user(
            user_id, db, today
        )
        if goal is None:
            _log.info("No active goal for user — skipping weekly message", extra={"user_id": str(user_id)})
            return None

        # Derive acwr_state from snapshot
        acwr_val = float(getattr(snapshot, "acwr", 0) or 0) if snapshot else 0.0
        acwr_state = "high_risk" if acwr_val > 1.30 else "productive"

        plan_state = build_plan_state(
            goal=goal,
            training_load_snapshot=snapshot,
            acwr_state=acwr_state,
            guardrail_state="ok",
            weight_status=weight_status,
            log_consistency=log_consistency,
            _today=today,
        )

        projection_info = _build_projection_info(goal, snapshot, today)
        text = _build_message(plan_state, projection_info, today)
        for_week = _iso_week(today)

        record = persist_weekly_message(
            user_id=user_id,
            for_week=for_week,
            text=text,
            plan_state_snapshot=plan_state,
            db=db,
        )
        db.commit()

        return _message_to_dict(record)

    except Exception as exc:
        _log.error("Failed to generate weekly message", extra={"user_id": str(user_id), "error": str(exc)})
        if _own_session:
            try:
                db.rollback()
            except Exception:
                pass
        raise
    finally:
        if _own_session:
            db.close()
