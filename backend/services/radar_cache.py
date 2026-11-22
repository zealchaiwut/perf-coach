"""Cached radar payload (axes only — SVG rendered per request)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Callable, Optional

from sqlalchemy.orm import Session

from backend.services.derived_cache import get_or_compute
from backend.services.radar_payload import build_radar

DERIVED_RADAR_KEY = "derived:radar"


def get_radar_payload(
    session: Session,
    user_id: uuid.UUID,
    as_of: date,
    *,
    focus_ranker: Optional[Callable] = None,
) -> dict:
    def _compute():
        return build_radar(session, user_id, as_of, focus_ranker=focus_ranker)

    if focus_ranker is not None:
        return _compute()
    return get_or_compute(session, user_id, DERIVED_RADAR_KEY, as_of, _compute)