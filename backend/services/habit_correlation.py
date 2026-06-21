"""Pure function to compute point-biserial correlation between a boolean habit
completion series and a numeric outcome series.

No database access. No network I/O. No mutations to inputs.
"""

import statistics


def compute_correlation(pairs):
    """Compute point-biserial correlation from a list of aligned habit–outcome pairs.

    Each element of ``pairs`` is a dict produced by ``align_habit_and_outcome``.
    The ``habit_value`` key must be a boolean and the ``outcome_value`` key must be
    a numeric scalar.

    Returns a dict with three keys:

    ``r``
        Pearson / point-biserial correlation coefficient as a float in [-1, 1].
        Zero is returned when the coefficient cannot be computed (see ``reason``).

    ``n``
        Number of pairs processed (the sample size used in the computation).

    ``reason``
        An empty string when the coefficient was successfully computed; a
        non-empty human-readable string when computation was not possible
        (e.g. ``n < 2``, zero variance in either series).

    The function handles all degenerate inputs gracefully and never raises an
    exception. Callers may therefore always read ``r`` and ``n`` without
    guarding for exceptions — but should check ``reason`` to know whether
    ``r`` is meaningful.

    Args:
        pairs: A list of dicts. Each dict must contain:
            - ``habit_value``: bool — whether the habit was completed.
            - ``outcome_value``: float — the measured outcome on the aligned date.
            Additional keys (e.g. ``habit_date``, ``outcome_date``) are ignored.

    Returns:
        dict with keys ``r`` (float), ``n`` (int), ``reason`` (str).

    Worked example::

        pairs = [
            {"habit_value": True,  "outcome_value": 80.0},
            {"habit_value": False, "outcome_value": 40.0},
            {"habit_value": True,  "outcome_value": 80.0},
            {"habit_value": False, "outcome_value": 40.0},
        ]
        result = compute_correlation(pairs)
        # n == 4
        # r == 1.0  (perfect positive correlation)
        # reason == ""

    Zero-variance example::

        pairs = [{"habit_value": True, "outcome_value": float(v)} for v in range(10)]
        result = compute_correlation(pairs)
        # r == 0.0  (habit_value is constant — zero variance in x)
        # reason != ""  (explains why r could not be computed)
    """
    n = len(pairs)

    if n < 2:
        return {
            "r": 0.0,
            "n": n,
            "reason": f"insufficient data: need at least 2 pairs, got {n}",
        }

    x = [1 if p["habit_value"] else 0 for p in pairs]
    y = [float(p["outcome_value"]) for p in pairs]

    try:
        r = statistics.correlation(x, y)
        return {"r": r, "n": n, "reason": ""}
    except statistics.StatisticsError as exc:
        return {
            "r": 0.0,
            "n": n,
            "reason": f"cannot compute correlation: {exc}",
        }
