"""injury_log_service — DB operations for /api/injury-log CRUD (issue #1350).

All DB interaction lives here; the router contains no raw ORM calls.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date as _date
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import InjuryLog


def _to_dict(row: InjuryLog) -> dict:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "kind": row.kind,
        "body_area": row.body_area,
        "severity": row.severity,
        "started_on": str(row.started_on),
        "ended_on": str(row.ended_on) if row.ended_on is not None else None,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_entries(
    user_id: _uuid.UUID,
    from_date: Optional[_date] = None,
    to_date: Optional[_date] = None,
) -> list[dict]:
    with Session(engine) as db:
        q = db.query(InjuryLog).filter(InjuryLog.user_id == user_id)
        if from_date is not None:
            q = q.filter(InjuryLog.started_on >= from_date)
        if to_date is not None:
            q = q.filter(InjuryLog.started_on <= to_date)
        rows = q.order_by(InjuryLog.started_on.desc()).all()
        return [_to_dict(r) for r in rows]


def list_active(user_id: _uuid.UUID) -> list[dict]:
    with Session(engine) as db:
        rows = (
            db.query(InjuryLog)
            .filter(InjuryLog.user_id == user_id, InjuryLog.ended_on.is_(None))
            .order_by(InjuryLog.started_on.desc())
            .all()
        )
        return [_to_dict(r) for r in rows]


def create_entry(
    user_id: _uuid.UUID,
    kind: str,
    severity: int,
    started_on: str,
    body_area: Optional[str] = None,
    ended_on: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    with Session(engine) as db:
        row = InjuryLog(
            user_id=user_id,
            kind=kind,
            body_area=body_area,
            severity=severity,
            started_on=_date.fromisoformat(started_on),
            ended_on=_date.fromisoformat(ended_on) if ended_on else None,
            notes=notes,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_dict(row)


_MUTABLE_FIELDS = {"kind", "body_area", "severity", "started_on", "ended_on", "notes"}


def update_entry(
    entry_id: _uuid.UUID,
    user_id: _uuid.UUID,
    fields: dict[str, Any],
) -> Optional[dict]:
    with Session(engine) as db:
        row = db.get(InjuryLog, entry_id)
        if row is None or row.user_id != user_id:
            return None
        for key, value in fields.items():
            if key not in _MUTABLE_FIELDS:
                continue
            if key in ("started_on", "ended_on") and value is not None:
                value = _date.fromisoformat(str(value))
            setattr(row, key, value)
        db.commit()
        db.refresh(row)
        return _to_dict(row)


def delete_entry(entry_id: _uuid.UUID, user_id: _uuid.UUID) -> bool:
    with Session(engine) as db:
        row = db.get(InjuryLog, entry_id)
        if row is None or row.user_id != user_id:
            return False
        db.delete(row)
        db.commit()
        return True
