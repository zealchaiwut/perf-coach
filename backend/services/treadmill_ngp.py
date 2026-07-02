"""Single normalization point for treadmill incline → NGP conversion (issue #1169).

All grade-adjusted pace computation flows through :func:`compute_ngp`.  No
other code path may apply a separate grade adjustment after this function runs
— doing so would double-count the incline correction.

Normalized Graded Pace (NGP / GAP)
------------------------------------
NGP converts the pace recorded during a treadmill (or hilly outdoor) run into a
"flat-equivalent pace" — the pace at which the athlete would exert the same
metabolic cost on level ground.  It is always computed from the raw pace and the
raw grade at a single point in the pipeline.

Formula
-------
Based on Minetti et al. (2002) J Physiol, the energy cost of running at
gradient *i* (decimal fraction, e.g. 0.05 for 5 %) is:

    Cr(i) = 155.4·i⁵ − 30.4·i⁴ − 43.3·i³ + 46.3·i² + 19.5·i + 3.6  [J·kg⁻¹·m⁻¹]

The flat-running cost is Cr(0) = 3.6.  The flat-equivalent pace is therefore:

    flat_equivalent_pace = raw_pace × (3.6 / Cr(i))

At grade 0 the factor is exactly 1 (no transformation).  For positive grades
the factor is < 1, making the flat-equivalent pace *faster* (lower s/km) than
the raw treadmill pace.

Worked example
--------------
Athlete runs at 360 s/km (6:00/km) on a 5 % incline:

    i  = 0.05
    Cr = 155.4×(0.05)⁵ − 30.4×(0.05)⁴ − 43.3×(0.05)³
         + 46.3×(0.05)² + 19.5×(0.05) + 3.6
       ≈ 4.686 J·kg⁻¹·m⁻¹
    flat_equivalent_pace = 360 × (3.6 / 4.686) ≈ 276.5 s/km  (~4:37/km)

This module is pure: no database access, no side effects, no I/O.
"""

from __future__ import annotations

from typing import Optional

# Flat-running energy cost constant from Minetti et al. (2002).
# This is also the value of Cr(0) — the constant term in the polynomial.
_CR_FLAT: float = 3.6  # J·kg⁻¹·m⁻¹


def _energy_cost_ratio(grade_percent: float) -> float:
    """Return Cr(i) / Cr(0) using the Minetti (2002) polynomial.

    Parameters
    ----------
    grade_percent:
        Treadmill incline as a percentage (e.g. 5.0 for 5 %).

    Returns
    -------
    float — the ratio of graded energy cost to flat energy cost.
             Always ≥ 1 for grades ≥ 0 (running uphill costs more energy).
             Exactly 1 when grade_percent == 0.
    """
    i = grade_percent / 100.0
    cr_i = (
        155.4 * i**5
        - 30.4 * i**4
        - 43.3 * i**3
        + 46.3 * i**2
        + 19.5 * i
        + _CR_FLAT
    )
    return cr_i / _CR_FLAT


def compute_ngp(
    raw_pace_seconds_per_km: float,
    grade_percent: float,
) -> float:
    """Convert a treadmill pace at a known incline to its flat-equivalent pace.

    This is the single canonical normalization point for incline → NGP.  All
    downstream consumers of flat-equivalent pace must call this function; no
    other code path may apply a grade adjustment independently.

    Parameters
    ----------
    raw_pace_seconds_per_km:
        The athlete's actual recorded pace on the treadmill, in seconds per km.
        Must be a positive number.
    grade_percent:
        Treadmill incline in percent (e.g. 5.0 for 5 %).
        Pass 0.0 for a flat treadmill belt; the return value will equal the
        raw pace exactly.

    Returns
    -------
    float — flat-equivalent pace in seconds per km.
             Equal to raw_pace_seconds_per_km when grade_percent is 0.
             Strictly less than raw_pace_seconds_per_km for positive grades
             (faster pace represents the same effort on flat ground).

    Worked example
    --------------
    >>> round(compute_ngp(360.0, 5.0), 1)
    276.5
    >>> compute_ngp(360.0, 0.0) == 360.0
    True
    """
    ratio = _energy_cost_ratio(grade_percent)
    return float(raw_pace_seconds_per_km) / ratio


def normalize_treadmill_signal(signal: dict) -> dict:
    """Enrich a raw activity signal dict with ``flat_equivalent_pace``.

    This is the single entry-point for grade normalization in the activity
    signal pipeline.  It reads ``grade_percent`` from the signal exactly once,
    calls :func:`compute_ngp`, and returns a new dict with the result.

    Rules
    -----
    * If ``grade_percent`` is absent or ``None``, the signal is returned
      unchanged (no ``flat_equivalent_pace`` key is added).  Outdoor activities
      that carry no incline data fall into this path.
    * If ``grade_percent`` is 0, ``flat_equivalent_pace`` is set to the raw
      pace (no numeric transformation applied, but the field is present).
    * The input dict is never mutated; a shallow copy is always returned.

    Parameters
    ----------
    signal:
        Raw activity signal dict.  Relevant keys:
        - ``pace_seconds_per_km`` (float) — raw recorded pace.
        - ``grade_percent`` (float or None) — treadmill incline in percent.
          When absent or None the signal passes through unchanged.

    Returns
    -------
    dict — copy of *signal* with ``flat_equivalent_pace`` added when incline
           data is present.  All other keys are preserved verbatim.
    """
    out = dict(signal)

    grade: Optional[float] = signal.get("grade_percent")
    if grade is None:
        return out

    raw_pace: Optional[float] = signal.get("pace_seconds_per_km")
    if raw_pace is None:
        return out

    out["flat_equivalent_pace"] = compute_ngp(
        raw_pace_seconds_per_km=float(raw_pace),
        grade_percent=float(grade),
    )
    return out
