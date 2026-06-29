"""Tests for issue #1109: Add Riegel cross-distance equivalence for race entries.

AC coverage:
  AC1 — every race/checkpoint entry includes half_marathon_equivalent_seconds
  AC2 — formula: T2 = T1 * (D2/D1)^1.06, exponent fixed at 1.06
  AC3 — half-marathon entry's equivalent equals its own raw time (within ±1 second)
  AC4 — 5 K in 20:00 (1200 s) → half-equivalent matches formula within ±1 second
  AC5 — round-trip: A→half→A recovers original within ±1 second
  AC6 — py_compile passes (no syntax errors in modified files)
  AC7 — returned value is rounded to the nearest second (integer)
"""

import math
import py_compile
import pathlib
import pytest

from backend.services.riegel import (
    HALF_MARATHON_KM,
    RIEGEL_EXPONENT,
    riegel_project,
    riegel_half_equivalent,
)


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── AC2: formula constants ────────────────────────────────────────────────────

def test_half_marathon_km_constant():
    assert HALF_MARATHON_KM == pytest.approx(21.0975, abs=1e-4)


def test_riegel_exponent_constant():
    assert RIEGEL_EXPONENT == pytest.approx(1.06, abs=1e-6)


# ── AC2: formula correctness ──────────────────────────────────────────────────

def test_riegel_project_formula():
    """T2 = T1 * (D2/D1)^1.06 — verified by recomputing with math.pow."""
    t1, d1, d2 = 1200, 5.0, HALF_MARATHON_KM
    expected = t1 * math.pow(d2 / d1, 1.06)
    result = riegel_project(t1, d1, d2)
    assert abs(result - round(expected)) <= 1


def test_riegel_half_equivalent_formula():
    """riegel_half_equivalent wraps riegel_project with D2=HALF_MARATHON_KM."""
    t1, d1 = 1200, 5.0
    expected = round(t1 * math.pow(HALF_MARATHON_KM / d1, 1.06))
    result = riegel_half_equivalent(t1, d1)
    assert abs(result - expected) <= 1


# ── AC3: half-marathon identity ───────────────────────────────────────────────

def test_half_marathon_identity_round_trip():
    """A half-marathon entry's equivalent should equal its own raw time (≤1 s)."""
    raw = 5400  # 1:30:00
    result = riegel_half_equivalent(raw, HALF_MARATHON_KM)
    assert abs(result - raw) <= 1


def test_half_marathon_identity_different_times():
    for raw in [3600, 5400, 6300, 7200]:
        result = riegel_half_equivalent(raw, HALF_MARATHON_KM)
        assert abs(result - raw) <= 1, f"Identity failed for raw={raw}: got {result}"


# ── AC4: known-good pair ──────────────────────────────────────────────────────

def test_5k_20min_half_equivalent_matches_formula():
    """5K in 20:00 (1200 s) → formula gives ~5520 s, result within ±1 second."""
    t1 = 1200  # 20:00
    d1 = 5.0  # 5 km
    formula_result = t1 * math.pow(HALF_MARATHON_KM / d1, 1.06)
    computed = riegel_half_equivalent(t1, d1)
    assert abs(computed - formula_result) <= 1


def test_10k_result_within_formula_tolerance():
    """10 K in 42:00 (2520 s) — result within ±1 s of formula."""
    t1 = 2520
    d1 = 10.0
    formula_result = t1 * math.pow(HALF_MARATHON_KM / d1, 1.06)
    computed = riegel_half_equivalent(t1, d1)
    assert abs(computed - formula_result) <= 1


# ── AC5: round-trip ───────────────────────────────────────────────────────────

def test_round_trip_5k_to_half_and_back():
    """Convert 5K time → half equivalent, then half → 5K; original recovered ±1 s."""
    t1 = 1200
    d1 = 5.0
    t_half = riegel_half_equivalent(t1, d1)
    t_recovered = riegel_project(t_half, HALF_MARATHON_KM, d1)
    assert abs(t_recovered - t1) <= 1


def test_round_trip_marathon_to_half_and_back():
    """Convert marathon time → half equivalent, then half → marathon ±1 s."""
    t1 = 12600  # 3:30:00
    d1 = 42.195
    t_half = riegel_half_equivalent(t1, d1)
    t_recovered = riegel_project(t_half, HALF_MARATHON_KM, d1)
    assert abs(t_recovered - t1) <= 1


def test_round_trip_10k_to_half_and_back():
    t1 = 2520  # 42:00
    d1 = 10.0
    t_half = riegel_half_equivalent(t1, d1)
    t_recovered = riegel_project(t_half, HALF_MARATHON_KM, d1)
    assert abs(t_recovered - t1) <= 1


# ── AC7: rounded to nearest second ───────────────────────────────────────────

def test_result_is_integer():
    result = riegel_half_equivalent(1200, 5.0)
    assert isinstance(result, int)


def test_riegel_project_is_integer():
    result = riegel_project(1200, 5.0, HALF_MARATHON_KM)
    assert isinstance(result, int)


# ── None propagation for missing inputs ───────────────────────────────────────

def test_riegel_half_equivalent_none_time():
    assert riegel_half_equivalent(None, 5.0) is None


