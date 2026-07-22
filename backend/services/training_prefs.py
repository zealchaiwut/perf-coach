"""Versioned training-preferences store + confirm / import / export."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.services.pref_catalog import (
    catalog_docs_for_template,
    default_payload,
    get_field,
    normalize_payload,
    set_field,
    strip_migrated_habit_fields,
    validate_payload,
)
from backend.utils.log import get_logger

_log = get_logger(__name__)
BANGKOK = ZoneInfo("Asia/Bangkok")
STALE_DAYS = 14
SCHEMA_VERSION = 1

_USER_PRESET_CODE_RE = re.compile(r"^user:[a-z0-9_]+$")
_HINT_RE = re.compile(r"^[\w\s,.\-:/%()+]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return datetime.now(BANGKOK).date()


def get_active(db: Session, user_id) -> Any | None:
    from backend.models import TrainingPreference

    return (
        db.query(TrainingPreference)
        .filter(TrainingPreference.user_id == user_id)
        .order_by(TrainingPreference.version.desc())
        .first()
    )


def ensure_active(db: Session, user_id) -> Any:
    """Return latest prefs row, creating v1 defaults if none."""
    row = get_active(db, user_id)
    if row is not None:
        return row
    return write_version(
        db,
        user_id,
        default_payload(),
        source="user",
        confirm=True,
    )


def write_version(
    db: Session,
    user_id,
    payload: dict,
    *,
    source: str,
    origin_gap_code: str | None = None,
    origin_proposal_id=None,
    confirm: bool = True,
    effective_from: date | None = None,
) -> Any:
    from backend.models import TrainingPreference

    payload = strip_migrated_habit_fields(payload)
    errs = validate_payload(payload)
    if errs:
        raise ValueError(errs)
    normalized = normalize_payload(payload)
    # Re-validate after normalize
    errs = validate_payload(normalized)
    if errs:
        raise ValueError(errs)

    prev = get_active(db, user_id)
    next_ver = (prev.version + 1) if prev else 1
    row = TrainingPreference(
        user_id=user_id,
        version=next_ver,
        effective_from=effective_from or _today(),
        payload=normalized,
        source=source,
        origin_gap_code=origin_gap_code,
        origin_proposal_id=origin_proposal_id,
        confirmed_at=_now() if confirm else None,
    )
    db.add(row)
    db.flush()
    return row


def confirm_active(db: Session, user_id) -> Any:
    """One-tap confirm: re-stamp confirmed_at without bumping version."""
    row = ensure_active(db, user_id)
    row.confirmed_at = _now()
    db.flush()
    return row


def maybe_carry_forward(db: Session, user_id, today: date | None = None) -> Any:
    """If a new week started without action, write carried_forward with same payload."""
    today = today or _today()
    row = ensure_active(db, user_id)
    # Monday of current week
    week_start = today - timedelta(days=today.weekday())
    if row.effective_from >= week_start:
        return row
    if row.source == "carried_forward" and row.effective_from >= week_start - timedelta(days=7):
        return row
    return write_version(
        db,
        user_id,
        deepcopy(row.payload),
        source="carried_forward",
        confirm=False,
        effective_from=week_start,
    )


def active_dict(db: Session, user_id) -> dict:
    """Serialize active prefs for API / assemble_facts."""
    row = ensure_active(db, user_id)
    confirmed = row.confirmed_at
    stale = False
    if confirmed is None:
        stale = True
    else:
        if confirmed.tzinfo is None:
            confirmed = confirmed.replace(tzinfo=timezone.utc)
        stale = (_now() - confirmed).total_seconds() > STALE_DAYS * 86400
    return {
        "version": row.version,
        "effective_from": row.effective_from.isoformat(),
        "payload": row.payload,
        "source": row.source,
        "origin_gap_code": row.origin_gap_code,
        "origin_proposal_id": str(row.origin_proposal_id) if row.origin_proposal_id else None,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "stale": stale,
    }


def update_from_user(db: Session, user_id, payload: dict) -> Any:
    return write_version(db, user_id, payload, source="user", confirm=True)


# ── Export / import ──────────────────────────────────────────────────────────


def export_bundle(db: Session, user_id) -> dict:
    from backend.models import UserCustomPreset

    prefs = active_dict(db, user_id)
    presets = (
        db.query(UserCustomPreset)
        .filter(UserCustomPreset.user_id == user_id)
        .order_by(UserCustomPreset.code)
        .all()
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "preferences": prefs["payload"],
        "presets": [{"code": p.code, **(p.payload if isinstance(p.payload, dict) else {})} for p in presets],
    }


def validate_import_bundle(raw: dict) -> dict[str, str]:
    """Field-level errors for import; empty = ok."""
    errors: dict[str, str] = {}
    if not isinstance(raw, dict):
        return {"": "body must be a JSON object"}
    prefs = raw.get("preferences")
    if prefs is None:
        errors["preferences"] = "required"
    elif not isinstance(prefs, dict):
        errors["preferences"] = "must be an object"
    else:
        errors.update(validate_payload(strip_migrated_habit_fields(prefs)))

    presets = raw.get("presets")
    if presets is None:
        presets = []
    if not isinstance(presets, list):
        errors["presets"] = "must be a list"
    else:
        for i, p in enumerate(presets):
            prefix = f"presets[{i}]"
            if not isinstance(p, dict):
                errors[prefix] = "must be an object"
                continue
            code = p.get("code")
            if not isinstance(code, str) or not _USER_PRESET_CODE_RE.match(code):
                errors[f"{prefix}.code"] = "must match ^user:[a-z0-9_]+$"
            # Built-in codes cannot be shadowed — user:* already prevents that
            constraints = p.get("constraints") or {}
            if not isinstance(constraints, dict):
                errors[f"{prefix}.constraints"] = "must be an object"
            else:
                min_tss = constraints.get("min_tss")
                if min_tss is not None:
                    try:
                        if float(min_tss) > 120:
                            errors[f"{prefix}.constraints.min_tss"] = (
                                f"{min_tss} exceeds max 120"
                            )
                    except (TypeError, ValueError):
                        errors[f"{prefix}.constraints.min_tss"] = "must be numeric"
            hints = p.get("structure_hints") or {}
            if hints and not isinstance(hints, dict):
                errors[f"{prefix}.structure_hints"] = "must be an object"
            elif isinstance(hints, dict):
                for hk, hv in hints.items():
                    if not isinstance(hv, str):
                        errors[f"{prefix}.structure_hints.{hk}"] = "must be string"
                    elif len(hv) > 80:
                        errors[f"{prefix}.structure_hints.{hk}"] = "max 80 chars"
                    elif not _HINT_RE.match(hv):
                        errors[f"{prefix}.structure_hints.{hk}"] = (
                            "invalid characters (prompt-safe charset only)"
                        )
    return errors


def import_bundle(db: Session, user_id, raw: dict) -> dict:
    """Validate + apply import. Raises ValueError(errors dict) on failure."""
    from backend.models import PreferenceImportAudit, PreferenceProposal, UserCustomPreset

    errors = validate_import_bundle(raw)
    if errors:
        raise ValueError(errors)

    prefs = normalize_payload(raw["preferences"])
    # Force load ceiling on every preset
    presets_in = raw.get("presets") or []
    cleaned_presets = []
    for p in presets_in:
        payload = {k: v for k, v in p.items() if k != "code"}
        constraints = dict(payload.get("constraints") or {})
        constraints["must_respect_load_ceiling"] = True
        payload["constraints"] = constraints
        cleaned_presets.append((p["code"], payload))

    row = write_version(db, user_id, prefs, source="user_import", confirm=True)

    # Replace custom presets
    db.query(UserCustomPreset).filter(UserCustomPreset.user_id == user_id).delete()
    for code, payload in cleaned_presets:
        db.add(UserCustomPreset(user_id=user_id, code=code, payload=payload))

    # Open coach proposals for changed fields → declined
    open_props = (
        db.query(PreferenceProposal)
        .filter(
            PreferenceProposal.user_id == user_id,
            PreferenceProposal.status == "proposed",
        )
        .all()
    )
    for prop in open_props:
        field = (prop.delta or {}).get("field")
        if field and get_field(prefs, field) != (prop.delta or {}).get("from"):
            prop.status = "declined"
            prop.decided_at = _now()

    audit = PreferenceImportAudit(
        user_id=user_id,
        raw_json=raw,
        prefs_version=row.version,
    )
    db.add(audit)
    db.flush()
    return active_dict(db, user_id)


def ai_edit_template(db: Session, user_id) -> str:
    """Static copy-paste template for an external LLM — no LLM call here."""
    bundle = export_bundle(db, user_id)
    example_preset = {
        "code": "user:easy_aerobic",
        "kind": "easy_run",
        "session_type": "run",
        "constraints": {
            "min_duration_min": 40,
            "max_duration_min": 75,
            "min_tss": 35,
            "must_respect_load_ceiling": True,
            "load_adding": True,
        },
        "structure_hints": {"effort": "Z1-Z2, conversational"},
    }
    return (
        "You are helping me edit my training-preferences JSON; obey this schema "
        "and these bounds; return only JSON.\n\n"
        f"{catalog_docs_for_template()}\n\n"
        "Example preset:\n"
        f"{json.dumps(example_preset, indent=2, sort_keys=True)}\n\n"
        "My current export:\n"
        f"{json.dumps(bundle, indent=2, sort_keys=True)}\n"
    )


def prefs_for_assemble_facts(db: Session, user_id) -> dict:
    """Shape consumed by plan_suggestions.assemble_facts."""
    maybe_carry_forward(db, user_id)
    info = active_dict(db, user_id)
    p = info["payload"]
    out = {
        "prefs_version": info["version"],
        "preferred_rest_days": list(get_field(p, "rest_days") or []),
        "strength_emphasis": get_field(p, "strength_emphasis") or "same",
        "plyo_mode": get_field(p, "plyo_mode") or "off",
        "plyo_sessions_per_week": int(get_field(p, "plyo_sessions_per_week") or 0),
        "long_run_mp_segment_min": int(get_field(p, "long_run.mp_segment_min") or 0),
        "stretch_daily_min": 0,
        "zone2_weekly_min": 0,
        "notes": get_field(p, "notes") or "",
    }
    try:
        from backend.services.coach_habit_targets import habit_targets_for_coach

        ht = habit_targets_for_coach(db, user_id, ensure=True)
        out["stretch_daily_min"] = int(ht.get("stretch_daily_min") or 0)
        out["zone2_weekly_min"] = int(ht.get("zone2_weekly_min") or 0)
    except Exception:
        pass
    return out
