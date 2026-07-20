"""Plan draft generation + storage (pipeline v2 stage assemble → store)."""
from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from backend.services.plan_prefs_accessor import get_plan_prefs
from backend.services.plan_skeleton import assemble_week, build_skeleton
from backend.services.plan_slot import (
    build_week_ctx,
    fill_week_slots,
    generate_slot_content,
    stamp_session,
)
from backend.services.plan_slot_cache import (
    SURFACE,
    content_ctx_from_week,
    slot_cache_key,
)
from backend.services.plan_suggestions import assemble_facts, build_signature, _load_history_rows
from backend.utils.log import get_logger

_log = get_logger(__name__)

PLAN_PIPELINE = os.getenv("PLAN_PIPELINE", "legacy").strip().lower()  # legacy | skeleton_v2
_MAX_CONCURRENT_SLOTS = 3
_SLOT_TIMEOUT_SEC = 120


def pipeline_enabled() -> bool:
    return PLAN_PIPELINE in ("skeleton_v2", "v2", "shadow")


def is_shadow() -> bool:
    return PLAN_PIPELINE == "shadow"


def facts_signature_for_draft(facts: dict) -> str:
    """Signature over the facts that affect skeleton + content_ctx (not raw CTL alone)."""
    slim = {
        "week_start": facts.get("week_start"),
        "preferred_rest_days": facts.get("preferred_rest_days"),
        "strength_emphasis": facts.get("strength_emphasis"),
        "notes": facts.get("notes"),
        "prefs_version": facts.get("prefs_version"),
        "target_tss": facts.get("target_tss"),
        "phase": facts.get("phase"),
        "logged_tss_so_far": facts.get("logged_tss_so_far"),
        "trailing_28d_weekly_avg_tss": facts.get("trailing_28d_weekly_avg_tss"),
        "allowed_offsets": facts.get("allowed_offsets"),
        "days_to_next_race": facts.get("days_to_next_race"),
        "recent_exercise_names": facts.get("recent_exercise_names"),
    }
    return hashlib.sha256(
        json.dumps(slim, sort_keys=True, default=str).encode()
    ).hexdigest()


def _llm_call_for_transport() -> Callable[[str, str], dict | None]:
    """Resolve LLM_TRANSPORT: claude_cli | groq_api."""
    transport = os.getenv("LLM_TRANSPORT", "").strip().lower()
    if not transport:
        # Default: worker → claude_cli when available, else groq
        try:
            from backend.services.coach_claude_cli import claude_cli_enabled
            transport = "claude_cli" if claude_cli_enabled() else "groq_api"
        except Exception:
            transport = "groq_api"

    def _call(system: str, user: str) -> dict | None:
        if transport in ("claude_cli", "claude", "cli"):
            return _call_claude_cli(system, user)
        return _call_groq(system, user)

    return _call


def _call_groq(system: str, user: str) -> dict | None:
    import backend.services.llm as llm_svc

    schema = {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "maxLength": 140},
            "notes": {"type": ["string", "null"]},
            "blocks": {"type": ["array", "null"]},
            "exercises": {"type": ["array", "null"]},
        },
        "required": ["intent"],
        "additionalProperties": True,
    }
    return llm_svc.complete_structured(
        system=system,
        user=user,
        json_schema=schema,
        schema_name="plan_slot_content",
        model_tier="deep",
    )


