"""Polarized-split target-band deviation check.

check_polarized_split compares an athlete's actual low/moderate/high intensity
percentages against configurable target bounds and returns whether all bands
are on target, which bands deviate and in which direction, and whether the
"grey zone" (excessive moderate) flag is raised.

Default polarized model bounds:
    low      [75, 85]
    moderate  [5, 10]
    high     [15, 20]
"""

_DEFAULT_BOUNDS = {
    "low":      [75, 85],
    "moderate": [5, 10],
    "high":     [15, 20],  # authoritative bound: [15, 20] per original AC (#1131) and docstring
}


def check_polarized_split(low, moderate, high, bounds=None):
    """Check whether an intensity split falls within polarized target bands.

    Args:
        low:      Actual percentage in the low-intensity band.
        moderate: Actual percentage in the moderate (grey zone) band.
        high:     Actual percentage in the high-intensity band.
        bounds:   Optional dict overriding default target bounds.  Keys are
                  "low", "moderate", and "high"; each value is a two-element
                  list [lower_bound, upper_bound] (both inclusive).

    Returns:
        dict with:
            on_target  (bool)   True only when all three bands are within
                                their respective bounds.
            deviations (list)   Each entry is a dict with "band" (str) and
                                "direction" ("above" or "below").
            grey_zone  (bool)   True when the moderate band is above its
                                upper bound, explicitly surfacing grey-zone
                                overaccumulation.
    """
    resolved = dict(_DEFAULT_BOUNDS)
    if bounds:
        resolved.update(bounds)

    actuals = {"low": low, "moderate": moderate, "high": high}

    deviations = []
    for band, value in actuals.items():
        lo, hi = resolved[band]
        if value < lo:
            deviations.append({"band": band, "direction": "below"})
        elif value > hi:
            deviations.append({"band": band, "direction": "above"})

    moderate_hi = resolved["moderate"][1]
    grey_zone = moderate > moderate_hi

    return {
        "on_target": len(deviations) == 0,
        "deviations": deviations,
        "grey_zone": grey_zone,
    }
