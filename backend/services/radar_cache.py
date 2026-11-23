"""Cached radar payload (axes only — SVG rendered per request)."""
from __future__ import annotations

import copy
import uuid
from datetime import date
from typing import Callable, Optional

from sqlalchemy.orm import Session

from backend.services.derived_cache import get_or_compute

DERIVED_RADAR_KEY = "derived:radar"


def get_radar_payload(
    session: Session,
    user_id: uuid.UUID,
    as_of: date,
    *,
    focus_ranker: Optional[Callable] = None,
) -> dict:
    def _compute():
        from backend.services.radar_payload import build_radar

        return build_radar(session, user_id, as_of)

    payload = copy.deepcopy(
        get_or_compute(session, user_id, DERIVED_RADAR_KEY, as_of, _compute)
    )
    if focus_ranker is not None:
        from backend.services.radar_payload import apply_focus_ranker

        apply_focus_ranker(payload, focus_ranker)
    return payload
