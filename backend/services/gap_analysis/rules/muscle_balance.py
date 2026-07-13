"""Muscle balance rules pack (issue #1381).

Two rules that turn per-muscle classifications (issue #1380) into findings:

  muscle_overused   — elevated or overused group; recommends reducing load
  muscle_untrained  — priority group untrained 4+ weeks (severity 2);
                      detraining groups get severity 1

Thresholds are imported from muscle_load_acwr — never redefined here.

Input key: muscle_load_ledger
  {
    "groups": {
      "<group>": {
        "acute_7d":        float,
        "chronic_28d":     float,
        "acwr":            float | None,
        "classification":  str,       # overused/elevated/balanced/detraining/untrained/inactive
        "injured":         bool,
        "source_breakdown": {str: float},  # source → share (0–1)
        "trending_up":     bool,      # acute load higher than prior week
        "weeks_untrained": int,       # consecutive weeks near-zero weekly load
      }, ...
    },
    "history_weeks": int,   # weeks of ledger data available
  }

Both rules return a list[GapAnalysisFinding] — one per qualifying group.
The registry handles list returns (updated in this issue).

Dedup (AC3)
-----------
claimed_groups is injected by the registry as a mutable set.  When pack C's
recurrent_niggle_area fires for a group, that group is added to claimed_groups
before pack D runs.  Both rules skip any group already claimed, enforcing
"one finding per group per week max".
"""
from __future__ import annotations

from backend.services.gap_analysis.schemas import GapAnalysisFinding
from backend.services.muscle_load_acwr import (
    CHRONIC_FLOOR,
    ELEVATED_BOUND,
    OVERUSED_BOUND,
    PRIORITY_GROUPS,
)

UNTRAINED_MIN_WEEKS: int = 4
"""Consecutive weeks of near-zero weekly load required before muscle_untrained fires."""

_MIN_HISTORY_WEEKS: int = 4
"""Minimum weeks of ledger history before either rule fires."""


def _get_claimed(inputs: dict) -> set[str]:
    return inputs.get("claimed_groups", set())


# ── Rule: muscle_overused ─────────────────────────────────────────────────────

def muscle_overused(inputs: dict) -> list[GapAnalysisFinding]:
    """Return severity-3/2 findings for every overloaded or elevated muscle group.

    Severity 3: classification == overused AND trending_up
    Severity 2: classification == overused (not trending) OR == elevated

    Injured + overused: still fires — stronger rest recommendation.
    Injured + elevated: still fires.

    Suppressed for any group already in claimed_groups (dedup with pack C).

    Returns [] when:
    - muscle_load_ledger absent
    - history_weeks < _MIN_HISTORY_WEEKS
    - No qualifying groups after suppression
    """
    ledger = inputs.get("muscle_load_ledger")
    if ledger is None:
        return []
    if ledger.get("history_weeks", 0) < _MIN_HISTORY_WEEKS:
        return []

    claimed = _get_claimed(inputs)
    week_start = inputs["week_start"]
    findings: list[GapAnalysisFinding] = []

    for group, gdata in ledger.get("groups", {}).items():
        classification = gdata.get("classification")
        if classification not in ("overused", "elevated"):
            continue
        if group in claimed:
            continue

        injured = gdata.get("injured", False)
        trending_up = gdata.get("trending_up", False)
        acute = gdata.get("acute_7d", 0.0)
        chronic = gdata.get("chronic_28d", 0.0)
        acwr = gdata.get("acwr")
        source_breakdown = gdata.get("source_breakdown", {})

        if classification == "overused" and trending_up:
            severity = 3
            if injured:
                rec = (
                    f"Your {group} is overloaded and injured — "
                    f"rest it completely for 7–10 days to avoid a more serious injury."
                )
            else:
                rec = (
                    f"Your {group} is overloaded and load is still rising — "
                    f"back off {group} training for 7–10 days to prevent injury."
                )
        else:
            severity = 2
            if injured:
                rec = (
                    f"Your {group} shows elevated load and is injured — "
                    f"ease off and allow full recovery before resuming normal training."
                )
            else:
                rec = (
                    f"Your {group} is showing elevated load — "
                    f"reduce {group} training intensity for the next 7–10 days."
                )

        threshold = OVERUSED_BOUND if classification == "overused" else ELEVATED_BOUND
        main_source = (
            max(source_breakdown, key=source_breakdown.__getitem__)
            if source_breakdown else None
        )

        evidence: list[dict] = [
            {
                "metric": "acwr",
                "value": round(acwr, 3) if acwr is not None else None,
                "threshold": threshold,
                "window": "4w",
            },
            {
                "metric": "acute_7d",
                "value": round(acute, 2),
                "threshold": None,
                "window": "7d",
            },
            {
                "metric": "chronic_28d",
                "value": round(chronic, 2),
                "threshold": None,
                "window": "28d",
            },
            {
                "metric": "main_source",
                "value": main_source,
                "threshold": None,
                "window": "28d",
            },
        ]
        if main_source is not None:
            evidence.append({
                "metric": f"source_share_{main_source}",
                "value": round(source_breakdown[main_source], 3),
                "threshold": None,
                "window": "28d",
            })

        findings.append(GapAnalysisFinding(
            code=f"muscle_overused.{group}",
            severity=severity,
            recommendation=rec,
            evidence=evidence,
            target=group,
            week_start=week_start,
        ))

    return findings


