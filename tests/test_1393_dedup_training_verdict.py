"""Tests for issue #1393 — remove dead/duplicate code from training_verdict.py.

AC items:
  AC1: READINESS_LOW_TODAY and READINESS_LOW_TREND are each defined exactly once.
  AC2: _downgrade_one is defined exactly once and behaves correctly.
  AC3: _VERDICT_ORDER is deleted (not exported from the module).
  AC4: All existing behavior is preserved — no change in computed verdicts.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

import backend.services.training_verdict as tv
from backend.services.training_verdict import (
    READINESS_LOW_TODAY,
    READINESS_LOW_TREND,
    compute_verdict,
)

_SOURCE = pathlib.Path(tv.__file__).read_text()
_TREE = ast.parse(_SOURCE)

_TODAY_DATE = __import__("datetime").date(2026, 8, 4)
_SNAP_BUILD = {"acwr": 1.0, "tsb": 5.0, "ctl": 40.0, "atl": 38.0}
_SNAP_HOLD = {"acwr": 1.35, "tsb": -5.0, "ctl": 40.0, "atl": 50.0}
_SNAP_BACK_OFF = {"acwr": 1.60, "tsb": -16.8, "ctl": 32.0, "atl": 48.8}


# ── AC1: single definition of READINESS_LOW_TODAY and READINESS_LOW_TREND ────

def _count_assignments(tree: ast.Module, name: str) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            count += sum(1 for t in node.targets if isinstance(t, ast.Name) and t.id == name)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value is not None:
                count += 1
    return count


def test_readiness_low_today_defined_exactly_once():
    """AC1: READINESS_LOW_TODAY must appear as an assignment exactly once."""
    count = _count_assignments(_TREE, "READINESS_LOW_TODAY")
    assert count == 1, f"READINESS_LOW_TODAY defined {count} times (expected 1)"


def test_readiness_low_trend_defined_exactly_once():
    """AC1: READINESS_LOW_TREND must appear as an assignment exactly once."""
    count = _count_assignments(_TREE, "READINESS_LOW_TREND")
    assert count == 1, f"READINESS_LOW_TREND defined {count} times (expected 1)"


def test_readiness_thresholds_values_unchanged():
    """AC4: threshold values must remain 40.0 and 50.0."""
    assert READINESS_LOW_TODAY == 40.0
    assert READINESS_LOW_TREND == 50.0


# ── AC2: single definition of _downgrade_one ─────────────────────────────────

def _count_function_defs(tree: ast.Module, name: str) -> int:
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_downgrade_one_defined_exactly_once():
    """AC2: _downgrade_one must be defined exactly once."""
    count = _count_function_defs(_TREE, "_downgrade_one")
    assert count == 1, f"_downgrade_one defined {count} times (expected 1)"


def test_downgrade_one_build_to_hold():
    """AC2: build → hold."""
    from backend.services.training_verdict import _downgrade_one
    assert _downgrade_one("build") == "hold"


def test_downgrade_one_hold_to_back_off():
    """AC2: hold → back_off."""
    from backend.services.training_verdict import _downgrade_one
    assert _downgrade_one("hold") == "back_off"


def test_downgrade_one_back_off_stays():
    """AC2: back_off → back_off (floor)."""
    from backend.services.training_verdict import _downgrade_one
    assert _downgrade_one("back_off") == "back_off"


# ── AC3: _VERDICT_ORDER is gone ───────────────────────────────────────────────

def test_verdict_order_not_in_module():
    """AC3: _VERDICT_ORDER must not be present in the module namespace."""
    assert not hasattr(tv, "_VERDICT_ORDER"), "_VERDICT_ORDER still exists in module"


def test_verdict_order_not_assigned_in_source():
    """AC3: _VERDICT_ORDER must not appear as an assignment in the source."""
    count = _count_assignments(_TREE, "_VERDICT_ORDER")
    assert count == 0, f"_VERDICT_ORDER still assigned {count} time(s) in source"


# ── AC4: behavior is fully preserved ─────────────────────────────────────────

def test_verdict_build_unchanged():
    result = compute_verdict(_SNAP_BUILD, today=_TODAY_DATE)
    assert result["verdict"] == "build"


def test_verdict_hold_unchanged():
    result = compute_verdict(_SNAP_HOLD, today=_TODAY_DATE)
    assert result["verdict"] == "hold"


def test_verdict_back_off_unchanged():
    result = compute_verdict(_SNAP_BACK_OFF, today=_TODAY_DATE)
    assert result["verdict"] == "back_off"


def test_low_readiness_today_still_downgrades():
    result = compute_verdict(
        _SNAP_BUILD, today=_TODAY_DATE,
        readiness_today=READINESS_LOW_TODAY - 1,
    )
    assert result["verdict"] == "hold"
    assert any(m["rule"] == "low_readiness_today" for m in result["modifiers"])


def test_low_readiness_trend_still_downgrades():
    result = compute_verdict(
        _SNAP_BUILD, today=_TODAY_DATE,
        readiness_7d_mean=READINESS_LOW_TREND - 1,
    )
    assert result["verdict"] == "hold"
    assert any(m["rule"] == "low_readiness_trend" for m in result["modifiers"])
