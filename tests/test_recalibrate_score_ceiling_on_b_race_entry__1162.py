"""Tests for issue #1162: Recalibrate score ceiling on B race entry.

Acceptance criteria verified:
- AC1: When a B race result is saved, the score ceiling is updated to match the
       performance expressed by that result.
- AC2: All forward projections generated after the B race use the race date as
       the new baseline anchor point.
- AC3: Projections generated before the B race entry are unaffected (no
       retroactive re-anchoring).
- AC4: If the B race result is deleted or edited, the ceiling and baseline
       revert or update accordingly.
- AC5: py_compile passes with zero errors on all modified files.
- AC6: Unit tests cover the ceiling-anchor logic for a B race result entry.
"""

import py_compile
from datetime import date, timedelta

import pytest

from backend.services.score_ceiling import (
    SCORE_CEILING_MAX,
    ceiling_from_b_race_result,
    projected_ctl_to_score_ceiling,
)
from backend.services.projection import build_plan_projection_payload


# ── Shared test data ───────────────────────────────────────────────────────────

_THRESHOLD_PACE = 300.0  # s/km — 5:00/km threshold pace
_THRESHOLDS = {"threshold_pace_seconds_per_km": _THRESHOLD_PACE}
_TODAY = date(2026, 6, 15)
_B_RACE_DATE = date(2026, 5, 1)          # past B race
_FUTURE_RACE_DATE = date(2026, 8, 1)     # race after the B race
_PRE_B_RACE_DATE = date(2026, 3, 15)     # race before the B race


def _b_race_result(actual_time_seconds=3750, distance_km=10.0):
    """Return a B race result dict matching 75/100 score at the default threshold pace."""
    return {
        "race_date": _B_RACE_DATE,
        "actual_time_seconds": actual_time_seconds,
        "distance_km": distance_km,
    }


# ── AC5: py_compile passes on modified files ──────────────────────────────────

def test_ac5_py_compile_score_ceiling():
    import backend.services.score_ceiling as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


def test_ac5_py_compile_projection():
    import backend.services.projection as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


def test_ac5_py_compile_plan_router():
    import backend.routers.projection as mod
    path = mod.__file__
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


# ── AC1: ceiling_from_b_race_result derives correct ceiling ───────────────────

def test_ac1_function_importable():
    """ceiling_from_b_race_result must be importable from score_ceiling."""
    assert callable(ceiling_from_b_race_result)


def test_ac1_returns_endurance_and_speed_keys():
    """Return value must have endurance_ceiling and speed_ceiling keys."""
    result = ceiling_from_b_race_result(3750, 10.0, _THRESHOLD_PACE)
    assert "endurance_ceiling" in result
    assert "speed_ceiling" in result


def test_ac1_round_trip_score_75():
    """Ceiling derived from the B race result round-trips: score→time→ceiling == score.

    At score=75, threshold_pace=300 s/km, distance=10 km:
        estimated_pace = 300 * (2 - 0.75) = 375 s/km
        actual_time    = 375 * 10 = 3750 s
        derived score  = (2 - 3750/10/300) * 100 = 75.0
    """
    actual_time = 3750  # 75-score equivalent
    result = ceiling_from_b_race_result(actual_time, 10.0, _THRESHOLD_PACE)
    assert result["endurance_ceiling"] == pytest.approx(75.0, abs=0.01)
    assert result["speed_ceiling"] == pytest.approx(75.0, abs=0.01)


def test_ac1_round_trip_score_100():
    """Score 100 round-trip: athlete ran at exactly threshold pace."""
    # At score=100: estimated_pace = 300 * (2 - 1.0) = 300 s/km
    # actual_time = 300 * 10 = 3000 s
    result = ceiling_from_b_race_result(3000, 10.0, _THRESHOLD_PACE)
    assert result["endurance_ceiling"] == pytest.approx(100.0, abs=0.01)


def test_ac1_slow_result_maps_to_low_ceiling():
    """A slow B race result yields a low ceiling score."""
    # Very slow: actual_pace = 2 * threshold_pace → score = 0
    # actual_time = 2 * 300 * 10 = 6000 s → score = (2 - 2.0) * 100 = 0
    result = ceiling_from_b_race_result(6000, 10.0, _THRESHOLD_PACE)
    assert result["endurance_ceiling"] == pytest.approx(0.0, abs=0.01)


