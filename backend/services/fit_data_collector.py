"""Fit-data collector with minimum-data gate (issue #1166).

Assembles paired (load, performance) tuples from historical records for use by
the forecasting pipeline.  The gate raises ``InsufficientDataError`` when the
dataset is too small to produce reliable curve-fitting constants, preventing
spurious or unstable estimates from reaching downstream consumers.

This module is pure: no database access, no side effects, no I/O.
"""

from __future__ import annotations

# Minimum number of paired (load, performance) points required before the
# curve-fitting step may be invoked.  Raising this threshold increases
# reliability of fitted constants at the cost of requiring more history.
MIN_FIT_POINTS: int = 5


class InsufficientDataError(Exception):
    """Raised when the collected dataset contains fewer than MIN_FIT_POINTS pairs.

    Callers must populate more history before attempting curve-fitting.
    """


def collect_fit_data(history: list) -> list:
    """Assemble paired (load, performance) tuples from *history* records.

    Parameters
    ----------
    history:
        A list of dicts, each containing at minimum:
          - ``load``        — numeric training load value
          - ``performance`` — numeric performance measurement

        Records are returned in the same order as supplied.

    Returns
    -------
    list of (load, performance) tuples — one per record in *history*.

    Raises
    ------
    InsufficientDataError
        When ``len(history) < MIN_FIT_POINTS``.  The exception message
        states the actual count and the minimum required.

    Worked example
    --------------
    >>> records = [{"load": 100.0, "performance": 55.0},
    ...            {"load": 200.0, "performance": 60.0},
    ...            {"load": 300.0, "performance": 65.0},
    ...            {"load": 400.0, "performance": 70.0},
    ...            {"load": 500.0, "performance": 75.0}]
    >>> pairs = collect_fit_data(records)
    >>> pairs[0]
    (100.0, 55.0)
    >>> len(pairs)
    5
    """
    n = len(history)
    if n < MIN_FIT_POINTS:
        raise InsufficientDataError(
            f"Insufficient data for curve fitting: {n} point(s) collected, "
            f"minimum required is {MIN_FIT_POINTS}."
        )
    return [(float(record["load"]), float(record["performance"])) for record in history]
