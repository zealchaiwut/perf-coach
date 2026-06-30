"""Weekly check-in assembly service.

Pure function — no DB access, no mutations.
Assembles coaching-voice-formatted check-in data from raw data slices
provided by the endpoint layer.

All user-facing strings pass through coaching_voice builders so that a
single tone change propagates here automatically.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import backend.services.coaching_voice as coaching_voice

# Minimum distinct days of ANY data (weight, habit, workout) required
# before showing a real weekly summary instead of the baseline state.
BASELINE_DAYS_REQUIRED = 7

# Days a focus-habit change is locked out after an adjustment.
# Stored client-side in localStorage; exported so tests can assert it.
FOCUS_HABIT_COOLDOWN_DAYS = 7


def build_weekly_check_in(
    *,
    weight_entries_this_week: list[dict],
    weight_entries_prev_week: list[dict],
    habits_summary: list[dict],
    workouts_this_week: list[dict],
    insights: list[dict],
    insights_building: bool,
    today: date,
    week_start: date,
) -> dict:
    """Return the structured weekly check-in dict.

    Parameters
    ----------
    weight_entries_this_week:
        Dicts with ``entry_date`` (str YYYY-MM-DD) and ``weight_kg`` (float).
    weight_entries_prev_week:
        Same shape; previous 7-day window for trend comparison.
    habits_summary:
        List of habit dicts from /api/habits/summary. Must include
        ``id``, ``name``, ``consistency_percent``, ``week_done``,
        ``weekly_target``, ``current_streak``, ``sort_order``.
    workouts_this_week:
        Workout dicts with ``workout_date``, ``distance_km``,
        ``duration_seconds``, ``tss``.
    insights:
        Insight dicts from /api/habits/insights. May be empty.
    insights_building:
        True when the insights endpoint returned building=True.
    today:
        Reference date (avoids datetime.date.today() for determinism).
    week_start:
        Monday of the current week.
    """
    # Count distinct data days across all sources
    data_days = _count_data_days(
        weight_entries_this_week,
        weight_entries_prev_week,
        workouts_this_week,
    )

    # Focus habits = top 3 active habits by sort_order
    focus_habits = [_focus_habit_dict(h) for h in habits_summary[:3]]

    if data_days < BASELINE_DAYS_REQUIRED:
        return {
            "building": True,
            "reason": (
                "Less than 7 days of data logged — building your baseline."
            ),
            "week_summary": None,
            "bright_spot": None,
            "next_lever": None,
            "focus_habits": focus_habits,
        }

    week_summary = {
        "weight_trend": _build_weight_trend(
            weight_entries_this_week, weight_entries_prev_week
        ),
        "habit_consistency": _build_habit_consistency(habits_summary),
        "training_note": _build_training_note(workouts_this_week),
    }

    bright_spot = _build_bright_spot(
        habits_summary=habits_summary,
        insights=insights,
        workouts=workouts_this_week,
    )

    next_lever = _build_next_lever(
        habits_summary=habits_summary,
        workouts=workouts_this_week,
    )

    return {
        "building": False,
        "reason": None,
        "week_summary": week_summary,
        "bright_spot": bright_spot,
        "next_lever": next_lever,
        "focus_habits": focus_habits,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _count_data_days(
    entries_this_week: list[dict],
    entries_prev_week: list[dict],
    workouts: list[dict],
) -> int:
    """Return number of distinct calendar days that have any data entry."""
    days: set[str] = set()
    for e in entries_this_week + entries_prev_week:
        d = e.get("entry_date") or e.get("date")
        if d:
            days.add(str(d)[:10])
    for w in workouts:
        d = w.get("workout_date") or w.get("date")
        if d:
            days.add(str(d)[:10])
    return len(days)


def _focus_habit_dict(h: dict) -> dict:
    return {
        "id": h.get("id", ""),
        "name": h.get("name", ""),
        "consistency_percent": h.get("consistency_percent", 0.0),
        "week_done": h.get("week_done", 0),
        "weekly_target": h.get("weekly_target"),
        "current_streak": h.get("current_streak", 0),
        "cooldown_days": FOCUS_HABIT_COOLDOWN_DAYS,
    }


def _build_weight_trend(
    this_week: list[dict],
    prev_week: list[dict],
) -> Optional[str]:
    """Return a voice-formatted weight trend line, or None if insufficient data."""
    if not this_week:
        return None

    weights_this = [float(e["weight_kg"]) for e in this_week if e.get("weight_kg") is not None]
    if not weights_this:
        return None

    avg_this = sum(weights_this) / len(weights_this)

    if prev_week:
        weights_prev = [float(e["weight_kg"]) for e in prev_week if e.get("weight_kg") is not None]
        if weights_prev:
            avg_prev = sum(weights_prev) / len(weights_prev)
            delta = avg_this - avg_prev
            direction = "up" if delta > 0.05 else "down" if delta < -0.05 else "neutral"
            delta_abs = abs(delta)
            context = f"{delta_abs:.1f} kg {'above' if delta > 0 else 'below'} last week"
            if direction == "neutral":
                context = "stable week-over-week"
            return coaching_voice.praise_line_builder(
                "weight",
                round(avg_this, 1),
                direction,
                context,
            )

    # Only this week data available
    return coaching_voice.praise_line_builder(
        "weight",
        round(avg_this, 1),
        "neutral",
        f"average over {len(weights_this)} entries this week",
    )


def _build_habit_consistency(habits: list[dict]) -> Optional[str]:
    """Return a voice-formatted habit consistency line, or None if no habits."""
    if not habits:
        return None

    focus = habits[:3]
    total_done = sum(h.get("week_done", 0) for h in focus)
    total_target = sum(
        int(h.get("weekly_target") or 7) for h in focus
    )

    if total_target == 0:
        return None

    pct = round(total_done / total_target * 100)
    direction = "up" if pct >= 70 else "down"
    context = f"{total_done} of {total_target} across focus habits"
    return coaching_voice.praise_line_builder(
        "habit consistency",
        pct,
        direction,
        context,
    )


def _build_training_note(workouts: list[dict]) -> Optional[str]:
    """Return a voice-formatted training note, or None if no workouts."""
    if not workouts:
        return None

    n = len(workouts)
    total_km = sum(
        float(w["distance_km"])
        for w in workouts
        if w.get("distance_km") is not None
    )
    context = (
        f"{round(total_km, 1)} km total" if total_km > 0
        else "training sessions logged"
    )
    return coaching_voice.praise_line_builder(
        "sessions",
        float(n),
        "up",
        context,
    )


def _build_bright_spot(
    *,
    habits_summary: list[dict],
    insights: list[dict],
    workouts: list[dict],
) -> Optional[dict]:
    """Return a single bright-spot highlight, or None if no data at all."""
    # Prefer H3 correlation insights
    if insights:
        top = insights[0]
        habit_name = top.get("habit_name", "this habit")
        outcome = top.get("outcome", "your outcomes")
        text = coaching_voice.praise_line_builder(
            habit_name,
            None,
            "up",
            f"linked to better {outcome} — your top correlation this week",
        )
        return {"text": text, "source": "correlation"}

    # Fall back to highest-consistency focus habit
    if habits_summary:
        best = max(habits_summary[:3], key=lambda h: h.get("consistency_percent", 0))
        pct = best.get("consistency_percent", 0)
        week_done = best.get("week_done", 0)
        weekly_target = int(best.get("weekly_target") or 7)
        context = f"{week_done} of {weekly_target} this week"
        text = coaching_voice.praise_line_builder(
            best["name"],
            round(pct, 1),
            "up" if pct >= 70 else "neutral",
            context,
        )

        # Prefer streak source when streak is significant
        streak = best.get("current_streak", 0)
        if streak >= 7:
            text = coaching_voice.praise_line_builder(
                best["name"],
                float(streak),
                "up",
                f"{streak}-day streak — your longest active run",
            )
            return {"text": text, "source": "streak"}

        return {"text": text, "source": "consistency"}

    # Fall back to training
    if workouts:
        n = len(workouts)
        text = coaching_voice.praise_line_builder(
            "sessions",
            float(n),
            "up",
            f"{n} training sessions this week",
        )
        return {"text": text, "source": "training"}

    return None


def _build_next_lever(
    *,
    habits_summary: list[dict],
    workouts: list[dict],
) -> Optional[dict]:
    """Return a single concrete next-week action, or None if no data."""
    focus = habits_summary[:3]

    if focus:
        # Target the lowest-consistency focus habit
        lowest = min(focus, key=lambda h: h.get("consistency_percent", 100))
        week_done = lowest.get("week_done", 0)
        weekly_target = int(lowest.get("weekly_target") or 7)
        gap = weekly_target - week_done
        if gap > 0:
            context = (
                f"adding {gap} more session{'s' if gap > 1 else ''} next week "
                f"would hit your {weekly_target}-day target"
            )
        else:
            context = "maintain this week's pace to stay on target"
        text = coaching_voice.decision_prompt_line_builder(
            lowest["name"],
            round(lowest.get("consistency_percent", 0), 1),
            "under" if gap > 0 else "neutral",
            context,
        )
        return {"text": text, "metric": "habit"}

    # Fallback: training note
    if workouts:
        n = len(workouts)
        context = "keep at least this volume next week to maintain your load"
        text = coaching_voice.decision_prompt_line_builder(
            "training sessions",
            float(n),
            "neutral",
            context,
        )
        return {"text": text, "metric": "training"}

    return None
