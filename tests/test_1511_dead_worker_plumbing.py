"""Tests for issue #1511: Remove dead worker_url plumbing from export_brief.py.

Acceptance criteria:
  AC1  WORKER_DEFAULT_URL constant is removed from scripts/export_brief.py.
  AC2  main() no longer resolves worker_url from WORKER_BASE_URL env var or
       WORKER_DEFAULT_URL fallback — the resolution line is gone.
  AC3  main() does not pass a live worker_url variable to _build_brief calls
       (worker_url threading in main() is dropped; only None or nothing is passed).
  AC4  --worker-url CLI flag is retained for backward-compatibility (the flag
       is accepted without error) but its value is not threaded internally.
  AC5  _fetch_plan function accepts worker_url as first parameter but does NOT
       make any HTTP call — the parameter is accepted but ignored (existing compat).
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import os
import pathlib
import sys
from unittest.mock import patch

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_brief.py"


def _import_module():
    spec = importlib.util.spec_from_file_location("export_brief_1511", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _import_module()


# ── AC1: WORKER_DEFAULT_URL constant removed ──────────────────────────────────

def test_worker_default_url_constant_removed(m):
    """AC1: WORKER_DEFAULT_URL must not exist as a module-level attribute."""
    assert not hasattr(m, "WORKER_DEFAULT_URL"), (
        "WORKER_DEFAULT_URL constant should have been removed — it is dead plumbing "
        "since the export path no longer calls the worker."
    )


def test_worker_default_url_not_in_source():
    """AC1: WORKER_DEFAULT_URL string must not appear in the script source."""
    src = _SCRIPT.read_text()
    assert "WORKER_DEFAULT_URL" not in src, (
        "WORKER_DEFAULT_URL still present in export_brief.py source"
    )


# ── AC2: worker_url resolution removed from main() ────────────────────────────

def test_worker_base_url_getenv_not_in_main_source():
    """AC2: main() must not call os.getenv('WORKER_BASE_URL') for worker_url resolution.

    After the cleanup the WORKER_BASE_URL env var lookup must be absent from the
    main() function body — the export path has no reason to consult it.
    """
    src = _SCRIPT.read_text()
    tree = ast.parse(src)
    main_fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    assert main_fn is not None, "main() function not found in export_brief.py"

    main_src = ast.get_source_segment(src, main_fn) or ""
    assert "WORKER_BASE_URL" not in main_src, (
        "main() still references WORKER_BASE_URL — dead env-var lookup should be removed"
    )


def test_worker_url_variable_not_assigned_in_main_source():
    """AC2: The 'worker_url = ...' resolution line must be absent from main()."""
    src = _SCRIPT.read_text()
    tree = ast.parse(src)
    main_fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    assert main_fn is not None
    main_src = ast.get_source_segment(src, main_fn) or ""
    # The dead resolution was: worker_url = args.worker_url or os.getenv("WORKER_BASE_URL") or WORKER_DEFAULT_URL
    # After cleanup, no 'worker_url =' assignment should exist in main()
    assert "worker_url =" not in main_src and "worker_url=" not in main_src, (
        "main() still has a 'worker_url = ...' assignment — dead internal resolution should be removed"
    )


# ── AC3: main() does not thread worker_url into _build_brief calls ────────────

def test_build_brief_not_called_with_live_worker_url(m, tmp_path, capsys):
    """AC3: _build_brief calls in main() must not pass a live worker_url variable.

    We confirm this by intercepting the call and checking that the second
    argument (worker_url positional) is None, or that _build_brief is called
    with fewer than 2 positional args.
    """
    import json
    output = tmp_path / "brief.json"
    fake_brief = {"schema_version": 3, "for_date": "2026-08-04"}
    captured_args = []

    def spy_build_brief(*args, **kwargs):
        captured_args.append((args, kwargs))
        return fake_brief

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--date", "2026-08-04",
        "--output", str(output),
        "--env", "uat",
    ]), patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}), \
       patch.object(m, "_resolve_user", return_value="uid"), \
       patch.object(m, "_build_brief", side_effect=spy_build_brief):
        rc = m.main()

    assert rc == 0
    assert len(captured_args) == 1
    args_passed, kwargs_passed = captured_args[0]

    # If worker_url is the 2nd positional arg, it must be None (not a URL string)
    if len(args_passed) >= 2:
        worker_url_val = args_passed[1]
        assert worker_url_val is None, (
            f"main() is passing a live worker_url ({worker_url_val!r}) to _build_brief — "
            "dead internal threading should be removed"
        )
    # If worker_url is in kwargs, it must be None or absent
    if "worker_url" in kwargs_passed:
        assert kwargs_passed["worker_url"] is None, (
            f"main() is passing worker_url={kwargs_passed['worker_url']!r} — must be None or absent"
        )


def test_build_brief_dry_run_not_called_with_live_worker_url(m, tmp_path, capsys):
    """AC3: _build_brief call in --dry-run path also must not pass live worker_url."""
    captured_args = []

    def spy_build_brief(*args, **kwargs):
        captured_args.append((args, kwargs))
        return {"schema_version": 3, "for_date": "2026-08-04"}

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--dry-run",
        "--date", "2026-08-04",
        "--env", "uat",
    ]), patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}), \
       patch.object(m, "_resolve_user", return_value="uid"), \
       patch.object(m, "_build_brief", side_effect=spy_build_brief):
        rc = m.main()

    assert rc == 0
    assert len(captured_args) == 1
    args_passed, kwargs_passed = captured_args[0]

    if len(args_passed) >= 2:
        assert args_passed[1] is None, (
            f"--dry-run path passes live worker_url ({args_passed[1]!r}) to _build_brief"
        )
    if "worker_url" in kwargs_passed:
        assert kwargs_passed["worker_url"] is None


# ── AC4: --worker-url flag retained for backward-compatibility ─────────────────

def test_worker_url_flag_accepted_without_error(m, tmp_path, capsys):
    """AC4: --worker-url CLI flag is accepted without error (backward-compat)."""
    output = tmp_path / "brief.json"
    fake_brief = {"schema_version": 3, "for_date": "2026-08-04"}

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--worker-url", "http://some-old-caller:9100",
        "--output", str(output),
        "--env", "uat",
    ]), patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}), \
       patch.object(m, "_resolve_user", return_value="uid"), \
       patch.object(m, "_build_brief", return_value=fake_brief):
        rc = m.main()

    assert rc == 0, "--worker-url flag must be accepted without error for backward-compat"


# ── AC5: _fetch_plan still accepts worker_url but makes no HTTP call ───────────

def test_fetch_plan_accepts_worker_url_but_no_http(m):
    """AC5: _fetch_plan signature still accepts worker_url but has no HTTP code."""
    sig = inspect.signature(m._fetch_plan)
    params = list(sig.parameters.keys())
    assert params[0] == "worker_url" or "worker_url" in params, (
        "_fetch_plan must still accept worker_url for compat with existing test patches"
    )

    src = inspect.getsource(m._fetch_plan)
    assert "urlopen" not in src
    assert "requests.get" not in src
    assert "httpx." not in src
    assert "http://" not in src, (
        "_fetch_plan source must not contain a hardcoded HTTP URL — no HTTP calls"
    )
