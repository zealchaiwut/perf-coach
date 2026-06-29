"""
Tests for issue #1105: Scaffold projection.py and roll CTL/ATL/TSB forward.

Acceptance criteria verified:
- AC1: projection.py exists and imports CTL/ATL decay constants from the Layer-1
       module (no redefinition of the 42 or 7 magic numbers).
- AC2: Given a planned_load sequence and a starting CTL/ATL state, the module
       produces day-by-day projected CTL, ATL, and TSB series up to the A-race date.
- AC3: A taper scenario (load decreasing toward zero in final days) results in a
       positive projected TSB at the race date.
- AC4: EWMA constants in projection.py match Layer-1 exactly (CTL_DECAY ≈ 1-1/42,
       ATL_DECAY ≈ 1-1/7, derived via exp(-1/time_constant)).
- AC5: py_compile.compile on the projection.py file completes with no errors.
- AC6: Output series are indexable by date and contain one entry per day from
       start through A-race date.
"""
import ast
import math
import py_compile
import inspect
import os
import textwrap
from datetime import date, timedelta

import pytest

from backend.services.projection import (
    CTL_DECAY,
    ATL_DECAY,
    project_fitness,
)
from backend.services.fitness_model import CTL_TIME_CONSTANT, ATL_TIME_CONSTANT

TODAY = date(2026, 6, 29)


# ── AC5: file compiles without errors ─────────────────────────────────────────

def test_ac5_py_compile_no_errors():
    """py_compile.compile on projection.py must succeed with no errors."""
    import backend.services.projection as mod
    path = mod.__file__
    # Compile .py source (not .pyc)
    if path.endswith(".pyc"):
        path = path[:-1]
    py_compile.compile(path, doraise=True)


# ── AC1: imports from Layer-1, no magic-number redefinition ──────────────────

def test_ac1_module_imports_from_fitness_model():
    """projection.py must import time constants from fitness_model (Layer-1)."""
    import backend.services.projection as mod
    src = inspect.getsource(mod)
    assert "fitness_model" in src, (
        "projection.py must import from backend.services.fitness_model"
    )


def test_ac1_no_hardcoded_42_or_7_as_literals():
    """projection.py must not contain 42 or 7 as standalone numeric literals."""
    import backend.services.projection as mod
    src = inspect.getsource(mod)
    tree = ast.parse(textwrap.dedent(src))
    magic = {42, 7}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            assert node.value not in magic, (
                f"projection.py hardcodes magic number {node.value}; "
                "import from fitness_model instead"
            )


def test_ac1_ctl_decay_exported():
    assert hasattr(__import__("backend.services.projection", fromlist=["CTL_DECAY"]), "CTL_DECAY")


def test_ac1_atl_decay_exported():
    assert hasattr(__import__("backend.services.projection", fromlist=["ATL_DECAY"]), "ATL_DECAY")


# ── AC4: constants match Layer-1 exactly ──────────────────────────────────────

def test_ac4_ctl_decay_matches_layer1():
    """CTL_DECAY must equal exp(-1 / CTL_TIME_CONSTANT) from fitness_model."""
    expected = math.exp(-1 / CTL_TIME_CONSTANT)
    assert abs(CTL_DECAY - expected) < 1e-12, (
        f"CTL_DECAY={CTL_DECAY} does not match exp(-1/{CTL_TIME_CONSTANT})={expected}"
    )


def test_ac4_atl_decay_matches_layer1():
    """ATL_DECAY must equal exp(-1 / ATL_TIME_CONSTANT) from fitness_model."""
    expected = math.exp(-1 / ATL_TIME_CONSTANT)
    assert abs(ATL_DECAY - expected) < 1e-12, (
        f"ATL_DECAY={ATL_DECAY} does not match exp(-1/{ATL_TIME_CONSTANT})={expected}"
    )


def test_ac4_ctl_decay_approx_1_minus_1_over_42():
    """CTL_DECAY ≈ 1 - 1/42 (the approximate Banister decay factor)."""
    assert abs(CTL_DECAY - (1 - 1 / CTL_TIME_CONSTANT)) < 0.001


def test_ac4_atl_decay_approx_1_minus_1_over_7():
    """ATL_DECAY ≈ 1 - 1/7 (the approximate ATL decay factor, within 2%)."""
    # exp(-1/7) ≈ 0.867 vs 1-1/7 ≈ 0.857; the approx. is coarser for small tau
    assert abs(ATL_DECAY - (1 - 1 / ATL_TIME_CONSTANT)) < 0.02


def test_ac4_ctl_decay_less_than_1_greater_than_0():
    assert 0 < CTL_DECAY < 1


def test_ac4_atl_decay_less_than_ctl_decay():
    """ATL decays faster (smaller factor) than CTL."""
    assert ATL_DECAY < CTL_DECAY


# ── AC2: day-by-day projection ────────────────────────────────────────────────

def test_ac2_function_is_callable():
    assert callable(project_fitness)


def test_ac2_returns_series_for_flat_load():
    """Flat load of 100 for 30 days produces a 30-entry series."""
    loads = [100.0] * 30
    result = project_fitness(loads, start_ctl=80.0, start_atl=80.0, start_date=TODAY)
    assert len(result) == 30


def test_ac2_series_has_ctl_atl_tsb_keys():
    loads = [50.0] * 5
    result = project_fitness(loads, start_ctl=40.0, start_atl=40.0, start_date=TODAY)
    for entry in result.values():
        assert "ctl" in entry
        assert "atl" in entry
        assert "tsb" in entry


