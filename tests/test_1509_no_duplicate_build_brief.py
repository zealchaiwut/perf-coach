"""Tests for issue #1509: _build_brief must not be duplicated in export_brief.py.

The CLI wrapper must delegate to backend.services.daily_brief._build_brief so
there is a single source of truth for brief assembly.  A future change to the
service payload shape will be reflected in the CLI output automatically.

Acceptance criteria (derived from the issue suggestion):
  AC1  The CLI's export_brief.py does NOT contain an independent _build_brief
       implementation — its body must be a thin delegation to the service.
  AC2  _assemble_coach is defined in backend.services.daily_brief (the service),
       not only in scripts/export_brief.py.
  AC3  The service's _build_brief includes the coach block when _assemble_coach
       returns a non-None dict.
  AC4  The service's _build_brief omits the "coach" key (not null) when
       _assemble_coach returns None.
  AC5  The CLI's _build_brief output is identical to the service's _build_brief
       output (same dict) for the same inputs.
  AC6  Compat: m._build_brief still accepts (for_date, worker_url, user_id,
       username) four-arg signature so existing call sites are not broken.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import pathlib
from datetime import date
from unittest.mock import patch

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_brief.py"


def _import_cli():
    spec = importlib.util.spec_from_file_location("export_brief_1509", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _import_cli()


@pytest.fixture(scope="module")
def svc():
    import backend.services.daily_brief as svc_mod
    importlib.reload(svc_mod)
    return svc_mod


# ── AC1: No independent _build_brief implementation in the CLI ────────────────

def test_cli_build_brief_body_is_thin_delegation():
    """AC1: The CLI's _build_brief must not contain assembly logic.

    An independent implementation body would have many statements computing
    form/weight/advisories etc.  A thin delegation is at most a 1–3 line body
    (call service, return result).
    """
    src = _SCRIPT.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_brief":
            non_doc = [
                s for s in node.body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            ]
            assert len(non_doc) <= 3, (
                f"CLI _build_brief has {len(non_doc)} non-docstring statements — "
                "it appears to contain its own assembly logic instead of delegating "
                "to backend.services.daily_brief._build_brief"
            )
            return
    # If _build_brief is not defined at all in the CLI, that's also acceptable
    # (it would be a pure re-export from the service)


def test_cli_build_brief_calls_service_build_brief(m, svc):
    """AC1/AC5: CLI's _build_brief produces the same result as the service's."""
    for_date = date(2026, 7, 17)
    user_id = "00000000-0000-0000-0000-000000000001"

    fake_plan = {"planned": False, "sessions": [], "plan_date": "2026-07-17"}
    fake_form = {
        "ctl": 42.0, "atl": 38.0, "tsb": 4.0,
        "ramp": 0.5, "flags": {}, "interpretation": "Neutral", "acwr": 0.95,
    }
    fake_wrap = {
        "window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
        "adherence": 0.0, "load_trend": 0.0, "highlights_md": "Rest week.",
    }
    fake_weight = {
        "current_kg": None, "trend_7d": None, "trend_28d": None,
        "target_kg": None, "target_date": None, "pace_kg_per_week": None,
        "on_track": None, "projection_date": None,
    }

    with patch.object(svc, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(svc, "_assemble_form", return_value=fake_form), \
         patch.object(svc, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(svc, "_assemble_weight", return_value=fake_weight), \
         patch.object(svc, "_assemble_advisories", return_value=[]), \
         patch.object(svc, "_assemble_coach", return_value=None):
        svc_result = svc._build_brief(for_date, user_id=user_id)

    with patch.object(svc, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(svc, "_assemble_form", return_value=fake_form), \
         patch.object(svc, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(svc, "_assemble_weight", return_value=fake_weight), \
         patch.object(svc, "_assemble_advisories", return_value=[]), \
         patch.object(svc, "_assemble_coach", return_value=None):
        cli_result = m._build_brief(for_date, None, user_id, None)

    # Both should return the same shape
    assert set(cli_result.keys()) == set(svc_result.keys())
    assert cli_result["schema_version"] == svc_result["schema_version"]
    assert cli_result["for_date"] == svc_result["for_date"]
    assert cli_result["form"] == svc_result["form"]


# ── AC2: _assemble_coach lives in the service ─────────────────────────────────

def test_assemble_coach_in_service_module(svc):
    """AC2: _assemble_coach is defined in backend.services.daily_brief."""
    assert hasattr(svc, "_assemble_coach"), (
        "_assemble_coach must be defined in backend.services.daily_brief"
    )
    assert callable(svc._assemble_coach)


def test_assemble_coach_not_independently_defined_in_cli():
    """AC2: _assemble_coach is NOT independently defined in scripts/export_brief.py.

    It must either be absent (re-imported from service) or be identical to the
    service's implementation.  An independent copy means the two can diverge.
    """
    src = _SCRIPT.read_text()
    tree = ast.parse(src)
    cli_defs = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert "_assemble_coach" not in cli_defs, (
        "_assemble_coach must not be independently defined in export_brief.py; "
        "import it from backend.services.daily_brief instead"
    )


# ── AC3: service._build_brief includes coach when _assemble_coach returns dict ─

def test_service_build_brief_includes_coach(svc):
    """AC3: When _assemble_coach returns a dict, _build_brief includes 'coach' key."""
    for_date = date(2026, 7, 17)
    user_id = "00000000-0000-0000-0000-000000000001"
    fake_coach = {
        "directive": "Hold TSS at 315/week.",
        "projection": "plan → ~1:45 by mid-Dec",
        "levers": ["load: locked until 31 Jul"],
    }

    with patch.object(svc, "_get_plan_for_date", return_value={"planned": False, "sessions": []}), \
         patch.object(svc, "_assemble_form", return_value={"ctl": 0.0, "atl": 0.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "Neutral", "acwr": None}), \
         patch.object(svc, "_assemble_recent_wrap", return_value={"window_days": 14, "sessions_planned": 0, "sessions_completed": 0, "adherence": 0.0, "load_trend": 0.0, "highlights_md": ""}), \
         patch.object(svc, "_assemble_weight", return_value=dict(svc._NULL_WEIGHT_BLOCK)), \
         patch.object(svc, "_assemble_advisories", return_value=[]), \
         patch.object(svc, "_assemble_coach", return_value=fake_coach):
        result = svc._build_brief(for_date, user_id=user_id)

    assert "coach" in result, "service._build_brief must include 'coach' key when _assemble_coach returns a dict"
    assert result["coach"]["directive"] == fake_coach["directive"]
    assert result["coach"]["levers"] == fake_coach["levers"]


# ── AC4: service._build_brief omits coach when _assemble_coach returns None ───

def test_service_build_brief_omits_coach_when_none(svc):
    """AC4: When _assemble_coach returns None, 'coach' key is absent (not null)."""
    for_date = date(2026, 7, 17)
    user_id = "00000000-0000-0000-0000-000000000001"

    with patch.object(svc, "_get_plan_for_date", return_value={"planned": False, "sessions": []}), \
         patch.object(svc, "_assemble_form", return_value={"ctl": 0.0, "atl": 0.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "Neutral", "acwr": None}), \
         patch.object(svc, "_assemble_recent_wrap", return_value={"window_days": 14, "sessions_planned": 0, "sessions_completed": 0, "adherence": 0.0, "load_trend": 0.0, "highlights_md": ""}), \
         patch.object(svc, "_assemble_weight", return_value=dict(svc._NULL_WEIGHT_BLOCK)), \
         patch.object(svc, "_assemble_advisories", return_value=[]), \
         patch.object(svc, "_assemble_coach", return_value=None):
        result = svc._build_brief(for_date, user_id=user_id)

    assert "coach" not in result, "'coach' key must be absent (not None) when _assemble_coach returns None"


# ── AC6: CLI _build_brief signature compat ───────────────────────────────────

def test_cli_build_brief_accepts_four_positional_args(m):
    """AC6: m._build_brief accepts (for_date, worker_url, user_id, username)."""
    sig = inspect.signature(m._build_brief)
    params = list(sig.parameters.keys())
    assert len(params) >= 4, "_build_brief must accept for_date, worker_url, user_id, username"
    assert params[0] == "for_date"
