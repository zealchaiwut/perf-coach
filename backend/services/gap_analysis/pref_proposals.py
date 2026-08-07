"""Preference proposals driven by persistent gap findings.

The LLM never authors a delta — Python computes one catalog step from the
current prefs when a gap code has fired for ≥ persist_weeks consecutive weeks.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.services.gap_analysis.suppression import (
    SUPPRESSION_DAYS,
    evidence_hash,
    in_cooldown_window,
)
from backend.services.pref_catalog import (
    PREF_FIELDS,
    apply_enum_step,
    apply_step,
    enum_options,
    field_meta,
    get_field,
    persist_weeks_for,
    set_field,
    validate_payload,
)
from backend.services.training_prefs import (
    active_dict,
    ensure_active,
    get_active,
    write_version,
)
from backend.utils.log import get_logger

_log = get_logger(__name__)

PROPOSAL_EXPIRE_DAYS = 14
REVIEW_AFTER_DAYS = 28
MIN_ACTIVE_WEEKS_BEFORE_NEXT = 2
SAFETY_ROLLBACK_WINDOW_DAYS = 14

# Gap code → preference field + signed step direction (magnitude from catalog).
#
# recurrent_niggle_area (priority/severity-3, recurring injury pattern) and
# undertrained_area_under_ramp (already has its own severe-injury guard) are
# deliberately NOT mapped — both need human/coach judgment, not a blind
# catalog step. cadence_drift, gct_lengthening, intensity_too_hard,
# speed_neglected, base_neglected are pure form/biomechanical signals with no
# clean 1:1 preference-field mapping and are out of scope. All five stay
# diagnostic-only in the gap panel.
GAP_TO_PREF_DELTA: dict[str, dict[str, Any]] = {
    "plyo_deficit": {"field": "plyo_sessions_per_week", "step": +1},
    "no_recent_plyo": {"field": "plyo_sessions_per_week", "step": +1},
    "aerobic_durability_gap": {"field": "long_run.mp_segment_min", "step": +10},
    "strength_lapsed": {"field": "strength_emphasis", "step": +1},
    "muscle_overused": {"field": "strength_emphasis", "step": -1},
    # muscle_untrained → add_to_set homework (Pass 6), not a strength_emphasis bump
    # stretch_neglect lands when that gap rule ships
}

# muscle_overused findings carry a dynamic per-group code
# ("muscle_overused.calf", not bare "muscle_overused" — see
# gap_analysis/rules/muscle_balance.py and templates.py's _PREFIX table for
# the same pattern). Resolve those by prefix instead of exact dict lookup.
# muscle_untrained.* is handled as add_to_set in maybe_create_proposals_from_findings.
_PREFIX_GAP_CODES: tuple[str, ...] = ("muscle_overused",)


def mapping_for_gap_code(code: str) -> dict[str, Any] | None:
    """Resolve a finding code (exact, or dynamic "<prefix>.<group>") to its
    GAP_TO_PREF_DELTA entry, or None if the code has no proposal mapping."""
    if not code:
        return None
    if code in GAP_TO_PREF_DELTA:
        return GAP_TO_PREF_DELTA[code]
    if code.startswith("muscle_untrained."):
        # Homework add_to_set — field used for open-proposal / cooldown keys.
        return {"field": "weekly_focus", "kind": "add_to_set"}
    for prefix in _PREFIX_GAP_CODES:
        if code.startswith(prefix + "."):
            return GAP_TO_PREF_DELTA[prefix]
    return None


def has_open_proposal_for_code(db: Session, user_id, code: str) -> bool:
    """True when *code* maps to a preference field that currently has an open
    ("proposed") proposal. Used by the gap-analysis endpoint to suppress a
    finding that's already actionable elsewhere — never used to hide a
    finding just because it's proposal-eligible but hasn't proposed yet."""
    mapping = mapping_for_gap_code(code)
    if mapping is None:
        return False
    return _open_proposal_for_field(db, user_id, mapping["field"]) is not None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def proposal_dict(row: Any) -> dict:
    return {
        "id": str(row.id),
        "gap_code": row.gap_code,
        "finding_ref": row.finding_ref,
        "delta": row.delta,
        "status": row.status,
        "proposed_at": row.proposed_at.isoformat() if row.proposed_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "review_at": row.review_at.isoformat() if row.review_at else None,
        "review_outcome": row.review_outcome,
        "dismissed_severity": row.dismissed_severity,
    }


def expire_stale(db: Session, user_id) -> int:
    """Lazy expiry: proposed past expires_at → expired. Returns count updated."""
    from backend.models import PreferenceProposal

    now = _now()
    rows = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.user_id == user_id,
            PreferenceProposal.status == "proposed",
            PreferenceProposal.expires_at <= now,
        )
        .all()
    )
    for r in rows:
        r.status = "expired"
    if rows:
        db.flush()
    return len(rows)


def list_proposals(db: Session, user_id, *, include_settled: bool = True) -> list[dict]:
    from backend.models import PreferenceProposal

    expire_stale(db, user_id)
    q = db.query(PreferenceProposal).filter(PreferenceProposal.user_id == user_id)
    if not include_settled:
        q = q.filter(PreferenceProposal.status.in_(("proposed", "accepted")))
    rows = q.order_by(PreferenceProposal.proposed_at.desc()).limit(50).all()
    return [proposal_dict(r) for r in rows]


def open_proposals_for_brief(db: Session, user_id) -> list[dict]:
    """Proposed (and recently accepted awaiting review) for coach brief."""
    from backend.models import PreferenceProposal

    expire_stale(db, user_id)
    now = _now()
    rows = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.user_id == user_id,
            PreferenceProposal.status.in_(("proposed", "accepted")),
        )
        .order_by(PreferenceProposal.proposed_at.desc())
        .all()
    )
    out = []
    for r in rows:
        if r.status == "proposed":
            out.append(proposal_dict(r))
        elif r.status == "accepted" and r.review_at and r.review_outcome is None:
            # Surface accepted-pending-review; also include just-reviewed outcomes briefly
            d = proposal_dict(r)
            d["lifecycle"] = "active"
            out.append(d)
        elif r.status == "accepted" and r.review_outcome and r.decided_at:
            # Show review outcome for a few days
            if r.review_at and (now - (r.review_at if r.review_at.tzinfo else r.review_at.replace(tzinfo=timezone.utc))).days <= 7:
                d = proposal_dict(r)
                d["lifecycle"] = "reviewed"
                out.append(d)
    return out


def _consecutive_weeks_firing(db: Session, user_id, gap_code: str, week_start) -> int:
    """Count consecutive ISO weeks ending at week_start where gap_code has a row."""
    from sqlalchemy import text

    # Walk backwards week by week until a miss
    count = 0
    ws = week_start
    for _ in range(12):
        row = db.execute(
            text("""
                SELECT 1 FROM gap_findings
                WHERE user_id = :uid AND week_start = :ws AND code = :code
                LIMIT 1
            """),
            {"uid": str(user_id), "ws": ws.isoformat() if hasattr(ws, "isoformat") else str(ws), "code": gap_code},
        ).fetchone()
        if not row:
            break
        count += 1
        from datetime import date as _date, timedelta
        if isinstance(ws, str):
            ws = _date.fromisoformat(ws)
        ws = ws - timedelta(days=7)
    return count


def _open_proposal_for_field(db: Session, user_id, field: str) -> Any | None:
    from backend.models import PreferenceProposal

    rows = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.user_id == user_id,
            PreferenceProposal.status == "proposed",
        )
        .all()
    )
    for r in rows:
        if (r.delta or {}).get("field") == field:
            return r
    return None


def _decline_quiet(db: Session, user_id, field: str, current_severity: int) -> bool:
    """True if a recent decline for this field is still quiet."""
    from backend.models import PreferenceProposal

    row = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.user_id == user_id,
            PreferenceProposal.status == "declined",
        )
        .order_by(PreferenceProposal.decided_at.desc())
        .all()
    )
    for r in row:
        if (r.delta or {}).get("field") != field:
            continue
        cd = in_cooldown_window(
            decided_at=r.decided_at,
            dismissed_severity=r.dismissed_severity,
            current_severity=current_severity,
        )
        return cd["quiet"]
    return False


def _accepted_still_ramping(db: Session, user_id, field: str) -> bool:
    """Block next step until prior accept has been active ≥ 2 weeks."""
    from backend.models import PreferenceProposal

    row = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.user_id == user_id,
            PreferenceProposal.status == "accepted",
            PreferenceProposal.gap_code != "safety_rollback",
        )
        .order_by(PreferenceProposal.decided_at.desc())
        .all()
    )
    for r in row:
        if (r.delta or {}).get("field") != field:
            continue
        if r.decided_at is None:
            return True
        decided = r.decided_at
        if decided.tzinfo is None:
            decided = decided.replace(tzinfo=timezone.utc)
        age = (_now() - decided).total_seconds() / 86400
        if age < MIN_ACTIVE_WEEKS_BEFORE_NEXT * 7:
            return True
        return False
    return False


def maybe_create_proposals_from_findings(
    db: Session,
    user_id,
    findings: list[dict],
    week_start,
) -> list[Any]:
    """After gap analysis: create proposals for persistent gaps. Returns new rows."""
    from backend.models import PreferenceProposal

    expire_stale(db, user_id)
    active = ensure_active(db, user_id)
    payload = deepcopy(active.payload or {})
    created = []

    for f in findings or []:
        code = f.get("code") if isinstance(f, dict) else getattr(f, "code", None)
        if not code:
            continue

        # Pass 6: muscle underload → add_to_set homework proposal (≥2 weeks).
        if str(code).startswith("muscle_untrained."):
            row = _maybe_create_add_to_set(db, user_id, f, week_start, payload)
            if row is not None:
                created.append(row)
            continue

        mapping = mapping_for_gap_code(code)
        if mapping is None:
            continue
        if mapping.get("kind") == "add_to_set":
            continue
        severity = int(
            f.get("severity") if isinstance(f, dict) else getattr(f, "severity", 1) or 1
        )
        field = mapping["field"]
        meta = field_meta(field) or {}
        need = persist_weeks_for(field)
        weeks = _consecutive_weeks_firing(db, user_id, code, week_start)
        if weeks < need:
            continue
        if _open_proposal_for_field(db, user_id, field):
            continue
        if _decline_quiet(db, user_id, field, severity):
            continue
        if _accepted_still_ramping(db, user_id, field):
            continue

        field_type = str(meta.get("type") or "")
        cur = get_field(payload, field)

        if field_type.startswith("enum:"):
            options = enum_options(field)
            if not options:
                continue
            cur_s = str(cur) if cur is not None else str(meta.get("default") or options[0])
            if cur_s not in options:
                continue
            direction = 1 if int(mapping["step"]) > 0 else -1
            idx = options.index(cur_s)
            at_extreme = (
                (direction > 0 and idx >= len(options) - 1)
                or (direction < 0 and idx <= 0)
            )
            if at_extreme:
                continue
            stepped = apply_enum_step(payload, field, int(mapping["step"]))
            if stepped is None:
                continue
            from_val: Any = cur_s
        else:
            try:
                cur_i = int(cur if cur is not None else meta.get("default") or 0)
            except (TypeError, ValueError):
                continue
            hi = int(meta.get("max") or 0)
            if cur_i >= hi:
                continue
            stepped = apply_step(payload, field, int(mapping["step"]))
            if stepped is None:
                continue
            from_val = cur_i

        new_val = get_field(stepped, field)
        evidence = f.get("evidence") if isinstance(f, dict) else getattr(f, "evidence", None)
        finding_ref = evidence_hash(evidence or [])[:32]

        now = _now()
        row = PreferenceProposal(
            user_id=user_id,
            gap_code=code,
            finding_ref=finding_ref,
            delta={"field": field, "from": from_val, "to": new_val},
            status="proposed",
            proposed_at=now,
            expires_at=now + timedelta(days=PROPOSAL_EXPIRE_DAYS),
            dismissed_severity=severity,
        )
        db.add(row)
        db.flush()
        created.append(row)
        _log.info(
            "pref proposal created user=%s field=%s %s→%s gap=%s weeks=%s",
            user_id, field, from_val, new_val, code, weeks,
        )
    return created


def _maybe_create_add_to_set(
    db: Session,
    user_id,
    finding: dict | Any,
    week_start,
    payload: dict,
) -> Any | None:
    """Create an add_to_set homework proposal for muscle_untrained.<group>."""
    from backend.models import PreferenceProposal
    from backend.services.plan_pattern_fill import _load_exercise_pool
    from backend.services.session_homework import pick_exercise_for_muscle

    code = finding.get("code") if isinstance(finding, dict) else getattr(finding, "code", None)
    if not code or not str(code).startswith("muscle_untrained."):
        return None
    group = str(code).split(".", 1)[1].strip().lower()
    if not group:
        return None
    severity = int(
        finding.get("severity") if isinstance(finding, dict) else getattr(finding, "severity", 1) or 1
    )
    field = "weekly_focus"
    need = persist_weeks_for(field)  # 2
    weeks = _consecutive_weeks_firing(db, user_id, code, week_start)
    if weeks < need:
        return None
    # Also suppress if either homework field already has an open add_to_set
    if _open_proposal_for_field(db, user_id, "weekly_focus"):
        return None
    if _open_proposal_for_field(db, user_id, "required_exercises"):
        return None
    if _decline_quiet(db, user_id, field, severity):
        return None
    if _accepted_still_ramping(db, user_id, field):
        return None

    pool = _load_exercise_pool(db)
    # Avoid exercises already in standing / weekly homework
    avoid: set[str] = set()
    for raw in list(payload.get("required_exercises") or []) + list(payload.get("weekly_focus") or []):
        if isinstance(raw, dict):
            n = raw.get("exercise_name") or raw.get("name")
            if n:
                avoid.add(str(n).strip().lower())
    picked = pick_exercise_for_muscle(pool, group, avoid_names=avoid)
    if picked is None:
        return None

    item = {
        "exercise_id": str(picked["id"]) if picked.get("id") else None,
        "exercise_name": picked.get("name"),
        "session_types": ["strength"],
        "sets": picked.get("default_sets") if picked.get("default_sets") is not None else 3,
        "reps": picked.get("default_reps") or "12",
        "load": picked.get("default_load") or "moderate",
        "block": "Accessories",
    }
    evidence = finding.get("evidence") if isinstance(finding, dict) else getattr(finding, "evidence", None)
    finding_ref = evidence_hash(evidence or [])[:32]
    now = _now()
    strip = (
        f"Add {item['exercise_name']} to strength sessions "
        f"(underloaded {group}, {weeks}w)"
    )
    row = PreferenceProposal(
        user_id=user_id,
        gap_code=code,
        finding_ref=finding_ref,
        delta={
            "kind": "add_to_set",
            "field": field,
            "muscle_group": group,
            "from": None,
            "to": item,
            "strip": strip,
            "actions": ["try_week", "standing", "decline"],
        },
        status="proposed",
        proposed_at=now,
        expires_at=now + timedelta(days=PROPOSAL_EXPIRE_DAYS),
        dismissed_severity=severity,
    )
    db.add(row)
    db.flush()
    _log.info(
        "pref add_to_set created user=%s exercise=%s group=%s weeks=%s",
        user_id, item.get("exercise_name"), group, weeks,
    )
    return row


def accept_proposal(
    db: Session,
    user_id,
    proposal_id,
    *,
    adjusted_to: Any | None = None,
    action: str | None = None,
) -> dict:
    from backend.models import PreferenceProposal

    expire_stale(db, user_id)
    row = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.id == proposal_id,
            PreferenceProposal.user_id == user_id,
        )
        .first()
    )
    if row is None:
        raise LookupError("proposal not found")
    if row.status != "proposed":
        raise ValueError(f"proposal status is {row.status}, expected proposed")

    delta = dict(row.delta or {})
    if delta.get("kind") == "add_to_set":
        return _accept_add_to_set(db, user_id, row, action=action)

    field = delta.get("field")
    from_v = delta.get("from")
    to_v = adjusted_to if adjusted_to is not None else delta.get("to")
    if field is None:
        raise ValueError("proposal delta missing field")

    active = ensure_active(db, user_id)
    payload = deepcopy(active.payload or {})
    # Adjust path: catalog-clamp + one-step from current for non-import
    if adjusted_to is not None:
        meta = field_meta(field) or {}
        try:
            to_v = int(adjusted_to)
        except (TypeError, ValueError):
            raise ValueError({field: "must be an integer"})
        lo = int(meta.get("min") or 0)
        hi = int(meta.get("max") or 0)
        if to_v < lo or to_v > hi:
            raise ValueError({field: f"{to_v} out of range [{lo}, {hi}]"})
        step = int(meta.get("step") or 1)
        cur = get_field(payload, field)
        try:
            cur_i = int(cur if cur is not None else 0)
        except (TypeError, ValueError):
            cur_i = 0
        if abs(to_v - cur_i) not in (0, step) and abs(to_v - int(from_v or cur_i)) not in (0, step):
            # Allow adjust to any in-bound value still one step from current
            if abs(to_v - cur_i) != step:
                raise ValueError({field: f"adjust must be one catalog step from current ({cur_i})"})

    set_field(payload, field, to_v)
    errs = validate_payload(payload)
    if errs:
        raise ValueError(errs)

    now = _now()
    prefs_row = write_version(
        db,
        user_id,
        payload,
        source="coach_proposal",
        origin_gap_code=row.gap_code,
        origin_proposal_id=row.id,
        confirm=True,
    )
    row.status = "accepted"
    row.decided_at = now
    row.review_at = now + timedelta(days=REVIEW_AFTER_DAYS)
    # Preserve extra keys (e.g. safety_rollback `reverts`)
    new_delta = dict(row.delta or {})
    new_delta.update({"field": field, "from": from_v, "to": to_v})
    row.delta = new_delta
    db.flush()
    return {
        "proposal": proposal_dict(row),
        "preferences": active_dict(db, user_id),
        "prefs_version": prefs_row.version,
    }


def _accept_add_to_set(
    db: Session,
    user_id,
    row: Any,
    *,
    action: str | None = None,
) -> dict:
    """Accept add_to_set: try_week → weekly_focus (+7d); standing → required_exercises."""
    from backend.services.session_homework import append_homework_item

    act = (action or "try_week").strip().lower()
    if act in ("try", "week", "try_for_a_week"):
        act = "try_week"
    if act in ("make_standing", "standing_homework"):
        act = "standing"
    if act not in ("try_week", "standing"):
        raise ValueError({"action": "must be try_week or standing"})

    item = (row.delta or {}).get("to")
    if not isinstance(item, dict):
        raise ValueError("add_to_set proposal missing exercise item")

    field = "weekly_focus" if act == "try_week" else "required_exercises"
    active = ensure_active(db, user_id)
    payload = deepcopy(active.payload or {})
    payload = append_homework_item(payload, field, item)
    errs = validate_payload(payload)
    if errs:
        raise ValueError(errs)

    now = _now()
    prefs_row = write_version(
        db,
        user_id,
        payload,
        source="coach_proposal",
        origin_gap_code=row.gap_code,
        origin_proposal_id=row.id,
        confirm=True,
    )
    row.status = "accepted"
    row.decided_at = now
    row.review_at = now + timedelta(days=REVIEW_AFTER_DAYS)
    new_delta = dict(row.delta or {})
    new_delta["field"] = field
    new_delta["action"] = act
    new_delta["from"] = None
    # Reflect the stored homework item (with expires_on for weekly)
    stored = (payload.get(field) or [])[-1] if payload.get(field) else item
    new_delta["to"] = stored
    row.delta = new_delta
    db.flush()
    return {
        "proposal": proposal_dict(row),
        "preferences": active_dict(db, user_id),
        "prefs_version": prefs_row.version,
    }


def decline_proposal(db: Session, user_id, proposal_id) -> dict:
    from backend.models import PreferenceProposal

    expire_stale(db, user_id)
    row = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.id == proposal_id,
            PreferenceProposal.user_id == user_id,
        )
        .first()
    )
    if row is None:
        raise LookupError("proposal not found")
    if row.status != "proposed":
        raise ValueError(f"proposal status is {row.status}, expected proposed")
    row.status = "declined"
    row.decided_at = _now()
    db.flush()
    return {"proposal": proposal_dict(row)}


def run_reviews(db: Session, user_id, findings: list[dict], week_start) -> list[Any]:
    """At review_at: gap_closed vs gap_persists (+ optional next-step proposal)."""
    from backend.models import PreferenceProposal

    now = _now()
    due = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.user_id == user_id,
            PreferenceProposal.status == "accepted",
            PreferenceProposal.review_at <= now,
            PreferenceProposal.review_outcome.is_(None),
        )
        .all()
    )
    firing = {f.get("code") for f in (findings or []) if isinstance(f, dict)}
    new_props = []
    for r in due:
        code = r.gap_code
        if code == "safety_rollback":
            r.review_outcome = "gap_closed"
            continue
        if code in firing:
            r.review_outcome = "gap_persists"
            # Next step if not at max and prior active ≥ 2 weeks
            field = (r.delta or {}).get("field")
            if field and not _open_proposal_for_field(db, user_id, field):
                if not _accepted_still_ramping(db, user_id, field):
                    # Temporarily treat as past ramp by clearing the check via age
                    mapping = GAP_TO_PREF_DELTA.get(code)
                    if mapping:
                        active = ensure_active(db, user_id)
                        payload = deepcopy(active.payload or {})
                        stepped = apply_step(payload, field, int(mapping["step"]))
                        if stepped is not None:
                            cur = get_field(payload, field)
                            new_val = get_field(stepped, field)
                            prop = PreferenceProposal(
                                user_id=user_id,
                                gap_code=code,
                                finding_ref=r.finding_ref,
                                delta={"field": field, "from": cur, "to": new_val},
                                status="proposed",
                                proposed_at=now,
                                expires_at=now + timedelta(days=PROPOSAL_EXPIRE_DAYS),
                                dismissed_severity=r.dismissed_severity,
                            )
                            db.add(prop)
                            db.flush()
                            new_props.append(prop)
        else:
            r.review_outcome = "gap_closed"
    db.flush()
    return new_props


def check_safety_rollback(db: Session, user_id, *, acwr: float | None, has_niggle: bool) -> Any | None:
    """If load_adding accept within 14d and ACWR high or niggle → revert proposal."""
    from backend.models import PreferenceProposal
    from backend.services.acwr import HIGH_BOUND

    now = _now()
    cutoff = now - timedelta(days=SAFETY_ROLLBACK_WINDOW_DAYS)
    accepted = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.user_id == user_id,
            PreferenceProposal.status == "accepted",
            PreferenceProposal.decided_at >= cutoff,
            PreferenceProposal.gap_code != "safety_rollback",
        )
        .order_by(PreferenceProposal.decided_at.desc())
        .all()
    )
    trigger = (acwr is not None and acwr > HIGH_BOUND) or has_niggle
    if not trigger:
        return None

    for r in accepted:
        field = (r.delta or {}).get("field")
        meta = field_meta(field or "") or {}
        if not meta.get("load_adding"):
            continue
        # Don't stack duplicate rollback proposals
        existing = (
            db.query(PreferenceProposal)
            .filter(
                PreferenceProposal.user_id == user_id,
                PreferenceProposal.status == "proposed",
                PreferenceProposal.gap_code == "safety_rollback",
            )
            .all()
        )
        for e in existing:
            if (e.delta or {}).get("field") == field:
                return e

        from_v = (r.delta or {}).get("to")
        to_v = (r.delta or {}).get("from")
        row = PreferenceProposal(
            user_id=user_id,
            gap_code="safety_rollback",
            finding_ref=str(r.id),
            delta={"field": field, "from": from_v, "to": to_v, "reverts": str(r.id)},
            status="proposed",
            proposed_at=now,
            expires_at=now + timedelta(days=PROPOSAL_EXPIRE_DAYS),
        )
        db.add(row)
        db.flush()
        return row
    return None


def accept_rollback_marks_original(db: Session, user_id, proposal_id) -> dict:
    """Accept a safety_rollback proposal and mark original as reverted."""
    from backend.models import PreferenceProposal
    import uuid as _uuid

    row = (
        db.query(PreferenceProposal)
        .filter(PreferenceProposal.id == proposal_id, PreferenceProposal.user_id == user_id)
        .first()
    )
    orig_id = (row.delta or {}).get("reverts") if row else None
    result = accept_proposal(db, user_id, proposal_id)
    if orig_id:
        try:
            oid = _uuid.UUID(str(orig_id))
        except (ValueError, TypeError):
            oid = None
        if oid:
            orig = (
                db.query(PreferenceProposal)
                .filter(PreferenceProposal.id == oid, PreferenceProposal.user_id == user_id)
                .first()
            )
            if orig:
                orig.status = "reverted"
                orig.review_outcome = "reverted"
                db.flush()
                result["reverted_proposal_id"] = str(oid)
    row = (
        db.query(PreferenceProposal)
        .filter(PreferenceProposal.id == proposal_id, PreferenceProposal.user_id == user_id)
        .first()
    )
    if row:
        result["proposal"] = proposal_dict(row)
    return result


def title_for_proposal(delta: dict) -> str:
    field = (delta or {}).get("field") or ""
    to_v = (delta or {}).get("to")
    fr = (delta or {}).get("from")
    labels = {
        "plyo_sessions_per_week": "plyo session / week",
        "long_run.mp_segment_min": "min MP segment in long run",
        "stretch_daily_min": "min daily stretch",
        "strength_emphasis": "strength training emphasis",
    }
    label = labels.get(field, field.replace("_", " ").replace(".", " "))
    if field == "strength_emphasis":
        try:
            opts = enum_options(field) or ()
            step = opts.index(str(to_v)) - opts.index(str(fr))
            verb = "increase" if step > 0 else "decrease"
        except (ValueError, TypeError):
            verb = "change"
        return f"PROPOSAL · {verb} {label} ({fr} → {to_v})"
    try:
        step = int(to_v) - int(fr)
        verb = "add" if step > 0 else "reduce"
        mag = abs(step)
    except (TypeError, ValueError):
        verb, mag = "change", to_v
    return f"PROPOSAL · {verb} {mag} {label}"


def delta_strip(delta: dict) -> str:
    field = (delta or {}).get("field") or ""
    short = {
        "plyo_sessions_per_week": "plyo / week",
        "long_run.mp_segment_min": "long-run MP min",
        "stretch_daily_min": "stretch min / day",
        "strength_emphasis": "strength emphasis",
    }.get(field, field)
    return f"{short}: {(delta or {}).get('from')} → {(delta or {}).get('to')}"