def test_ac2_tsb_equals_ctl_minus_atl():
    loads = [60.0] * 10
    result = project_fitness(loads, start_ctl=50.0, start_atl=55.0, start_date=TODAY)
    for day, entry in result.items():
        assert abs(entry["tsb"] - (entry["ctl"] - entry["atl"])) < 1e-9, (
            f"TSB on {day} should equal CTL - ATL"
        )


def test_ac2_ctl_updates_with_correct_ewma():
    """Day-1 CTL must equal: start_ctl * CTL_DECAY + load * (1 - CTL_DECAY)."""
    start_ctl = 80.0
    start_atl = 80.0
    load = 100.0
    expected_ctl1 = start_ctl * CTL_DECAY + load * (1 - CTL_DECAY)
    result = project_fitness([load], start_ctl=start_ctl, start_atl=start_atl, start_date=TODAY)
    day1_entry = result[TODAY + timedelta(days=1)]
    assert abs(day1_entry["ctl"] - expected_ctl1) < 1e-9


def test_ac2_atl_updates_with_correct_ewma():
    """Day-1 ATL must equal: start_atl * ATL_DECAY + load * (1 - ATL_DECAY)."""
    start_ctl = 80.0
    start_atl = 80.0
    load = 100.0
    expected_atl1 = start_atl * ATL_DECAY + load * (1 - ATL_DECAY)
    result = project_fitness([load], start_ctl=start_ctl, start_atl=start_atl, start_date=TODAY)
    day1_entry = result[TODAY + timedelta(days=1)]
    assert abs(day1_entry["atl"] - expected_atl1) < 1e-9


def test_ac2_flat_100_ctl_converges_toward_100():
    """With constant load 100, CTL should move toward 100 from a lower start."""
    loads = [100.0] * 30
    result = project_fitness(loads, start_ctl=80.0, start_atl=80.0, start_date=TODAY)
    values = list(result.values())
    assert values[-1]["ctl"] > values[0]["ctl"], "CTL should rise toward 100 from 80"
    assert values[-1]["ctl"] < 100.0, "CTL cannot exceed the load in 30 days"


def test_ac2_flat_100_atl_converges_faster():
    """ATL (7-day) converges to 100 faster than CTL (42-day) from the same start."""
    loads = [100.0] * 30
    result = project_fitness(loads, start_ctl=80.0, start_atl=80.0, start_date=TODAY)
    values = list(result.values())
    # ATL should be closer to 100 than CTL after 30 days
    assert values[-1]["atl"] > values[-1]["ctl"], (
        "ATL converges faster so should be above CTL after 30 days of load > start"
    )


# ── AC3: taper scenario → positive TSB at race date ──────────────────────────

def test_ac3_taper_produces_positive_tsb():
    """21 days at 100 + 7 days at 20 → positive TSB on day 28 (race day)."""
    loads = [100.0] * 21 + [20.0] * 7
    result = project_fitness(loads, start_ctl=80.0, start_atl=80.0, start_date=TODAY)
    race_date = TODAY + timedelta(days=28)
    race_entry = result[race_date]
    assert race_entry["tsb"] > 0, (
        f"Taper scenario should produce positive TSB on race day, got {race_entry['tsb']:.2f}"
    )


def test_ac3_taper_tsb_rises_during_taper_window():
    """TSB must increase (become less negative then positive) during the taper window."""
    loads = [100.0] * 21 + [20.0] * 7
    result = project_fitness(loads, start_ctl=80.0, start_atl=80.0, start_date=TODAY)
    values = list(result.values())
    # TSB on day 28 must be higher than TSB on day 21
    tsb_day21 = values[20]["tsb"]
    tsb_day28 = values[27]["tsb"]
    assert tsb_day28 > tsb_day21, (
        f"TSB should rise during taper: day21={tsb_day21:.2f}, day28={tsb_day28:.2f}"
    )


# ── AC6: series is indexable by date, contiguous, correct count ───────────────

def test_ac6_series_indexed_by_date_objects():
    loads = [50.0] * 5
    result = project_fitness(loads, start_ctl=40.0, start_atl=40.0, start_date=TODAY)
    for key in result:
        assert isinstance(key, date), f"Keys must be date objects, got {type(key)}"


def test_ac6_dates_are_contiguous_no_gaps():
    n = 10
    loads = [50.0] * n
    result = project_fitness(loads, start_ctl=40.0, start_atl=40.0, start_date=TODAY)
    keys = sorted(result.keys())
    for i in range(1, len(keys)):
        gap = (keys[i] - keys[i - 1]).days
        assert gap == 1, f"Gap of {gap} days between {keys[i-1]} and {keys[i]}"


def test_ac6_first_entry_is_start_date_plus_one():
    loads = [50.0] * 5
    result = project_fitness(loads, start_ctl=40.0, start_atl=40.0, start_date=TODAY)
    keys = sorted(result.keys())
    assert keys[0] == TODAY + timedelta(days=1), (
        f"First entry should be start_date+1, got {keys[0]}"
    )


def test_ac6_last_entry_is_start_date_plus_n():
    n = 7
    loads = [50.0] * n
    result = project_fitness(loads, start_ctl=40.0, start_atl=40.0, start_date=TODAY)
    keys = sorted(result.keys())
    assert keys[-1] == TODAY + timedelta(days=n), (
        f"Last entry should be start_date+{n}, got {keys[-1]}"
    )


def test_ac6_count_equals_planned_load_length():
    for n in (1, 5, 28, 30):
        loads = [60.0] * n
        result = project_fitness(loads, start_ctl=50.0, start_atl=55.0, start_date=TODAY)
        assert len(result) == n, f"Expected {n} entries for {n} load days, got {len(result)}"


def test_ac6_empty_load_returns_empty_series():
    result = project_fitness([], start_ctl=50.0, start_atl=55.0, start_date=TODAY)
    assert len(result) == 0
