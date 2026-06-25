"""
Pure power-branch running TSS calculation.

This module contains no database access. All inputs are passed by the caller.

Worked example:
    3600 seconds at np equal to ftp_w gives intensity_factor of 1.0, tss of 100,
    method of "power".
"""


def calculate_running_tss_power(
    *,
    duration_seconds,
    np,
    ftp_w,
):
    """Compute running Training Stress Score from power data.

    All inputs are passed directly by the caller; this function never reads from
    or writes to the database.

    Parameters
    ----------
    duration_seconds:
        Total workout duration in seconds. Must be a positive number.
    np:
        Normalized Power in watts. Must be provided and not null.
    ftp_w:
        Functional Threshold Power in watts. Must be a positive number.

    Returns
    -------
    dict with keys:
        tss    -- whole integer or None
        method -- "power" on success, "none" when any required input is invalid
        debug  -- on success: {"intensity_factor": float, "duration_hours": float}
                  on failure: {"reason": str}

    Worked example:
        duration_seconds=3600, np=250, ftp_w=250
        intensity_factor = 250 / 250 = 1.0
        tss = round(3600 * 1.0 * 1.0 / 3600 * 100) = 100
        method = "power"
    """
    if duration_seconds is None or duration_seconds <= 0:
        return {
            "tss": None,
            "method": "none",
            "debug": {"reason": "duration missing or invalid"},
        }

    if np is None:
        return {
            "tss": None,
            "method": "none",
            "debug": {"reason": "normalized_power missing"},
        }

    if ftp_w is None or ftp_w <= 0:
        return {
            "tss": None,
            "method": "none",
            "debug": {"reason": "ftp_w missing or invalid"},
        }

    intensity_factor = np / ftp_w
    duration_hours = duration_seconds / 3600
    tss = round(duration_hours * intensity_factor * intensity_factor * 100)

    return {
        "tss": tss,
        "method": "power",
        "debug": {
            "intensity_factor": float(intensity_factor),
            "duration_hours": float(duration_hours),
        },
    }
