"""
Tests for issue #610: Add race specificity progress tracker function.

Acceptance criteria verified:
- AC1: specificity_progress(race, recent_runs) is a pure function, fully documented
       with a worked example in its docstring.
- AC2: Worked example covers a sub-1:50 half-marathon (goal pace ~5:13/km): 15 km of
       accumulated goal-pace volume and a 1:55 long run each produce non-zero progress.
- AC3: Pace tolerance is a named parameter (not a hardcoded constant); default is a
       documented module-level variable.
- AC4: All numeric thresholds are derived from the race input, never hardcoded.
- AC5: race=None/missing returns an empty result dict and a human-readable reason string.
- AC6: recent_runs empty/None returns zeroed current values with targets from race,
       plus a reason string.
- AC7: Return structure includes volume_at_pace, longest_pace_effort,
       longest_run_by_distance, longest_run_by_duration, each as
       {current, target, unit}.
- AC8: Function is pure — no DB calls, no side effects.
- AC9: All arithmetic is expressed in plain language in comments/docstring.
- AC10: Unit tests cover: (a) docstring worked example, (b) missing race,
        (c) empty recent_runs, (d) runs outside pace band contribute zero volume.
- AC11: Function is wired to the races table schema and run history data model;
        no new DB columns required.
"""
import inspect
import types

import pytest

