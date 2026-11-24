"""Sprint 149 #1953 — lap_classifier shim is gone; tests use lap_classify."""
from pathlib import Path

from backend.services.lap_classify import classify_laps, classify_laps_for_workout


def test_lap_classifier_file_is_gone():
    assert not Path("backend/services/lap_classifier.py").exists()
    assert callable(classify_laps) and callable(classify_laps_for_workout)
