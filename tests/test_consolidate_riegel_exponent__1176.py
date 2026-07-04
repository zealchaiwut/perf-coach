"""Tests for issue #1176: Consolidate duplicate Riegel logic and RIEGEL_EXPONENT constant.

AC coverage:
  AC1 — projection.py no longer declares RIEGEL_EXPONENT locally; imports it from riegel.py
  AC2 — compute_half_equivalent is renamed to compute_half_race_equivalent
  AC3 — projection payload field is renamed to half_race_equivalent / half_race_equivalent_seconds
  AC4 — no usages of a local RIEGEL_EXPONENT declaration in projection.py
  AC5 — all existing projection and Riegel helper tests pass
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date, timedelta

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PROJECTION_PY = _ROOT / "backend" / "services" / "projection.py"


# ── AC1 + AC4: no local RIEGEL_EXPONENT declaration in projection.py ────────────

def test_no_local_riegel_exponent_assignment():
    """AC1/AC4: projection.py must not declare RIEGEL_EXPONENT = ... locally."""
    source = _PROJECTION_PY.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "RIEGEL_EXPONENT":
                    pytest.fail(
                        f"Found local 'RIEGEL_EXPONENT = ...' assignment at line "
                        f"{node.lineno} in projection.py — it must be imported from riegel.py"
                    )
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "RIEGEL_EXPONENT":
                pytest.fail(
                    f"Found annotated 'RIEGEL_EXPONENT: ... = ...' at line "
                    f"{node.lineno} in projection.py — it must be imported from riegel.py"
                )


def test_riegel_exponent_imported_from_riegel():
    """AC1: RIEGEL_EXPONENT importable from projection.py resolves to riegel.py's value."""
    from backend.services.riegel import RIEGEL_EXPONENT as riegel_exp
    from backend.services.projection import RIEGEL_EXPONENT as proj_exp
    assert proj_exp == riegel_exp, (
        "projection.RIEGEL_EXPONENT must be the same object/value as riegel.RIEGEL_EXPONENT"
    )


def test_projection_imports_riegel_exponent_from_riegel_module():
    """AC1: projection.py source must contain an import of RIEGEL_EXPONENT from riegel."""
    source = _PROJECTION_PY.read_text()
    assert "RIEGEL_EXPONENT" in source, "RIEGEL_EXPONENT must appear in projection.py"
    # There must be a 'from ... riegel import ... RIEGEL_EXPONENT' line
    import_lines = [
        line.strip() for line in source.splitlines()
        if "import" in line and "RIEGEL_EXPONENT" in line
    ]
    assert import_lines, (
        "projection.py must import RIEGEL_EXPONENT (expected a 'from riegel import ...' line)"
    )
    assert any("riegel" in line for line in import_lines), (
        "The RIEGEL_EXPONENT import in projection.py must reference 'riegel'"
    )


# ── AC2: compute_half_race_equivalent exists and compute_half_equivalent is renamed ─

def test_compute_half_race_equivalent_is_callable():
    """AC2: compute_half_race_equivalent must be importable from projection.py."""
    from backend.services.projection import compute_half_race_equivalent
    assert callable(compute_half_race_equivalent)


def test_compute_half_race_equivalent_none_on_none_seconds():
    """AC2: compute_half_race_equivalent returns None when finish_seconds is None."""
    from backend.services.projection import compute_half_race_equivalent
    assert compute_half_race_equivalent(None, 42.195) is None


def test_compute_half_race_equivalent_none_on_none_distance():
    """AC2: compute_half_race_equivalent returns None when distance_km is None."""
    from backend.services.projection import compute_half_race_equivalent
    assert compute_half_race_equivalent(13500, None) is None


def test_compute_half_race_equivalent_none_on_zero_distance():
    """AC2: compute_half_race_equivalent returns None when distance_km is 0."""
    from backend.services.projection import compute_half_race_equivalent
    assert compute_half_race_equivalent(13500, 0.0) is None