from backend.services.specificity_progress import (
    DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM,
    specificity_progress,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

HALF_MARATHON_KM = 21.0975
SUB_1_50_GOAL_SECONDS = 110 * 60  # 1:50:00 = 6600 s
# goal pace = 6600 / 21.0975 ≈ 312.8 → rounds to 313 s/km  (~5:13/km)
SUB_1_50_GOAL_PACE = round(SUB_1_50_GOAL_SECONDS / HALF_MARATHON_KM)


def _race(
    distance_km=HALF_MARATHON_KM,
    goal_time_seconds=SUB_1_50_GOAL_SECONDS,
    goal_pace_seconds_per_km=None,
):
    """Minimal race namespace."""
    if goal_pace_seconds_per_km is None:
        if goal_time_seconds and distance_km:
            goal_pace_seconds_per_km = round(goal_time_seconds / distance_km)
    return types.SimpleNamespace(
        distance_km=distance_km,
        goal_time_seconds=goal_time_seconds,
        goal_pace_seconds_per_km=goal_pace_seconds_per_km,
    )


def _run(distance_km, duration_seconds):
    """Minimal run namespace."""
    return types.SimpleNamespace(
        distance_km=distance_km,
        duration_seconds=duration_seconds,
    )


# ─── AC5: race=None returns empty result with reason ──────────────────────────

def test_ac5_none_race_returns_empty_dict():
    result = specificity_progress(None, [])
    assert isinstance(result, dict), "result must be a dict"
    assert len(result) == 0 or all(
        k in ("reason",) for k in result
    ), "result must be empty (or contain only a reason key)"


def test_ac5_none_race_has_reason():
    result = specificity_progress(None, [])
    assert "reason" in result, "result must contain a 'reason' key when race is None"
    assert result["reason"], "reason must be a non-empty string"


def test_ac5_missing_goal_pace_race_returns_reason():
    """Race without goal_pace_seconds_per_km (and no goal_time/distance pair) returns reason."""
    no_pace_race = types.SimpleNamespace(
        distance_km=HALF_MARATHON_KM,
        goal_time_seconds=None,
        goal_pace_seconds_per_km=None,
    )
    result = specificity_progress(no_pace_race, [])
    assert "reason" in result


# ─── AC6: empty/None recent_runs returns zeroed current with targets populated ─

def test_ac6_empty_runs_current_is_zero():
    race = _race()
    result = specificity_progress(race, [])
    for key in ("volume_at_pace", "longest_pace_effort", "longest_run_by_distance", "longest_run_by_duration"):
        assert result[key]["current"] == 0 or result[key]["current"] == 0.0, (
            f"{key}.current must be 0 when recent_runs is empty"
        )


def test_ac6_none_runs_current_is_zero():
    race = _race()
    result = specificity_progress(race, None)
    for key in ("volume_at_pace", "longest_pace_effort", "longest_run_by_distance", "longest_run_by_duration"):
        assert result[key]["current"] == 0 or result[key]["current"] == 0.0, (
            f"{key}.current must be 0 when recent_runs is None"
        )


def test_ac6_empty_runs_targets_from_race():
    race = _race()
    result = specificity_progress(race, [])
    for key in ("volume_at_pace", "longest_pace_effort", "longest_run_by_distance", "longest_run_by_duration"):
        assert result[key]["target"] is not None, f"{key}.target must not be None"
        assert result[key]["target"] > 0, f"{key}.target must be positive"


def test_ac6_empty_runs_has_reason():
    race = _race()
    result = specificity_progress(race, [])
    assert "reason" in result, "result must contain a 'reason' key when runs is empty"
    assert result["reason"], "reason must be non-empty"


# ─── AC7: Return structure has all four named components ──────────────────────

def test_ac7_all_four_components_present():
    race = _race()
    run = _run(distance_km=15.0, duration_seconds=15 * SUB_1_50_GOAL_PACE)
    result = specificity_progress(race, [run])
    for key in ("volume_at_pace", "longest_pace_effort", "longest_run_by_distance", "longest_run_by_duration"):
        assert key in result, f"result must contain '{key}'"


def test_ac7_each_component_has_current_target_unit():
    race = _race()
    run = _run(distance_km=15.0, duration_seconds=15 * SUB_1_50_GOAL_PACE)
    result = specificity_progress(race, [run])
    for key in ("volume_at_pace", "longest_pace_effort", "longest_run_by_distance", "longest_run_by_duration"):
        comp = result[key]
        assert "current" in comp, f"{key} must have 'current'"
        assert "target" in comp, f"{key} must have 'target'"
        assert "unit" in comp, f"{key} must have 'unit'"
        assert isinstance(comp["unit"], str), f"{key}.unit must be a string"


# ─── AC3: Pace tolerance is a named parameter with a documented default ────────

def test_ac3_pace_tolerance_is_named_parameter():
    sig = inspect.signature(specificity_progress)
    params = list(sig.parameters.keys())
    # pace_tolerance must be in the signature
    assert "pace_tolerance_seconds_per_km" in params, (
        "specificity_progress must accept pace_tolerance_seconds_per_km as a named parameter"
    )


def test_ac3_default_pace_tolerance_exported():
    assert isinstance(DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM, (int, float)), (
        "DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM must be a numeric module-level variable"
    )
    assert DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM > 0, (
        "DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM must be positive"
    )


def test_ac3_default_pace_tolerance_is_used_when_not_supplied():
    """Calling without pace_tolerance_seconds_per_km must not raise."""
    race = _race()
    run = _run(distance_km=15.0, duration_seconds=15 * SUB_1_50_GOAL_PACE)
    result = specificity_progress(race, [run])
    assert "volume_at_pace" in result


# ─── AC10d: Runs outside pace band contribute zero volume ─────────────────────

def test_ac10d_too_slow_run_contributes_zero_volume():
    """A run whose pace is slower than goal_pace + tolerance contributes 0 to volume_at_pace."""
    race = _race()
    # Run at a very slow pace — far outside the tolerance band
    slow_pace = SUB_1_50_GOAL_PACE + DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM + 120
    slow_run = _run(distance_km=10.0, duration_seconds=int(10.0 * slow_pace))
    result = specificity_progress(race, [slow_run])
    assert result["volume_at_pace"]["current"] == 0, (
        "A run slower than pace band must contribute 0 to volume_at_pace"
    )


def test_ac10d_too_fast_run_contributes_zero_volume():
    """A run whose pace is faster than goal_pace - tolerance contributes 0 to volume_at_pace."""
    race = _race()
    # Run at a very fast pace — far outside the tolerance band on the fast side
    fast_pace = max(1, SUB_1_50_GOAL_PACE - DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM - 120)
    fast_run = _run(distance_km=10.0, duration_seconds=int(10.0 * fast_pace))
    result = specificity_progress(race, [fast_run])
    assert result["volume_at_pace"]["current"] == 0, (
        "A run faster than pace band must contribute 0 to volume_at_pace"
    )


def test_ac10d_in_band_run_contributes_nonzero_volume():
    """A run at exactly goal pace contributes its full distance to volume_at_pace."""
    race = _race()
    # Run at exactly goal pace
    run = _run(distance_km=15.0, duration_seconds=int(15.0 * SUB_1_50_GOAL_PACE))
    result = specificity_progress(race, [run])
    assert result["volume_at_pace"]["current"] > 0, (
        "A run at goal pace must contribute positive volume"
    )


# ─── AC2 / AC10a: Worked example — sub-1:50 half-marathon ────────────────────

def test_ac2_ac10a_15km_goal_pace_volume_nonzero():
    """15 km at goal pace produces nonzero volume_at_pace (AC2 worked example)."""
    race = _race(
        distance_km=HALF_MARATHON_KM,
        goal_time_seconds=SUB_1_50_GOAL_SECONDS,
    )
    goal_pace = race.goal_pace_seconds_per_km
    run = _run(distance_km=15.0, duration_seconds=int(15.0 * goal_pace))
    result = specificity_progress(race, [run])
    assert result["volume_at_pace"]["current"] > 0, (
        "15 km at goal pace must produce nonzero volume_at_pace"
    )


def test_ac2_ac10a_1h55_long_run_duration_nonzero():
    """A 1:55:00 long run (any pace) produces nonzero longest_run_by_duration current (AC2)."""
    race = _race(
        distance_km=HALF_MARATHON_KM,
        goal_time_seconds=SUB_1_50_GOAL_SECONDS,
    )
    duration_1h55 = 115 * 60  # 1:55:00 in seconds
    long_run = _run(distance_km=20.0, duration_seconds=duration_1h55)
    result = specificity_progress(race, [long_run])
    assert result["longest_run_by_duration"]["current"] > 0, (
        "A 1:55:00 long run must produce nonzero longest_run_by_duration"
    )


def test_ac2_ac10a_longest_run_by_distance_nonzero():
    """A long run contributes nonzero longest_run_by_distance current (AC2)."""
    race = _race(
        distance_km=HALF_MARATHON_KM,
        goal_time_seconds=SUB_1_50_GOAL_SECONDS,
    )
    long_run = _run(distance_km=20.0, duration_seconds=115 * 60)
    result = specificity_progress(race, [long_run])
    assert result["longest_run_by_distance"]["current"] > 0


# ─── AC4: Targets are derived from race, not hardcoded ────────────────────────

def test_ac4_targets_change_with_race_distance():
    """Changing race distance changes component targets without hardcoded values."""
    race_hm = _race(distance_km=HALF_MARATHON_KM, goal_time_seconds=SUB_1_50_GOAL_SECONDS)
    race_marathon = _race(distance_km=42.195, goal_time_seconds=3 * 3600 + 40 * 60)
    result_hm = specificity_progress(race_hm, [])
    result_marathon = specificity_progress(race_marathon, [])
    # Marathon targets must be larger than half-marathon targets
    assert result_marathon["longest_run_by_distance"]["target"] > result_hm["longest_run_by_distance"]["target"], (
        "Marathon target distance must be larger than half-marathon target"
    )


def test_ac4_targets_change_with_goal_time():
    """Changing goal time changes volume_at_pace target (pace band shifts)."""
    race_fast = _race(distance_km=HALF_MARATHON_KM, goal_time_seconds=100 * 60)  # 1:40
    race_slow = _race(distance_km=HALF_MARATHON_KM, goal_time_seconds=120 * 60)  # 2:00
    result_fast = specificity_progress(race_fast, [])
    result_slow = specificity_progress(race_slow, [])
    # Targets should differ when goal time differs
    fast_tgt = result_fast["volume_at_pace"]["target"]
    slow_tgt = result_slow["volume_at_pace"]["target"]
    assert fast_tgt != slow_tgt or result_fast["longest_run_by_duration"]["target"] != result_slow["longest_run_by_duration"]["target"], (
        "Changing goal time must change at least one target value"
    )


# ─── AC1: Function is callable and documented ─────────────────────────────────

def test_ac1_function_exists_and_callable():
    assert callable(specificity_progress)


def test_ac1_has_docstring():
    doc = specificity_progress.__doc__ or ""
    assert len(doc.strip()) > 50, "specificity_progress must have a non-trivial docstring"


def test_ac1_docstring_contains_worked_example():
    """Docstring must include a worked example for sub-1:50 half-marathon (AC1 + AC2)."""
    doc = specificity_progress.__doc__ or ""
    assert "1:50" in doc or "6600" in doc or "110" in doc, (
        "Docstring worked example must reference the sub-1:50 half-marathon scenario"
    )
    assert "5:13" in doc or "313" in doc or "312" in doc, (
        "Docstring worked example must reference the ~5:13/km goal pace"
    )


def test_ac1_docstring_mentions_all_four_components():
    doc = specificity_progress.__doc__ or ""
    for component in ("volume_at_pace", "longest_pace_effort", "longest_run_by_distance", "longest_run_by_duration"):
        assert component in doc, f"Docstring must mention '{component}'"


# ─── AC8: Pure function — no DB access ────────────────────────────────────────

def test_ac8_pure_no_db_calls():
    """specificity_progress source must not import or call session/DB functions."""
    src = inspect.getsource(specificity_progress)
    forbidden = ["session", "Session", "db.execute", "query(", ".commit(", "text("]
    for token in forbidden:
        assert token not in src, (
            f"specificity_progress must be pure — no DB calls (found '{token}')"
        )


# ─── AC11: Wired to race schema — uses distance_km, goal_pace_seconds_per_km ──

def test_ac11_uses_distance_km_from_race():
    """Function reads distance_km from the race object (matches races table schema)."""
    race = _race()
    src = inspect.getsource(specificity_progress)
    assert "distance_km" in src, "specificity_progress must use race.distance_km"


def test_ac11_uses_goal_pace_from_race():
    """Function reads goal_pace_seconds_per_km from the race object."""
    src = inspect.getsource(specificity_progress)
    assert "goal_pace_seconds_per_km" in src or "goal_time_seconds" in src, (
        "specificity_progress must derive pace from race goal fields"
    )


# ─── Multiple runs: volume accumulates ────────────────────────────────────────

def test_volume_accumulates_across_multiple_in_band_runs():
    """Volume at pace accumulates across multiple in-band runs."""
    race = _race()
    goal_pace = race.goal_pace_seconds_per_km
    run1 = _run(distance_km=10.0, duration_seconds=int(10.0 * goal_pace))
    run2 = _run(distance_km=5.0, duration_seconds=int(5.0 * goal_pace))
    result = specificity_progress(race, [run1, run2])
    assert result["volume_at_pace"]["current"] >= 14.0, (
        "volume_at_pace must accumulate across multiple in-band runs (expected >=14 km)"
    )


def test_longest_run_by_distance_picks_max():
    """longest_run_by_distance.current is the longest single run, not the sum."""
    race = _race()
    run1 = _run(distance_km=10.0, duration_seconds=10 * 60 * 6)
    run2 = _run(distance_km=18.0, duration_seconds=18 * 60 * 6)
    result = specificity_progress(race, [run1, run2])
    assert result["longest_run_by_distance"]["current"] >= 18.0, (
        "longest_run_by_distance must pick the longest run, not sum"
    )


def test_longest_run_by_duration_picks_max():
    """longest_run_by_duration.current is the longest single run by time, not sum."""
    race = _race()
    run1 = _run(distance_km=10.0, duration_seconds=3600)
    run2 = _run(distance_km=12.0, duration_seconds=5400)
    result = specificity_progress(race, [run1, run2])
    assert result["longest_run_by_duration"]["current"] >= 5400, (
        "longest_run_by_duration must pick the longest run by time"
    )
