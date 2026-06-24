"""Pure function for detecting slipping habits.

No database access. No network I/O. No mutations to inputs. No global state.
Caller passes already-fetched habit rows with completion histories.
"""

from __future__ import annotations

from datetime import date, timedelta

from backend.services.habit_consistency import compute_consistency

# Minimum drop in adherence rate (0–1 scale) to flag a habit as slipping.
# A value of 0.20 means a twenty percentage-point fall triggers the flag.
SLIPPING_DROP_THRESHOLD: float = 0.20

# Guard constant: minimum number of days required per comparison window.
# Habits whose history does not reach back far enough to fill both windows are skipped.
MIN_HISTORY_DAYS: int = 1  # effectively enforced by the per-habit oldest-date check


def detect_slipping_habits(habits_with_history, window) -> dict:
    """Detect habits whose adherence rate has meaningfully declined.

    Compares a recent completion window against an equally-sized prior window
    for each habit and flags habits whose adherence rate has dropped by at
    least SLIPPING_DROP_THRESHOLD.

    Example: a habit completed ninety percent of days in the prior window and
    fifty percent in the recent window produces prior_rate=0.9, current_rate=0.5,
    drop=0.4, and is included in the slipping list.

    Parameters
    ----------
    habits_with_history:
        List of habit objects, each with:
        - id: unique identifier
        - history: list of log objects, each with a log_date (date) and value
        - schedule_type, schedule_target, habit_type, target_value: required by
          compute_consistency and is_period_met
    window:
        Number of days in each comparison period. Must be a positive integer.
        The recent window covers the last ``window`` days from today; the prior
        window covers the ``window`` days immediately before that.

    Returns
    -------
    dict
        slipping: list of dicts, one per habit meeting the drop threshold. Each
            entry has habit_id, current_rate (0–1), prior_rate (0–1), drop
            (prior_rate - current_rate), and a debug object.
        per_habit_debug: dict mapping habit_id to per-habit processing details,
            including skip_reason for habits excluded due to insufficient history.
        reason: present only when top-level input is invalid; explains why the
            result is empty without raising.
    """
    # Validate window before touching any habits — invalid window blocks all processing
    if window is None or not isinstance(window, (int, float)) or int(window) <= 0:
        return {
            "slipping": [],
            "reason": f"window must be a positive integer; got {window!r}",
        }

    window = int(window)

    # Guard: None input is a distinct failure mode from an empty list
    if habits_with_history is None:
        return {
            "slipping": [],
            "reason": "habits_with_history is None; no habits to evaluate",
        }

    # Guard: non-iterable input is a caller error, not a normal empty case
    try:
        habits_list = list(habits_with_history)
    except TypeError:
        return {
            "slipping": [],
            "reason": "habits_with_history is not iterable; no habits to evaluate",
        }

    if not habits_list:
        return {
            "slipping": [],
            "reason": "habits_with_history is empty; no habits to evaluate",
        }

    # Anchor both windows to today so "most recent window days" is unambiguous
    today = date.today()

    # Recent window: last ``window`` days up to and including today
    recent_end = today
    recent_start = today - timedelta(days=window - 1)

    # Prior window: the ``window`` days immediately preceding the recent window
    prior_end = today - timedelta(days=window)
    prior_start = today - timedelta(days=2 * window - 1)

    slipping: list[dict] = []
    per_habit_debug: dict = {}

    for habit in habits_list:
        habit_id = getattr(habit, "id", None)
        history = getattr(habit, "history", None) or []

        if not history:
            # No history at all — cannot form either window; record and skip
            per_habit_debug[habit_id] = {
                "skip_reason": "history is empty; cannot form comparison windows",
            }
            continue

        # Collect all log dates that are non-null to assess coverage
        log_dates = [getattr(lg, "log_date", None) for lg in history]
        valid_dates = [d for d in log_dates if d is not None]

        if not valid_dates:
            per_habit_debug[habit_id] = {
                "skip_reason": "no logs with a valid log_date found in history",
            }
            continue

        oldest_date = min(valid_dates)

        # Skip habit if no logs reach into the prior window at all.
        # prior_end is the most-recent day of the prior window; if the oldest log is
        # more recent than that, there is no data in the prior period to compare against.
        if oldest_date > prior_end:
            per_habit_debug[habit_id] = {
                "skip_reason": (
                    f"insufficient history: oldest log {oldest_date} is more recent than "
                    f"prior window end {prior_end}; no data exists in the prior window"
                ),
                "window": window,
                "oldest_log_date": str(oldest_date),
                "prior_window_end": str(prior_end),
            }
            continue

        # Filter logs to each window before passing them to compute_consistency
        recent_logs = [
            lg for lg in history
            if getattr(lg, "log_date", None) is not None
            and recent_start <= lg.log_date <= recent_end
        ]

        prior_logs = [
            lg for lg in history
            if getattr(lg, "log_date", None) is not None
            and prior_start <= lg.log_date <= prior_end
        ]

        # Derive adherence rates by delegating to compute_consistency — no inline rate logic
        recent_result = compute_consistency(habit, recent_logs, recent_start, recent_end)
        prior_result = compute_consistency(habit, prior_logs, prior_start, prior_end)

        prior_pct = prior_result["consistency_percent"]
        recent_pct = recent_result["consistency_percent"]

        # Compute drop in percentage space first, then convert to 0–1 scale; this avoids
        # cumulative floating-point error from two independent /100 divisions
        drop = (prior_pct - recent_pct) / 100

        # Convert each percentage to a 0–1 rate for the return value
        recent_rate = recent_pct / 100
        prior_rate = prior_pct / 100

        habit_debug = {
            "window": window,
            "recent_days_counted": recent_result.get("scheduled_count", 0),
            "prior_days_counted": prior_result.get("scheduled_count", 0),
            "threshold_used": SLIPPING_DROP_THRESHOLD,
            "recent_rate": recent_rate,
            "prior_rate": prior_rate,
            "drop": drop,
        }
        per_habit_debug[habit_id] = habit_debug

        # Boundary-inclusive check: a drop exactly at the threshold still qualifies
        if drop >= SLIPPING_DROP_THRESHOLD:
            slipping.append(
                {
                    "habit_id": habit_id,
                    "current_rate": recent_rate,
                    "prior_rate": prior_rate,
                    # prior_rate - current_rate gives the signed drop
                    "drop": drop,
                    "debug": {
                        "window": window,
                        "recent_days_counted": recent_result.get("scheduled_count", 0),
                        "prior_days_counted": prior_result.get("scheduled_count", 0),
                        "threshold_used": SLIPPING_DROP_THRESHOLD,
                    },
                }
            )

    return {
        "slipping": slipping,
        "per_habit_debug": per_habit_debug,
    }
