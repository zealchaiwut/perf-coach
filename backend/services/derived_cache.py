"""Version-keyed derived payloads stored in ``summary_cache``."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Callable, TypeVar

from sqlalchemy.orm import Session

from backend.services.data_version import get_data_version
from backend.services.summary_cache_store import summary_cache_get, summary_cache_put
from backend.utils.log import get_logger

_log = get_logger(__name__)
T = TypeVar("T")

DERIVED_SCORE_CARDS = "derived:score_cards"
DERIVED_HERO = "derived:hero:v2"
DERIVED_PROJECTION = "derived:projection:v4"
DERIVED_RACE_LIST = "derived:race_list:v2"


def derived_signature(session: Session, user_id: uuid.UUID, as_of: date) -> str:
    return f"dv:{get_data_version(session, user_id)}|{as_of.isoformat()}"


def get_or_compute(
    session: Session,
    user_id: uuid.UUID,
    cache_key: str,
    as_of: date,
    compute: Callable[[], T],
) -> T:
    sig = derived_signature(session, user_id, as_of)
    cached = summary_cache_get(user_id, cache_key, sig)
    if cached is not None:
        _log.info("derived cache hit key=%s user=%s sig=%s", cache_key, user_id, sig)
        from backend.utils.query_log import note_radar_cache

        note_radar_cache(hit=True, key=cache_key)
        return cached
    from backend.utils.query_log import note_radar_cache

    note_radar_cache(hit=False, key=cache_key)
    payload = compute()
    summary_cache_put(user_id, cache_key, sig, payload)
    _log.info("derived cache store key=%s user=%s sig=%s", cache_key, user_id, sig)
    return payload