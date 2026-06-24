"""Pure function to compute Pearson linear correlation from paired numeric values.

This module is data-source agnostic: it accepts a pre-aligned list of
``[habit_value, outcome_value]`` pairs and performs no database queries, file
I/O, or network calls.
"""

from __future__ import annotations

import math

# Minimum number of paired days required before the correlation coefficient is
# considered statistically meaningful.  The literal number appears only here;
# the function references the constant name throughout.
MIN_PAIRED_DAYS: int = 14


def compute_correlation(paired_values):
    """Compute Pearson linear correlation over a list of paired numeric values.

    Accepts the output format produced by ``align_habit_and_outcome`` —
    a list of ``[habit_value, outcome_value]`` two-element sequences — and
    returns a summary of the linear relationship between the two columns.

    **Math (all steps described in prose):**

    Let ``x`` be the first column (habit values) and ``y`` be the second
    column (outcome values), with ``n`` elements in each.

    1. Compute the column means: ``x_mean = (Σ x_i) / n`` and
       ``y_mean = (Σ y_i) / n``.

    2. For each pair compute the deviation from the column mean:
       ``dx_i = x_i − x_mean`` and ``dy_i = y_i − y_mean``.

    3. Sum the cross-products of deviations:
       ``cross_sum = Σ (dx_i × dy_i)`` for i = 1 … n.

    4. Compute the sum of squared deviations for each column:
       ``ss_x = Σ dx_i²`` and ``ss_y = Σ dy_i²``.

    5. Compute the population standard deviation for each column:
       ``std_x = √(ss_x / n)`` and ``std_y = √(ss_y / n)``.

    6. Form the denominator: ``denominator = n × std_x × std_y``.

    7. The Pearson coefficient is ``r = cross_sum / denominator``.
       When the denominator is zero (one or both columns have zero variance),
       ``r`` is defined as ``0.0`` (no relationship can be inferred).
       The result is clipped to the closed range ``[−1, 1]`` to guard against
       floating-point rounding outside that range.

    Args:
        paired_values: A list of two-element sequences ``[habit_value,
            outcome_value]``, one per paired day, as produced by
            ``align_habit_and_outcome``.  May also be ``None`` or an empty
            list when no data is available.

    Returns:
        A two-element tuple ``(result, reason)`` in one of two forms:

        *Invalid input* — when ``paired_values`` is ``None`` or an empty list:
            ``(None, reason_str)`` where ``reason_str`` is a human-readable
            string describing why the input was rejected.

        *Valid input* — when at least one pair is present:
            ``(result_dict, None)`` where ``result_dict`` contains exactly:

            - ``coefficient`` (float): Pearson *r* in the closed range −1 to 1.
            - ``sample_size`` (int): number of pairs used in the computation.
            - ``confident`` (bool): ``True`` when
              ``sample_size >= MIN_PAIRED_DAYS``, ``False`` otherwise.
            - ``debug`` (dict): intermediate values — ``x_mean``, ``y_mean``,
              ``cross_sum``, ``std_x``, ``std_y``.
            - ``reason`` (str) — present **only** when ``confident`` is
              ``False`` — the string ``"not enough paired days yet"``.

    Worked example — positive relationship (coefficient near +1):

        Habit values and outcome values both increase together::

            pairs = [[1, 10], [2, 20], [3, 30], [4, 40], [5, 50]]
            result, _ = compute_correlation(pairs)
            # result["coefficient"] ≈ 1.0   (perfect positive relationship)
            # result["sample_size"] == 5
            # result["confident"] == False  (5 < MIN_PAIRED_DAYS)
            # result["reason"] == "not enough paired days yet"

    Worked example — no systematic relationship (coefficient near 0):

        Alternating values cancel out, producing a coefficient near 0::

            pairs = [
                [1, 10], [2, 5], [1, 10], [2, 5], [1, 10], [2, 5],
                [1, 10], [2, 5], [1, 10], [2, 5], [1, 10], [2, 5],
                [1, 10], [2, 5],
            ]  # 14 pairs (== MIN_PAIRED_DAYS)
            result, _ = compute_correlation(pairs)
            # result["coefficient"] ≈ 0.0   (x and y move in opposite directions
            #                                equally, net correlation ≈ 0)
            # result["confident"] == True   (14 >= MIN_PAIRED_DAYS)
            # "reason" key is absent from result
    """
    if paired_values is None:
        return None, "paired_values is required"

    if len(paired_values) == 0:
        return None, "paired_values is empty"

    sample_size = len(paired_values)

    x_values = [float(pair[0]) for pair in paired_values]
    y_values = [float(pair[1]) for pair in paired_values]

    x_mean = sum(x_values) / sample_size
    y_mean = sum(y_values) / sample_size

    deviations_x = [x - x_mean for x in x_values]
    deviations_y = [y - y_mean for y in y_values]

    cross_sum = sum(dx * dy for dx, dy in zip(deviations_x, deviations_y))
    ss_x = sum(dx * dx for dx in deviations_x)
    ss_y = sum(dy * dy for dy in deviations_y)

    std_x = math.sqrt(ss_x / sample_size)
    std_y = math.sqrt(ss_y / sample_size)

    denominator = sample_size * std_x * std_y

    if denominator == 0:
        coefficient = 0.0
    else:
        raw_coefficient = cross_sum / denominator
        coefficient = max(-1.0, min(1.0, raw_coefficient))

    confident = sample_size >= MIN_PAIRED_DAYS

    debug = {
        "x_mean": x_mean,
        "y_mean": y_mean,
        "cross_sum": cross_sum,
        "std_x": std_x,
        "std_y": std_y,
    }

    result = {
        "coefficient": coefficient,
        "sample_size": sample_size,
        "confident": confident,
        "debug": debug,
    }

    if not confident:
        result["reason"] = "not enough paired days yet"

    return result, None
