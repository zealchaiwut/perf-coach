"""Compute weekly percent bodyweight rate of change from EWMA values (issue #1155).

Formula: ((ewma_end - ewma_start) / ewma_start) * 100

For a true weekly rate, supply 8 consecutive daily EWMA values (spanning 7 days).
The caller is responsible for providing the correct window; this function applies
the formula directly to the first and last values in the supplied list.
"""
from __future__ import annotations

from typing import Optional


def compute_weekly_pct_bw_rate_of_change(ewma_values: list) -> Optional[float]:
    """Compute weekly percent bodyweight rate of change from a sequence of EWMA values.

    Parameters
    ----------
    ewma_values:
        Ordered list of EWMA bodyweight values (oldest first). For a true
        weekly rate, supply 8 consecutive daily values (7-day span).

    Returns
    -------
    float or None
        Percentage change from ewma_values[0] to ewma_values[-1].
        Positive = weight gain; negative = weight loss.
        Returns None when fewer than 2 data points are supplied.

    Raises
    ------
    ValueError
        If ewma_values[0] is zero (bodyweight of zero is physiologically
        invalid and would produce a division-by-zero error).
    """
    if len(ewma_values) < 2:
        return None

    ewma_start = float(ewma_values[0])
    ewma_end = float(ewma_values[-1])

    if ewma_start == 0.0:
        raise ValueError(
            "ewma_start is zero: cannot compute percent change from a zero bodyweight"
        )

    return ((ewma_end - ewma_start) / ewma_start) * 100.0
