"""The merge gate itself — issue #1606.

Before this, no PR in this repo ever ran an automated check. Every "verified"
claim came from a human reading a diff and hand-diffing baselines, and three
features were silently reverted by merges without anyone noticing: #1605 shipped
broken for 41 days because its 37-test regression module raised ImportError at
collection, which pytest reports as a top-level interruption rather than a
failure.

The gate is deliberately a ratchet rather than a green wall — 589 unit tests
still fail and pretending otherwise would mean either disabling the gate or
deleting untriaged tests. It enforces two things a PR must not do: add a
collection error, or add a failure.

This file tests the gate, because a gate nobody checks is the thing that let all
of this happen.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_test_regressions.py"
BASELINE = REPO / "tests" / "BASELINE_FAILURES.txt"
PYTEST_INI = REPO / "pytest.ini"
WORKFLOW = REPO / ".github" / "workflows" / "tests.yml"
CONFTEST = REPO / "tests" / "conftest.py"


def _run(output_text: str, tmp_path: Path) -> subprocess.CompletedProcess:
    f = tmp_path / "pytest-output.txt"
    f.write_text(output_text)
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(f)],
        capture_output=True, text=True, cwd=REPO, timeout=60,
    )


@pytest.fixture(scope="module")
def baseline_lines() -> list[str]:
    return [
        ln.strip() for ln in BASELINE.read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


# ── The gate blocks what it should ────────────────────────────────────────────

def test_new_failure_is_blocked(tmp_path, baseline_lines):
    out = _run("FAILED tests/test_invented__gate.py::test_nope - AssertionError\n", tmp_path)
    assert out.returncode == 1
    assert "NEW test failure" in out.stdout


def test_collection_error_is_blocked(tmp_path):
    """The single most important rule. A collection error deletes a whole module
    from the run, which is how three reverted features stayed invisible."""
    out = _run("ERROR tests/test_invented__gate.py\n", tmp_path)
    assert out.returncode == 1
    assert "collection error" in out.stdout


def test_a_collection_error_can_never_be_baselined(tmp_path):
    """--update-baseline records failures only. Baselining a collection error
    would re-hide exactly what this exists to surface.

    Runs against a throwaway baseline via TEST_BASELINE_PATH. The first version
    of this test wrote to the real one and emptied it — a test that mutates the
    artefact it is checking is worse than no test.
    """
    f = tmp_path / "out.txt"
    f.write_text("ERROR tests/test_invented__gate.py\n")
    env = {**os.environ, "TEST_BASELINE_PATH": str(tmp_path / "baseline.txt")}
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(f), "--update-baseline"],
        capture_output=True, text=True, cwd=REPO, timeout=60, env=env,
    )
    assert "never baselined" in out.stdout
    assert BASELINE.read_text().strip(), "the real baseline must be untouched"


# ── The gate allows what it should ────────────────────────────────────────────

def test_known_failures_pass(tmp_path, baseline_lines):
    body = "".join(f"FAILED {ln}\n" for ln in baseline_lines[:20])
    out = _run(body, tmp_path)
    assert out.returncode == 0, out.stdout


def test_fixing_a_baseline_failure_is_reported(tmp_path, baseline_lines):
    """Encouraged, and the script prints exactly what to delete so the ratchet
    tightens instead of drifting."""
    out = _run("", tmp_path)
    assert out.returncode == 0
    assert "now pass" in out.stdout


# ── Parsing ───────────────────────────────────────────────────────────────────

def test_parametrised_ids_with_spaces_round_trip(tmp_path):
    """Parametrised ids contain spaces and brackets. Parsing them with \\S+
    truncated every one into a different string, so the same test appeared
    simultaneously newly-failing and newly-fixed on every run."""
    nid = "tests/test_x.py::test_y[50.0-60.0--10.0-Productive (high load)]"
    out = _run(f"FAILED {nid} - AssertionError: nope\n", tmp_path)
    assert nid in out.stdout, "node id was truncated by the parser"


# ── Configuration ─────────────────────────────────────────────────────────────

def test_repo_has_its_own_pytest_config():
    """It had none, so it inherited ~/dev/pytest.ini from the sibling commander
    project — whose `timeout` setting did nothing because pytest-timeout was
    never installed."""
    assert PYTEST_INI.exists()


def test_timeout_is_configured_and_installed():
    """A hung test is the worst CI outcome: not red, never finishes."""
    assert "timeout" in PYTEST_INI.read_text()
    import pytest_timeout  # noqa: F401


def test_integration_marker_is_registered():
    assert "integration:" in PYTEST_INI.read_text()
    assert "--strict-markers" in PYTEST_INI.read_text()


def test_marker_is_applied_automatically_not_by_hand():
    """~400 files already declare their dependency by referencing a live service.
    Deriving the marker from that is more honest than 400 decorator edits, and
    cannot drift when someone adds a file."""
    src = CONFTEST.read_text()
    assert "pytest_collection_modifyitems" in src
    assert "_LIVE_SERVICE_MARKERS" in src


def test_ci_runs_the_unit_subset_only():
    wf = WORKFLOW.read_text()
    assert 'not integration' in wf
    assert "check_test_regressions.py" in wf


def test_ci_collect_step_does_not_tolerate_errors():
    """--continue-on-collection-errors here would reinstate the exact blindness
    this sprint exists to remove."""
    wf = WORKFLOW.read_text()
    collect = wf[wf.index("--collect-only") - 400: wf.index("--collect-only") + 100]
    assert "--continue-on-collection-errors" not in collect


def test_ci_pins_the_timezone():
    """The runner is UTC; this app is Asia/Bangkok. Without TZ every
    date-boundary assertion drifts by a day (#1600)."""
    assert "TZ: Asia/Bangkok" in WORKFLOW.read_text()


def test_test_dependencies_are_declared():
    """A fresh `uv pip install -r requirements.txt` used to produce a venv that
    could not run pytest — the suite only worked because someone's venv already
    had it."""
    dev = (REPO / "requirements-dev.txt").read_text()
    for pkg in ("pytest", "pytest-timeout", "responses"):
        assert pkg in dev


def test_production_requirements_exclude_the_test_runner():
    """Render installs requirements.txt into a 512MB instance with an OOM
    history (PR #1576)."""
    prod = (REPO / "requirements.txt").read_text()
    prod_pkgs = [
        ln.split("==")[0].strip()
        for ln in prod.splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    assert "pytest" not in prod_pkgs