# ── Rule: muscle_untrained ────────────────────────────────────────────────────

def muscle_untrained(inputs: dict) -> list[GapAnalysisFinding]:
    """Return findings for chronically untrained or detraining muscle groups.

    Severity 2: priority group (calf/hamstring/glute/hip) classified untrained
                AND weeks_untrained >= UNTRAINED_MIN_WEEKS (4).
    Severity 1: any group classified detraining (load declining but not zero).

    Suppression:
    - Injured + untrained: suppressed — never prescribe loading an injured area.
    - Injured + detraining: suppressed for same reason.
    - Any group already in claimed_groups: suppressed (dedup with pack C).

    Returns [] when:
    - muscle_load_ledger absent
    - history_weeks < _MIN_HISTORY_WEEKS
    - No qualifying groups after suppression
    """
    ledger = inputs.get("muscle_load_ledger")
    if ledger is None:
        return []
    if ledger.get("history_weeks", 0) < _MIN_HISTORY_WEEKS:
        return []

    claimed = _get_claimed(inputs)
    week_start = inputs["week_start"]
    findings: list[GapAnalysisFinding] = []

    for group, gdata in ledger.get("groups", {}).items():
        classification = gdata.get("classification")
        if group in claimed:
            continue

        injured = gdata.get("injured", False)

        if classification == "untrained":
            if injured:
                continue
            if group not in PRIORITY_GROUPS:
                continue
            weeks_unt = gdata.get("weeks_untrained", 0)
            if weeks_unt < UNTRAINED_MIN_WEEKS:
                continue
            rec = (
                f"Your {group} has been untrained for {weeks_unt}+ weeks — "
                f"gradually introduce {group} exercises to build resilience "
                f"and reduce injury risk."
            )
            findings.append(GapAnalysisFinding(
                code=f"muscle_untrained.{group}",
                severity=2,
                recommendation=rec,
                evidence=[
                    {
                        "metric": "weeks_untrained",
                        "value": weeks_unt,
                        "threshold": UNTRAINED_MIN_WEEKS,
                        "window": f"{weeks_unt}w",
                    },
                    {
                        "metric": "classification",
                        "value": "untrained",
                        "threshold": None,
                        "window": "4w",
                    },
                ],
                target=group,
                week_start=week_start,
            ))

        elif classification == "detraining":
            if injured:
                continue
            chronic = gdata.get("chronic_28d", 0.0)
            acwr = gdata.get("acwr")
            rec = (
                f"Your {group} training load is declining — "
                f"maintain at least some {group} work each week "
                f"to preserve the adaptations you have built."
            )
            findings.append(GapAnalysisFinding(
                code=f"muscle_detraining.{group}",
                severity=1,
                recommendation=rec,
                evidence=[
                    {
                        "metric": "classification",
                        "value": "detraining",
                        "threshold": None,
                        "window": "4w",
                    },
                    {
                        "metric": "chronic_28d",
                        "value": round(chronic, 2),
                        "threshold": None,
                        "window": "28d",
                    },
                    {
                        "metric": "acwr",
                        "value": round(acwr, 3) if acwr is not None else None,
                        "threshold": None,
                        "window": "4w",
                    },
                ],
                target=group,
                week_start=week_start,
            ))

    return findings
