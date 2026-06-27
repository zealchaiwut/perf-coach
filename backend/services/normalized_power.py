"""
Normalized Power computation utility.

Normalized Power (NP) is a power-based training metric that weights
high-intensity efforts more heavily than a simple average, providing
a better estimate of the physiological cost of a variable-intensity
power output.
"""


def compute_normalized_power(power_samples, sample_interval_seconds, window_duration_seconds=30):
    """Compute Normalized Power from an ordered sequence of power readings.

    Normalized Power accounts for the non-linear physiological cost of
    high-power efforts. A workout with power fluctuating between 100 watts and
    400 watts produces greater physiological stress than a steady 250-watt
    output, even though both share the same arithmetic mean. The fourth-power
    weighting step captures this asymmetry.

    Parameters
    ----------
    power_samples:
        An ordered list of numeric power readings, each expressed in watts.
        Each element represents the average power recorded during one
        sample_interval_seconds period. Must contain at least enough readings
        to fill one rolling window. Passing None or an empty list
        returns None with a reason string.
    sample_interval_seconds:
        A positive number describing the elapsed time, in seconds, between
        consecutive samples. The rolling-window size in samples is derived from
        this value: window_size = round(window_duration_seconds / sample_interval_seconds).
    window_duration_seconds:
        Duration of the rolling average window in seconds. Defaults to 30,
        the standard Normalized Power window. The sample count for the window
        is derived from this value and sample_interval_seconds.

    Returns
    -------
    A two-element tuple (result, info).

    On success:
        result — An integer number of watts (rounded), never a float.
        info   — A dict with three diagnostic keys:
                   "rolling_window_count": the number of rolling windows
                       that were computed (a positive integer).
                   "mean_of_fourth_powers": the arithmetic mean of each
                       rolling-average value raised to the fourth power
                       (a positive float).
                   "final_value": the Normalized Power before rounding,
                       equal to the fourth root of mean_of_fourth_powers
                       (a positive float).

    On failure (absent or insufficient input):
        result — None.
        info   — A dict with one key:
                   "reason": a human-readable string explaining why the
                       result could not be computed.

    Worked example
    --------------
    A cyclist holds a perfectly steady 250 watts for 120 seconds, sampled
    once per second (sample_interval_seconds = 1).

    Window size in samples = round(30 divided by 1) = 30 samples.

    Each of the 91 rolling window averages equals 250 watts.
    250 raised to the fourth power = 3,906,250,000.
    The arithmetic mean of all 91 fourth-power values = 3,906,250,000.
    The fourth root of 3,906,250,000 = 250.

    Return value:
        (250, {
            "rolling_window_count": 91,
            "mean_of_fourth_powers": 3906250000.0,
            "final_value": 250.0,
        })

    Algorithm
    ---------
    Step 1 — Derive the window size in number of samples:
        window_size = round(window_duration_seconds divided by sample_interval_seconds)

    Step 2 — Compute a rolling average over that window.
        Starting at index window_size minus 1 and ending at the last sample
        index, average the window_size samples ending at each position
        (inclusive of the current sample).

    Step 3 — Raise each rolling average to the fourth power.

    Step 4 — Compute the arithmetic mean of those fourth-power values.

    Step 5 — Take the fourth root of that mean.

    Step 6 — Round to the nearest integer and return.
    """
    if not power_samples:
        reason = (
            "power samples were not provided"
            if power_samples is None
            else "no power data was supplied"
        )
        return None, {"reason": reason}

    window_size = max(1, round(window_duration_seconds / sample_interval_seconds))

    if len(power_samples) < window_size:
        return None, {
            "reason": (
                f"the data duration ({len(power_samples) * sample_interval_seconds:.1f} s) "
                f"is shorter than one rolling window ({window_duration_seconds} s)"
            )
        }

    rolling_averages = [
        sum(power_samples[i - window_size + 1 : i + 1]) / window_size
        for i in range(window_size - 1, len(power_samples))
    ]

    mean_of_fourth_powers = sum(avg ** 4 for avg in rolling_averages) / len(rolling_averages)
    final_value = mean_of_fourth_powers ** 0.25

    return round(final_value), {
        "rolling_window_count": len(rolling_averages),
        "mean_of_fourth_powers": mean_of_fourth_powers,
        "final_value": final_value,
    }
