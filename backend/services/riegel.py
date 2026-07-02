"""Riegel cross-distance performance equivalence.

Implements the Riegel formula:

    T2 = T1 * (D2 / D1) ^ RIEGEL_EXPONENT

where the exponent is fixed at 1.06.  This formula is used to project a
known race time at one distance to a predicted time at another distance,
enabling apples-to-apples comparison across different race distances.

The canonical use case is expressing every race entry as a half-marathon-
equivalent time via :func:`riegel_half_equivalent`.

All functions are pure — no database access, no side effects.
"""

import math

HALF_MARATHON_KM: float = 21.0975
"""Official half-marathon distance in kilometres."""

RIEGEL_EXPONENT: float = 1.06
"""Riegel fatigue exponent — fixed per the original Riegel model."""


def riegel_project(
    time_seconds: int | float | None,
    source_distance_km: float | None,
    target_distance_km: float | None,
) -> int | None:
    """Project a race time from one distance to another using the Riegel formula.

    T2 = T1 * (D2 / D1) ^ 1.06

    :param time_seconds: Known finish time at *source_distance_km* (seconds).
    :param source_distance_km: Known race distance in kilometres (must be > 0).
    :param target_distance_km: Target distance in kilometres (must be > 0).
    :returns: Projected time in seconds rounded to the nearest second, or
              ``None`` when any argument is absent or non-positive.

    Worked example — 5 K in 20:00 projected to half-marathon:

        T1 = 1200 s   (20 minutes for 5 km)
        D1 = 5.0 km
        D2 = 21.0975 km

        T2 = 1200 * (21.0975 / 5.0) ^ 1.06
           = 1200 * 4.2195 ^ 1.06
           ≈ 5520 s
    """
    if time_seconds is None or source_distance_km is None or target_distance_km is None:
        return None
    if float(source_distance_km) <= 0 or float(target_distance_km) <= 0:
        return None
    projected = float(time_seconds) * math.pow(
        float(target_distance_km) / float(source_distance_km),
        RIEGEL_EXPONENT,
    )
    return round(projected)


def riegel_half_equivalent(
    time_seconds: int | float | None,
    distance_km: float | None,
) -> int | None:
    """Return the half-marathon-equivalent of a race time using the Riegel formula.

    Calls :func:`riegel_project` with *target_distance_km* fixed at
    :data:`HALF_MARATHON_KM` (21.0975 km).

    :param time_seconds: Known finish time in seconds.
    :param distance_km: Known race distance in kilometres.
    :returns: Half-marathon-equivalent time in seconds (nearest second), or
              ``None`` when inputs are absent or invalid.
    """
    return riegel_project(time_seconds, distance_km, HALF_MARATHON_KM)
