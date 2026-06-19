"""Regression tests for Strava HR sanitization in the workout merge.

Strava can report sentinel/garbage average_heartrate (-1, 0, single digits).
Writing those to workouts violates ck_workouts_avg_hr_range (HR NULL or 20..250)
and crashes reconcile, rolling back the whole sync (so the Strava link and
activity_streams never persist — the graph disappears). The merge must nullify
out-of-range HR and let a valid source (Stryd) win instead.
"""
from types import SimpleNamespace

import pytest

from backend.services.workout_merge import clean_hr, compute_best_values


@pytest.mark.parametrize(
    "value,expected",
    [
        (-1, None),     # Strava no-data sentinel
        (0, None),
        (17, None),     # below physiological floor
        (300, None),    # above ceiling
        (None, None),
        ("not-a-number", None),
        (20, 20),       # inclusive lower bound
        (250, 250),     # inclusive upper bound
        (122, 122),
        ("130.7", 131), # coerced + rounded
    ],
)
def test_clean_hr(value, expected):
    assert clean_hr(value) == expected


def _proxy(strava_hr, stryd_hr):
    return SimpleNamespace(
        manual_overrides=None,
        strava_activity=SimpleNamespace(
            avg_hr=strava_hr, distance_km=14.2, duration_seconds=5729,
            avg_power_w=None, name="Run",
        ),
        stryd_activity=SimpleNamespace(
            avg_hr=stryd_hr, distance_km=None, duration_seconds=None,
            avg_power_w=236, tss=80,
        ),
        avg_hr=None, distance_km=None, duration_seconds=None, tss=None, name=None,
    )


def test_bogus_strava_hr_yields_to_valid_stryd_hr():
    # Strava is picked before Stryd, but -1 must be skipped so Stryd's real HR wins.
    assert compute_best_values(_proxy(-1, 122))["best_avg_hr"] == 122


def test_all_bogus_hr_resolves_to_none_no_crash():
    assert compute_best_values(_proxy(-1, 0))["best_avg_hr"] is None


def test_valid_strava_hr_wins_by_precedence():
    assert compute_best_values(_proxy(140, 122))["best_avg_hr"] == 140
