"""Reference rule: no_recent_plyo (issue #1370).

Fires when the user has not completed a plyometric session in the last 28 days.
Severity 1 (note). Input requirement: structural_dose (from #1369 recency field).
"""
from __future__ import annotations

from typing import Optional

from backend.services.gap_analysis.schemas import GapAnalysisFinding

PLYO_RECENCY_THRESHOLD_DAYS = 28


def no_recent_plyo(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Return severity-1 finding when no plyo session in the last 28 days.

    Returns None when a recent plyo session exists.
    """
    dose = inputs["structural_dose"]
    days_ago = dose.get("last_plyo_days_ago")

    if days_ago is not None and days_ago <= PLYO_RECENCY_THRESHOLD_DAYS:
        return None

    evidence = [
        {
            "metric": "days_since_plyo",
            "value": days_ago,
            "threshold": PLYO_RECENCY_THRESHOLD_DAYS,
            "window": "28d",
        }
    ]
    return GapAnalysisFinding(
        code="no_recent_plyo",
        severity=1,
        recommendation="Schedule a plyometric session this week to maintain reactive strength.",
        evidence=evidence,
        target="plyo",
        week_start=inputs["week_start"],
    )
