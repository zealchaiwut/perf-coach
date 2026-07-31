#!/usr/bin/env python3
"""Fail when a PR adds a NEW test failure, or any collection error.

Why not just "the suite must be green": it isn't, and pretending otherwise would
mean either disabling the gate or deleting 589 tests nobody has triaged. Both
are worse than measuring the delta.

So the gate is:

1. **Zero collection errors.** Non-negotiable. A collection error silently
   removes an entire module from the run — pytest reports it as a top-level
   interruption rather than a failure. Three features have been silently
   reverted by merges in this repo and every one stayed invisible for weeks
   because its regression test wasn't running: #1605 shipped broken for 41 days
   that way.

2. **No new failures** versus ``tests/BASELINE_FAILURES.txt``. A PR may not make
   things worse. Fixing a baseline failure is welcome and the file should shrink
   — this script prints what to remove.

The baseline is a ratchet, not a permanent allowance. It only ever gets shorter.

Usage:
    python scripts/check_test_regressions.py <pytest-output-file>
    python scripts/check_test_regressions.py <pytest-output-file> --update-baseline

``--update-baseline`` rewrites the file using THIS script's parser, so the
generator and the checker can never disagree about how a node id is spelled.
Parametrised ids contain spaces and brackets; parsing them with a shell one-liner
produced a baseline that never matched what the checker read.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Overridable so the gate's own tests can exercise --update-baseline against a
# throwaway file. Without this they mutate the real baseline, which is how the
# first version of those tests silently emptied it.
BASELINE = Path(
    os.environ.get("TEST_BASELINE_PATH") or (REPO / "tests" / "BASELINE_FAILURES.txt")
)

# Capture the whole node id, not \S+ — parametrised ids contain spaces inside
# their brackets ("[50.0-60.0--10.0-Productive (high load)]"), and a greedy
# non-space match truncates them into a different string every run. That made
# every such test look simultaneously newly-failing and newly-fixed.
_FAILED_RE = re.compile(r"^FAILED (.+?)(?: - .*)?$")
_ERROR_RE = re.compile(r"^ERROR (.+?)(?: - .*)?$")


def _parse(output: str) -> tuple[set[str], set[str]]:
    """Return (failures, collection_errors).

    pytest prints two different things as ERROR and they are NOT equivalent:

        ERROR tests/foo.py                 <- COLLECTION error: the module could
                                              not be imported, so every test in
                                              it silently left the suite. Never
                                              baselineable; this is the failure
                                              mode that hid #1605 for 41 days.

        ERROR tests/foo.py::test_bar       <- a single test errored in setup or
                                              teardown. One test, loud, no worse
                                              than a failure — so it is tracked
                                              alongside failures.

    The presence of "::" is what separates them. Conflating the two made 16
    ordinary fixture errors look like 16 modules vanishing.
    """
    failures, collection_errors = set(), set()
    for line in output.splitlines():
        m = _FAILED_RE.match(line)
        if m:
            failures.add(m.group(1).strip())
            continue
        m = _ERROR_RE.match(line)
        if m:
            node = m.group(1).strip()
            (failures if "::" in node else collection_errors).add(node)
    return failures, collection_errors


_HEADER = """\
# Known-failing unit tests, as of the S6 test-suite work (issue #1606).
#
# A RATCHET, not a permanent allowance: a PR may not add to this list, and it
# should only ever get shorter. Regenerate after fixing some with:
#   python scripts/check_test_regressions.py <pytest-output> --update-baseline
#
# These are NOT environmental — the integration split is handled by the
# `integration` marker, applied automatically in tests/conftest.py. Everything
# here fails without any live service, so each line is a stale test asserting
# deleted behaviour, or a real bug nobody has triaged yet.
"""


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    update = "--update-baseline" in sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        return 2

    output = Path(args[0]).read_text()
    failures, errors = _parse(output)

    if update:
        BASELINE.write_text(_HEADER + "\n".join(sorted(failures)) + "\n")
        print(f"baseline updated: {len(failures)} known failures")
        if errors:
            print(f"WARNING: {len(errors)} collection error(s) not recorded — "
                  "those must be fixed, never baselined")
        return 0
    baseline = {
        line.strip()
        for line in BASELINE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

    exit_code = 0

    if errors:
        print(f"::error::{len(errors)} collection error(s) — each one silently "
              "removes a whole module from the suite")
        for e in sorted(errors):
            print(f"  {e}")
        exit_code = 1

    new_failures = failures - baseline
    if new_failures:
        print(f"::error::{len(new_failures)} NEW test failure(s) not in the baseline")
        for f in sorted(new_failures):
            print(f"  {f}")
        exit_code = 1

    fixed = baseline - failures
    if fixed:
        print(f"{len(fixed)} baseline failure(s) now pass — remove them from "
              f"{BASELINE.relative_to(REPO)}:")
        for f in sorted(fixed):
            print(f"  {f}")

    if exit_code == 0:
        print(f"OK — {len(failures)} failures, all known; 0 collection errors.")
        if not fixed:
            print(f"Baseline unchanged at {len(baseline)}.")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
