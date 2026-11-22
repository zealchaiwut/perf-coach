"""Deprecated shim — use ``backend.services.lap_classify`` (single classifier)."""
from backend.services.lap_classify import classify_laps, classify_laps_for_workout

__all__ = ["classify_laps", "classify_laps_for_workout"]