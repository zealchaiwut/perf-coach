"""Structural training dose aggregation — plyo and strength (issue #1369).

Computes per-week plyo session count, total foot contacts, dominant plyo phase,
and strength day count for a user's recent training history. Consumed by the
sprint-107 gap analyzer via GET /api/training/structural-dose.

Strength de-dup rule:
  A "strength day" is any calendar date in the window where at least one
  `strength_sessions` row OR at least one `workouts` row with
  workout_type='strength' exists for that user. If both tables have rows
  on the same date, the date counts once — we take the union of dates.
  There is no FK linking the two tables; de-dup is date-union.
"""
from __future__ import annotations

import uuid as _uuid
from collections import Counter
from datetime import date, timedelta
from typing import Optional

from backend.services.workout_types import WORKOUT_TYPE_STRENGTH

# Named constant: absolute foot-contact delta (per week) required to call
# the trend "rising" or "falling". Deltas ≤ this value are "flat".
FC_TREND_THRESHOLD: int = 15


def _week_start(d: date) -> date:
    """Monday of the ISO week containing d."""
    return d - timedelta(days=d.weekday())


def foot_contact_trend(weekly_fc: list[int]) -> str:
    """Return 'rising', 'flat', or 'falling' from a chronological list of
    per-week foot contacts (oldest first).

    Uses the last 4 entries (or fewer if not enough data). Compares the
    average of the most recent 2 weeks against the average of the prior 2.
    Delta must exceed FC_TREND_THRESHOLD (absolute) to be non-flat.
    """
    if len(weekly_fc) < 4:
        return "flat"
    tail = weekly_fc[-4:]
    past_avg = (tail[0] + tail[1]) / 2.0
    recent_avg = (tail[2] + tail[3]) / 2.0
    delta = recent_avg - past_avg
    if delta > FC_TREND_THRESHOLD:
        return "rising"
    if delta < -FC_TREND_THRESHOLD:
        return "falling"
    return "flat"


def dominant_phase(sessions: list[tuple]) -> Optional[str]:
    """Return the most-common plyo_phase string from a list of (phase,) tuples,
    or None if the list is empty."""
    if not sessions:
        return None
    counts = Counter(row[0] for row in sessions)
    return counts.most_common(1)[0][0]


def build_weekly_buckets(today: date, weeks: int) -> list[dict]:
    """Build an ordered list (oldest→newest) of weekly dose buckets, all zeroed out.

    The most-recent bucket is the ISO week that contains today; earlier
    buckets cover the preceding (weeks-1) ISO weeks.
    """
    current_monday = _week_start(today)
    buckets = []
    for i in range(weeks - 1, -1, -1):
        ws = current_monday - timedelta(weeks=i)
        buckets.append({
            "week_start": ws.isoformat(),
            "plyo_sessions": 0,
            "foot_contacts": 0,
            "dominant_plyo_phase": None,
            "strength_days": 0,
        })
    return buckets


