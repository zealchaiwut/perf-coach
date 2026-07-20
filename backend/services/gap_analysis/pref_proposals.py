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
    apply_step,
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
GAP_TO_PREF_DELTA: dict[str, dict[str, Any]] = {
    "plyo_deficit": {"field": "plyo_sessions_per_week", "step": +1},
    "no_recent_plyo": {"field": "plyo_sessions_per_week", "step": +1},
    "aerobic_durability_gap": {"field": "long_run.mp_segment_min", "step": +10},
    # stretch_neglect lands when that gap rule ships
}


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
        if not code or code not in GAP_TO_PREF_DELTA:
            continue
        severity = int(
            f.get("severity") if isinstance(f, dict) else getattr(f, "severity", 1) or 1
        )
        mapping = GAP_TO_PREF_DELTA[code]
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

        cur = get_field(payload, field)
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
        new_val = get_field(stepped, field)
        evidence = f.get("evidence") if isinstance(f, dict) else getattr(f, "evidence", None)
        finding_ref = evidence_hash(evidence or [])[:32]

        now = _now()
        row = PreferenceProposal(
            user_id=user_id,
            gap_code=code,
            finding_ref=finding_ref,
            delta={"field": field, "from": cur_i, "to": new_val},
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
            user_id, field, cur_i, new_val, code, weeks,
        )
    return created


def accept_proposal(
    db: Session,
    user_id,
    proposal_id,
    *,
    adjusted_to: Any | None = None,
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

    field = (row.delta or {}).get("field")
    from_v = (row.delta or {}).get("from")
    to_v = adjusted_to if adjusted_to is not None else (row.delta or {}).get("to")
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
    }
    label = labels.get(field, field.replace("_", " ").replace(".", " "))
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
    }.get(field, field)
    return f"{short}: {(delta or {}).get('from')} → {(delta or {}).get('to')}"