def test_ac1_ceiling_clamped_to_zero():
    """Ceiling never goes below 0 even for extremely slow results."""
    result = ceiling_from_b_race_result(99999, 10.0, _THRESHOLD_PACE)
    assert result["endurance_ceiling"] >= 0.0
    assert result["speed_ceiling"] >= 0.0


def test_ac1_ceiling_clamped_to_max():
    """Ceiling never exceeds SCORE_CEILING_MAX even for extremely fast results."""
    result = ceiling_from_b_race_result(100, 10.0, _THRESHOLD_PACE)
    assert result["endurance_ceiling"] <= SCORE_CEILING_MAX
    assert result["speed_ceiling"] <= SCORE_CEILING_MAX


def test_ac1_faster_race_yields_higher_ceiling():
    """A faster B race result produces a higher ceiling than a slower result."""
    fast_result = ceiling_from_b_race_result(3000, 10.0, _THRESHOLD_PACE)  # score=100
    slow_result = ceiling_from_b_race_result(3750, 10.0, _THRESHOLD_PACE)  # score=75
    assert fast_result["endurance_ceiling"] > slow_result["endurance_ceiling"]


def test_ac1_invalid_inputs_return_zero_ceiling():
    """Invalid inputs (non-positive values) return a zero ceiling without raising."""
    for bad_args in [
        (0, 10.0, 300.0),
        (3750, 0.0, 300.0),
        (3750, 10.0, 0.0),
        (-100, 10.0, 300.0),
    ]:
        result = ceiling_from_b_race_result(*bad_args)
        assert isinstance(result, dict), f"Must return dict for args {bad_args}"
        assert result["endurance_ceiling"] == 0.0, f"Expected 0 ceiling for args {bad_args}"
        assert result["speed_ceiling"] == 0.0, f"Expected 0 ceiling for args {bad_args}"


# ── AC2: projections after B race use race-anchored ceiling ───────────────────

def _base_projection_args(races=None):
    """Return a minimal set of valid args for build_plan_projection_payload."""
    if races is None:
        races = []
    return {
        "start_ctl": 40.0,
        "start_atl": 50.0,
        "start_date": _TODAY,
        "planned_load": [50.0] * 60,
        "races": races,
        "thresholds": _THRESHOLDS,
        "body_modifier": 1.0,
    }


def test_ac2_b_race_param_accepted():
    """build_plan_projection_payload accepts b_race_result without raising."""
    payload = build_plan_projection_payload(
        **_base_projection_args(),
        b_race_result=_b_race_result(),
    )
    assert "races" in payload


def test_ac2_post_b_race_uses_anchored_ceiling():
    """Races after the B race date use the B-race-derived ceiling, not CTL-based.

    The B race result at score=75 gives a ceiling of 75. A low CTL (20) would
    give a ceiling of ~13.3 (CTL-based). After the B race, the anchor ceiling
    of 75 is used instead.
    """
    low_ctl_args = dict(
        _base_projection_args(races=[{"date": str(_FUTURE_RACE_DATE), "distance_km": 10.0, "name": "Post-B Race"}]),
        start_ctl=20.0,
        start_atl=25.0,
    )
    # Without B race: CTL=20 → ceiling ≈ 13.3
    payload_no_b = build_plan_projection_payload(**low_ctl_args)
    # With B race result at score=75 → ceiling = 75
    payload_with_b = build_plan_projection_payload(
        **low_ctl_args,
        b_race_result=_b_race_result(actual_time_seconds=3750, distance_km=10.0),
    )

    assert len(payload_no_b["races"]) == 1
    assert len(payload_with_b["races"]) == 1

    ctl_ceiling_score = projected_ctl_to_score_ceiling(20.0)["endurance_ceiling"]
    b_race_ceiling_score = ceiling_from_b_race_result(3750, 10.0, _THRESHOLD_PACE)["endurance_ceiling"]

    # The B-race anchored payload must produce higher estimated scores
    # because b_race_ceiling > ctl_ceiling for low-CTL athletes
    assert b_race_ceiling_score > ctl_ceiling_score, (
        "Test precondition: B-race ceiling must be higher than low-CTL ceiling"
    )

    # The estimated finish time should differ — faster (lower) with the B-race ceiling
    time_no_b = payload_no_b["races"][0]["estimated_finish_seconds"]
    time_with_b = payload_with_b["races"][0]["estimated_finish_seconds"]
    assert time_no_b is not None
    assert time_with_b is not None
    assert time_with_b < time_no_b, (
        f"Post-B-race projection should be faster (lower time): "
        f"with_b={time_with_b}s vs no_b={time_no_b}s"
    )


