#!/usr/bin/env python3
"""Repair alembic_version rows that reference removed merge revisions.

UAT deploys occasionally stamp ahead of (or reference) a merge migration file that
is no longer in the repo graph. ``alembic upgrade head`` then fails with::

    Can't locate revision identified by '<id>'

This script rewrites known orphan stamps to a live revision so the normal
upgrade can proceed. Each replacement is chosen from applied DDL, not blindly
rolled back to an old ancestor.

Usage (called from deploy-start.sh before ``alembic upgrade head``)::

    python scripts/repair_orphan_alembic_stamps.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Merge node removed when ba386/978bc were reparented onto sprint-70/71 heads.
_ORPHAN_382389 = "382389e81d09"
# One live parent of the reparented sprint-75 branches; safe when both sprint-70
# and sprint-71 heads were already merged on the DB.
_FALLBACK_AFTER_382389 = "d915ffcb4c0c"


def _engine():
    from sqlalchemy import create_engine

    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_UAT")
    if not url:
        print(
            "[repair-orphan-stamps] skip: DATABASE_URL not set",
            file=sys.stderr,
        )
        return None
    return create_engine(url)


def _current_version(conn) -> str | None:
    from sqlalchemy import inspect, text

    if not inspect(conn).has_table("alembic_version"):
        return None
    row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
    return row[0] if row else None


def _rewrite_version(conn, new_revision: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text("UPDATE alembic_version SET version_num = :rev"),
        {"rev": new_revision},
    )
    conn.commit()


def main() -> int:
    engine = _engine()
    if engine is None:
        return 0

    with engine.connect() as conn:
        current = _current_version(conn)
        if current != _ORPHAN_382389:
            return 0

        print(
            f"[repair-orphan-stamps] rewriting orphan stamp "
            f"{_ORPHAN_382389} -> {_FALLBACK_AFTER_382389}",
            file=sys.stderr,
        )
        _rewrite_version(conn, _FALLBACK_AFTER_382389)
    return 0


if __name__ == "__main__":
    sys.exit(main())
