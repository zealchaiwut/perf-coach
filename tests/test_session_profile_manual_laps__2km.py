"""Interval detection prefers Stryd manual laps over 1 km splits when reps are ~2 km."""

from types import SimpleNamespace

from backend.services.session_profile_caller import (
    _prefer_manual_laps_for_detection,
)


def test_prefers_manual_when_fewer_laps_than_splits_and_rep_distance_2km():
    manual = [
        {"distance_km": 2.0, "duration_seconds": 720},
        {"distance_km": 0.4, "duration_seconds": 180},
    ] * 5
    splits = [SimpleNamespace(distance_km=1.0) for _ in range(18)]
    assert _prefer_manual_laps_for_detection(manual, splits) is True


def test_keeps_splits_when_manual_laps_are_only_km_sized():
    manual = [{"distance_km": 1.0, "duration_seconds": 400} for _ in range(8)]
    splits = [SimpleNamespace(distance_km=1.0) for _ in range(10)]
    assert _prefer_manual_laps_for_detection(manual, splits) is False
