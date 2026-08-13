"""Smoke for scripts/run_contract_tests.py + CONTRACT_SUITE.txt."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "run_contract_tests.py"
SUITE = REPO / "tests" / "CONTRACT_SUITE.txt"


def test_contract_suite_file_lists_existing_modules():
    assert SUITE.is_file()
    paths = []
    for raw in SUITE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            paths.append(line)
            assert (REPO / line).is_file(), line
    assert paths, "CONTRACT_SUITE.txt must list at least one module"


def test_run_contract_tests_list_exits_zero():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--list"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "test_frontend_shared_lib__1603.py" in r.stdout
    assert "test_reachability_gate__1602.py" in r.stdout
