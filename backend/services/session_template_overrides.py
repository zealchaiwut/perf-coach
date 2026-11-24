"""Gym-mode apply_to_future overrides for the next generated template."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import SessionTemplateOverride


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def list_overrides(session: Session, user_id) -> list[SessionTemplateOverride]:
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    return (
        session.query(SessionTemplateOverride)
        .filter(SessionTemplateOverride.user_id == uid)
        .order_by(SessionTemplateOverride.template_key, SessionTemplateOverride.exercise_key)
        .all()
    )


def override_dicts(session: Session, user_id, template_key: str) -> list[dict[str, Any]]:
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    rows = (
        session.query(SessionTemplateOverride)
        .filter(
            SessionTemplateOverride.user_id == uid,
            SessionTemplateOverride.template_key == template_key,
        )
        .all()
    )
    return [dict(r.override or {}) | {"exercise_key": r.exercise_key, "id": str(r.id)} for r in rows]


def upsert_from_edit_log(
    session: Session,
    user_id,
    template_key: str,
    edit_log: list[dict[str, Any]],
) -> int:
    if not template_key or not edit_log:
        return 0
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    n = 0
    for item in edit_log:
        if not isinstance(item, dict):
            continue
        kind = (item.get("type") or item.get("kind") or "").lower()
        key = (item.get("exercise_key") or item.get("from") or item.get("exercise") or "").strip().lower()
        if not key:
            continue
        payload: dict[str, Any] = {"type": kind}
        if kind == "swap":
            payload["replacement"] = item.get("to") or item.get("replacement")
        if item.get("kg") is not None:
            payload["kg"] = item.get("kg")
        if item.get("to_kg") is not None:
            payload["kg"] = item.get("to_kg")
        if item.get("kg_delta") is not None:
            payload["kg_delta"] = item.get("kg_delta")
        if kind in ("add_set", "added_set"):
            payload["added_sets"] = int(item.get("n") or 1)
        row = (
            session.query(SessionTemplateOverride)
            .filter(
                SessionTemplateOverride.user_id == uid,
                SessionTemplateOverride.template_key == template_key,
                SessionTemplateOverride.exercise_key == key,
            )
            .first()
        )
        if row is None:
            row = SessionTemplateOverride(
                user_id=uid,
                template_key=template_key,
                exercise_key=key,
                override=payload,
                updated_at=_utc_now(),
            )
            session.add(row)
        else:
            merged = dict(row.override or {})
            merged.update(payload)
            row.override = merged
            row.updated_at = _utc_now()
        n += 1
    return n


def delete_override(session: Session, user_id, override_id) -> bool:
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    try:
        oid = override_id if isinstance(override_id, uuid.UUID) else uuid.UUID(str(override_id))
    except ValueError:
        return False
    row = (
        session.query(SessionTemplateOverride)
        .filter(SessionTemplateOverride.id == oid, SessionTemplateOverride.user_id == uid)
        .first()
    )
    if row is None:
        return False
    session.delete(row)
    return True


def apply_overrides(exercises: list[dict[str, Any]], overrides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mutate a generated exercise list in place and return it."""
    by_key = {str(o.get("exercise_key") or "").strip().lower(): o for o in overrides if o}
    out = []
    for ex in exercises:
        name = str(ex.get("name") or "").strip()
        key = name.lower()
        ov = by_key.get(key)
        row = dict(ex)
        if ov:
            if ov.get("replacement"):
                row["name"] = ov["replacement"]
            kg = ov.get("kg")
            delta = ov.get("kg_delta")
            sets = row.get("sets")
            if isinstance(sets, list) and (kg is not None or delta is not None):
                new_sets = []
                for st in sets:
                    st = dict(st)
                    cur = float(st.get("kg") or 0)
                    if kg is not None:
                        st["kg"] = kg
                    elif delta is not None:
                        st["kg"] = cur + float(delta)
                    new_sets.append(st)
                row["sets"] = new_sets
                if kg is not None:
                    row["load"] = kg
            added = int(ov.get("added_sets") or 0)
            if added and isinstance(row.get("sets"), list) and row["sets"]:
                last = dict(row["sets"][-1])
                row["sets"] = list(row["sets"]) + [last for _ in range(added)]
        out.append(row)
    return out