def test_compute_half_race_equivalent_formula():
    """AC2: compute_half_race_equivalent applies 0.5^RIEGEL_EXPONENT multiplier."""
    from backend.services.projection import compute_half_race_equivalent, RIEGEL_EXPONENT
    seconds = 14400
    result = compute_half_race_equivalent(seconds, 42.195)
    expected = int(round(seconds * (0.5 ** RIEGEL_EXPONENT)))
    assert result == expected


def test_compute_half_race_equivalent_returns_int():
    """AC2: compute_half_race_equivalent returns an int."""
    from backend.services.projection import compute_half_race_equivalent
    result = compute_half_race_equivalent(10000, 21.0975)
    assert result is not None
    assert isinstance(result, int)


def test_old_name_absent_or_only_as_alias():
    """AC2: compute_half_equivalent must not be the primary definition in projection.py."""
    source = _PROJECTION_PY.read_text()
    # 'def compute_half_equivalent' (old primary definition) must be gone
    assert "def compute_half_equivalent(" not in source, (
        "compute_half_equivalent should no longer be the primary definition; "
        "rename it to compute_half_race_equivalent"
    )


# ── AC3: payload uses half_race_equivalent / half_race_equivalent_seconds ───────

_TODAY = date(2026, 7, 4)


def _make_payload(**kwargs):
    from backend.services.projection import build_plan_projection_payload
    defaults = {
        "start_ctl": 40.0,
        "start_atl": 45.0,
        "start_date": _TODAY,
        "planned_load": [50.0] * 30,
        "races": [{"date": _TODAY + timedelta(days=14), "distance_km": 42.195, "name": "Marathon"}],
        "thresholds": {"threshold_pace_seconds_per_km": 300},
    }
    defaults.update(kwargs)
    return build_plan_projection_payload(**defaults)


def test_payload_has_half_race_equivalent_key():
    """AC3: race entry must contain half_race_equivalent key."""
    result = _make_payload()
    assert len(result["races"]) == 1
    assert "half_race_equivalent" in result["races"][0], (
        "Expected 'half_race_equivalent' key in race entry"
    )


def test_payload_has_half_race_equivalent_seconds_key():
    """AC3: race entry must contain half_race_equivalent_seconds key."""
    result = _make_payload()
    assert len(result["races"]) == 1
    assert "half_race_equivalent_seconds" in result["races"][0], (
        "Expected 'half_race_equivalent_seconds' key in race entry"
    )


def test_payload_half_race_equivalent_shorter_than_full():
    """AC3: half_race_equivalent_seconds < estimated_finish_seconds for a positive race."""
    result = _make_payload()
    entry = result["races"][0]
    if entry["estimated_finish_seconds"] is not None and entry["half_race_equivalent_seconds"] is not None:
        assert entry["half_race_equivalent_seconds"] < entry["estimated_finish_seconds"]


def test_payload_half_race_equivalent_value_matches_formula():
    """AC3: half_race_equivalent_seconds matches compute_half_race_equivalent output."""
    from backend.services.projection import compute_half_race_equivalent
    result = _make_payload()
    entry = result["races"][0]
    est = entry["estimated_finish_seconds"]
    if est is not None:
        expected = compute_half_race_equivalent(est, 42.195)
        assert entry["half_race_equivalent_seconds"] == expected


# ── AC4: grep-level — no 'RIEGEL_EXPONENT = ' anywhere in projection.py ────────

def test_no_riegel_exponent_literal_in_projection_source():
    """AC4: 'RIEGEL_EXPONENT = 1.06' literal must not appear in projection.py."""
    source = _PROJECTION_PY.read_text()
    assert "RIEGEL_EXPONENT = 1.06" not in source, (
        "Found 'RIEGEL_EXPONENT = 1.06' in projection.py — must be imported from riegel.py"
    )
