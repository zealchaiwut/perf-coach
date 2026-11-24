"""P4-1 per-axis staleness rules."""

from datetime import date, timedelta

from backend.services.axis_spec import (
    anchor_effort_is_stale,
    axis_focus_ranking_eligible,
    axis_radar_eligible,
    is_never_measured,
    staleness_durability,
    staleness_economy,
    staleness_mobility,
    staleness_power_to_weight,
    staleness_strength,
)
from backend.services.vdot import GRACE_WEEKS


def test_anchor_staleness_matches_grace_weeks():
    as_of = date(2026, 6, 1)
    fresh = as_of - timedelta(days=int(GRACE_WEEKS * 7))
    stale_day = as_of - timedelta(days=int(GRACE_WEEKS * 7) + 1)
    assert anchor_effort_is_stale(fresh, as_of) is False
    assert anchor_effort_is_stale(stale_day, as_of) is True
    assert anchor_effort_is_stale(None, as_of) is True


def test_durability_staleness():
    assert staleness_durability(0) is True
    assert staleness_durability(1) is True
    assert staleness_durability(2) is False


def test_economy_staleness():
    assert staleness_economy(4) is True
    assert staleness_economy(5) is False


def test_power_to_weight_staleness():
    assert staleness_power_to_weight(None) is True
    assert staleness_power_to_weight(14) is False
    assert staleness_power_to_weight(15) is True


def test_strength_staleness():
    assert staleness_strength(False) is True
    assert staleness_strength(True) is False


def test_mobility_staleness():
    assert staleness_mobility(None) is True
    assert staleness_mobility(45) is False
    assert staleness_mobility(46) is True


def test_never_measured_vs_stale_radar_and_focus():
    assert is_never_measured(None) is True
    assert axis_radar_eligible(score=None, stale=False) is False
    assert axis_radar_eligible(score=44, stale=True) is True
    assert axis_focus_ranking_eligible(score=44, stale=True) is False
    assert axis_focus_ranking_eligible(score=44, stale=False) is True