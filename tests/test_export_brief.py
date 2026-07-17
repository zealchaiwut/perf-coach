"""Tests for issue #1496: thin CLI wrapper validation for scripts/export_brief.py.

AC coverage (1496-specific):
- AC5: export_brief.py is a thin CLI wrapper (no assembly logic beyond orchestration)
- AC9: Pre-existing export_brief tests continue to pass (no modification)
- AC10: No urllib/requests/httpx import in the execution path after refactor
- UAT1: Script runs without worker process (worker_url is unused)
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import pathlib
import sys
import os
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_brief.py"


def _import_script():
    spec = importlib.util.spec_from_file_location("export_brief_1496", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _import_script()


# ── AC10: No HTTP calls in the export path ────────────────────────────────────

def test_no_http_calls_in_build_brief_path():
    """AC10: No HTTP client calls (urlopen, requests) in _build_brief or _fetch_plan.

    _fetch_plan is now a DB-backed bridge, not an HTTP call; _fetch_weight_status
    is removed.  Neither _build_brief nor _fetch_plan should contain urlopen calls.
    """
    mod = _import_script()
    import inspect
    for fn in (mod._build_brief, mod._fetch_plan):
        src = inspect.getsource(fn)
        assert "urlopen" not in src, f"{fn.__name__} still calls urlopen (HTTP)"
        assert "requests.get" not in src
        assert "httpx." not in src


def test_service_build_brief_no_http(m):
    """AC10: The service module (imported by export_brief) has no HTTP client calls."""
    import backend.services.daily_brief as svc_mod
    src = inspect.getsource(svc_mod)
    assert "urllib.request" not in src
    assert "import requests" not in src
    assert "import httpx" not in src


# ── AC5: thin CLI wrapper ────────────────────────────────────────────────────

def test_assembly_helpers_not_defined_in_script_source(m):
    """AC5: Heavy assembly helpers are not independently defined in export_brief.py.

    _build_brief is allowed as a thin local orchestrator for test-patch compat.
    The logic functions (_assemble_form, _assemble_recent_wrap, etc.) must come
    only from the service module.
    """
    import ast
    src = _SCRIPT.read_text()
    tree = ast.parse(src)
    defined_fns = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    # These functions must NOT be defined in the script — they belong in the service
    service_only_fns = {
        "_assemble_form", "_assemble_recent_wrap", "_assemble_advisories",
        "_compute_weight_advisory", "_load_interpretation", "_assemble_weight",
        "_build_highlights_md",
    }
    overlap = service_only_fns & defined_fns
    assert not overlap, f"These functions should live only in the service: {overlap}"


def test_script_imports_from_service(m):
    """AC5: export_brief imports build_brief or service helpers from backend.services.daily_brief."""
    src = _SCRIPT.read_text()
    assert "daily_brief" in src, "export_brief.py must import from backend.services.daily_brief"


# ── UAT1: Script works without worker process ────────────────────────────────

def test_main_succeeds_without_worker(m, tmp_path, capsys):
    """UAT1: main() exits 0 and writes JSON without any HTTP calls to the worker."""
    output = tmp_path / "brief.json"

    fake_brief = {
        "schema_version": 2,
        "for_date": "2026-07-17",
        "generated_at": "2026-07-17T08:00:00+07:00",
        "today": {
            "date": "2026-07-17",
            "session_type": None,
            "planned": False,
            "intensity": None,
            "duration_min": None,
            "notes": None,
        },
        "tomorrow": {
            "date": "2026-07-18",
            "session_type": None,
            "planned": False,
            "intensity": None,
            "duration_min": None,
            "notes": None,
        },
        "form": {
            "ctl": 40.0, "atl": 38.0, "tsb": 2.0,
            "ramp": 0.5, "flags": {}, "interpretation": "Neutral",
        },
        "recent_wrap": {
            "window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
            "adherence": 0.0, "load_trend": 0.0, "highlights_md": "Rest week.",
        },
        "weight": {
            "current_kg": None, "trend_7d": None, "trend_28d": None,
            "target_kg": None, "target_date": None, "pace_kg_per_week": None,
            "on_track": None, "projection_date": None,
        },
        "advisories": [],
        "actions": [],
    }

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--date", "2026-07-17",
        "--output", str(output),
        "--env", "uat",
    ]), patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}), \
       patch.object(m, "_resolve_user", return_value="uid"), \
       patch.object(m, "_build_brief", return_value=fake_brief):
        rc = m.main()

    assert rc == 0
    assert output.exists()
    captured = capsys.readouterr()
    assert "Brief written to" in captured.err


def test_stderr_contains_brief_written(m, tmp_path, capsys):
    """UAT1: Successful export prints 'Brief written to' on stderr."""
    output = tmp_path / "brief.json"
    fake_brief = {"schema_version": 2, "for_date": "2026-07-17"}

    with patch.object(sys, "argv", ["export_brief.py", "--output", str(output), "--env", "uat"]), \
         patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}), \
         patch.object(m, "_resolve_user", return_value="uid"), \
         patch.object(m, "_build_brief", return_value=fake_brief):
        m.main()

    captured = capsys.readouterr()
    assert "Brief written to" in captured.err


# ── Regression: _build_brief signature compat ───────────────────────────────

def test_build_brief_accepts_four_positional_args(m):
    """Compat: _build_brief still accepts (for_date, worker_url, user_id, username) signature."""
    import inspect
    sig = inspect.signature(m._build_brief)
    params = list(sig.parameters.keys())
    assert len(params) >= 4, "_build_brief must accept for_date, worker_url, user_id, username"
    assert params[0] == "for_date"
