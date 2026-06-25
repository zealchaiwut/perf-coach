"""Coaching copy for habit logging surfaces.

Pure function — no database access, no mutations, no global state.
All coaching strings for the quick-log, streak-feedback, and milestone
surfaces are produced here so no surface hard-codes its own copy.

Public API
----------
compose_log_feedback(habit, week_done, week_target, total_logs, is_miss,
                     current_streak=0)
    Returns a dict with keys:
        message        (str)  — rendered coaching copy
        framing        (str)  — one of: "routine", "weekly", "streak",
                                "milestone", "miss"
        show_identity  (bool) — True only at milestone/landmark thresholds
        next_milestone (int|None) — the next landmark count, or None
"""

from __future__ import annotations

# Milestone log-count landmarks (ascending order)
_MILESTONES = [10, 25, 30, 50, 75, 100, 150, 200, 250, 365, 500, 750, 1000]

# Streak landmarks that unlock identity framing
_STREAK_LANDMARKS = {7, 14, 21, 30, 60, 90, 180, 365}


def _next_milestone(total: int) -> int | None:
    """Return the next milestone count above total, or None if beyond the list."""
    for m in _MILESTONES:
        if m > total:
            return m
    return None


def _is_milestone(total: int) -> bool:
    return total in set(_MILESTONES)


def _is_weekly_habit(habit) -> bool:
    """True when the habit's cadence is less than 7 times per week."""
    # Primary signal: schedule_type == 'times_per_week'
    if getattr(habit, "schedule_type", None) == "times_per_week":
        return True
    # Fallback: weekly_target explicitly set below 7
    wt = getattr(habit, "weekly_target", None)
    if wt is not None and float(wt) < 7:
        return True
    return False


def compose_log_feedback(
    habit,
    week_done: int | None,
    week_target: int | float | None,
    total_logs: int,
    is_miss: bool,
    current_streak: int = 0,
) -> dict:
    """Return coaching copy for one habit log event.

    Parameters
    ----------
    habit:
        Habit row (or SimpleNamespace) with ``name``, ``weekly_target``,
        ``tracking_type``, ``schedule_type``, ``schedule_target``.
    week_done:
        How many times the habit was completed in the current week
        (sourced from the API, never inferred client-side).
    week_target:
        The habit's weekly target (from ``habit.weekly_target``).
    total_logs:
        Total all-time log count for this habit.
    is_miss:
        True when the feedback event is triggered by a recognised missed day.
    current_streak:
        The current consecutive-periods streak (0 by default for non-streak
        events).

    Returns
    -------
    dict
        message        (str)
        framing        (str)  routine | weekly | streak | milestone | miss
        show_identity  (bool)
        next_milestone (int | None)
    """
    habit_name = getattr(habit, "name", "this habit")

    # ── Milestone detection ──────────────────────────────────────────────────
    if _is_milestone(total_logs):
        nxt = _next_milestone(total_logs)
        msg = f"You've logged {habit_name} {total_logs} times."
        if nxt is not None:
            msg += f" Next landmark: {nxt}."
        return {
            "message": msg,
            "framing": "milestone",
            "show_identity": True,
            "next_milestone": nxt,
        }

    # ── Miss acknowledgement ─────────────────────────────────────────────────
    if is_miss:
        wd = int(week_done) if week_done is not None else 0
        wt = int(week_target) if week_target is not None else 7
        msg = f"Yesterday slipped—{wd} of {wt} this week still puts you ahead of most."
        return {
            "message": msg,
            "framing": "miss",
            "show_identity": False,
            "next_milestone": None,
        }

    # ── Streak landmark check ────────────────────────────────────────────────
    if current_streak in _STREAK_LANDMARKS and current_streak > 0:
        wd = int(week_done) if week_done is not None else 0
        wt = int(week_target) if week_target is not None else 7
        msg = (
            f"{current_streak}-period streak on {habit_name}. "
            f"You are becoming someone who does this consistently."
        )
        return {
            "message": msg,
            "framing": "streak",
            "show_identity": True,
            "next_milestone": None,
        }

    # ── Weekly-cadence framing (< 7×/week habits) ────────────────────────────
    if _is_weekly_habit(habit):
        wd = int(week_done) if week_done is not None else 0
        wt_raw = week_target if week_target is not None else getattr(habit, "weekly_target", None)
        wt = int(wt_raw) if wt_raw is not None else 7
        if wd >= wt:
            msg = f"On track—{wd} of {wt} this week."
        else:
            msg = f"{wd} of {wt} this week. Keep going."
        return {
            "message": msg,
            "framing": "weekly",
            "show_identity": False,
            "next_milestone": None,
        }

    # ── Routine daily log ────────────────────────────────────────────────────
    return {
        "message": "Logged. Keep it going.",
        "framing": "routine",
        "show_identity": False,
        "next_milestone": None,
    }
