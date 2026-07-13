"""Rule: undertrained_area_under_ramp (issue #1373).

Fires when:
  - A lower-body priority muscle group (calf, hamstring, glute) has zero
    strength volume for >= ZERO_VOLUME_WEEKS_THRESHOLD consecutive weeks
    ending at the current week
  AND
  - The 4-week average running TSS rose by more than TSS_RAMP_THRESHOLD %
    compared to the prior TSS_RAMP_WINDOW_WEEKS/2 weeks

Active severe injury guard (severity >= 2, ended_on=None):
  - If an active severe injury maps to the same muscle group, suppress the
    loading recommendation and surface recovery-deferring advice instead.

Severity 2 (recommend). Returns None on insufficient data.
Thresholds documented in docs/calculations/gap-analysis.md.
"""
from __future__ import annotations

import datetime
from typing import Optional

from backend.services.gap_analysis.schemas import GapAnalysisFinding
from backend.services.muscle_load import BODY_AREA_TO_MUSCLE_GROUP

# ── Thresholds ────────────────────────────────────────────────────────────────

LOWER_BODY_PRIORITY_GROUPS: frozenset[str] = frozenset({"calf", "hamstring", "glute"})
"""Muscle groups watched for undertrained-under-ramp pattern (issue #1373)."""

ZERO_VOLUME_WEEKS_THRESHOLD: int = 4
"""Consecutive trailing weeks of zero strength volume required to trigger."""

TSS_RAMP_THRESHOLD: float = 10.0
"""Minimum TSS increase (%) over the ramp window to confirm the athlete is ramping."""

TSS_RAMP_WINDOW_WEEKS: int = 4
"""Total weeks used to assess TSS ramp: recent half vs prior half."""

ACTIVE_INJURY_SEVERITY_THRESHOLD: int = 2
"""Injuries at this severity or above suppress loading and surface recovery advice."""


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _has_active_severe_injury(injury_log: list[dict], group: str) -> bool:
    """Return True when the injury log has an active (ended_on=None) entry of
    severity >= ACTIVE_INJURY_SEVERITY_THRESHOLD that maps to `group`."""
    for entry in injury_log:
        if entry.get("ended_on") is not None:
            continue
        severity = entry.get("severity", 0)
        if severity < ACTIVE_INJURY_SEVERITY_THRESHOLD:
            continue
        body_area = (entry.get("body_area") or "").strip().lower()
        mapped = BODY_AREA_TO_MUSCLE_GROUP.get(body_area)
        if mapped == group:
            return True
    return False


def undertrained_area_under_ramp(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Return severity-2 finding for the first priority group meeting both conditions.

    Returns None when:
    - muscle_volume or training_load keys absent
    - No priority group has zero volume for ZERO_VOLUME_WEEKS_THRESHOLD trailing weeks
    - TSS has not ramped above TSS_RAMP_THRESHOLD %

    When an active severe injury maps to the firing group, returns a recovery-
    deferring finding rather than a loading recommendation.
    """
    muscle_volume = inputs.get("muscle_volume")
    training_load = inputs.get("training_load")
    if muscle_volume is None or training_load is None:
        return None

    injury_log: list[dict] = inputs.get("injury_log") or []
    week_start: datetime.date = inputs["week_start"]

    # ── TSS ramp check ────────────────────────────────────────────────────────
    weekly_tss = training_load.get("weekly", [])
    if len(weekly_tss) < TSS_RAMP_WINDOW_WEEKS:
        return None

    tail = weekly_tss[-TSS_RAMP_WINDOW_WEEKS:]
    half = TSS_RAMP_WINDOW_WEEKS // 2
    prior_tss = [float(w.get("running_tss") or 0) for w in tail[:half]]
    recent_tss = [float(w.get("running_tss") or 0) for w in tail[half:]]

    prior_mean = _mean(prior_tss) if prior_tss else 0.0
    recent_mean = _mean(recent_tss) if recent_tss else 0.0

    if prior_mean <= 0:
        tss_ramp_pct = 0.0 if recent_mean <= 0 else 100.0
    else:
        tss_ramp_pct = (recent_mean - prior_mean) / prior_mean * 100.0

    if tss_ramp_pct <= TSS_RAMP_THRESHOLD:
        return None

    # ── Volume check per priority group ───────────────────────────────────────
    # Build group → list of (week_start, load) sorted oldest→newest
    from collections import defaultdict
    group_weeks: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in muscle_volume:
        grp = row.get("muscle_group", "")
        if grp not in LOWER_BODY_PRIORITY_GROUPS:
            continue
        group_weeks[grp].append((row.get("week_start", ""), float(row.get("weekly_load") or 0)))

    for grp in sorted(LOWER_BODY_PRIORITY_GROUPS):
        rows = sorted(group_weeks.get(grp, []), key=lambda r: r[0])
        if not rows:
            zero_weeks = ZERO_VOLUME_WEEKS_THRESHOLD
        else:
            # Count consecutive zero-volume trailing weeks
            trailing = [v for _, v in rows]
            zero_weeks = 0
            for v in reversed(trailing):
                if v <= 0:
                    zero_weeks += 1
                else:
                    break

        if zero_weeks < ZERO_VOLUME_WEEKS_THRESHOLD:
            continue

        # Condition met for this group
        is_injured = _has_active_severe_injury(injury_log, grp)

        evidence = [
            {
                "metric": "zero_volume_weeks",
                "value": zero_weeks,
                "threshold": ZERO_VOLUME_WEEKS_THRESHOLD,
                "window": f"{ZERO_VOLUME_WEEKS_THRESHOLD}w",
            },
            {
                "metric": "tss_ramp_pct",
                "value": round(tss_ramp_pct, 1),
                "threshold": TSS_RAMP_THRESHOLD,
                "window": f"{TSS_RAMP_WINDOW_WEEKS}w",
            },
            {
                "metric": "running_tss_recent_mean",
                "value": round(recent_mean, 1),
                "threshold": None,
                "window": f"{half}w",
            },
        ]

        if is_injured:
            return GapAnalysisFinding(
                code="undertrained_area_under_ramp",
                severity=2,
                recommendation=(
                    f"Active {grp} injury detected while running load is rising — "
                    f"defer reintroducing {grp} strength work and prioritize recovery "
                    f"before adding volume to the area."
                ),
                evidence=evidence,
                target=grp,
                week_start=week_start,
            )
        else:
            return GapAnalysisFinding(
                code="undertrained_area_under_ramp",
                severity=2,
                recommendation=(
                    f"Running load is rising but {grp} strength volume has been zero "
                    f"for {zero_weeks} weeks — reintroduce {grp} targeted work to "
                    f"support the increased running demand."
                ),
                evidence=evidence,
                target=grp,
                week_start=week_start,
            )

    return None