def _call_claude_cli(system: str, user: str) -> dict | None:
    """Text-only claude -p --output-format json (no MCP allowlist)."""
    import shutil
    import subprocess

    bin_name = os.environ.get("COACH_CLAUDE_BIN") or "claude"
    if not shutil.which(bin_name):
        return None
    prompt = f"{system}\n\n{user}\n\nReturn ONLY the JSON object."
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    try:
        proc = subprocess.run(
            [bin_name, "-p", "--output-format", "json"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=_SLOT_TIMEOUT_SEC,
            env=env,
        )
    except Exception:
        _log.warning("claude_cli slot call failed", exc_info=True)
        return None
    if proc.returncode != 0:
        return None
    try:
        raw = json.loads(proc.stdout)
    except Exception:
        return None
    # claude -p json may wrap result
    if isinstance(raw, dict) and "result" in raw and isinstance(raw["result"], str):
        try:
            return json.loads(raw["result"])
        except Exception:
            return None
    if isinstance(raw, dict):
        return raw
    return None


def _cached_or_generate(
    db: Session,
    user_id,
    week_ctx: dict,
    slot: dict,
    llm_call,
    current: dict | None,
) -> dict:
    if current and current.get("source") == "user":
        return {**current, "source": "user"}

    ctx = content_ctx_from_week(week_ctx)
    key = slot_cache_key(pins=slot, content_ctx=ctx)

    from backend.models import LlmGeneration

    cached = (
        db.query(LlmGeneration)
        .filter_by(user_id=user_id, surface=SURFACE, input_signature=key)
        .first()
    )
    if cached and isinstance(cached.payload, dict):
        return {**cached.payload, "source": cached.payload.get("source") or "llm"}

    content = generate_slot_content(week_ctx, slot, current=current, llm_call=llm_call)
    if content.get("source") == "llm":
        try:
            row = LlmGeneration(
                user_id=user_id,
                surface=SURFACE,
                input_signature=key,
                payload=content,
                model=os.getenv("LLM_TRANSPORT", "groq_api"),
            )
            db.add(row)
            db.flush()
        except Exception:
            _log.debug("slot cache write skipped", exc_info=True)
    return content


def generate_draft_payload(
    db: Session,
    user_id,
    week_start: date,
    *,
    refresh_untouched_only: bool = False,
    previous_payload: dict | None = None,
) -> dict:
    """Build skeleton → fill slots (≤3 concurrent) → assemble."""
    prefs = get_plan_prefs(db, user_id)
    facts = assemble_facts(
        str(user_id),
        db,
        week_start=week_start,
        preferred_rest_days=prefs["preferred_rest_days"],
        strength_emphasis=prefs["strength_emphasis"],
        notes=prefs["notes"],
    )
    history = _load_history_rows(str(user_id), week_start, db=db)

    occupied = set()
    for e in facts.get("existing_week") or []:
        if e.get("has_workout") or e.get("has_planned"):
            occupied.add(int(e["day_offset"]))

    load_plan_week = None
    if facts.get("target_tss") is not None:
        load_plan_week = {
            "target_tss": facts["target_tss"],
            "phase": facts.get("phase"),
            "ceiling": facts.get("acwr_ceiling"),
        }

    sk = build_skeleton(
        week_start=week_start,
        history=history,
        preferred_rest_days=prefs["preferred_rest_days"],
        strength_emphasis=prefs["strength_emphasis"],
        trailing_28d_weekly_avg_tss=float(facts.get("trailing_28d_weekly_avg_tss") or 0),
        logged_tss_so_far=float(facts.get("logged_tss_so_far") or 0),
        allowed_offsets=facts.get("allowed_offsets"),
        load_plan_week=load_plan_week,
        race_anchored_target=facts.get("target_tss"),
        existing_occupied=occupied,
    )

    week_ctx = build_week_ctx(
        facts=facts,
        skeleton_slots=sk["slots"],
        strength_emphasis=prefs["strength_emphasis"],
        notes=prefs["notes"],
    )
    llm_call = _llm_call_for_transport()

    prev_by_day = {}
    if previous_payload:
        for s in (previous_payload.get("sessions") or previous_payload.get("slots") or []):
            if isinstance(s, dict) and s.get("day_offset") is not None:
                prev_by_day[int(s["day_offset"])] = s

    contents: list[dict | None] = [None] * 7
    to_fill: list[tuple[int, dict]] = []
    for slot in sk["slots"]:
        d = int(slot["day_offset"])
        prev = prev_by_day.get(d)
        if refresh_untouched_only and prev and prev.get("source") == "user":
            contents[d] = {
                "intent": prev.get("intent"),
                "notes": prev.get("notes"),
                "blocks": prev.get("blocks"),
                "exercises": prev.get("exercises"),
                "source": "user",
            }
            continue
        to_fill.append((d, slot))

    # ≤3 concurrent
    def _one(item):
        d, slot = item
        return d, _cached_or_generate(db, user_id, week_ctx, slot, llm_call, None)

    with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_SLOTS) as pool:
        futs = [pool.submit(_one, item) for item in to_fill]
        for fut in as_completed(futs):
            d, content = fut.result()
            contents[d] = content

    # Ensure order
    ordered_contents = [contents[i] or {"intent": "Rest", "source": "template"} for i in range(7)]
    assembled = assemble_week(sk["slots"], ordered_contents, facts=facts)

    return {
        "week_start": week_start.isoformat(),
        "budget": sk["budget"],
        "slots": sk["slots"],
        "sessions": assembled["sessions"],
        "sanity_errors": assembled.get("sanity_errors") or [],
        "facts_signature": facts_signature_for_draft(facts),
    }


