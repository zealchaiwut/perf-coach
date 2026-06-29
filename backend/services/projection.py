"""
Forward CTL/ATL/TSB projection module.

Rolls Chronic Training Load (CTL), Acute Training Load (ATL), and Training
Stress Balance (TSB) forward from a known fitness state using a sequence of
planned daily loads.  This is a pure function module — no database access, no
side effects.

Math
----
CTL and ATL are updated each day via exponential decay:

    new_ctl = prev_ctl * CTL_DECAY + load * (1 - CTL_DECAY)
    new_atl = prev_atl * ATL_DECAY + load * (1 - ATL_DECAY)
    tsb     = new_ctl - new_atl

where the decay factors are:

    CTL_DECAY = exp(-1 / 42)  ≈ 0.9763
    ATL_DECAY = exp(-1 /  7)  ≈ 0.8668

This is mathematically equivalent to the EWMA alpha form used in
``fitness_model.compute_fitness_series`` — the decay factor is simply
``1 - alpha``.

Time constants are imported from ``backend.services.fitness_model`` (Layer-1)
so no values are duplicated here.

Worked example
--------------
Start: CTL=50, ATL=70 (form = -20).  Planned load = 20 TSS/day for 14 days.

Because ATL has a shorter time constant (7-day) than CTL (42-day) it decays
faster toward 20.  After 14 rest days ATL approaches 20 while CTL remains
higher than ATL.  TSB (CTL - ATL) rises and becomes positive well before day 14,
illustrating how a taper window improves form.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from backend.services.fitness_model import ATL_TIME_CONSTANT, CTL_TIME_CONSTANT

# ── Decay factors derived from Layer-1 time constants ────────────────────────
# These are the per-day persistence fractions: how much of yesterday's load
# metric carries forward before today's load is blended in.
CTL_DECAY: float = math.exp(-1 / CTL_TIME_CONSTANT)
ATL_DECAY: float = math.exp(-1 / ATL_TIME_CONSTANT)


def project_fitness(
    planned_load: list[float],
    start_ctl: float,
    start_atl: float,
    start_date: date,
) -> dict[date, dict[str, float]]:
    """Roll CTL/ATL/TSB forward day by day from *start_date* using *planned_load*.

    Parameters
    ----------
    planned_load:
        Ordered list of TSS values, one per day.  Day 1 of the projection uses
        ``planned_load[0]``, day 2 uses ``planned_load[1]``, and so on.
        An empty list returns an empty dict.
    start_ctl:
        CTL value on *start_date* (the day before the first projected day).
    start_atl:
        ATL value on *start_date* (the day before the first projected day).
    start_date:
        Anchor date.  The first entry in the returned series is
        ``start_date + 1 day``; the last is ``start_date + len(planned_load) days``.

    Returns
    -------
    dict mapping ``date`` → ``{"ctl": float, "atl": float, "tsb": float}``.
    The dict contains exactly ``len(planned_load)`` entries, one per day, with
    no gaps.  An empty *planned_load* returns an empty dict.
    """
    series: dict[date, dict[str, float]] = {}
    ctl = start_ctl
    atl = start_atl
    for i, load in enumerate(planned_load):
        ctl = ctl * CTL_DECAY + load * (1 - CTL_DECAY)
        atl = atl * ATL_DECAY + load * (1 - ATL_DECAY)
        tsb = ctl - atl
        series[start_date + timedelta(days=i + 1)] = {
            "ctl": ctl,
            "atl": atl,
            "tsb": tsb,
        }
    return series
