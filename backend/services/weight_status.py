"""
Compute the status label for a weight target by comparing actual weight against
the linearly interpolated expected weight at a given date.

Math:
    expected = start_weight + (target_weight - start_weight) * (elapsed / total_days)
    gap = current_avg_kg - expected
    tolerance = max(0.5, 0.05 * abs(target_weight - start_weight))

Examples:
    Loss target: start=85 kg, target=75 kg (10 kg over 100 days).
      At day 50 → expected=80 kg.
      Actual=80 → "on_track". Actual=82 (gap +2) → "behind". Actual=78 (gap -2) → "ahead".

    Gain target: start=70 kg, target=80 kg (10 kg over 100 days).
      At day 50 → expected=75 kg.
      Actual=77 (gap +2) → "ahead". Actual=73 (gap -2) → "behind".
"""
from __future__ import annotations

from datetime import date as _date
from typing import Optional


def compute_status_label(
    target,
    current_avg_kg: Optional[float],
    as_of_date: _date,
) -> str:
    """Return 'on_track', 'behind', 'ahead', or 'no_data'."""
    if current_avg_kg is None:
        return "no_data"

    start_w = float(target.start_weight_kg)
    target_w = float(target.target_weight_kg)

    start_d = (
        target.start_date
        if isinstance(target.start_date, _date)
        else _date.fromisoformat(str(target.start_date))
    )
    target_d = (
        target.target_date
        if isinstance(target.target_date, _date)
        else _date.fromisoformat(str(target.target_date))
    )

    total_days = (target_d - start_d).days
    elapsed_days = (as_of_date - start_d).days

    t = elapsed_days / total_days if total_days > 0 else 1.0

    expected = start_w + (target_w - start_w) * t
    gap = current_avg_kg - expected

    tolerance = max(0.5, 0.05 * abs(target_w - start_w))

    if abs(gap) <= tolerance:
        return "on_track"

    is_loss = target_w < start_w
    if is_loss:
        return "ahead" if gap < 0 else "behind"
    else:
        return "ahead" if gap > 0 else "behind"
