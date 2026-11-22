"""Monotonic data version per user — invalidates derived caches on meaningful writes."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import User


def get_data_version(session: Session, user_id: uuid.UUID) -> int:
    row = session.get(User, user_id)
    if row is None:
        return 0
    return int(getattr(row, "data_version", None) or 0)


def bump_data_version(session: Session, user_id: uuid.UUID) -> int:
    """Increment and return the new version (flush only — caller commits)."""
    row = session.get(User, user_id)
    if row is None:
        return 0
    next_v = int(getattr(row, "data_version", None) or 0) + 1
    row.data_version = next_v
    session.flush()
    return next_v