"""Issue #1836 — race-day TSS estimates."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.services.race_day_tss import (
    compute_race_day_tss,
    intensity_factor_for_distance,
)


def test_marathon_4_10_estimates_about_290():
    race = SimpleNamespace(
        distance_km=42.2,
        goal_time_seconds=4 * 3600 + 10 * 60,
        status="planned",
        user_id=None,
        tss_if_override=None,
    )
    session = MagicMock()
    out = compute_race_day_tss(session, race)
    assert out["tss"] is not None
    assert 285 <= out["tss"] <= 295
    assert out["if"] == 0.84


def test_if_override_wins():
    assert intensity_factor_for_distance(42.2, 0.77) == 0.77
    assert abs(intensity_factor_for_distance(15.0) - 0.895) < 0.02


def test_rollup_skips_finish_estimate_when_duration_unknown():
    from unittest.mock import patch

    race = SimpleNamespace(
        distance_km=42.2,
        goal_time_seconds=None,
        actual_time_seconds=None,
        status="planned",
        user_id=None,
        tss_if_override=None,
    )
    session = MagicMock()
    with patch("backend.services.race_day_tss.estimate_race_finish") as est:
        out = compute_race_day_tss(session, race, allow_finish_estimate=False)
    est.assert_not_called()
    assert out["tss"] is None
    assert out["reason"] == "duration unknown"