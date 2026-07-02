"""Heat and humidity correction for training load normalization (issue #1168).

Computes a correction factor that accounts for the physiological overhead
imposed by heat and humidity on HR-based metrics (aerobic decoupling, pace
efficiency).  The correction is bounded to prevent over-adjustment on outlier
conditions.

Public API
----------
compute_heat_correction_factor(temperature_c, humidity_pct, **kwargs)
    -> tuple[float, bool]
    Pure function.  Returns (correction_factor, heat_active).

apply_heat_correction_to_decoupling(result, correction_factor, threshold)
    -> dict
    Adjusts a decoupling result dict to account for heat-induced HR elevation.
"""

from __future__ import annotations

# Default thresholds and penalty rates (match Bangkok summer conditions).
TEMP_THRESHOLD_C: float = 32.0           # °C above which heat penalty starts
HUMIDITY_THRESHOLD_PCT: float = 70.0     # % above which humidity penalty starts
MAX_CORRECTION_PCT: float = 15.0         # cap: no run adjusted by more than ±15%
TEMP_PENALTY_PER_DEGREE: float = 0.5    # % HR inflation per degree above threshold
HUMIDITY_PENALTY_PER_POINT: float = 0.1  # % HR inflation per humidity point above threshold


def compute_heat_correction_factor(
    temperature_c: float | None,
    humidity_pct: float | None,
    *,
    temp_threshold: float = TEMP_THRESHOLD_C,
    humidity_threshold: float = HUMIDITY_THRESHOLD_PCT,
    max_correction_pct: float = MAX_CORRECTION_PCT,
    temp_penalty_per_degree: float = TEMP_PENALTY_PER_DEGREE,
    humidity_penalty_per_point: float = HUMIDITY_PENALTY_PER_POINT,
) -> tuple[float, bool]:
    """Compute the HR correction factor due to heat and humidity.

    Combines a temperature penalty and a humidity penalty, then caps the total
    at ``max_correction_pct`` to prevent outlier overcorrection (AC3).

    Parameters
    ----------
    temperature_c:
        Ambient air temperature in Celsius, or ``None`` if not recorded.
    humidity_pct:
        Relative humidity (0–100), or ``None`` if not recorded.
    temp_threshold:
        Temperature (°C) above which the heat penalty starts.
    humidity_threshold:
        Humidity (%) above which the humidity penalty starts.
    max_correction_pct:
        Maximum total correction in percent (default 15).
    temp_penalty_per_degree:
        Percent penalty per degree above ``temp_threshold``.
    humidity_penalty_per_point:
        Percent penalty per humidity point above ``humidity_threshold``.

    Returns
    -------
    tuple[float, bool]
        ``(correction_factor, heat_active)`` where:

        - ``correction_factor`` is in ``[0.0, max_correction_pct / 100]``.
          It represents the estimated fraction by which heat/humidity
          inflated the second-half HR relative to a neutral environment.
        - ``heat_active`` is ``True`` when any correction applies.
    """
    temp_penalty_pct = 0.0
    if temperature_c is not None and temperature_c > temp_threshold:
        temp_penalty_pct = (temperature_c - temp_threshold) * temp_penalty_per_degree

    humidity_penalty_pct = 0.0
    if humidity_pct is not None and humidity_pct > humidity_threshold:
        humidity_penalty_pct = (humidity_pct - humidity_threshold) * humidity_penalty_per_point

    total_pct = temp_penalty_pct + humidity_penalty_pct
    capped_pct = min(total_pct, max_correction_pct)
    correction_factor = capped_pct / 100.0

    return correction_factor, correction_factor > 0.0


def apply_heat_correction_to_decoupling(
    result: dict,
    correction_factor: float,
    threshold: float | None,
) -> dict:
    """Return a new decoupling result with heat/humidity correction applied.

    Heat stress builds progressively over a run and primarily elevates HR in
    the second half.  The ``correction_factor`` represents the estimated
    fraction of second-half HR elevation attributable to heat rather than
    aerobic drift.  Dividing the second-half HR by ``(1 + factor)`` restores
    the cool-equivalent efficiency:

        adjusted_e2 = raw_e2 * (1 + correction_factor)

    Both raw and adjusted values are returned for transparency (UAT step 3).

    Parameters
    ----------
    result:
        A decoupling result dict as returned by ``compute_decoupling``.
        Must contain ``"debug"`` with ``"first_half_efficiency"`` and
        ``"second_half_efficiency"``.
    correction_factor:
        Value in ``[0.0, MAX_CORRECTION_PCT / 100]`` from
        ``compute_heat_correction_factor``.  If 0.0 the original dict is
        returned unchanged.
    threshold:
        User's aerobic decoupling threshold (or ``None``).  Used to
        re-evaluate ``faded_late`` on the adjusted result.

    Returns
    -------
    dict
        When ``correction_factor == 0``: the original ``result`` object.

        Otherwise a new dict with the same shape plus:

        - ``raw_decoupling_pct``: original uncorrected decoupling percentage
        - ``heat_correction_factor``: the applied factor
        - ``heat_correction_active``: ``True``
    """
    if correction_factor <= 0.0:
        return result

    e1 = result["debug"]["first_half_efficiency"]
    e2 = result["debug"]["second_half_efficiency"]

    if e1 == 0:
        return result

    # Heat inflates second-half HR; correcting reduces it, restoring efficiency.
    adjusted_e2 = e2 * (1.0 + correction_factor)
    adjusted_pct = round((e1 - adjusted_e2) / e1 * 100, 2)

    if threshold is not None:
        faded_late = adjusted_pct > threshold
    else:
        faded_late = False

    return {
        "decoupling_pct": adjusted_pct,
        "faded_late": faded_late,
        "debug": {
            "first_half_efficiency": e1,
            "second_half_efficiency": adjusted_e2,
        },
        "raw_decoupling_pct": result["decoupling_pct"],
        "heat_correction_factor": correction_factor,
        "heat_correction_active": True,
    }