# ── AC3: pre-B-race projections are unaffected ────────────────────────────────

def test_ac3_pre_b_race_ceiling_unchanged():
    """Races before the B race date use the same CTL-based ceiling as without B race.

    The B race result must NOT retroactively recalibrate races scheduled before it.
    """
    race = {"date": str(_PRE_B_RACE_DATE), "distance_km": 10.0, "name": "Pre-B Race"}
    args = _base_projection_args(races=[race])

    payload_no_b = build_plan_projection_payload(**args)
    payload_with_b = build_plan_projection_payload(**args, b_race_result=_b_race_result())

    time_no_b = payload_no_b["races"][0]["estimated_finish_seconds"]
    time_with_b = payload_with_b["races"][0]["estimated_finish_seconds"]

    assert time_no_b == time_with_b, (
        f"Pre-B-race projections must be identical with and without b_race_result: "
        f"no_b={time_no_b}s, with_b={time_with_b}s"
    )


def test_ac3_only_post_b_race_entries_differ():
    """Mixed race list: pre-B entries unchanged, post-B entries recalibrated."""
    races = [
        {"date": str(_PRE_B_RACE_DATE), "distance_km": 10.0, "name": "Pre-B"},
        {"date": str(_FUTURE_RACE_DATE), "distance_km": 10.0, "name": "Post-B"},
    ]
    low_ctl_args = dict(
        _base_projection_args(races=races),
        start_ctl=20.0,
        start_atl=25.0,
    )

    payload_no_b = build_plan_projection_payload(**low_ctl_args)
    payload_with_b = build_plan_projection_payload(
        **low_ctl_args,
        b_race_result=_b_race_result(),
    )

    # Map by name for easy access
    no_b_by_name = {r["name"]: r for r in payload_no_b["races"]}
    with_b_by_name = {r["name"]: r for r in payload_with_b["races"]}

    # Pre-B race: identical
    assert no_b_by_name["Pre-B"]["estimated_finish_seconds"] == with_b_by_name["Pre-B"]["estimated_finish_seconds"], (
        "Pre-B race finish time must be unchanged"
    )

    # Post-B race: recalibrated (faster with high B-race ceiling vs low CTL ceiling)
    assert no_b_by_name["Post-B"]["estimated_finish_seconds"] != with_b_by_name["Post-B"]["estimated_finish_seconds"], (
        "Post-B race finish time must change when B-race result is present"
    )


# ── AC4: deleting or editing B race result reverts or updates ceiling ─────────

def test_ac4_no_b_race_result_reverts_to_ctl_ceiling():
    """When b_race_result is None (deleted), projection reverts to CTL-based ceiling."""
    race = {"date": str(_FUTURE_RACE_DATE), "distance_km": 10.0, "name": "Future Race"}
    low_ctl_args = dict(
        _base_projection_args(races=[race]),
        start_ctl=20.0,
        start_atl=25.0,
    )

    payload_deleted = build_plan_projection_payload(**low_ctl_args, b_race_result=None)
    payload_no_b_arg = build_plan_projection_payload(**low_ctl_args)

    assert (
        payload_deleted["races"][0]["estimated_finish_seconds"]
        == payload_no_b_arg["races"][0]["estimated_finish_seconds"]
    ), "Deleted B race result (None) must produce same result as no b_race_result arg"


def test_ac4_editing_b_race_updates_ceiling():
    """Editing the B race result (new actual_time_seconds) updates the ceiling."""
    race = {"date": str(_FUTURE_RACE_DATE), "distance_km": 10.0, "name": "Future Race"}
    low_ctl_args = dict(
        _base_projection_args(races=[race]),
        start_ctl=20.0,
        start_atl=25.0,
    )

    # Original B race: score=75, time=3750s
    payload_orig = build_plan_projection_payload(
        **low_ctl_args,
        b_race_result=_b_race_result(actual_time_seconds=3750),
    )
    # Edited B race: score=100, time=3000s (faster)
    payload_edited = build_plan_projection_payload(
        **low_ctl_args,
        b_race_result=_b_race_result(actual_time_seconds=3000),
    )

    orig_time = payload_orig["races"][0]["estimated_finish_seconds"]
    edited_time = payload_edited["races"][0]["estimated_finish_seconds"]

    assert edited_time is not None and orig_time is not None
    assert edited_time < orig_time, (
        f"Faster B race result should produce faster future projection: "
        f"edited={edited_time}s < orig={orig_time}s"
    )


