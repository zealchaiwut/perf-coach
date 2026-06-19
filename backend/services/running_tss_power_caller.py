"""Thin caller for the pure running-power TSS function.

This module is the ONLY place in the running_tss_power family that accesses
the database.  All math is delegated to the pure
``calculate_running_tss_power`` function in ``running_tss_power.py``.
"""

from backend.models import UserPreferences
from backend.services.running_tss_power import calculate_running_tss_power


def calculate_running_tss_power_for_user(session, user_id, normalized_power_w, duration_seconds):
    """Read ftp_w from user_preferences, then compute power TSS.

    Parameters
    ----------
    session:
        SQLAlchemy session.
    user_id:
        ID of the user whose ftp_w preference should be read.
    normalized_power_w:
        Normalized Power in watts.
    duration_seconds:
        Total workout duration in seconds.

    Returns
    -------
    dict — same shape as calculate_running_tss_power:
        tss (int or None), method ("power" or "none"), debug (dict).
    """
    prefs = (
        session.query(UserPreferences)
        .filter(UserPreferences.user_id == user_id)
        .first()
    )
    ftp_w = prefs.ftp_w if prefs is not None else None

    return calculate_running_tss_power(
        ftp_w=ftp_w,
        np=normalized_power_w,
        duration_seconds=duration_seconds,
    )
