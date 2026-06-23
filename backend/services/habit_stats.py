"""Habit streak and summary utilities.

Streak rules:
- Only ``daily_checkmark`` habits have streaks.
- A log on date D counts regardless of source (manual, autofill, etc.).
- Streaks are continuous across week boundaries.
- Streak scan capped at 365 days lookback.

The "met" rule for individual days is delegated to
``habit_completion._is_binary_met`` so the logic lives in exactly one place.
"""

from collections import defaultdict
from datetime import date, timedelta

from backend.services.habit_completion import _is_binary_met


# ── Pure computation helpers ──────────────────────────────────────────────────

def _current_streak_from_dates(as_of_date: date, logged_dates: set) -> int:
    """Compute current streak given a set of logged dates.

    If as_of_date is not logged the scan starts from the previous day,
    so a missing "today" does not break the streak.
    """
    check = as_of_date if as_of_date in logged_dates else as_of_date - timedelta(days=1)
    lookback_limit = as_of_date - timedelta(days=365)
    streak = 0
    while check >= lookback_limit:
        if check in logged_dates:
            streak += 1
            check -= timedelta(days=1)
        else:
            break
    return streak


def _best_streak_from_dates(sorted_dates: list) -> int:
    """Return the longest consecutive-day run in a sorted unique date list."""
    if not sorted_dates:
        return 0
    best = current = 1
    for i in range(1, len(sorted_dates)):
        if sorted_dates[i] == sorted_dates[i - 1] + timedelta(days=1):
            current += 1
            if current > best:
                best = current
        else:
            current = 1
    return best


# ── Session-based public API (used in unit tests) ─────────────────────────────

def current_streak(habit_id, as_of_date: date, *, session) -> int:
    """Return consecutive days with a log ending at ``as_of_date``.

    If ``as_of_date`` is unlogged the streak extends through the previous day
    without breaking.  Returns 0 for non-``daily_checkmark`` habits.
    """
    from backend.models import Habit, HabitLog

    habit = session.query(Habit).filter(Habit.id == habit_id).first()
    if habit is None or habit.tracking_type != "daily_checkmark":
        return 0

    lookback_start = as_of_date - timedelta(days=365)
    logs = (
        session.query(HabitLog)
        .filter(
            HabitLog.habit_id == habit_id,
            HabitLog.log_date >= lookback_start,
            HabitLog.log_date <= as_of_date,
        )
        .all()
    )
    # Group logs by date and delegate the per-day met check to _is_binary_met
    logs_by_date: dict = defaultdict(list)
    for lg in logs:
        logs_by_date[lg.log_date].append(lg)
    logged_dates = {d for d, day_logs in logs_by_date.items() if _is_binary_met(day_logs)[0]}
    return _current_streak_from_dates(as_of_date, logged_dates)


def best_streak(habit_id, *, session) -> dict:
    """Return ``{"length": int}`` for the longest streak for that habit.

    Returns ``{"length": 0}`` for non-``daily_checkmark`` habits.
    Scan is capped at 365 days lookback from today.
    """
    from backend.models import Habit, HabitLog

    habit = session.query(Habit).filter(Habit.id == habit_id).first()
    if habit is None or habit.tracking_type != "daily_checkmark":
        return {"length": 0}

    today = date.today()
    lookback_start = today - timedelta(days=365)
    logs = (
        session.query(HabitLog)
        .filter(
            HabitLog.habit_id == habit_id,
            HabitLog.log_date >= lookback_start,
        )
        .all()
    )
    # Group by date and delegate met check to _is_binary_met
    logs_by_date: dict = defaultdict(list)
    for lg in logs:
        logs_by_date[lg.log_date].append(lg)
    logged_dates = {d for d, day_logs in logs_by_date.items() if _is_binary_met(day_logs)[0]}
    return {"length": _best_streak_from_dates(sorted(logged_dates))}


def week_summary(user_id, week_start: date, *, session) -> dict | None:
    """Return ``{"done": N, "possible": N, "pct": float}`` for the given week.

    Returns ``None`` when no log data exists for that period.
    Only ``daily_checkmark`` habits contribute to the counts.
    """
    from backend.models import Habit, HabitLog

    habits = (
        session.query(Habit)
        .filter(
            Habit.user_id == user_id,
            Habit.tracking_type == "daily_checkmark",
            Habit.is_archived.is_(False),
        )
        .all()
    )

    if not habits:
        return None

    logs = (
        session.query(HabitLog)
        .filter(
            HabitLog.user_id == user_id,
            HabitLog.log_week_start == week_start,
        )
        .all()
    )

    if not logs:
        return None

    habit_ids = {h.id for h in habits}
    done = len({(lg.habit_id, lg.log_date) for lg in logs if lg.habit_id in habit_ids})
    possible = len(habits) * 7
    pct = round(done / possible * 100.0, 2) if possible > 0 else 0.0
    return {"done": done, "possible": possible, "pct": pct}


# ── Batch helper for the endpoint (no extra per-habit DB queries) ─────────────

def compute_habit_streaks(daily_habits, streak_logs_by_habit: dict, as_of_date: date) -> dict:
    """Compute streak data for all daily_checkmark habits using pre-loaded logs.

    Args:
        daily_habits: list of Habit objects (tracking_type == "daily_checkmark")
        streak_logs_by_habit: mapping of habit_id → set of logged date objects
        as_of_date: reference date (today in the local timezone)

    Returns::

        {
            "best": {"habit_id": str, "habit_name": str, "length": int} | None,
            "per_habit": {habit_id_str: current_streak_int, ...},
        }
    """
    per_habit: dict = {}
    best_info: dict | None = None

    for h in daily_habits:
        dates = streak_logs_by_habit.get(h.id, set())
        cs = _current_streak_from_dates(as_of_date, dates)
        bs = _best_streak_from_dates(sorted(dates))
        per_habit[str(h.id)] = cs
        if best_info is None or bs > best_info["length"]:
            best_info = {"habit_id": str(h.id), "habit_name": h.name, "length": bs}

    return {"best": best_info, "per_habit": per_habit}
