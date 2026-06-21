"""Pure function to build plain-language habit-outcome association insights.

No database access. No network I/O. No mutations to inputs.
The caller is responsible for fetching habit logs and outcome series from the
data store before passing them in.
"""

from backend.services.habit_outcome_alignment import align_habit_and_outcome
from backend.services.habit_correlation import compute_correlation


def _lag_description(lag_days):
    """Return a human-readable lag label for use inside an insight string."""
    if lag_days == 0:
        return "same-day"
    if lag_days == 1:
        return "next-day"
    return f"{lag_days}-day-later"


def build_habit_outcome_insights(
    habits,
    outcome_series,
    lags=None,
    min_n=10,
    min_r=0.1,
):
    """Build plain-language association strings for every (habit, outcome, lag) triple
    that clears the supplied confidence bar.

    The function is deliberately stateless and data-source agnostic.  All DB
    access is delegated entirely to the caller — no queries, file I/O, or network
    calls occur here.

    Args:
        habits: A list of dicts, each with:
            - ``name`` (str): human-readable habit name.
            - ``logs`` (dict[str, bool]): mapping of ``YYYY-MM-DD`` date strings
              to boolean completion values for that day.
            Pass ``None`` or an empty list when no habits are available.
        outcome_series: A dict mapping outcome name strings to their date-keyed
            numeric series.  Each value is a dict mapping ``YYYY-MM-DD`` date
            strings to float measurements.  Supported by the existing callers:
            ``readiness_tsb``, ``daily_load``, ``weight_trend``.  Adding a new
            outcome requires only adding it to this dict — no changes to this
            function.
            Pass ``None`` or ``{}`` when no outcomes are available.
        lags: A list of non-negative integers specifying which lag offsets to
            test.  Defaults to ``[0, 1]`` (same-day and next-day).
        min_n: Minimum number of aligned pairs required for a triple to survive.
            Triples whose sample size is strictly less than ``min_n`` are
            suppressed.  Defaults to ``10``.
        min_r: Minimum absolute correlation coefficient required for a triple to
            survive.  Triples whose ``|r|`` is strictly less than ``min_r`` are
            suppressed.  Defaults to ``0.1``.

    Returns:
        A two-element tuple ``(insights, reason)``.

        ``insights`` is a list of plain-language strings, one per surviving
        triple.  Each string names the habit, the outcome, the direction of
        association (``higher`` or ``lower``), the lag (e.g. ``same-day`` or
        ``next-day``), the correlation coefficient (``r = X.XX``), and the
        sample size (``n = NN``).  All phrasing is associative — causal language
        such as *causes*, *leads to*, *results in*, or *drives* does not appear.

        ``reason`` is an empty string when at least one insight is returned.
        It is a non-empty human-readable string when the list is empty,
        explaining which condition was triggered (no habits, no outcomes, or no
        triples met the confidence bar).

    Worked example::

        habits = [
            {
                "name": "Sleep ≥ 7h",
                "logs": {
                    "2025-01-01": True,
                    "2025-01-02": False,
                    "2025-01-03": True,
                    # ... 27 more days, alternating True/False
                },
            }
        ]
        outcome_series = {
            "readiness_tsb": {
                "2025-01-01": 80.0,
                "2025-01-02": 40.0,
                "2025-01-03": 80.0,
                # ... 27 more days matching the habit pattern
            }
        }

        insights, reason = build_habit_outcome_insights(
            habits,
            outcome_series,
            lags=[0],
            min_n=5,
            min_r=0.1,
        )

        # Intermediate: align_habit_and_outcome produces 30 pairs at lag=0.
        # compute_correlation returns r ≈ 1.0 and n = 30, both above thresholds.
        #
        # Expected output (one insight):
        # insights == [
        #     "days you hit your Sleep ≥ 7h habit, same-day readiness tsb "
        #     "tends to be higher (r = 1.00, n = 30)"
        # ]
        # reason == ""
    """
    if lags is None:
        lags = [0, 1]

    if not habits:
        return [], "no habits provided; habit list is missing or empty"

    if not outcome_series:
        return [], "no outcome series provided; outcome dict is missing or empty"

    insights = []

    for habit in habits:
        habit_name = habit["name"]
        habit_logs = habit.get("logs") or {}

        for outcome_name, series in outcome_series.items():
            for lag in lags:
                pairs, _debug = align_habit_and_outcome(habit_logs, series, lag)
                corr = compute_correlation(pairs)

                if corr["n"] < min_n:
                    continue
                if abs(corr["r"]) < min_r:
                    continue
                if corr["reason"]:
                    continue

                lag_desc = _lag_description(lag)
                direction = "higher" if corr["r"] > 0 else "lower"
                readable_outcome = outcome_name.replace("_", " ")

                insight = (
                    f"days you hit your {habit_name} habit, "
                    f"{lag_desc} {readable_outcome} tends to be {direction} "
                    f"(r = {corr['r']:.2f}, n = {corr['n']})"
                )
                insights.append(insight)

    if not insights:
        return [], "no habit-outcome pairs met the confidence minimum (min_n or min_r)"

    return insights, ""
