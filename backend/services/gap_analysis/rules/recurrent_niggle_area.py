"""Rule: recurrent_niggle_area (issue #1373).

Fires when:
  - >= RECURRENT_NIGGLE_MIN_COUNT injury-log entries exist for the same
    mapped muscle group within the last RECURRENT_NIGGLE_WINDOW_DAYS days.

body_area strings are mapped to canonical muscle groups via
BODY_AREA_TO_MUSCLE_GROUP from backend.services.muscle_load.

Severity 3 (priority). Returns None when no area meets the threshold.
Thresholds documented in docs/calculations/gap-analysis.md.
"""
from __future__ import annotations

import datetime
from typing import Optional

from backend.services.gap_analysis.schemas import GapAnalysisFinding
from backend.services.muscle_load import BODY_AREA_TO_MUSCLE_GROUP

# ── Thresholds ────────────────────────────────────────────────────────────────

RECURRENT_NIGGLE_WINDOW_DAYS: int = 90
"""Lookback window for counting injury-log entries."""

RECURRENT_NIGGLE_MIN_COUNT: int = 2
"""Minimum entries for the same muscle group within the window to fire."""


def recurrent_niggle_area(inputs: dict) -> Optional[GapAnalysisFinding]:
    """Return severity-3 finding for the muscle group with the most recurrent niggles.

    Groups entries by their mapped muscle group (via BODY_AREA_TO_MUSCLE_GROUP).
    Fires for the group with the highest count that meets the threshold.
    Returns None when:
    - injury_log key absent
    - No muscle group has >= RECURRENT_NIGGLE_MIN_COUNT entries in the window
    """
    entries = inputs.get("injury_log")
    if entries is None:
        return None

    week_start: datetime.date = inputs["week_start"]
    today = week_start + datetime.timedelta(days=6)
    cutoff = today - datetime.timedelta(days=RECURRENT_NIGGLE_WINDOW_DAYS - 1)

    # Count entries per mapped muscle group within window
    group_entries: dict[str, list[dict]] = {}
    for entry in entries:
        body_area = (entry.get("body_area") or "").strip().lower()
        started_on_str = entry.get("started_on")
        if not started_on_str:
            continue
        try:
            started_on = datetime.date.fromisoformat(str(started_on_str))
        except ValueError:
            continue
        if started_on < cutoff:
            continue
        group = BODY_AREA_TO_MUSCLE_GROUP.get(body_area)
        if group is None:
            group = body_area or "unknown"
        group_entries.setdefault(group, []).append(entry)

    # Find the group with the most entries that meets the minimum count
    qualifying = {g: ents for g, ents in group_entries.items()
                  if len(ents) >= RECURRENT_NIGGLE_MIN_COUNT}
    if not qualifying:
        return None

    # Pick the group with the highest count (ties: alphabetical for stability)
    top_group = max(qualifying, key=lambda g: (len(qualifying[g]), g))
    top_entries = qualifying[top_group]
    count = len(top_entries)

    # Find the most recent entry date
    dates = sorted(
        [e["started_on"] for e in top_entries],
        reverse=True,
    )
    most_recent = dates[0] if dates else None

    evidence = [
        {
            "metric": "niggle_count",
            "value": count,
            "threshold": RECURRENT_NIGGLE_MIN_COUNT,
            "window": f"{RECURRENT_NIGGLE_WINDOW_DAYS}d",
        },
        {
            "metric": "most_recent_entry_date",
            "value": most_recent,
            "threshold": None,
            "window": f"{RECURRENT_NIGGLE_WINDOW_DAYS}d",
        },
    ]

    return GapAnalysisFinding(
        code="recurrent_niggle_area",
        severity=3,
        recommendation=(
            f"Recurrent niggles in {top_group} ({count} entries in the last "
            f"{RECURRENT_NIGGLE_WINDOW_DAYS} days) — add targeted capacity work "
            f"for the {top_group} to build resilience and reduce re-injury risk."
        ),
        evidence=evidence,
        target=top_group,
        week_start=week_start,
    )
