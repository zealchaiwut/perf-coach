"""Pydantic schema for gap analyzer findings (issue #1370)."""
from __future__ import annotations

import datetime
from typing import Any, Optional

from pydantic import BaseModel


class GapAnalysisFinding(BaseModel):
    """Machine-readable finding emitted by one rule.

    code          — stable string id (e.g. 'no_recent_plyo')
    severity      — 1=note, 2=recommend, 3=priority
    recommendation — short imperative sentence for the athlete
    evidence      — [{metric, value, threshold, window}] machine-readable only
    target        — nullable muscle group or session type
    week_start    — ISO week Monday this finding belongs to
    """

    code: str
    severity: int
    recommendation: str
    evidence: list[dict[str, Any]]
    target: Optional[str] = None
    week_start: datetime.date