def upsert_draft(db: Session, user_id, week_start: date, payload: dict, *, status: str = "fresh"):
    from backend.models import PlanDraft

    row = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
        .first()
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = PlanDraft(
            user_id=user_id,
            week_start=week_start,
            payload=payload,
            facts_signature=payload.get("facts_signature") or "",
            status=status,
        )
        db.add(row)
    else:
        # If existing has user edits and we're regenerating → outdated path handled by caller
        row.payload = payload
        row.facts_signature = payload.get("facts_signature") or row.facts_signature
        row.status = status
        row.updated_at = now
    db.flush()
    return row


def get_draft(db: Session, user_id, week_start: date) -> dict | None:
    from backend.models import PlanDraft

    row = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
        .first()
    )
    if row is None:
        return None
    return {
        "id": str(row.id),
        "week_start": row.week_start.isoformat(),
        "status": row.status,
        "facts_signature": row.facts_signature,
        "payload": row.payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def draft_has_user_edits(payload: dict | None) -> bool:
    if not payload:
        return False
    for s in payload.get("sessions") or payload.get("slots") or []:
        if isinstance(s, dict) and s.get("source") == "user":
            return True
    return False


def enqueue_plan_draft(user_id, week_start: date | None = None, *, enqueued_by: str = "web") -> str | None:
    """Debounced enqueue: skip if pending plan_draft for user exists."""
    from backend.services import job_queue as jq
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    ws = week_start or (today - timedelta(days=today.weekday()))
    dedupe = f"plan_draft:{user_id}:{ws.isoformat()}"
    return jq.enqueue(
        "plan_draft",
        {"user_id": str(user_id), "week_start": ws.isoformat()},
        priority=5,
        enqueued_by=enqueued_by,
        dedupe_key=dedupe,
    )


def run_plan_draft_job(payload: dict) -> dict:
    """Worker entry: recompute signature; no-op if cached draft matches."""
    from backend.db import engine
    from backend.models import PlanDraft
    from uuid import UUID

    user_id = UUID(str(payload["user_id"]))
    week_start = date.fromisoformat(payload["week_start"])

    with Session(engine) as db:
        prefs = get_plan_prefs(db, user_id)
        facts = assemble_facts(
            str(user_id), db, week_start=week_start,
            preferred_rest_days=prefs["preferred_rest_days"],
            strength_emphasis=prefs["strength_emphasis"],
            notes=prefs["notes"],
        )
        sig = facts_signature_for_draft(facts)
        existing = (
            db.query(PlanDraft)
            .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
            .first()
        )
        if existing and existing.facts_signature == sig and existing.status == "fresh":
            _log.info("plan_draft no-op — signature match user=%s week=%s", user_id, week_start)
            return {"status": "noop", "reason": "signature_match"}

        refresh_only = bool(existing and draft_has_user_edits(existing.payload))
        if refresh_only and existing:
            existing.status = "outdated"
            db.flush()

        draft_payload = generate_draft_payload(
            db, user_id, week_start,
            refresh_untouched_only=refresh_only,
            previous_payload=(existing.payload if existing else None),
        )
        # New/regenerated draft needs a morning Hermes nudge (not at job time).
        draft_payload["notify_pending"] = True
        draft_payload.pop("notified_at", None)
        status = "fresh"
        upsert_draft(db, user_id, week_start, draft_payload, status=status)
        db.commit()
        return {"status": "ok", "facts_signature": draft_payload["facts_signature"]}


_VALID_SESSION_TYPES = frozenset({"run", "strength", "plyo", "stretch", "rest"})


def pipeline_status() -> dict:
    return {
        "mode": PLAN_PIPELINE or "legacy",
        "enabled": pipeline_enabled(),
        "shadow": is_shadow(),
        # UI may show drafts in shadow only with ?draft=1 (client-enforced).
        "ui_default": PLAN_PIPELINE in ("skeleton_v2", "v2"),
    }


def _session_to_planned_body(week_start: date, session: dict) -> dict | None:
    """Map a draft session → PlannedSession create body, or None to skip."""
    wt = (session.get("workout_type") or "").strip().lower()
    if wt not in _VALID_SESSION_TYPES:
        return None
    if wt == "rest":
        return None  # rest days stay empty on the week grid
    offset = int(session.get("day_offset", -1))
    if offset < 0 or offset > 6:
        return None
    planned_date = week_start + timedelta(days=offset)
    structure = None
    if session.get("exercises"):
        structure = {"exercises": session["exercises"]}
    elif session.get("blocks"):
        structure = {"blocks": session["blocks"]}
    notes = session.get("notes")
    if not notes and (session.get("target_tss") or session.get("duration_minutes")):
        bits = []
        if session.get("target_tss"):
            bits.append(f"Target TSS: {session['target_tss']}")
        if session.get("duration_minutes"):
            bits.append(f"Duration: {session['duration_minutes']} min")
        notes = ". ".join(bits)
    return {
        "planned_date": planned_date.isoformat(),
        "session_type": wt,
        "name": (str(session.get("intent") or "")[:80] or None),
        "structure": structure,
        "notes": notes,
    }


def apply_draft(db: Session, user_id, week_start: date, *, today: date | None = None) -> dict:
    """Create planned sessions for open/future draft days; mark draft applied."""
    from backend.models import PlanDraft, PlannedSession

    today = today or date.today()
    row = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
        .first()
    )
    if row is None:
        return {"ok": False, "error": "no_draft", "created": []}
    if row.status == "applied":
        return {"ok": True, "already_applied": True, "created": [], "draft_id": str(row.id)}

    payload = row.payload or {}
    sessions = payload.get("sessions") or []
    created_ids: list[str] = []
    skipped_past = 0

    for sess in sessions:
        if not isinstance(sess, dict):
            continue
        body = _session_to_planned_body(week_start, sess)
        if body is None:
            continue
        pdate = date.fromisoformat(body["planned_date"])
        if pdate < today:
            skipped_past += 1
            continue
        # Skip days that already have a planned session
        existing = (
            db.query(PlannedSession)
            .filter(
                PlannedSession.user_id == user_id,
                PlannedSession.planned_date == pdate,
            )
            .first()
        )
        if existing is not None:
            continue
        ps = PlannedSession(
            user_id=user_id,
            planned_date=pdate,
            session_type=body["session_type"],
            name=body["name"],
            structure=body["structure"],
            notes=body["notes"],
            status="planned",
        )
        db.add(ps)
        db.flush()
        created_ids.append(str(ps.id))

    row.status = "applied"
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return {
        "ok": True,
        "draft_id": str(row.id),
        "created": created_ids,
        "skipped_past": skipped_past,
    }


