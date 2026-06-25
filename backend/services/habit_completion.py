"""Pure functions for determining whether a habit period is met.

Centralises the single authoritative rule for habit completion so that
streak, consistency, and any other callers all derive the answer from one
place.  No database access happens here; all queries are the caller's
responsibility.

Examples
--------
Binary habit with a log of value 1 → met::

    import types
    habit = types.SimpleNamespace(habit_type='binary', target_value=None)
    log   = types.SimpleNamespace(value=1)
    result, debug = is_period_met(habit, [log])
    # (True, {'reason': 'binary log value 1 >= 1'})

Count habit with target 8, logged 6 → not met::

    habit = types.SimpleNamespace(habit_type='count', target_value=8)
    log   = types.SimpleNamespace(value=6)
    result, debug = is_period_met(habit, [log])
    # (False, {'reason': 'logged 6 does not meet target 8'})

Count habit with target 8, logged 8 → met::

    habit = types.SimpleNamespace(habit_type='count', target_value=8)
    log   = types.SimpleNamespace(value=8)
    result, debug = is_period_met(habit, [log])
    # (True, {'reason': 'logged 8 meets target 8'})
"""

_BINARY_TYPE = "binary"
_MEASURABLE_TYPES = ("count", "duration")


def _fmt(x) -> str:
    """Format a numeric value as int string when whole, otherwise float string."""
    f = float(x)
    i = int(f)
    # Strip the decimal point for whole numbers so reasons read as "logged 8 meets target 8"
    return str(i) if f == i else str(f)


def _is_binary_met(logs_in_period: list) -> tuple:
    """Return (bool, debug) for a binary habit.

    True when at least one log in the period has value >= 1.
    The reason records which value triggered the result.
    """
    for log in logs_in_period:
        v = float(log.value)
        # Any log with value >= 1 satisfies the binary period
        if v >= 1:
            return (True, {"reason": f"binary log value {_fmt(v)} >= 1"})
    return (False, {"reason": "no log with value >= 1 found"})


def _is_count_met(logs_in_period: list, target_value) -> tuple:
    """Return (bool, debug) for a count or duration habit.

    True when the sum of all logged values in the period meets or exceeds
    target_value.  Caller is responsible for passing only logs that belong
    to the period in question.
    """
    # Sum every value logged in the period
    total = sum(float(log.value) for log in logs_in_period)
    target = float(target_value)

    if total >= target:
        return (True, {"reason": f"logged {_fmt(total)} meets target {_fmt(target)}"})
    return (False, {"reason": f"logged {_fmt(total)} does not meet target {_fmt(target)}"})


def is_period_met(habit, logs_in_period: list) -> tuple:
    """Return ``(bool, {"reason": str})`` indicating whether the habit period is met.

    Parameters
    ----------
    habit:
        A habit row (or any object) with ``habit_type`` (``"binary"``,
        ``"count"``, or ``"duration"``) and, for count/duration types,
        ``target_value``.  Target value is always read from the habit row —
        never hardcoded.
    logs_in_period:
        List of log objects with a numeric ``value`` attribute, scoped to the
        period being evaluated.  All DB queries happen in the caller.

    Returns
    -------
    tuple
        ``(met: bool, debug: dict)`` where ``debug["reason"]`` is a
        human-readable string explaining the decision.

    Examples
    --------
    Binary habit with a log of value 1 → met::

        result, debug = is_period_met(habit, [log])
        # (True, {'reason': 'binary log value 1 >= 1'})

    Count habit with target 8, logged 6 → not met::

        result, debug = is_period_met(habit, [log])
        # (False, {'reason': 'logged 6 does not meet target 8'})

    Count habit with target 8, logged 8 → met::

        result, debug = is_period_met(habit, [log])
        # (True, {'reason': 'logged 8 meets target 8'})
    """
    # Guard: habit must be a valid object with a recognised type
    if habit is None:
        return (False, {"reason": "invalid habit"})

    habit_type = getattr(habit, "habit_type", None)
    if habit_type not in (_BINARY_TYPE,) + _MEASURABLE_TYPES:
        return (False, {"reason": "invalid habit"})

    # Guard: a period with no logs cannot be met regardless of type
    if not logs_in_period:
        return (False, {"reason": "no logs in period"})

    if habit_type == _BINARY_TYPE:
        return _is_binary_met(logs_in_period)

    # count or duration: sum of logged values must reach the target
    target = getattr(habit, "target_value", None)
    if target is None:
        return (False, {"reason": "invalid habit"})
    return _is_count_met(logs_in_period, target)
