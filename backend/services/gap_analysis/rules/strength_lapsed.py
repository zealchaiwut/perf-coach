"""Rule: strength_lapsed (issue #1373).

Fires when:
  - No strength sessions at all in the last STRENGTH_LAPSED_DAYS days
    (uses last_strength_days_ago from structural_dose, issue #1369)
  AND
  - Neither recurrent_niggle_area nor undertrained_area_under_ramp already fired
    (to avoid piling generic advice on top of specific structural advice).

Severity 1 (note). Returns None when strength is recent or a specific structural
rule has already fired.
Thresholds documented in docs/calculations/gap-analysis.md.
"""
from __future__ import annotations

from typing import Optional

from backend.services.gap_analysis.schemas import GapAnalysisFinding

# ── Thresholds ────────────────────────────────────────────────────────────────

STRENGTH_LAPSED_DAYS: int = 21
"""Days without any strength session before the reminder fires."""

_SUPPRESSING_RULES: frozenset[str] = frozenset({
    "recurrent_niggle_area",
    "undertrained_area_under_ramp",
})


def strength_lapsed(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Return severity-1 general strength reminder when no strength in 21+ days.

    Returns None when:
    - structural_dose key absent
    - last_strength_days_ago < STRENGTH_LAPSED_DAYS (strength is recent)
    - Any rule in _SUPPRESSING_RULES appears in inputs['other_findings_codes']
    """
    dose = inputs.get("structural_dose")
    if dose is None:
        return None

    # Suppression: don't pile general reminder on top of specific structural rules
    other_codes: list[str] = inputs.get("other_findings_codes") or []
    if any(code in _SUPPRESSING_RULES for code in other_codes):
        return None

    days_ago = dose.get("last_strength_days_ago")
    if days_ago is not None and days_ago < STRENGTH_LAPSED_DAYS:
        return None

    evidence = [
        {
            "metric": "days_since_strength",
            "value": days_ago,
            "threshold": STRENGTH_LAPSED_DAYS,
            "window": f"{STRENGTH_LAPSED_DAYS}d",
        }
    ]

    if days_ago is None:
        recommendation = (
            "No strength sessions on record — schedule one this week to "
            "maintain structural resilience."
        )
    else:
        recommendation = (
            f"{days_ago} days since your last strength session — schedule "
            "one this week to maintain structural resilience."
        )

    return GapAnalysisFinding(
        code="strength_lapsed",
        severity=1,
        recommendation=recommendation,
        evidence=evidence,
        target=None,
        week_start=inputs["week_start"],
    )
