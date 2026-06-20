"""Pure function for computing habit streaks from pre-fetched data.

No database access occurs here; all log fetching is the caller's responsibility.

Examples
--------
Daily binary habit with five consecutive met days ending on today → current=5, longest=5::

    import types
    from datetime import date, timedelta
    from backend.services.habit_streak import compute_streak

    habit = types.SimpleNamespace(
        habit_type='binary', target_value=None,
        schedule_type='daily', schedule_target=None,
    )
    today = date(2024, 6, 14)
    logs = [
        types.SimpleNamespace(log_date=today - timedelta(days=i), value=1)
        for i in range(5)
    ]
    result = compute_streak(habit, logs, today)
    # {'current_streak': 5, 'longest_streak': 5, 'debug': {...}}

A times_per_week habit (schedule_target=3) where the current (incomplete)
week has only 2 met days, preceded by N=3 fully-met weeks → current=3, longest≥3::

    habit = types.SimpleNamespace(
        habit_type='binary', target_value=None,
        schedule_type='times_per_week', schedule_target=3,
    )
    # Build logs: 3 met days per week for the last 3 weeks, plus 2 met
    # days so far this week (mid-week, e.g. Wednesday).
    result = compute_streak(habit, logs, today_midweek)
    # {'current_streak': 3, 'longest_streak': 3, 'debug': {...}}
"""

from datetime import date, timedelta

from backend.services.habit_completion import is_period_met


def _week_start(d: date) -> date:
    """Return the Monday of the week that contains d (ISO week: Mon=0)."""
    return d - timedelta(days=d.weekday())


def _build_logs_by_date(logs) -> dict:
    """Group logs into a dict keyed by log_date → list of logs for that date."""
    by_date = {}
    for log in logs:
        d = log.log_date
        by_date.setdefault(d, []).append(log)
    return by_date


def _daily_streak(habit, by_date: dict, today: date) -> dict:
    """Compute streaks for a daily schedule habit.

    A period is one calendar day; met status is delegated to is_period_met.
    """
    # Determine the earliest date that has any log so we know when to stop scanning
    all_dates = sorted(by_date.keys())
    earliest = all_dates[0]

    # ── current streak ────────────────────────────────────────────────────────
    # Walk backwards one day at a time starting from today.
    # Stop when we hit a fully elapsed, unmet day.
    current = 0
    d = today
    while d >= earliest:
        period_logs = by_date.get(d, [])
        met, _ = is_period_met(habit, period_logs)
        if met:
            # This day is met; count it and continue backward
            current += 1
            d -= timedelta(days=1)
        elif d == today:
            # Today's period has not yet ended; treat it as pending and skip to yesterday
            d -= timedelta(days=1)
        else:
            # Fully elapsed unmet period breaks the streak; stop here
            break

    # ── longest streak ────────────────────────────────────────────────────────
    # Scan every day from the earliest log date through today and record the
    # maximum run of consecutive met days.
    longest = 0
    run = 0
    scan = earliest
    while scan <= today:
        day_logs = by_date.get(scan, [])
        met, _ = is_period_met(habit, day_logs)
        if met:
            run += 1
            if run > longest:
                longest = run
        else:
            # Any unmet day (including today if not yet logged) resets the run counter
            run = 0
        scan += timedelta(days=1)

    return {
        "current_streak": current,
        "longest_streak": longest,
        "debug": {
            "schedule_type": "daily",
            "today": str(today),
            "earliest_log_date": str(earliest),
        },
    }


def _week_met(habit, by_date: dict, week_start: date, schedule_target: int) -> bool:
    """Return True if the week starting on week_start meets schedule_target.

    Count individual days within the week where is_period_met returns True;
    the week is met when that count is >= schedule_target.
    """
    days_met = 0
    # Check each of the seven days in this Mon-Sun week
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        day_logs = by_date.get(day, [])
        met, _ = is_period_met(habit, day_logs)
        if met:
            days_met += 1
    return days_met >= schedule_target


