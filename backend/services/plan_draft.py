"""Plan draft generation + storage (pipeline v2 stage assemble → store)."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from backend.services.plan_prefs_accessor import get_plan_prefs
from backend.services.plan_extras import apply_prefs_extras
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
    llm_call=None,
    current: dict | None = None,
    *,
    avoid_parts: set | None = None,
) -> dict:
    """Pattern-fill one slot. `llm_call` ignored (planning LLM removed)."""
    del user_id, llm_call
    if current and current.get("source") == "user":
        return {**current, "source": "user"}
    return generate_slot_content(
        week_ctx, slot, current=current, db=db, avoid_parts=avoid_parts,
    )


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
    # Stretch / plyo / monthly benchmark (lean program D5): prefs-driven extras
    # decorated onto the skeleton. With those prefs unset this is the identity
    # function, so a week is unchanged for anyone who hasn't opted in.
    sk = apply_prefs_extras(
        sk,
        prefs=prefs,
        week_start=week_start,
        rest_days=set(prefs.get("preferred_rest_days") or []),
    )

    week_ctx = build_week_ctx(
        facts=facts,
        skeleton_slots=sk["slots"],
        strength_emphasis=prefs["strength_emphasis"],
        notes=prefs["notes"],
    )

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

    # Sequential — one SQLAlchemy Session must not be shared across threads
    for d, slot in to_fill:
        contents[d] = _cached_or_generate(db, user_id, week_ctx, slot, None, None)

    # Ensure order
    ordered_contents = [contents[i] or {"intent": "Rest", "source": "template"} for i in range(7)]
    assembled = assemble_week(sk["slots"], ordered_contents, facts=facts)

    from backend.services.plan_skeleton_ops import ensure_slot_ids, sync_slots_from_sessions
    from backend.services.plan_week_balance import balance_week_sessions, sore_parts_for_user
    from backend.utils.time import today_bangkok

    sessions = ensure_slot_ids(assembled["sessions"])
    sore = sore_parts_for_user(db, user_id, today_bangkok())
    sessions, muscle_summary = balance_week_sessions(
        sessions, db=db, week_ctx=week_ctx, sore_parts=sore,
    )
    sessions = ensure_slot_ids(sessions)

    # Carry slot_ids onto skeleton slots by day
    by_day = {int(s["day_offset"]): s for s in sessions}
    for slot in sk["slots"]:
        sid = by_day.get(int(slot["day_offset"]), {}).get("slot_id")
        if sid:
            slot["slot_id"] = sid

    return {
        "week_start": week_start.isoformat(),
        "budget": sk["budget"],
        "slots": sync_slots_from_sessions(sessions) if sessions else sk["slots"],
        "sessions": sessions,
        "sanity_errors": assembled.get("sanity_errors") or [],
        "facts_signature": facts_signature_for_draft(facts),
        "muscle_summary": muscle_summary,
        "version": 1,
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


def refresh_draft_sync(
    db: Session,
    user_id,
    week_start: date,
    *,
    refresh_untouched_only: bool = True,
) -> dict:
    """Synchronously regenerate draft content from patterns (no worker / no LLM)."""
    previous = None
    existing = get_draft(db, user_id, week_start)
    if existing and refresh_untouched_only:
        previous = existing.get("payload")
    payload = generate_draft_payload(
        db,
        user_id,
        week_start,
        previous_payload=previous,
        refresh_untouched_only=refresh_untouched_only and previous is not None,
    )
    upsert_draft(db, user_id, week_start, payload, status="fresh")
    return get_draft(db, user_id, week_start) or {
        "week_start": week_start.isoformat(),
        "payload": payload,
        "status": "fresh",
    }


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
        "draft_version": draft_version_token(row),
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


def enqueue_plan_draft(
    user_id,
    week_start: date | None = None,
    *,
    enqueued_by: str = "web",
    slot_ids: list[str] | None = None,
) -> str | None:
    """Debounced enqueue: skip if pending plan_draft for user exists.

    When ``slot_ids`` is set, the worker regenerates ONLY those slots (partial).
    """
    from backend.services import job_queue as jq
    from backend.utils.time import today_bangkok

    today = today_bangkok()
    ws = week_start or (today - timedelta(days=today.weekday()))
    dedupe_suffix = ",".join(sorted(slot_ids)) if slot_ids else "full"
    dedupe = f"plan_draft:{user_id}:{ws.isoformat()}:{dedupe_suffix}"
    payload: dict[str, Any] = {"user_id": str(user_id), "week_start": ws.isoformat()}
    if slot_ids:
        payload["slot_ids"] = list(slot_ids)
        payload["mode"] = "partial"
    return jq.enqueue(
        "plan_draft",
        payload,
        priority=5,
        enqueued_by=enqueued_by,
        dedupe_key=dedupe,
    )


def run_plan_draft_job(payload: dict) -> dict:
    """Worker entry: full regen or partial slot_ids regen."""
    from backend.db import engine
    from backend.models import PlanDraft
    from uuid import UUID

    user_id = UUID(str(payload["user_id"]))
    week_start = date.fromisoformat(payload["week_start"])
    slot_ids = payload.get("slot_ids") or None
    mode = (payload.get("mode") or "").lower()

    with Session(engine) as db:
        if mode == "partial" and slot_ids:
            result = regenerate_partial_slots(db, user_id, week_start, list(slot_ids))
            db.commit()
            return result

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

    today = today or today_bangkok()
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


def ensure_draft_shell(db: Session, user_id, week_start: date) -> dict:
    """Ensure a mutable draft row exists for the week (empty sessions ok).

    If the draft was already applied, reopen it as fresh with remaining
    (non-applied) payload so single-slot adds can continue.
    """
    from backend.models import PlanDraft

    row = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
        .first()
    )
    if row is None:
        payload = {
            "sessions": [],
            "slots": [],
            "budget": {},
            "version": 1,
            "facts_signature": "",
        }
        row = upsert_draft(db, user_id, week_start, payload, status="fresh")
    elif row.status == "applied":
        payload = dict(row.payload or {})
        payload.setdefault("sessions", [])
        payload.setdefault("slots", [])
        payload["version"] = int(payload.get("version") or 1) + 1
        row = upsert_draft(db, user_id, week_start, payload, status="fresh")
    return get_draft(db, user_id, week_start) or {}


def apply_draft_slot(
    db: Session,
    user_id,
    week_start: date,
    *,
    slot_id: str | None = None,
    day_offset: int | None = None,
    today: date | None = None,
) -> dict:
    """Apply one draft session → PlannedSession; leave the rest of the draft open."""
    from backend.models import PlanDraft, PlannedSession
    from backend.services import plan_skeleton_ops as ops

    today = today or today_bangkok()
    row = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
        .first()
    )
    if row is None:
        return {"ok": False, "error": "no_draft", "status_code": 404}

    payload = dict(row.payload or {})
    sessions = list(payload.get("sessions") or [])
    sess = None
    for s in sessions:
        if not isinstance(s, dict):
            continue
        if slot_id and s.get("slot_id") == slot_id:
            sess = s
            break
        if day_offset is not None and int(s.get("day_offset", -1)) == int(day_offset):
            sess = s
            break
    if sess is None:
        return {"ok": False, "error": "slot_not_found", "status_code": 404}

    body = _session_to_planned_body(week_start, sess)
    if body is None:
        return {"ok": False, "error": "not_applicable", "status_code": 422}

    pdate = date.fromisoformat(body["planned_date"])
    if pdate < today:
        return {"ok": False, "error": "past_day", "status_code": 409}

    existing = (
        db.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date == pdate,
        )
        .first()
    )
    if existing is not None:
        return {
            "ok": False,
            "error": "day_already_planned",
            "status_code": 409,
            "planned_session_id": str(existing.id),
        }

    # Preserve gap origin tag if present
    structure = body.get("structure") or {}
    if sess.get("_gap_code"):
        structure = dict(structure)
        structure["_gap_code"] = sess["_gap_code"]
    if sess.get("structure") and isinstance(sess["structure"], dict):
        merged = dict(sess["structure"])
        merged.update(structure)
        structure = merged

    ps = PlannedSession(
        user_id=user_id,
        planned_date=pdate,
        session_type=body["session_type"],
        name=body["name"],
        structure=structure or None,
        notes=body["notes"],
        status="planned",
    )
    db.add(ps)
    db.flush()

    sid = sess.get("slot_id")
    day = int(sess.get("day_offset", -1))
    sessions = [s for s in sessions if not (
        isinstance(s, dict) and (
            (sid and s.get("slot_id") == sid) or
            (day >= 0 and int(s.get("day_offset", -1)) == day)
        )
    )]
    # Leave an empty rest placeholder so the day stays in the draft grid
    rest_slot = {
        "slot_id": str(uuid.uuid4()),
        "day_offset": day,
        "workout_type": "rest",
        "subtype": "rest",
        "target_tss": 0,
        "duration_minutes": 0,
        "intent": "Rest",
        "notes": None,
        "blocks": None,
        "exercises": None,
        "source": "template",
        "structure_hints": {},
        "locked": False,
        "pending": False,
    }
    if day >= 0:
        sessions.append(rest_slot)

    payload["sessions"] = sessions
    payload["slots"] = ops.sync_slots_from_sessions(sessions)
    payload["version"] = int(payload.get("version") or 1) + 1
    row.payload = payload
    if row.status == "applied":
        row.status = "fresh"
    row.updated_at = datetime.now(timezone.utc)
    db.flush()

    return {
        "ok": True,
        "created_id": str(ps.id),
        "draft": get_draft(db, user_id, week_start),
        "day_offset": day,
        "slot_id": sid,
    }


def request_slot_regen(
    db: Session,
    user_id,
    week_start: date,
    *,
    slot_id: str,
    draft_version: str | None = None,
) -> dict:
    """Sync pattern-refill one slot (no worker / no LLM)."""
    from backend.models import PlanDraft

    row = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
        .first()
    )
    if row is None:
        return {"ok": False, "error": "no_draft", "status_code": 404}

    token = draft_version_token(row)
    if draft_version is not None and draft_version != token:
        return {"ok": False, "error": "stale_draft", "status_code": 409, "draft_version": token}

    result = regenerate_partial_slots(db, user_id, week_start, [slot_id])
    if result.get("status") != "ok":
        return {"ok": False, "error": result.get("reason") or "regen_failed", "status_code": 422}

    return {
        "ok": True,
        "job_id": None,
        "slot_id": slot_id,
        "draft": get_draft(db, user_id, week_start),
        "draft_version": draft_version_token(row),
        "dispatch": {"dispatch": "inline", "slot_ids": [slot_id]},
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

    today = today or today_bangkok()
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

def draft_version_token(row) -> str:
    """Client sends this back; reject ops if mismatched (stale draft)."""
    if row is None:
        return ""
    ts = row.updated_at.isoformat() if row.updated_at else ""
    ver = (row.payload or {}).get("version") or 0
    return f"{ver}:{ts}:{row.facts_signature[:12]}"


def rewrite_slot_cache_key(db: Session, user_id, *, old_pins: dict, new_pins: dict, week_ctx: dict) -> bool:
    """Move cache entry under new pin key without regenerating. Returns True if rewritten."""
    from backend.models import LlmGeneration
    from backend.services.plan_slot_cache import SURFACE, content_ctx_from_week, slot_cache_key

    ctx = content_ctx_from_week(week_ctx)
    old_key = slot_cache_key(pins=old_pins, content_ctx=ctx)
    new_key = slot_cache_key(pins=new_pins, content_ctx=ctx)
    if old_key == new_key:
        return False
    row = (
        db.query(LlmGeneration)
        .filter_by(user_id=user_id, surface=SURFACE, input_signature=old_key)
        .first()
    )
    if row is None:
        return False
    # Avoid unique collision
    existing_new = (
        db.query(LlmGeneration)
        .filter_by(user_id=user_id, surface=SURFACE, input_signature=new_key)
        .first()
    )
    if existing_new is not None:
        db.delete(row)
    else:
        row.input_signature = new_key
    db.flush()
    return True


def regenerate_partial_slots(db: Session, user_id, week_start: date, slot_ids: list[str]) -> dict:
    """Regenerate ONLY listed slot_ids; clear pending flags."""
    from backend.models import PlanDraft
    from backend.services.plan_skeleton_ops import ensure_slot_ids, sync_slots_from_sessions
    from backend.services.plan_slot import stamp_session

    row = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
        .first()
    )
    if row is None:
        return {"status": "error", "reason": "no_draft"}

    payload = dict(row.payload or {})
    sessions = ensure_slot_ids(list(payload.get("sessions") or []))
    want = set(slot_ids)
    prefs = get_plan_prefs(db, user_id)
    facts = assemble_facts(
        str(user_id), db, week_start=week_start,
        preferred_rest_days=prefs["preferred_rest_days"],
        strength_emphasis=prefs["strength_emphasis"],
        notes=prefs["notes"],
    )
    slots_for_ctx = [
        {
            "day_offset": s["day_offset"],
            "workout_type": s.get("workout_type"),
            "target_tss": s.get("target_tss"),
            "duration_minutes": s.get("duration_minutes"),
            "subtype": s.get("subtype"),
            "structure_hints": s.get("structure_hints") or {},
            "locked": bool(s.get("locked")),
        }
        for s in sessions
    ]
    week_ctx = build_week_ctx(
        facts=facts,
        skeleton_slots=slots_for_ctx,
        strength_emphasis=prefs["strength_emphasis"],
        notes=prefs["notes"],
    )
    regenerated = 0
    results: dict[str, dict] = {}
    for sess in sessions:
        sid = sess.get("slot_id")
        if sid not in want:
            continue
        pins = {
            "day_offset": sess["day_offset"],
            "workout_type": sess.get("workout_type"),
            "target_tss": sess.get("target_tss"),
            "duration_minutes": sess.get("duration_minutes"),
            "subtype": sess.get("subtype"),
            "structure_hints": sess.get("structure_hints") or {},
        }
        if sess.get("source") == "user":
            results[sid] = sess
            continue
        content = _cached_or_generate(db, user_id, week_ctx, pins, None, None)
        stamped = stamp_session(pins, content)
        stamped["slot_id"] = sess["slot_id"]
        stamped["pending"] = False
        stamped["source"] = stamped.get("source") or content.get("source") or "pattern"
        if content.get("_muscle_footprint"):
            stamped["_muscle_footprint"] = content["_muscle_footprint"]
        if content.get("pattern_name"):
            stamped["pattern_name"] = content["pattern_name"]
        results[sid] = stamped
        regenerated += 1

    new_sessions = []
    for s in sessions:
        sid = s.get("slot_id")
        if sid in results:
            new_sessions.append(results[sid])
        else:
            new_sessions.append(s)

    from backend.services.plan_week_balance import balance_week_sessions, sore_parts_for_user
    from backend.utils.time import today_bangkok

    sore = sore_parts_for_user(db, user_id, today_bangkok())
    new_sessions, muscle_summary = balance_week_sessions(
        new_sessions, db=db, week_ctx=week_ctx, sore_parts=sore,
    )
    new_sessions = ensure_slot_ids(new_sessions)

    payload["sessions"] = new_sessions
    payload["slots"] = sync_slots_from_sessions(new_sessions)
    payload["muscle_summary"] = muscle_summary
    payload["version"] = int(payload.get("version") or 1) + 1
    row.payload = payload
    row.updated_at = datetime.now(timezone.utc)
    if row.status == "outdated":
        row.status = "fresh"
    db.flush()
    return {"status": "ok", "regenerated": regenerated, "slot_ids": list(want)}


def _dispatch_after_op(
    db: Session,
    user_id,
    week_start: date,
    affected: list[str],
    *,
    inline: bool,
    background: bool,
) -> dict:
    """Refill affected slots with patterns synchronously (no worker enqueue)."""
    del inline, background
    n = len(affected)
    if n == 0:
        return {"dispatch": "none"}
    result = regenerate_partial_slots(db, user_id, week_start, affected)
    return {"dispatch": "inline", "result": result, "slot_ids": affected}


def apply_structure_op(
    db: Session,
    user_id,
    week_start: date,
    *,
    op: str,
    draft_version: str | None = None,
    confirm_warnings: bool = False,
    inline: bool = True,
    background: bool = False,
    **kwargs,
) -> dict:
    """Run a skeleton op against the live draft; version-guard; dispatch regen."""
    from backend.models import PlanDraft
    from backend.services import plan_skeleton_ops as ops
    from backend.utils.time import today_bangkok

    row = (
        db.query(PlanDraft)
        .filter(PlanDraft.user_id == user_id, PlanDraft.week_start == week_start)
        .first()
    )
    if row is None:
        return {"ok": False, "error": "no_draft", "status_code": 404}

    token = draft_version_token(row)
    if draft_version is not None and draft_version != token:
        return {"ok": False, "error": "stale_draft", "status_code": 409, "draft_version": token}

    payload = dict(row.payload or {})
    sessions = ops.ensure_slot_ids(list(payload.get("sessions") or []))
    prefs = get_plan_prefs(db, user_id)
    today = today_bangkok()
    today_offset = None
    if week_start <= today <= week_start + timedelta(days=6):
        today_offset = (today - week_start).days

    budget = payload.get("budget") or {}
    ceiling = budget.get("acwr_ceiling")
    common = dict(
        preferred_rest_days=prefs.get("preferred_rest_days") or [],
        today_offset=today_offset,
        confirm_warnings=confirm_warnings,
    )

    if op == "move":
        result = ops.move(
            sessions,
            slot_id=kwargs["slot_id"],
            to_day=int(kwargs["to_day"]),
            **common,
        )
    elif op == "swap":
        result = ops.swap(
            sessions,
            day_a=int(kwargs["day_a"]),
            day_b=int(kwargs["day_b"]),
            **common,
        )
    elif op == "remove":
        result = ops.remove(
            sessions,
            slot_id=kwargs["slot_id"],
            mode=kwargs.get("mode") or "drop",
            acwr_ceiling=ceiling,
            weekly_target=budget.get("weekly_target"),
        )
    elif op == "add":
        result = ops.add(
            sessions,
            day=int(kwargs["day"]),
            kind=kwargs.get("kind") or "easy_run",
            acwr_ceiling=ceiling,
            custom=kwargs.get("custom"),
            **common,
        )
    elif op == "preview_move":
        return {
            "ok": True,
            "preview": ops.preview_move_target(
                sessions,
                slot_id=kwargs["slot_id"],
                to_day=int(kwargs["to_day"]),
                preferred_rest_days=prefs.get("preferred_rest_days") or [],
                today_offset=today_offset,
            ),
            "draft_version": token,
        }
    else:
        return {"ok": False, "error": f"unknown op {op}", "status_code": 422}

    if result.get("blocked"):
        return {
            "ok": False,
            "blocked": True,
            "block_reason": result.get("block_reason"),
            "warnings": result.get("warnings") or [],
            "status_code": 422,
            "draft_version": token,
        }
    if result.get("needs_confirm") and not confirm_warnings:
        return {
            "ok": False,
            "needs_confirm": True,
            "warnings": result.get("warnings") or [],
            "swap_with": result.get("swap_with"),
            "status_code": 409,
            "draft_version": token,
        }

    new_sessions = result["slots"]
    # Cache rewrite for moves (no LLM)
    week_ctx = None
    if result.get("moved_cache_rewrite"):
        facts = assemble_facts(
            str(user_id), db, week_start=week_start,
            preferred_rest_days=prefs["preferred_rest_days"],
            strength_emphasis=prefs["strength_emphasis"],
            notes=prefs["notes"],
        )
        week_ctx = build_week_ctx(
            facts=facts,
            skeleton_slots=ops.sync_slots_from_sessions(new_sessions),
            strength_emphasis=prefs["strength_emphasis"],
            notes=prefs["notes"],
        )
        for mv in result["moved_cache_rewrite"]:
            sess = next((s for s in new_sessions if s.get("slot_id") == mv["slot_id"]), None)
            if not sess:
                continue
            old_pins = {
                "day_offset": mv["from_day"],
                "workout_type": sess.get("workout_type"),
                "target_tss": sess.get("target_tss"),
                "duration_minutes": sess.get("duration_minutes"),
                "subtype": sess.get("subtype"),
                "structure_hints": sess.get("structure_hints") or {},
            }
            new_pins = {**old_pins, "day_offset": mv["to_day"]}
            rewrite_slot_cache_key(db, user_id, old_pins=old_pins, new_pins=new_pins, week_ctx=week_ctx)

    payload["sessions"] = new_sessions
    payload["slots"] = ops.sync_slots_from_sessions(new_sessions)
    payload["version"] = int(payload.get("version") or 1) + 1
    if result.get("redistribute") is not None:
        payload["last_redistribute"] = result["redistribute"]
    row.payload = payload
    row.updated_at = datetime.now(timezone.utc)
    db.flush()

    affected = list(result.get("affected_slot_ids") or [])
    # Never sync-LLM on structure add — Generate details is an explicit async path.
    if op == "add":
        inline = False
        affected = []
    dispatch = _dispatch_after_op(
        db, user_id, week_start, affected, inline=inline, background=background,
    )
    fresh = get_draft(db, user_id, week_start)
    out = {
        "ok": True,
        "draft": fresh,
        "draft_version": draft_version_token(row),
        "warnings": result.get("warnings") or [],
        "affected_slot_ids": affected,
        "redistribute": result.get("redistribute"),
        "dispatch": dispatch,
    }
    if result.get("added_slot_id"):
        out["added_slot_id"] = result["added_slot_id"]
    return out


def replan_remaining_budget(
    db: Session,
    user_id,
    week_start: date,
    *,
    today: date | None = None,
) -> dict:
    """Budget for open days = weekly − Σ matched ACTUAL TSS; partial skeleton."""
    from backend.models import PlannedSession, Workout
    from backend.services.plan_skeleton import weekly_budget, build_skeleton
    from backend.utils.time import today_bangkok

    today = today or today_bangkok()
    prefs = get_plan_prefs(db, user_id)
    facts = assemble_facts(
        str(user_id), db, week_start=week_start,
        preferred_rest_days=prefs["preferred_rest_days"],
        strength_emphasis=prefs["strength_emphasis"],
        notes=prefs["notes"],
    )

    # Matched actual TSS for done sessions this week
    rows = (
        db.query(PlannedSession)
        .filter(
            PlannedSession.user_id == user_id,
            PlannedSession.planned_date >= week_start,
            PlannedSession.planned_date <= week_start + timedelta(days=6),
        )
        .all()
    )
    matched_actual = 0.0
    occupied: set[int] = set()
    for p in rows:
        offset = (p.planned_date - week_start).days
        if p.status in ("done_auto", "done_manual") and p.matched_workout_id:
            w = db.get(Workout, p.matched_workout_id)
            if w and w.tss is not None:
                matched_actual += float(w.tss)
            occupied.add(offset)
        elif p.status in ("done_auto", "done_manual", "needs_review"):
            # Fall back to planned estimate only for done-but-unmatched review
            occupied.add(offset)
        elif p.status in ("missed_manual", "missed_auto", "missed"):
            occupied.add(offset)  # closed — no redistribute
        elif p.planned_date < today:
            occupied.add(offset)
        else:
            # Open planned — will be replaced; still occupy until apply
            occupied.add(offset)

    # Open = future days without a matched/done/missed lock — for replan we
    # treat "still planned & today-or-future" as regenerable.
    open_offsets = []
    for p in rows:
        offset = (p.planned_date - week_start).days
        if p.status == "planned" and p.planned_date >= today and not p.matched_workout_id:
            open_offsets.append(offset)

    # Also include empty future days
    for d in range(7):
        day = week_start + timedelta(days=d)
        if day < today:
            continue
        if d not in { (p.planned_date - week_start).days for p in rows }:
            open_offsets.append(d)
    open_offsets = sorted(set(open_offsets))

    load_plan_week = None
    if facts.get("target_tss") is not None:
        load_plan_week = {
            "target_tss": facts["target_tss"],
            "phase": facts.get("phase"),
            "ceiling": facts.get("acwr_ceiling"),
        }
    budget = weekly_budget(
        trailing_28d_weekly_avg_tss=float(facts.get("trailing_28d_weekly_avg_tss") or 0),
        logged_tss_so_far=matched_actual,
        open_slot_count=max(1, len(open_offsets)),
        load_plan_week=load_plan_week,
        race_anchored_target=facts.get("target_tss"),
    )

    # Existing occupied for skeleton = everything NOT in open_offsets
    existing_occupied = set(range(7)) - set(open_offsets)
    history = _load_history_rows(str(user_id), week_start, db=db)
    sk = build_skeleton(
        week_start=week_start,
        history=history,
        preferred_rest_days=prefs["preferred_rest_days"],
        strength_emphasis=prefs["strength_emphasis"],
        trailing_28d_weekly_avg_tss=float(facts.get("trailing_28d_weekly_avg_tss") or 0),
        logged_tss_so_far=matched_actual,
        allowed_offsets=open_offsets,
        load_plan_week=load_plan_week,
        race_anchored_target=facts.get("target_tss"),
        existing_occupied=existing_occupied,
    )
    sk = apply_prefs_extras(
        sk,
        prefs=prefs,
        week_start=week_start,
        rest_days=set(prefs.get("preferred_rest_days") or []),
    )
    return {
        "budget": budget,
        "matched_actual_tss": matched_actual,
        "open_offsets": open_offsets,
        "skeleton": sk,
    }
