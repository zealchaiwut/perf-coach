"""Mobility axis score from the monthly self-test (revamp P4-5).

- Form: knee-to-wall left and right (cm, 0..30), sit-and-reach (cm, -20..40), date.
- Sub-scores, clamped 0..100:
    knee-to-wall  = min(left, right) / 12 x 100   (asymmetry rule: the weaker side counts)
    sit-and-reach = (value + 10) / 30 x 100
- Score = rounded mean of the two sub-scores. The latest test wins.
- Stale (and the Performance page shows a test-due chip) after 45 days.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional

from backend.services.axis_spec import staleness_mobility

KNEE_TO_WALL_MIN_CM, KNEE_TO_WALL_MAX_CM = 0.0, 30.0
SIT_AND_REACH_MIN_CM, SIT_AND_REACH_MAX_CM = -20.0, 40.0


class MobilityValidationError(ValueError):
    """Raised with a field-specific message (mapped to HTTP 422)."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def knee_to_wall_sub_score(left_cm: float, right_cm: float) -> float:
    return _clamp(min(float(left_cm), float(right_cm)) / 12.0 * 100.0)


def sit_and_reach_sub_score(value_cm: float) -> float:
    return _clamp((float(value_cm) + 10.0) / 30.0 * 100.0)


def mobility_score(left_cm: float, right_cm: float, sit_and_reach_cm: float) -> int:
    k = knee_to_wall_sub_score(left_cm, right_cm)
    s = sit_and_reach_sub_score(sit_and_reach_cm)
    return int(round((k + s) / 2.0))


def validate_test_input(
    left_cm: Any, right_cm: Any, sit_and_reach_cm: Any, test_date: Optional[date], today: date
) -> None:
    def num(v, field):
        if isinstance(v, bool) or v is None:
            raise MobilityValidationError(field, f"{field} is required")
        try:
            return float(v)
        except (TypeError, ValueError):
            raise MobilityValidationError(field, f"{field} must be a number")

    for v, field in ((left_cm, "knee_to_wall_left_cm"), (right_cm, "knee_to_wall_right_cm")):
        n = num(v, field)
        if not (KNEE_TO_WALL_MIN_CM <= n <= KNEE_TO_WALL_MAX_CM):
            raise MobilityValidationError(field, f"{field} must be between 0 and 30 cm")
    n = num(sit_and_reach_cm, "sit_and_reach_cm")
    if not (SIT_AND_REACH_MIN_CM <= n <= SIT_AND_REACH_MAX_CM):
        raise MobilityValidationError("sit_and_reach_cm", "sit_and_reach_cm must be between -20 and 40 cm")
    if test_date is None:
        raise MobilityValidationError("test_date", "test_date is required")
    if test_date > today:
        raise MobilityValidationError("test_date", "test_date cannot be in the future")


def compute_mobility(latest: Any, as_of: date) -> dict[str, Any]:
    """Axis block from the latest test row (dict or ORM) or None."""
    base: dict[str, Any] = {
        "axis": "mobility",
        "score": None,
        "raw": None,
        "sub_scores": None,
        "never_measured": True,
        "stale": True,
        "test_due": True,
        "days_since_test": None,
        "delta_28d": None,
        "anchor_date": None,
        "anchor_title": None,
    }
    if latest is None:
        return base

    def g(k):
        return latest.get(k) if isinstance(latest, dict) else getattr(latest, k)

    left, right, sar = float(g("knee_to_wall_left_cm")), float(g("knee_to_wall_right_cm")), float(g("sit_and_reach_cm"))
    test_date = g("test_date")
    days = (as_of - test_date).days
    stale = staleness_mobility(days)
    base.update(
        score=mobility_score(left, right, sar),
        raw={"knee_to_wall_min_cm": min(left, right), "knee_to_wall_left_cm": left,
             "knee_to_wall_right_cm": right, "sit_and_reach_cm": sar},
        sub_scores={
            "knee_to_wall": round(knee_to_wall_sub_score(left, right), 1),
            "sit_and_reach": round(sit_and_reach_sub_score(sar), 1),
        },
        never_measured=False,
        stale=stale,
        test_due=stale,
        days_since_test=days,
        anchor_date=test_date.isoformat(),
    )
    return base


def latest_test(session, user_id: uuid.UUID, as_of: date):
    from backend.models import MobilityTest as M

    return (
        session.query(M)
        .filter(M.user_id == user_id, M.test_date <= as_of)
        .order_by(M.test_date.desc(), M.created_at.desc())
        .first()
    )


def get_mobility(session, user_id: uuid.UUID, as_of: date) -> dict[str, Any]:
    return compute_mobility(latest_test(session, user_id, as_of), as_of)


def mobility_test_dict(row) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "test_date": row.test_date.isoformat(),
        "knee_to_wall_left_cm": float(row.knee_to_wall_left_cm),
        "knee_to_wall_right_cm": float(row.knee_to_wall_right_cm),
        "sit_and_reach_cm": float(row.sit_and_reach_cm),
        "score": mobility_score(row.knee_to_wall_left_cm, row.knee_to_wall_right_cm, row.sit_and_reach_cm),
    }


AXIS_FUNCS = {"mobility": get_mobility}
