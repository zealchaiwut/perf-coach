"""Energy availability (EA) proxy computation (issue #1157).

Computes a relative energy-availability proxy from intake and training-load
data, then raises a low-EA flag when the proxy falls below the defined
threshold.  Output is a sufficiency signal only — no calorie prescriptions or
absolute daily targets are produced.

Formula
-------
    ea_proxy = intake / training_load   (when training_load > 0)

When training_load is zero, the proxy is undefined (no load demand), so
``ea_proxy`` is returned as ``None`` and ``low_ea`` is ``False``
(absence of training load is not an insufficiency event).
"""
from __future__ import annotations

# Intake-to-load ratio below this value triggers the low-EA flag.
# A ratio of 1.0 means intake equals load; below 1.0 indicates the athlete
# is taking in less energy than the training load demands.
LOW_EA_THRESHOLD: float = 1.0


def compute_ea_proxy(
    *,
    intake: float,
    training_load: float,
) -> dict:
    """Compute the energy availability proxy and low-EA flag.

    Parameters
    ----------
    intake:
        Energy intake proxy (e.g. normalised kcal or any consistent intake
        signal).  Must be >= 0.
    training_load:
        Training load for the same period (e.g. TSS or equivalent signal).
        Must be >= 0.

    Returns
    -------
    dict with exactly two keys:

    ``ea_proxy``
        The intake-to-load ratio (float) when ``training_load > 0``, or
        ``None`` when ``training_load`` is zero (ratio is undefined; the
        absence of load is not flagged as insufficient).

    ``low_ea``
        ``True`` when ``ea_proxy`` is strictly below ``LOW_EA_THRESHOLD``;
        ``False`` otherwise, including when ``ea_proxy`` is ``None``.
    """
    if training_load == 0.0:
        return {"ea_proxy": None, "low_ea": False}

    ea_proxy: float = float(intake) / float(training_load)
    low_ea: bool = ea_proxy < LOW_EA_THRESHOLD

    return {"ea_proxy": ea_proxy, "low_ea": low_ea}