def test_ac4_b_race_on_same_date_does_not_recalibrate():
    """A race ON the B race date is not recalibrated — only STRICTLY after."""
    race = {"date": str(_B_RACE_DATE), "distance_km": 10.0, "name": "Same Day Race"}
    low_ctl_args = dict(
        _base_projection_args(races=[race]),
        start_ctl=20.0,
        start_atl=25.0,
    )

    payload_no_b = build_plan_projection_payload(**low_ctl_args)
    payload_with_b = build_plan_projection_payload(
        **low_ctl_args,
        b_race_result=_b_race_result(),
    )

    # A race on the exact B race date should be unaffected (not after)
    time_no_b = payload_no_b["races"][0]["estimated_finish_seconds"]
    time_with_b = payload_with_b["races"][0]["estimated_finish_seconds"]
    assert time_no_b == time_with_b, (
        "A race on the same date as the B race must not be recalibrated"
    )


# ── AC6: coverage — canonical ceiling-anchor unit test ────────────────────────

def test_ac6_ceiling_anchor_logic_covered():
    """Explicit anchor test: B-race ceiling replaces CTL ceiling for post-B races.

    This test precisely verifies the ceiling-switching logic using known values.
    score=75 → ceiling=75.  CTL=20 → CTL ceiling≈13.3.  Post-B race should use 75.
    """
    b_result = _b_race_result(actual_time_seconds=3750, distance_km=10.0)
    b_ceiling = ceiling_from_b_race_result(
        b_result["actual_time_seconds"],
        b_result["distance_km"],
        _THRESHOLD_PACE,
    )
    ctl_ceiling = projected_ctl_to_score_ceiling(ctl=20.0)

    assert b_ceiling["endurance_ceiling"] == pytest.approx(75.0, abs=0.01)
    assert ctl_ceiling["endurance_ceiling"] < 20.0, "Sanity: CTL=20 gives low ceiling"
    assert b_ceiling["endurance_ceiling"] > ctl_ceiling["endurance_ceiling"], (
        "B-race ceiling must exceed low-CTL ceiling for this test to be meaningful"
    )

    # Projection with B-race anchor should use b_ceiling for post-B dates
    race = {"date": str(_FUTURE_RACE_DATE), "distance_km": 10.0, "name": "Target"}
    payload = build_plan_projection_payload(
        start_ctl=20.0,
        start_atl=25.0,
        start_date=_TODAY,
        planned_load=[50.0] * 60,
        races=[race],
        thresholds=_THRESHOLDS,
        b_race_result=b_result,
    )

    # With threshold_pace=300, score=75, distance=10 km:
    # estimated_pace = 300 * (2 - 0.75) = 375 s/km
    # finish_time    = 375 * 10 = 3750 s
    expected_seconds = 3750
    actual_seconds = payload["races"][0]["estimated_finish_seconds"]
    assert actual_seconds == pytest.approx(expected_seconds, abs=5), (
        f"Expected ~{expected_seconds}s for score=75 at 10 km, got {actual_seconds}s"
    )


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_no_races_b_race_result_ignored():
    """With no target races, b_race_result is accepted without error."""
    payload = build_plan_projection_payload(
        **_base_projection_args(races=[]),
        b_race_result=_b_race_result(),
    )
    assert payload["races"] == []


def test_no_thresholds_b_race_not_applied():
    """Without thresholds, ceiling derivation from B race is skipped gracefully."""
    race = {"date": str(_FUTURE_RACE_DATE), "distance_km": 10.0, "name": "Future Race"}
    args = dict(_base_projection_args(races=[race]), thresholds=None)
    payload = build_plan_projection_payload(**args, b_race_result=_b_race_result())
    # Should not raise; estimated_finish_seconds will be None (no threshold pace)
    assert payload["races"][0]["estimated_finish_seconds"] is None


def test_b_race_result_no_threshold_pace():
    """threshold_pace_seconds_per_km missing from thresholds skips B-race anchor."""
    race = {"date": str(_FUTURE_RACE_DATE), "distance_km": 10.0, "name": "Future Race"}
    no_tp_thresholds = {"some_other_key": 300}
    args = dict(_base_projection_args(races=[race]), thresholds=no_tp_thresholds)
    payload = build_plan_projection_payload(**args, b_race_result=_b_race_result())
    # Should not raise; falls back to CTL-based ceiling with null finish time
    assert "races" in payload
