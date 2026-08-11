#!/usr/bin/env python3
"""Fast must-green contract suite (CI + local preflight).

The full unit gate allows ~350 known failures via BASELINE_FAILURES.txt. That is
correct for the broad suite, but it means structural FE/API edits often only
fail CI on the *first* push when they trip a static ratchet (#1602, #1603,
phase contracts, cache-bust).

This script runs a curated list of those ratchets and requires **zero**
failures — no baseline. Target: a few seconds locally, ~15–30s on CI.

Usage:
    .venv/bin/python scripts/run_contract_tests.py
    .venv/bin/python scripts/run_contract_tests.py --list
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUITE = REPO / "tests" / "CONTRACT_SUITE.txt"


def _paths() -> list[str]:
    lines = []
    for raw in SUITE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        p = REPO / line
        if not p.is_file():
            raise SystemExit(f"CONTRACT_SUITE entry missing: {line}")
        lines.append(str(p.relative_to(REPO)))
    if not lines:
        raise SystemExit(f"{SUITE} has no test paths")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--list",
        action="store_true",
        help="Print suite paths and exit",
    )
    ap.add_argument(
        "pytest_args",
        nargs="*",
        help="Extra args forwarded to pytest (after suite paths)",
    )
    args = ap.parse_args()
    paths = _paths()
    if args.list:
        print("\n".join(paths))
        return 0

    env = os.environ.copy()
    env.setdefault("TZ", "Asia/Bangkok")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *paths,
        "-q",
        "--tb=short",
        *args.pytest_args,
    ]
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=REPO, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
