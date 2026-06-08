"""Unit tests for compute_status_label (issue #338)."""
import datetime
from types import SimpleNamespace

import pytest

from backend.services.weight_status import compute_status_label


def _target(start_w, target_w, days_total=100):
    today = datetime.date.today()
    return SimpleNamespace(
        start_weight_kg=start_w,
        target_weight_kg=target_w,
        start_date=today - datetime.timedelta(days=50),
        target_date=today + datetime.timedelta(days=days_total - 50),
    )


def _as_of(target):
    return datetime.date.today()


# (a) on-track when actual matches expected exactly
def test_on_track_exact_match():
    t = _target(85.0, 75.0)
    # 50 days elapsed of 100 total → expected = 85 - 5 = 80
    result = compute_status_label(t, 80.0, _as_of(t))
    assert result == "on_track"


# (b) on-track within tolerance band (small over/under)
def test_on_track_within_tolerance():
    t = _target(85.0, 75.0)
    # tolerance = max(0.5, 0.05 * 10) = 0.5; gap of 0.3 is within
    result = compute_status_label(t, 80.3, _as_of(t))
    assert result == "on_track"


# (c) behind when over expected on a loss target
def test_behind_over_expected_loss_target():
    t = _target(85.0, 75.0)
    # current 82 > expected 80 → gap +2 > tolerance 0.5 → behind (loss)
    result = compute_status_label(t, 82.0, _as_of(t))
    assert result == "behind"


# (d) ahead when under expected on a loss target
def test_ahead_under_expected_loss_target():
    t = _target(85.0, 75.0)
    # current 78 < expected 80 → gap -2 → ahead (loss)
    result = compute_status_label(t, 78.0, _as_of(t))
    assert result == "ahead"


# (e) reversed direction logic for gain targets
def test_reversed_direction_gain_target():
    t = _target(70.0, 80.0)
    # 50 days of 100 → expected = 70 + 5 = 75; current 77 → gap +2 → ahead (gain)
    result = compute_status_label(t, 77.0, _as_of(t))
    assert result == "ahead"


# (f) no_data when current_avg_kg is None
def test_no_data_when_current_is_none():
    t = _target(85.0, 75.0)
    result = compute_status_label(t, None, _as_of(t))
    assert result == "no_data"


# (g) tolerance scales: 5% of 30 kg = 1.5 kg; gap 1.2 kg → on_track
def test_tolerance_scales_with_total_change():
    # 30 kg total change: tol = max(0.5, 0.05*30) = 1.5
    # 5% of 10 kg = 0.5 → floor check
    today = datetime.date.today()
    t_small = SimpleNamespace(
        start_weight_kg=85.0,
        target_weight_kg=75.0,  # 10 kg change
        start_date=today - datetime.timedelta(days=50),
        target_date=today + datetime.timedelta(days=50),
    )
    assert compute_status_label(t_small, 80.5, today) == "on_track"  # 0.5 = tol, edge

    t_large = SimpleNamespace(
        start_weight_kg=100.0,
        target_weight_kg=70.0,  # 30 kg change
        start_date=today - datetime.timedelta(days=50),
        target_date=today + datetime.timedelta(days=50),
    )
    # expected = 100 - 15 = 85; gap = 86.2 - 85 = +1.2; tol = 1.5 → on_track
    assert compute_status_label(t_large, 86.2, today) == "on_track"
