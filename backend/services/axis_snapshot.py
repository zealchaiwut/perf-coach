"""Shared daily snapshot of the Phase 4 axes (revamp P4-2).

One row per (user, day, formula_version) in ``performance_score_history`` —
the same table that already stores endurance/speed. Writing is idempotent
(``ON CONFLICT DO UPDATE``) so a rerun on the same day replaces that day's row.

Axis computers register in ``AXIS_COMPUTERS`` (axis -> fn(session, user_id,
as_of) -> axis block). Later axes (economy, strength, power_to_weight,
mobility) add themselves via ``register_axis``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any, Callable, Dict, Optional

from backend.services.formula_versions import SCORE_VERSION

logger = logging.getLogger(__name__)

AxisComputer = Callable[[Any, uuid.UUID, date], Dict[str, Any]]

AXIS_COMPUTERS: dict[str, AxisComputer] = {}

# Snapshot columns owned by this module (the new axes); endurance/speed keep
# their existing writer in performance_scores.
SNAPSHOT_AXES: tuple[str, ...] = (
    "durability",
    "economy",
    "strength",
    "mobility",
    "power_to_weight",
)


def register_axis(axis: str, fn: AxisComputer) -> None:
    AXIS_COMPUTERS[axis] = fn


# Modules that expose ``AXIS_FUNCS = {axis: fn}``; later P4 tickets append here.
_AXIS_MODULES: tuple[str, ...] = ("axis_durability",)


def _load_computers() -> None:
    """Register every axis module's functions (idempotent)."""
    import importlib

    for mod_name in _AXIS_MODULES:
        mod = importlib.import_module(f"backend.services.{mod_name}")
        for axis, fn in mod.AXIS_FUNCS.items():
            register_axis(axis, fn)


def compute_axes(session, user_id: uuid.UUID, as_of: date) -> dict[str, dict]:
    """Compute every registered new-axis block. One failing axis never breaks the rest."""
    _load_computers()
    out: dict[str, dict] = {}
    for axis in SNAPSHOT_AXES:
        fn = AXIS_COMPUTERS.get(axis)
        if fn is None:
            continue
        try:
            out[axis] = fn(session, user_id, as_of)
        except Exception:
            logger.warning("axis %s compute failed for user %s", axis, user_id, exc_info=True)
    return out


def snapshot_values(blocks: dict[str, dict]) -> dict[str, Optional[float]]:
    return {
        axis: (float(b["score"]) if b.get("score") is not None else None)
        for axis, b in blocks.items()
    }


def upsert_axis_snapshot(
    session,
    user_id: uuid.UUID,
    score_date: date,
    values: dict[str, Optional[float]],
    *,
    endurance: Optional[float] = None,
    speed: Optional[float] = None,
    formula_version: str = SCORE_VERSION,
) -> None:
    """Upsert the new-axis columns for one day.

    ``endurance``/``speed`` are only used when the row does not exist yet (so a
    snapshot-first row is not left with NULLs); an existing row's endurance/speed
    is never overwritten here.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.models import PerformanceScoreHistory

    cols = {k: v for k, v in values.items() if k in SNAPSHOT_AXES}
    stmt = pg_insert(PerformanceScoreHistory).values(
        user_id=user_id,
        score_date=score_date,
        endurance=endurance,
        speed=speed,
        formula_version=formula_version,
        **cols,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_performance_score_history_user_date_version",
        set_={k: getattr(stmt.excluded, k) for k in cols},
    )
    session.execute(stmt)
    session.commit()


def snapshot_user(session, user_id: uuid.UUID, as_of: date, *, overall: Optional[dict] = None) -> dict[str, Any]:
    """Compute and store today's new-axis snapshot for one user. Returns the blocks."""
    blocks = compute_axes(session, user_id, as_of)
    values = snapshot_values(blocks)
    end = spd = None
    if overall:
        end = (overall.get("endurance") or {}).get("score")
        spd = (overall.get("speed") or {}).get("score")
    try:
        upsert_axis_snapshot(session, user_id, as_of, values, endurance=end, speed=spd)
    except Exception:
        logger.warning("axis snapshot upsert failed for user %s", user_id, exc_info=True)
        session.rollback()
    return blocks


def snapshot_row_on_or_before(session, user_id: uuid.UUID, day: date, *, formula_version: str = SCORE_VERSION):
    """Latest snapshot row on/before ``day`` (None when history does not reach back)."""
    from backend.models import PerformanceScoreHistory as H

    return (
        session.query(H)
        .filter(H.user_id == user_id, H.score_date <= day, H.formula_version == formula_version)
        .order_by(H.score_date.desc(), H.created_at.desc())
        .first()
    )


def score_n_days_ago(session, user_id: uuid.UUID, as_of: date, axis: str, days: int = 28) -> Optional[float]:
    """Stored score for ``axis`` from the snapshot at (as_of - days) or earlier."""
    from datetime import timedelta

    row = snapshot_row_on_or_before(session, user_id, as_of - timedelta(days=days))
    return getattr(row, axis, None) if row is not None else None


def run_daily_snapshot(as_of: Optional[date] = None) -> dict[str, str]:
    """Snapshot every active user (worker entry point). Returns user_id -> ok|error."""
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User
    from backend.services import score_reader
    from backend.utils.time import today_bangkok

    day = as_of or today_bangkok()
    results: dict[str, str] = {}
    with Session(engine) as s:
        users = [r.id for r in s.query(User.id).filter(User.is_active.is_(True)).all()]
    for uid in users:
        try:
            with Session(engine) as s:
                try:
                    overall = score_reader.get_scores(uid, as_of=day)["overall"]
                except Exception:
                    overall = None
                snapshot_user(s, uid, day, overall=overall)
            results[str(uid)] = "ok"
        except Exception:
            logger.warning("daily axis snapshot failed for %s", uid, exc_info=True)
            results[str(uid)] = "error"
    return results
