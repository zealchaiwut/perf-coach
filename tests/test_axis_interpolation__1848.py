"""P4-1 marathon profile interpolation."""

from backend.services.axis_spec import (
    MARATHON_PROFILE_MAX_SECONDS,
    MARATHON_PROFILE_MIN_SECONDS,
    goal_time_to_marathon_seconds,
    interpolate_marathon_profile,
    profile_for_race_goal,
    profile_label_marathon_time,
)


def test_profile_rows_at_boundaries():
    fast = interpolate_marathon_profile(MARATHON_PROFILE_MIN_SECONDS)
    slow = interpolate_marathon_profile(MARATHON_PROFILE_MAX_SECONDS)
    assert fast["power_to_weight_w_per_kg"] == 3.2
    assert slow["power_to_weight_w_per_kg"] == 2.3


def test_profile_interpolation_midpoint_337():
    # Halfway between 3:30 and 3:45 → 3:37:30 = 13050 s
    mid = interpolate_marathon_profile(13050)
    assert mid["power_to_weight_w_per_kg"] == 3.125
    assert mid["leg_spring_stiffness_kn_m"] == 10.0


def test_profile_clamps_below_table():
    low = interpolate_marathon_profile(10_000)
    at_min = interpolate_marathon_profile(MARATHON_PROFILE_MIN_SECONDS)
    assert low == at_min


def test_profile_clamps_above_table():
    high = interpolate_marathon_profile(99_999)
    at_max = interpolate_marathon_profile(MARATHON_PROFILE_MAX_SECONDS)
    assert high == at_max


def test_half_marathon_goal_maps_via_riegel():
    # 1:45:00 half → marathon equivalent, then profile
    profile = profile_for_race_goal(6300, 21.0975)
    assert profile is not None
    marathon_sec = goal_time_to_marathon_seconds(6300, 21.0975)
    assert marathon_sec is not None
    assert profile == interpolate_marathon_profile(marathon_sec)


def test_marathon_goal_direct():
    profile = profile_for_race_goal(16200, 42.195)
    assert profile is not None
    assert profile["endurance_target_score"] == 58.0


def test_profile_label():
    assert profile_label_marathon_time(12600) == "3:30"