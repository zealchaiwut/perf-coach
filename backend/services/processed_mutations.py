"""Idempotent client mutation ledger (PWA P0-1)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import ProcessedMutation

MUTATION_TTL_DAYS = 30


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _get(session: Session, user_id, client_mutation_id) -> ProcessedMutation | None:
    return (
        session.query(ProcessedMutation)
        .filter(
            ProcessedMutation.user_id == _as_uuid(user_id),
            ProcessedMutation.client_mutation_id == _as_uuid(client_mutation_id),
        )
        .first()
    )


def apply_once(
    session: Session,
    user_id,
    client_mutation_id,
    op_type: str,
    fn: Callable[[], Any],
) -> Any:
    """Run ``fn`` once per (user, client_mutation_id). Repeat calls return the stored result.

    Claims the unique (user_id, client_mutation_id) row first so two concurrent
    callers cannot both execute ``fn``. The unique constraint is the lock.
    """
    existing = _get(session, user_id, client_mutation_id)
    if existing is not None and existing.result is not None:
        return existing.result

    nested = session.begin_nested()
    row = ProcessedMutation(
        user_id=_as_uuid(user_id),
        client_mutation_id=_as_uuid(client_mutation_id),
        op_type=op_type,
        result=None,
    )
    try:
        session.add(row)
        session.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()
        stored = _get(session, user_id, client_mutation_id)
        if stored is None:
            raise
        return stored.result

    try:
        result = fn()
    except Exception:
        session.delete(row)
        session.flush()
        raise
    row.result = result
    session.flush()
    return result


def cleanup_old_mutations(session: Session, *, now: datetime | None = None) -> int:
    """Delete ledger rows older than 30 days. Returns the number removed."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MUTATION_TTL_DAYS)
    q = session.query(ProcessedMutation).filter(ProcessedMutation.received_at < cutoff)
    n = q.count()
    q.delete(synchronize_session=False)
    session.flush()
    return n