def compute_structural_dose(
    db,
    user_id: _uuid.UUID,
    today: date,
    weeks: int = 8,
) -> dict:
    """Aggregate structural training dose for user over the last `weeks` ISO weeks.

    Returns:
    {
      "weeks": int,
      "window_start": "YYYY-MM-DD",
      "window_end": "YYYY-MM-DD",
      "weekly": [
        {
          "week_start": "YYYY-MM-DD",   # Monday of the week
          "plyo_sessions": int,          # number of plyo_sessions rows in this week
          "foot_contacts": int,          # sum of foot_contacts in this week
          "dominant_plyo_phase": str | null,  # most-common plyo_phase ("intro"/"build"/"maintain")
          "strength_days": int           # unique dates with ≥1 strength_sessions or strength workout
        },
        ...  # ordered oldest → newest
      ],
      "last_plyo_days_ago": int | null,      # days since most-recent plyo session (null = never)
      "last_strength_days_ago": int | null,  # days since most-recent strength day (null = never)
      "foot_contact_trend": "rising" | "flat" | "falling"
                                             # 4-week trend, FC_TREND_THRESHOLD absolute delta
    }

    Strength de-dup rule: A date counts as 1 strength_day even if it has rows
    in both strength_sessions and workouts (workout_type='strength').
    """
    from sqlalchemy import text as _text

    uid_str = str(user_id)
    current_monday = _week_start(today)
    window_start = current_monday - timedelta(weeks=weeks - 1)
    window_end = today

    # ── Plyo aggregation ──────────────────────────────────────────────────────
    plyo_rows = db.execute(
        _text("""
            SELECT session_date, foot_contacts, plyo_phase
            FROM plyo_sessions
            WHERE user_id = :uid
              AND session_date >= :ws
              AND session_date <= :we
            ORDER BY session_date
        """),
        {"uid": uid_str, "ws": window_start, "we": window_end},
    ).fetchall()

    # Most-recent plyo date (global, not per-week)
    last_plyo_row = db.execute(
        _text("""
            SELECT MAX(session_date) FROM plyo_sessions WHERE user_id = :uid
        """),
        {"uid": uid_str},
    ).scalar()

    # ── Strength aggregation (union of both tables) ───────────────────────────
    # Unique dates in the window with ≥1 strength record in either table.
    strength_dates_rows = db.execute(
        _text("""
            SELECT DISTINCT d FROM (
                SELECT session_date AS d
                  FROM strength_sessions
                 WHERE user_id = :uid AND session_date >= :ws AND session_date <= :we
                UNION
                SELECT workout_date AS d
                  FROM workouts
                 WHERE user_id = :uid AND LOWER(workout_type) = LOWER(:strength_type)
                   AND workout_date >= :ws AND workout_date <= :we
            ) AS combined
        """),
        {"uid": uid_str, "ws": window_start, "we": window_end, "strength_type": WORKOUT_TYPE_STRENGTH},
    ).fetchall()
    strength_dates_in_window: set[date] = {row[0] for row in strength_dates_rows}

    # Most-recent strength date (global, not per-week)
    last_strength_row = db.execute(
        _text("""
            SELECT d FROM (
                SELECT MAX(session_date) AS d FROM strength_sessions WHERE user_id = :uid
                UNION ALL
                SELECT MAX(workout_date) AS d FROM workouts
                 WHERE user_id = :uid AND LOWER(workout_type) = LOWER(:strength_type)
            ) AS combined
            WHERE d IS NOT NULL
            ORDER BY d DESC
            LIMIT 1
        """),
        {"uid": uid_str, "strength_type": WORKOUT_TYPE_STRENGTH},
    ).scalar()

    # ── Build weekly buckets ──────────────────────────────────────────────────
    buckets = build_weekly_buckets(today, weeks)

    # Map week_start → bucket index for O(1) assignment
    ws_to_idx = {b["week_start"]: i for i, b in enumerate(buckets)}

    # Fill plyo rows
    week_plyo_phases: dict[str, list[str]] = {}
    for row in plyo_rows:
        session_date, fc, phase = row[0], row[1], row[2]
        ws_key = _week_start(session_date).isoformat()
        if ws_key in ws_to_idx:
            idx = ws_to_idx[ws_key]
            buckets[idx]["plyo_sessions"] += 1
            buckets[idx]["foot_contacts"] += fc
            week_plyo_phases.setdefault(ws_key, []).append(phase)

    for ws_key, phases in week_plyo_phases.items():
        if ws_key in ws_to_idx:
            counts = Counter(phases)
            buckets[ws_to_idx[ws_key]]["dominant_plyo_phase"] = counts.most_common(1)[0][0]

    # Fill strength days
    for d in strength_dates_in_window:
        ws_key = _week_start(d).isoformat()
        if ws_key in ws_to_idx:
            buckets[ws_to_idx[ws_key]]["strength_days"] += 1

    # ── Recency ───────────────────────────────────────────────────────────────
    last_plyo_days_ago: Optional[int] = None
    if last_plyo_row is not None:
        last_plyo_days_ago = (today - last_plyo_row).days

    last_strength_days_ago: Optional[int] = None
    if last_strength_row is not None:
        last_strength_days_ago = (today - last_strength_row).days

    # ── Foot-contact trend (last 4 weeks) ────────────────────────────────────
    weekly_fc = [b["foot_contacts"] for b in buckets]
    trend = foot_contact_trend(weekly_fc)

    return {
        "weeks": weeks,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "weekly": buckets,
        "last_plyo_days_ago": last_plyo_days_ago,
        "last_strength_days_ago": last_strength_days_ago,
        "foot_contact_trend": trend,
    }
