"""Three-focus-habit business logic (issue #924).

Pure function module — no database access, no mutations, no global state.
All named constants are defined here so callers never hard-code magic numbers.

Named constants
---------------
MAX_FOCUS_COUNT
    Maximum number of focus habits a user may have simultaneously.

FOCUS_COOLDOWN_DAYS
    Minimum days a habit must be focus before it can be swapped out.

SUBTRACTION_MISS_THRESHOLD_DAYS
    Rolling-window length (days) used to detect consistently missing focus habits.

SUBTRACTION_REPEAT_COOLDOWN_DAYS
    Minimum days between subtraction suggestions to avoid nagging.

Public API
----------
check_focus_cap(current_focus_count)
    Return True when the user is already at the maximum.

days_until_swap_allowed(focus_since, today)
    Days remaining in the cooldown, 0 when the swap is permitted.

is_cooldown_active(focus_since, today)
    True when the habit is still inside FOCUS_COOLDOWN_DAYS.

filter_focus_habits(habits)
    Return only habits where is_focus is True.

should_suggest_subtraction(focus_habits, logs_by_habit_id, today)
    True when the user is consistently missing at least one focus habit
    over SUBTRACTION_MISS_THRESHOLD_DAYS.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

MAX_FOCUS_COUNT: int = 3
FOCUS_COOLDOWN_DAYS: int = 7
SUBTRACTION_MISS_THRESHOLD_DAYS: int = 7
SUBTRACTION_REPEAT_COOLDOWN_DAYS: int = 14


def check_focus_cap(current_focus_count: int) -> bool:
    """Return True when adding another focus habit would exceed the cap."""
    return current_focus_count >= MAX_FOCUS_COUNT


def _focus_since_as_date(focus_since) -> date | None:
    """Normalise focus_since to a date, handling datetime and date inputs."""
    if focus_since is None:
        return None
    if isinstance(focus_since, datetime):
        return focus_since.astimezone(timezone.utc).date()
    if isinstance(focus_since, date):
        return focus_since
    return None


def days_until_swap_allowed(focus_since, today: date) -> int:
    """Return days remaining in cooldown; 0 means the swap is permitted now."""
    fs = _focus_since_as_date(focus_since)
    if fs is None:
        return 0
    elapsed = (today - fs).days
    remaining = FOCUS_COOLDOWN_DAYS - elapsed
    return max(0, remaining)


def is_cooldown_active(focus_since, today: date) -> bool:
    """True when the habit cannot yet be swapped out."""
    return days_until_swap_allowed(focus_since, today) > 0


def filter_focus_habits(habits: list) -> list:
    """Return only habits where is_focus is True."""
    return [h for h in habits if getattr(h, "is_focus", False) is True]


def should_suggest_subtraction(
    focus_habits: list,
    logs_by_habit_id: dict,
    today: date,
) -> bool:
    """Return True when the user is consistently missing at least one focus habit.

    Scans the rolling SUBTRACTION_MISS_THRESHOLD_DAYS window ending today.
    A focus habit is "missed" for the window when it has zero logged dates
    across that entire period.
    """
    if not focus_habits:
        return False

    window_dates: set[date] = set()
    for offset in range(SUBTRACTION_MISS_THRESHOLD_DAYS):
        from datetime import timedelta
        window_dates.add(today - timedelta(days=offset))

    for habit in focus_habits:
        logged_dates: set[date] = set(logs_by_habit_id.get(habit.id, []))
        if not logged_dates & window_dates:
            return True

    return False
