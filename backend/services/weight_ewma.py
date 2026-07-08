"""Exponentially Weighted Moving Average smoothing for bodyweight entries (issue #1154).

Public API
----------
compute_ewma(entries, *, span=DEFAULT_SPAN, alpha=None) -> list[float]

    entries : list of dicts with keys ``date`` (datetime.date) and ``weight_kg`` (float).
              Must be in chronological order. Gaps in the date sequence are handled
              by carrying the last smoothed value forward — missing days are skipped,
              never zero-filled.
    span    : Lookback span in days (default 14). Converted to alpha via
              ``alpha = 2 / (span + 1)``.
    alpha   : Override computed alpha directly. Clamped to ``[0.0, 1.0]`` via
              ``max(0.0, min(1.0, a))``. alpha=0 freezes the EWMA at the first value.

Returns a list of smoothed float values the same length as the input.
An empty input returns an empty list without raising.
"""
from __future__ import annotations

from typing import Optional

DEFAULT_SPAN: int = 14


def compute_ewma(
    entries: list,
    *,
    span: int = DEFAULT_SPAN,
    alpha: Optional[float] = None,
) -> list[float]:
    """Return EWMA-smoothed weights for the given time-ordered entries.

    Parameters
    ----------
    entries:
        Time-ordered list of dicts, each with ``date`` (datetime.date) and
        ``weight_kg`` (float/Decimal). Gaps in dates are skipped — the last
        smoothed value is carried forward implicitly.
    span:
        Window span for computing alpha. Ignored when ``alpha`` is provided.
    alpha:
        Explicit smoothing factor, clamped to ``[0.0, 1.0]`` via
        ``max(0.0, min(1.0, a))``. ``alpha=1`` yields no smoothing (raw values
        pass through). ``alpha=0`` freezes the EWMA at the first value — every
        subsequent value equals the bootstrap weight.

    Returns
    -------
    list[float]
        Same length as ``entries``. First element is always the raw first
        weight (bootstrap). Each subsequent element blends the previous
        smoothed value with the new raw value.
    """
    if not entries:
        return []

    if alpha is None:
        a = 2.0 / (span + 1)
    else:
        a = float(alpha)

    a = max(0.0, min(1.0, a))

    smoothed: list[float] = []
    prev = float(entries[0]["weight_kg"])
    smoothed.append(prev)

    for entry in entries[1:]:
        raw = float(entry["weight_kg"])
        prev = a * raw + (1.0 - a) * prev
        smoothed.append(prev)

    return smoothed
