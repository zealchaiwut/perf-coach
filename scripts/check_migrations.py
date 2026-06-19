#!/usr/bin/env python3
"""Offline Alembic sanity check — no database required.

Catches the two failure modes that have repeatedly broken UAT/PRD deploys
(`alembic upgrade head` dies with "Multiple head revisions are present" /
"Revision X is present more than once"):

  1. Duplicate revision ids — two migration files declaring the same id.
  2. Multiple heads — the revision graph has more than one head.

Reads the version files only (via Alembic's ScriptDirectory), so it runs in
CI without Postgres. Exits non-zero on any problem.

Usage:
    python3 scripts/check_migrations.py
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSIONS_DIR = REPO_ROOT / "alembic" / "versions"

# Matches `revision = "abc"` and `revision: str = "abc"` at line start, but NOT
# `down_revision = ...` (anchored on `revision` at the start of the line).
_REVISION_RE = re.compile(r"^revision(?:\s*:\s*\w+)?\s*=\s*[\"']([^\"']+)[\"']", re.M)


def find_duplicate_revisions() -> dict[str, list[str]]:
    """Return {revision_id: [file, ...]} for any id declared in >1 file."""
    by_id: dict[str, list[str]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        text = path.read_text()
        for rev in _REVISION_RE.findall(text):
            by_id.setdefault(rev, []).append(path.name)
    return {rev: files for rev, files in by_id.items() if len(files) > 1}


def find_heads() -> list[str]:
    """Return the list of head revision ids via Alembic's own graph parser."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    return list(script.get_heads())


def main() -> int:
    problems: list[str] = []

    dupes = find_duplicate_revisions()
    if dupes:
        for rev, files in sorted(dupes.items()):
            problems.append(
                f"duplicate revision id {rev!r} declared in: {', '.join(files)}"
            )

    heads = find_heads()
    if len(heads) != 1:
        problems.append(
            f"expected exactly 1 head, found {len(heads)}: {', '.join(heads) or '(none)'}\n"
            f"    reconcile with: alembic merge heads -m \"merge_heads\""
        )

    if problems:
        print("Alembic migration check FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"Alembic migration check OK — single head: {heads[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