def update_draft_slot(
    db: Session,
    user_id,
    week_start: date,
    day_offset: int,
    *,
    patch: dict | None = None,
    remove: bool = False,
) -> dict | None:
    """Edit or remove one draft slot. Any edit stamps source=user (pinned)."""
    from backend.models import PlanDraft

    row = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
        .first()
    )
    if row is None:
        return None
    payload = dict(row.payload or {})
    sessions = list(payload.get("sessions") or [])
    idx = next(
        (i for i, s in enumerate(sessions)
         if isinstance(s, dict) and int(s.get("day_offset", -1)) == day_offset),
        None,
    )
    if remove:
        if idx is not None:
            sessions.pop(idx)
        # Also drop matching skeleton slot
        slots = [
            s for s in (payload.get("slots") or [])
            if not (isinstance(s, dict) and int(s.get("day_offset", -1)) == day_offset)
        ]
        payload["slots"] = slots
        payload["sessions"] = sessions
        row.payload = payload
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
        return get_draft(db, user_id, week_start)

    if idx is None:
        # Create a user-authored slot for an empty day
        base = {
            "day_offset": day_offset,
            "workout_type": (patch or {}).get("workout_type") or "run",
            "target_tss": (patch or {}).get("target_tss") or 0,
            "duration_minutes": (patch or {}).get("duration_minutes") or 0,
            "intent": (patch or {}).get("intent") or "Session",
            "source": "user",
        }
        if patch:
            base.update({k: v for k, v in patch.items() if v is not None})
        base["source"] = "user"
        sessions.append(base)
    else:
        cur = dict(sessions[idx])
        if patch:
            for k, v in patch.items():
                if v is not None:
                    cur[k] = v
        cur["source"] = "user"
        sessions[idx] = cur
    payload["sessions"] = sessions
    row.payload = payload
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return get_draft(db, user_id, week_start)


