"""Zone band constants for running performance scoring (issue #701).

This module defines the default intensity band groupings and scoring
thresholds used by compute_endurance_score and compute_speed_score.
All values can be overridden by the caller via make_zone_constants;
nothing is hardcoded inside the pure score functions themselves.

Default band groupings
-----------------------
Endurance bands: easy, steady
    These correspond to sub-threshold aerobic effort where the primary
    adaptation is cardiovascular efficiency and fat oxidation.

Speed bands: hard, interval
    These correspond to above-threshold anaerobic effort where the
    primary adaptation is power output and lactate tolerance.
    "interval" is a supplementary label used when a lap is flagged as
    an interval rep; it maps to the same high-intensity category as
    "hard" for scoring purposes.

Band definitions (from lap_classify.py)
-----------------------------------------
    easy:      power/pace/HR ratio below 0.80
    steady:    ratio at least 0.80 and below 0.90
    tempo:     ratio at least 0.90 and below 1.00
    threshold: ratio at least 1.00 and below 1.06
    hard:      ratio at least 1.06
    interval:  detected by interval_detector (high-intensity rep)

Tempo and threshold laps are excluded from both endurance and speed
scores; they represent mixed-intensity work not cleanly attributed to
either aerobic base or speed development.

Minimum qualifying runs
-----------------------
Both score functions require at least MIN_QUALIFYING_RUNS runs whose
qualifying lap count is positive before returning a numeric score.
Fewer than this threshold returns the building_baseline state.

Worked example
--------------
A run with 3 easy laps, 1 tempo lap, and 2 hard laps:
    Endurance score considers: the 3 easy laps (tempo/hard excluded).
    Speed score considers: the 2 hard laps (easy/tempo excluded).
"""

DEFAULT_ENDURANCE_BANDS = ["easy", "steady"]
DEFAULT_SPEED_BANDS = ["hard", "interval"]

MIN_QUALIFYING_RUNS = 3

DIRECTION_SLOPE_THRESHOLD = 0.005


def make_zone_constants(preferences=None, overrides=None):
    """Build a zone_constants dict from defaults, optionally merged with overrides.

    Parameters
    ----------
    preferences : dict or None
        User preferences dict.  Reserved for future per-user band configuration;
        currently unused — band groupings are not stored in user_preferences.
        Pass the loaded user_preferences row so this function is ready to
        consume user-specific overrides when they are added.
    overrides : dict or None
        Explicit key-by-key overrides applied on top of defaults.
        Recognised keys:
            endurance_bands          list[str] — lap bands to include in endurance score
            speed_bands              list[str] — lap bands to include in speed score
            min_qualifying_runs      int — minimum runs needed before scoring
            direction_slope_threshold float — slope magnitude below which the trend is "flat"

    Returns
    -------
    dict
        Zone constants dict with all required keys populated.

    Worked example
    --------------
    Override min_qualifying_runs to 5 for a more conservative baseline:

        constants = make_zone_constants(overrides={"min_qualifying_runs": 5})
        # constants["min_qualifying_runs"] == 5
        # constants["endurance_bands"] == ["easy", "steady"]  (default)
    """
    constants = {
        "endurance_bands": list(DEFAULT_ENDURANCE_BANDS),
        "speed_bands": list(DEFAULT_SPEED_BANDS),
        "min_qualifying_runs": MIN_QUALIFYING_RUNS,
        "direction_slope_threshold": DIRECTION_SLOPE_THRESHOLD,
    }
    if overrides:
        for key in ("endurance_bands", "speed_bands", "min_qualifying_runs", "direction_slope_threshold"):
            if key in overrides:
                constants[key] = overrides[key]
    return constants