def _weekly_streak(habit, by_date: dict, today: date) -> dict:
    """Compute streaks for a times_per_week (or weekly) schedule habit.

    A period is one calendar week (Mon-Sun); the week is met when the count
    of individual days in that week satisfying is_period_met >= schedule_target.
    """
    schedule_target = getattr(habit, "schedule_target", None)
    if schedule_target is None:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "debug": {"reason": "schedule_target is not set for this habit"},
        }

    # Identify the bounds of the weekly scan
    earliest_log = min(by_date.keys())
    earliest_ws = _week_start(earliest_log)
    current_ws = _week_start(today)

    # ── current streak ────────────────────────────────────────────────────────
    # Walk backwards one week at a time starting from the current week.
    # Stop when we hit a fully elapsed, unmet week.
    current = 0
    ws = current_ws
    while ws >= earliest_ws:
        met = _week_met(habit, by_date, ws, schedule_target)
        is_current_week = ws == current_ws
        if met:
            # This week satisfied the target; count it and move to the previous week
            current += 1
            ws -= timedelta(weeks=1)
        elif is_current_week:
            # Current week is still in progress and hasn't reached target yet; treat
            # as pending (does not break the streak) and move to the prior week
            ws -= timedelta(weeks=1)
        else:
            # A fully elapsed week that did not meet the target resets the streak
            break

    # ── longest streak ────────────────────────────────────────────────────────
    # Walk all weeks from the earliest log's week through the current week and
    # find the maximum run of consecutive met weeks.
    longest = 0
    run = 0
    scan_ws = earliest_ws
    while scan_ws <= current_ws:
        met = _week_met(habit, by_date, scan_ws, schedule_target)
        if met:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 0
        scan_ws += timedelta(weeks=1)

    return {
        "current_streak": current,
        "longest_streak": longest,
        "debug": {
            "schedule_type": getattr(habit, "schedule_type", None),
            "schedule_target": schedule_target,
            "today": str(today),
            "current_week_start": str(current_ws),
            "earliest_week_start": str(earliest_ws),
        },
    }


def compute_streak(habit, logs, today) -> dict:
    """Derive ``current_streak``, ``longest_streak``, and ``debug`` from pre-fetched data.

    Pure function: no I/O, no mutations, deterministic output.  All schedule
    configuration is read from the ``habit`` row; no values are hardcoded here.
    Database access lives exclusively in the calling layer; this function receives
    only in-memory ``logs``.

    Parameters
    ----------
    habit:
        A habit row (or any object with attributes) providing ``habit_type``,
        ``schedule_type``, ``schedule_target`` (for times_per_week), and
        ``target_value`` (for count/duration).  Read-only; never mutated.
    logs:
        Pre-fetched list of habit log rows, each with a ``log_date``
        (:class:`datetime.date`) and a numeric ``value``.  Pass all logs for
        this habit across its full history so ``longest_streak`` is accurate.
    today:
        The reference date (:class:`datetime.date`) defining "now".  Always
        supplied by the caller — never inferred inside this function.

    Returns
    -------
    dict
        Exactly three keys:

        * ``current_streak`` (int) — consecutive met periods ending at or
          before ``today``.  An in-progress current period that has not yet
          ended is treated as **pending** and does not break the count; only
          a fully elapsed, unmet period resets it to zero.
        * ``longest_streak`` (int) — maximum run of consecutive met periods
          anywhere in the full ``logs`` history.
        * ``debug`` (dict) — intermediate values sufficient to trace a wrong
          result.  Contains ``reason`` (str) when an input guard fired.

    Examples
    --------
    Daily binary habit with five consecutive met days ending on today → 5, 5::

        import types
        from datetime import date, timedelta
        from backend.services.habit_streak import compute_streak

        habit = types.SimpleNamespace(
            habit_type='binary', target_value=None,
            schedule_type='daily', schedule_target=None,
        )
        today = date(2024, 6, 14)
        logs = [
            types.SimpleNamespace(log_date=today - timedelta(days=i), value=1)
            for i in range(5)
        ]
        result = compute_streak(habit, logs, today)
        # {'current_streak': 5, 'longest_streak': 5, 'debug': {...}}

    A times_per_week habit (schedule_target=3) with the current (incomplete)
    week showing only 2 met days, preceded by N=3 fully-met weeks → current=N,
    longest≥N::

        habit = types.SimpleNamespace(
            habit_type='binary', target_value=None,
            schedule_type='times_per_week', schedule_target=3,
        )
        # 3 met days per week for 3 prior weeks + 2 met days mid-week now
        result = compute_streak(habit, logs, today_midweek)
        # {'current_streak': 3, 'longest_streak': 3, 'debug': {...}}
    """
    # Guard: habit must be provided
    if habit is None:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "debug": {"reason": "habit is None"},
        }

    # Guard: today must be provided
    if today is None:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "debug": {"reason": "today is None"},
        }

    # Guard: logs must be provided and non-empty
    if logs is None:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "debug": {"reason": "logs is None"},
        }
    if len(logs) == 0:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "debug": {"reason": "logs is empty"},
        }

    schedule_type = getattr(habit, "schedule_type", None)
    by_date = _build_logs_by_date(logs)

    if schedule_type == "daily":
        return _daily_streak(habit, by_date, today)

    if schedule_type in ("times_per_week", "weekly"):
        return _weekly_streak(habit, by_date, today)

    # Unrecognised schedule type — return zeros with a diagnostic reason
    return {
        "current_streak": 0,
        "longest_streak": 0,
        "debug": {"reason": f"unrecognised schedule_type: {schedule_type!r}"},
    }