def test_riegel_half_equivalent_none_distance():
    assert riegel_half_equivalent(1200, None) is None


def test_riegel_half_equivalent_zero_distance():
    assert riegel_half_equivalent(1200, 0) is None


def test_riegel_half_equivalent_negative_distance():
    assert riegel_half_equivalent(1200, -5.0) is None


def test_riegel_project_none_inputs():
    assert riegel_project(None, 5.0, HALF_MARATHON_KM) is None
    assert riegel_project(1200, None, HALF_MARATHON_KM) is None
    assert riegel_project(1200, 5.0, None) is None


# ── Marathon scaling direction ────────────────────────────────────────────────

def test_marathon_half_equivalent_less_than_marathon_time():
    """Half-equiv of a marathon time must be < the marathon time (shorter distance)."""
    marathon_time = 12600  # 3:30:00
    half_equiv = riegel_half_equivalent(marathon_time, 42.195)
    assert half_equiv < marathon_time


def test_longer_distance_same_pace_lower_equivalent():
    """Same pace over longer distance → lower (faster) half-equivalent.

    The Riegel exponent > 1 means sustaining a pace over a longer distance
    is harder, so the model projects a faster half-marathon time for the
    10K athlete than the 5K athlete running at the same pace.
    """
    pace = 300  # 5:00/km
    half_equiv_5k = riegel_half_equivalent(round(pace * 5), 5.0)
    half_equiv_10k = riegel_half_equivalent(round(pace * 10), 10.0)
    assert half_equiv_10k < half_equiv_5k


# ── AC6: py_compile passes on all modified Python files ──────────────────────

def test_py_compile_riegel():
    path = REPO_ROOT / "backend" / "services" / "riegel.py"
    py_compile.compile(str(path), doraise=True)


def test_py_compile_main():
    path = REPO_ROOT / "backend" / "main.py"
    py_compile.compile(str(path), doraise=True)


# ── AC1: _race_dict and _checkpoint_dict include the field ───────────────────

def test_race_dict_has_half_equivalent():
    """_race_dict must include half_marathon_equivalent_seconds."""
    import importlib
    import types
    import datetime

    main = importlib.import_module("backend.main")

    class FakeRace:
        id = __import__("uuid").uuid4()
        user_id = __import__("uuid").uuid4()
        name = "Test Race"
        race_date = datetime.date(2026, 1, 1)
        distance_km = 5.0
        goal_time_seconds = None
        goal_pace_seconds_per_km = None
        actual_time_seconds = 1200
        priority = "A"
        status = "done"
        race_type = "race"
        created_at = None
        updated_at = None

    result = main._race_dict(FakeRace())
    assert "half_marathon_equivalent_seconds" in result
    # 5K in 1200 s → formula result (not None)
    assert result["half_marathon_equivalent_seconds"] is not None
    assert isinstance(result["half_marathon_equivalent_seconds"], int)


def test_race_dict_no_actual_time_equivalent_is_none():
    """When actual_time_seconds is None, equivalent must be None."""
    import importlib
    import datetime

    main = importlib.import_module("backend.main")

    class FakeRace:
        id = __import__("uuid").uuid4()
        user_id = __import__("uuid").uuid4()
        name = "Future Race"
        race_date = datetime.date(2027, 1, 1)
        distance_km = 21.0975
        goal_time_seconds = None
        goal_pace_seconds_per_km = None
        actual_time_seconds = None
        priority = "A"
        status = "planned"
        race_type = "race"
        created_at = None
        updated_at = None

    result = main._race_dict(FakeRace())
    assert result["half_marathon_equivalent_seconds"] is None


def test_checkpoint_dict_has_half_equivalent():
    """_checkpoint_dict must include half_marathon_equivalent_seconds when both fields set."""
    import importlib
    import datetime

    main = importlib.import_module("backend.main")

    class FakeCheckpoint:
        id = __import__("uuid").uuid4()
        race_id = __import__("uuid").uuid4()
        user_id = __import__("uuid").uuid4()
        label = "10K checkpoint"
        target_distance_km = 10.0
        target_pace_seconds_per_km = None
        target_duration_seconds = 2520
        met = False
        met_override = False
        met_workout_id = None
        created_at = None
        updated_at = None

    result = main._checkpoint_dict(FakeCheckpoint())
    assert "half_marathon_equivalent_seconds" in result
    assert result["half_marathon_equivalent_seconds"] is not None
    assert isinstance(result["half_marathon_equivalent_seconds"], int)


def test_checkpoint_dict_missing_duration_equivalent_is_none():
    """When target_duration_seconds is None, equivalent must be None."""
    import importlib

    main = importlib.import_module("backend.main")

    class FakeCheckpoint:
        id = __import__("uuid").uuid4()
        race_id = __import__("uuid").uuid4()
        user_id = __import__("uuid").uuid4()
        label = "Distance only checkpoint"
        target_distance_km = 10.0
        target_pace_seconds_per_km = 300
        target_duration_seconds = None
        met = False
        met_override = False
        met_workout_id = None
        created_at = None
        updated_at = None

    result = main._checkpoint_dict(FakeCheckpoint())
    assert result["half_marathon_equivalent_seconds"] is None
