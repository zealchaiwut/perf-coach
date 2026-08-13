"""Shared durable summary_cache helpers (worker-safe, no backend.main import).

Used by the web GET path (read latest row, never wait on a recompute) and by
the worker precompute path (write a fresh payload). Signature matching is
still the freshness check — a mismatched signature means the row is stale
and the worker should refresh it — but a stale row is still served to the
browser so page load stays a SELECT.
"""
from __future__ import annotations

from datetime import datetime as _datetime, timezone as _timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import SummaryCache, Workout
from backend.utils.log import get_logger

_log = get_logger(__name__)

_SUMMARY_CACHE: dict = {}


def l1_cacheable(key: str) -> bool:
    """Fixed keys are bounded by active users; per-period keys are not."""
    return not key.startswith("monthly:") and not key.startswith("weekly:")


def summary_signature(session, user_id) -> str:
    row = (
        session.query(
            func.max(Workout.created_at),
            func.count(Workout.id),
            func.max(Workout.updated_at),
        )
        .filter(Workout.user_id == user_id)
        .one()
    )
    return "%s|%s|%s" % (row[0], row[1], row[2])


def summary_cache_get(user_id, key, sig):
    """Return payload only when the stored signature matches ``sig``."""
    cacheable = l1_cacheable(key)
    if cacheable:
        ent = _SUMMARY_CACHE.get((str(user_id), key))
        if ent and ent[0] == sig:
            return ent[1]

    try:
        with Session(engine) as _s:
            row = (
                _s.query(SummaryCache.signature, SummaryCache.payload)
                .filter(
                    SummaryCache.user_id == user_id,
                    SummaryCache.cache_key == key,
                )
                .first()
            )
        if row is not None and row[0] == sig:
            payload = row[1]
            if cacheable:
                _SUMMARY_CACHE[(str(user_id), key)] = (sig, payload)
            return payload
    except Exception:
        _log.exception("summary_cache L2 read failed for %s/%s", user_id, key)
    return None


def summary_cache_get_latest(user_id, key):
    """Return the last stored payload for ``key``, ignoring signature.

    Used by dashboard GETs so a post-sync signature bump does not force the
    web request to recompute. ``None`` when no row exists yet.
    """
    cacheable = l1_cacheable(key)
    if cacheable:
        ent = _SUMMARY_CACHE.get((str(user_id), key))
        if ent:
            return ent[1]

    try:
        with Session(engine) as _s:
            row = (
                _s.query(SummaryCache.signature, SummaryCache.payload)
                .filter(
                    SummaryCache.user_id == user_id,
                    SummaryCache.cache_key == key,
                )
                .first()
            )
        if row is not None:
            payload = row[1]
            if cacheable:
                _SUMMARY_CACHE[(str(user_id), key)] = (row[0], payload)
            return payload
    except Exception:
        _log.exception("summary_cache L2 latest-read failed for %s/%s", user_id, key)
    return None


def summary_cache_put(user_id, key, sig, payload):
    """Two-level cache write: L1 (if bounded) then UPSERT the durable L2 row."""
    if l1_cacheable(key):
        _SUMMARY_CACHE[(str(user_id), key)] = (sig, payload)
    try:
        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        stmt = _pg_insert(SummaryCache.__table__).values(
            user_id=user_id,
            cache_key=key,
            signature=sig,
            payload=payload,
            updated_at=_datetime.now(_timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "cache_key"],
            set_={
                "signature": stmt.excluded.signature,
                "payload": stmt.excluded.payload,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        with Session(engine) as _s:
            _s.execute(stmt)
            _s.commit()
    except Exception:
        _log.exception("summary_cache L2 write failed for %s/%s", user_id, key)