def draft_status_for_badge(db: Session, user_id, *, today: date | None = None) -> dict:
    """In-app badge/chip: fresh or outdated draft awaiting review."""
    from backend.models import PlanDraft

    today = today or date.today()
    ws = today - timedelta(days=today.weekday())
    row = (
        db.query(PlanDraft)
        .filter(
            PlanDraft.user_id == user_id,
            PlanDraft.week_start.in_([ws, ws + timedelta(days=7)]),
            PlanDraft.status.in_(["fresh", "outdated"]),
        )
        .order_by(PlanDraft.week_start.asc())
        .first()
    )
    if row is None:
        return {"ready": False}
    return {
        "ready": True,
        "week_start": row.week_start.isoformat(),
        "status": row.status,
        "deeplink": f"/log?tab=plan&week={row.week_start.isoformat()}",
    }


def hermes_draft_notify(
    db: Session,
    user_id,
    *,
    now: datetime | None = None,
    ack: bool = False,
) -> dict:
    """Morning-window Discord/Hermes notify payload.

    Generation never notifies at job completion — Hermes polls this and only
    delivers when ``deliver_now`` is true (BKK 07:00–09:00, pending, unacked).
    Sunday sets ``combine_with_prefs_reconfirm`` so Hermes can fold the weekly
    prefs reconfirm into the same touchpoint.
    """
    from backend.models import PlanDraft
    from zoneinfo import ZoneInfo

    bkk = ZoneInfo("Asia/Bangkok")
    now = now or datetime.now(bkk)
    if now.tzinfo is None:
        now = now.replace(tzinfo=bkk)
    else:
        now = now.astimezone(bkk)

    today = now.date()
    ws = today - timedelta(days=today.weekday())
    row = (
        db.query(PlanDraft)
        .filter(
            PlanDraft.user_id == user_id,
            PlanDraft.week_start.in_([ws, ws + timedelta(days=7)]),
            PlanDraft.status.in_(["fresh", "outdated"]),
        )
        .order_by(PlanDraft.week_start.asc())
        .first()
    )
    if row is None:
        return {"ready": False, "deliver_now": False}

    payload = dict(row.payload or {})
    already = bool(payload.get("notified_at"))
    pending = bool(payload.get("notify_pending", True)) and not already
    hour = now.hour
    in_window = 7 <= hour < 9
    deliver_now = pending and in_window

    if ack and pending:
        payload["notify_pending"] = False
        payload["notified_at"] = now.isoformat()
        row.payload = payload
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
        already = True
        pending = False
        deliver_now = False

    n_sessions = sum(
        1 for s in (payload.get("sessions") or [])
        if isinstance(s, dict) and (s.get("workout_type") or "") != "rest"
    )
    msg = (
        f"Your week draft is ready ({n_sessions} sessions) — review on the Plan tab."
    )
    return {
        "ready": True,
        "deliver_now": deliver_now,
        "pending": pending,
        "in_morning_window": in_window,
        "week_start": row.week_start.isoformat(),
        "status": row.status,
        "message": msg,
        "deeplink": f"/log?tab=plan&week={row.week_start.isoformat()}",
        "combine_with_prefs_reconfirm": today.weekday() == 6,  # Sunday
    }