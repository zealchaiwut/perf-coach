"""Polarized-training verdict computation for intensity distribution endpoints.

compute_polarized_check is a pure function: no database calls, no side effects.
It accepts low/moderate/high percentage values (0–100) and returns one of four
enum strings indicating how well the distribution matches the polarized-training
model (≥75% low, ≤15% moderate, remainder high).

Verdict enum:
    "pass"              low ≥ 75% AND moderate ≤ 15%
    "borderline"        low ≥ 60% AND moderate ≤ 25% (but not pass)
    "fail"              data present but does not meet pass or borderline thresholds
    "insufficient_data" any of low/moderate/high is None (no classified laps)
"""

_PASS_LOW_MIN = 75.0
_PASS_MOD_MAX = 15.0
_BORDERLINE_LOW_MIN = 60.0
_BORDERLINE_MOD_MAX = 25.0


def compute_polarized_check(low_pct, moderate_pct, high_pct):
    """Return a polarized-training verdict string for the given intensity percentages.

    Args:
        low_pct:      float or None — percentage of session time in low intensity
        moderate_pct: float or None — percentage of session time in moderate intensity
        high_pct:     float or None — percentage of session time in high intensity

    Returns:
        "pass"              when low_pct >= 75 and moderate_pct <= 15
        "borderline"        when low_pct >= 60 and moderate_pct <= 25 (but not pass)
        "fail"              when data is present but thresholds are not met
        "insufficient_data" when any input value is None
    """
    if low_pct is None or moderate_pct is None or high_pct is None:
        return "insufficient_data"
    if low_pct >= _PASS_LOW_MIN and moderate_pct <= _PASS_MOD_MAX:
        return "pass"
    if low_pct >= _BORDERLINE_LOW_MIN and moderate_pct <= _BORDERLINE_MOD_MAX:
        return "borderline"
    return "fail"
