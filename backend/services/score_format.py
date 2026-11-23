"""Integer display for 0–100 scores.

Half rounds up (52.5 → 53). Python's ``round`` uses banker's rounding
(52.5 → 52), which made the radar, focus header and why list disagree
when JS used ``Math.round``.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union

Number = Union[int, float, str, Decimal]


def display_score(x: Optional[Number]) -> Optional[int]:
    if x is None:
        return None
    return int(Decimal(str(x)).quantize(Decimal("0"), rounding=ROUND_HALF_UP))
