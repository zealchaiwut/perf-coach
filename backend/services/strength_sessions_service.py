"""strength_sessions_service — DB operations for strength and plyo session CRUD (issue #1144).

All DB interaction lives here; routers contain no raw SQL or ORM calls.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date as _date, datetime as _datetime, timezone as _tz
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import PlyoSession, StrengthSession

_VALID_PLYO_PHASES = frozenset(("intro", "build", "maintain"))


# ── Serialisers ───────────────────────────────────────────────────────────────

def _strength_to_dict(row: StrengthSession) -> dict:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "session_date": str(row.session_date),
        "sets": row.sets,
        "reps": row.reps,
        "load": float(row.load) if row.load is not None else None,
        "session_rpe": row.session_rpe,
        "duration_minutes": row.duration_minutes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _plyo_to_dict(row: PlyoSession) -> dict:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "session_date": str(row.session_date),
        "foot_contacts": row.foot_contacts,
        "plyo_phase": row.plyo_phase,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── Strength session operations ───────────────────────────────────────────────

def list_strength_sessions(user_id: _uuid.UUID) -> list[dict]:
    with Session(engine) as db:
        rows = (
            db.query(StrengthSession)
            .filter(StrengthSession.user_id == user_id)
            .order_by(StrengthSession.session_date.desc())
            .all()
        )
        return [_strength_to_dict(r) for r in rows]


def get_strength_session(session_id: _uuid.UUID, user_id: _uuid.UUID) -> Optional[dict]:
    with Session(engine) as db:
        row = db.get(StrengthSession, session_id)
        if row is None or row.user_id != user_id:
            return None
        return _strength_to_dict(row)


def create_strength_session(
    user_id: _uuid.UUID,
    session_date: str,
    sets: Optional[int] = None,
    reps: Optional[int] = None,
    load: Optional[float] = None,
    session_rpe: Optional[int] = None,
    duration_minutes: Optional[int] = None,
) -> dict:
    with Session(engine) as db:
        row = StrengthSession(
            user_id=user_id,
            session_date=_date.fromisoformat(session_date),
            sets=sets,
            reps=reps,
            load=load,
            session_rpe=session_rpe,
            duration_minutes=duration_minutes,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _strength_to_dict(row)


_STRENGTH_MUTABLE_FIELDS = {"session_date", "sets", "reps", "load", "session_rpe", "duration_minutes"}


def update_strength_session(
    session_id: _uuid.UUID,
    user_id: _uuid.UUID,
    fields: dict[str, Any],
) -> Optional[dict]:
    with Session(engine) as db:
        row = db.get(StrengthSession, session_id)
        if row is None or row.user_id != user_id:
            return None
        for key, value in fields.items():
            if key not in _STRENGTH_MUTABLE_FIELDS:
                continue
            if key == "session_date" and value is not None:
                value = _date.fromisoformat(str(value))
            setattr(row, key, value)
        row.updated_at = _datetime.now(_tz.utc)
        db.commit()
        db.refresh(row)
        return _strength_to_dict(row)


def delete_strength_session(session_id: _uuid.UUID, user_id: _uuid.UUID) -> bool:
    with Session(engine) as db:
        row = db.get(StrengthSession, session_id)
        if row is None or row.user_id != user_id:
            return False
        db.delete(row)
        db.commit()
        return True


# ── Plyo session operations ────────────────────────────────────────────────────

def list_plyo_sessions(user_id: _uuid.UUID) -> list[dict]:
    with Session(engine) as db:
        rows = (
            db.query(PlyoSession)
            .filter(PlyoSession.user_id == user_id)
            .order_by(PlyoSession.session_date.desc())
            .all()
        )
        return [_plyo_to_dict(r) for r in rows]


def get_plyo_session(session_id: _uuid.UUID, user_id: _uuid.UUID) -> Optional[dict]:
    with Session(engine) as db:
        row = db.get(PlyoSession, session_id)
        if row is None or row.user_id != user_id:
            return None
        return _plyo_to_dict(row)


def create_plyo_session(
    user_id: _uuid.UUID,
    session_date: str,
    foot_contacts: int,
    plyo_phase: str,
) -> dict:
    with Session(engine) as db:
        row = PlyoSession(
            user_id=user_id,
            session_date=_date.fromisoformat(session_date),
            foot_contacts=foot_contacts,
            plyo_phase=plyo_phase,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _plyo_to_dict(row)


_PLYO_MUTABLE_FIELDS = {"session_date", "foot_contacts", "plyo_phase"}


def update_plyo_session(
    session_id: _uuid.UUID,
    user_id: _uuid.UUID,
    fields: dict[str, Any],
) -> Optional[dict]:
    with Session(engine) as db:
        row = db.get(PlyoSession, session_id)
        if row is None or row.user_id != user_id:
            return None
        for key, value in fields.items():
            if key not in _PLYO_MUTABLE_FIELDS:
                continue
            if key == "session_date" and value is not None:
                value = _date.fromisoformat(str(value))
            setattr(row, key, value)
        db.commit()
        db.refresh(row)
        return _plyo_to_dict(row)


def delete_plyo_session(session_id: _uuid.UUID, user_id: _uuid.UUID) -> bool:
    with Session(engine) as db:
        row = db.get(PlyoSession, session_id)
        if row is None or row.user_id != user_id:
            return False
        db.delete(row)
        db.commit()
        return True
