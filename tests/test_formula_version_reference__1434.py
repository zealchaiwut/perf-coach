"""Tests for issue #1434: Reference prediction_snapshot.FORMULA_VERSION instead of
hardcoded "1" in projection router.

Acceptance criteria verified:
- AC1: No hardcoded formula_version="1" literal at the _build_snap call site in
       backend/routers/projection.py — the kwarg must be absent (relying on the
       function's own default) or reference the FORMULA_VERSION constant.
- AC2: build_snapshot_payload's default formula_version matches the module-level
       FORMULA_VERSION constant, ensuring they are always in sync.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PROJECTION_ROUTER = _ROOT / "backend" / "routers" / "projection.py"


# ── AC1: no hardcoded literal at the _build_snap call site ───────────────────

def test_ac1_no_hardcoded_formula_version_literal():
    """AC1: the _build_snap call in projection.py must not pass formula_version="1"."""
    src = _PROJECTION_ROUTER.read_text()
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        func_name = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        if func_name != "_build_snap":
            continue
        for kw in node.keywords:
            if kw.arg == "formula_version" and isinstance(kw.value, ast.Constant):
                assert False, (
                    f"projection.py line {node.lineno}: "
                    f"formula_version is a hardcoded literal {kw.value.value!r}. "
                    "Drop the kwarg (use the default) or pass prediction_snapshot.FORMULA_VERSION."
                )


def test_ac1_if_formula_version_kwarg_present_it_references_constant():
    """AC1: if formula_version IS passed at the _build_snap call site, it must
    reference a Name or Attribute node (FORMULA_VERSION constant), not a literal."""
    src = _PROJECTION_ROUTER.read_text()
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        func_name = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        if func_name != "_build_snap":
            continue
        for kw in node.keywords:
            if kw.arg != "formula_version":
                continue
            # Must be a Name or Attribute (a constant reference), not a literal
            assert isinstance(kw.value, (ast.Name, ast.Attribute)), (
                f"projection.py line {node.lineno}: formula_version kwarg "
                "must reference a constant (e.g. FORMULA_VERSION), not a literal string."
            )


# ── AC2: build_snapshot_payload default matches the module constant ───────────

def test_ac2_default_formula_version_matches_module_constant():
    """AC2: build_snapshot_payload's default formula_version == FORMULA_VERSION.

    This confirms the function's default is always derived from the single
    source-of-truth constant, not a separate magic string.
    """
    from backend.services import prediction_snapshot as _ps

    sig = inspect.signature(_ps.build_snapshot_payload)
    default = sig.parameters["formula_version"].default
    assert default == _ps.FORMULA_VERSION, (
        "build_snapshot_payload's default formula_version must equal "
        f"prediction_snapshot.FORMULA_VERSION ({_ps.FORMULA_VERSION!r}), "
        f"got {default!r}"
    )


def test_ac2_calling_without_formula_version_uses_module_constant():
    """AC2: calling build_snapshot_payload without formula_version kwarg yields
    a payload whose formula_version equals prediction_snapshot.FORMULA_VERSION."""
    from datetime import date
    from backend.services import prediction_snapshot as _ps

    payload = _ps.build_snapshot_payload(
        race_projections=[],
        ctl_series=[40.0],
        start_date=date(2026, 7, 22),
        races_meta=[],
        # No formula_version kwarg — relies on the default
    )
    assert payload["formula_version"] == _ps.FORMULA_VERSION, (
        "Payload formula_version must equal prediction_snapshot.FORMULA_VERSION"
    )
