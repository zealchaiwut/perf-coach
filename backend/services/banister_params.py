"""Per-user Banister parameter storage with versioned history (issue #1204).

Population defaults (τ1=50.0, τ2=11.0, k1=1.0, k2=2.0) are returned for
users with no stored fit, keeping existing model consumers backward-compatible.

Each call to save_banister_params inserts a new row; prior rows are never
overwritten, so a full audit trail of refits is available via
list_banister_param_versions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.models import UserBanisterParams

# Population-level defaults from Banister (1991).
POPULATION_DEFAULTS: dict[str, float] = {
    "tau1": 50.0,
    "tau2": 11.0,
    "k1": 1.0,
    "k2": 2.0,
}


def save_banister_params(
    session: Session,
    user_id: Any,
    tau1: float,
    tau2: float,
    k1: float,
    k2: float,
) -> dict:
    """Insert a new versioned Banister parameter record for *user_id*.

    Prior records are never overwritten; each call creates a new row.
    Returns the serialised record dict.
    """
    record = UserBanisterParams(
        user_id=user_id,
        tau1=float(tau1),
        tau2=float(tau2),
        k1=float(k1),
        k2=float(k2),
        fitted_at=datetime.now(timezone.utc),
    )
    session.add(record)
    session.flush()
    return _to_dict(record)


def get_banister_params(session: Session, user_id: Any) -> dict:
    """Return the most-recently fitted Banister params for *user_id*.

    Falls back to POPULATION_DEFAULTS when no row exists, so existing callers
    are unaffected when no stored params have been saved yet.
    """
    record = (
        session.query(UserBanisterParams)
        .filter(UserBanisterParams.user_id == user_id)
        .order_by(UserBanisterParams.fitted_at.desc(), UserBanisterParams.id.desc())
        .first()
    )
    if record is None:
        return dict(POPULATION_DEFAULTS)
    return _to_dict(record)


def list_banister_param_versions(session: Session, user_id: Any) -> list:
    """Return all stored Banister params for *user_id*, newest first."""
    rows = (
        session.query(UserBanisterParams)
        .filter(UserBanisterParams.user_id == user_id)
        .order_by(UserBanisterParams.fitted_at.desc(), UserBanisterParams.id.desc())
        .all()
    )
    return [_to_dict(r) for r in rows]


def _to_dict(record: UserBanisterParams) -> dict:
    return {
        "id": record.id,
        "user_id": str(record.user_id),
        "tau1": float(record.tau1),
        "tau2": float(record.tau2),
        "k1": float(record.k1),
        "k2": float(record.k2),
        "fitted_at": record.fitted_at.isoformat() if record.fitted_at else None,
    }
