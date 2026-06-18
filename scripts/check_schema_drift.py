#!/usr/bin/env python3
"""Fail loudly when the live DB is missing columns the models declare.

Alembic tracks *which* migration the DB claims to be at, but if a stamp ever
gets ahead of its DDL (e.g. a DB stamped to a revision whose add_column never
actually ran), `alembic upgrade head` is a no-op and the app only discovers the
missing column at request time as a 500 (UndefinedColumn).

This preflight closes that gap: it compares each SQLAlchemy model's columns
against the live database and exits non-zero, listing the drift, so a deploy
aborts before serving traffic instead of after.

Run after `alembic upgrade head`:

    python3 scripts/check_schema_drift.py

Exit codes: 0 = schema matches models, 1 = drift (missing table/column),
2 = could not connect / inspect.
"""
import os
import sys

# Allow running as a bare script (python scripts/check_schema_drift.py): the
# repo root, not scripts/, must be importable so `backend` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect

# Importing models registers every table on Base.metadata.
from backend.db import engine
from backend.models import Base


def main() -> int:
    try:
        insp = inspect(engine)
        existing_tables = set(insp.get_table_names())
    except Exception as exc:  # connection / inspection failure
        print(f"[schema-drift] could not inspect database: {exc}", file=sys.stderr)
        return 2

    drift: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            drift.append(f"missing table: {table_name}")
            continue
        db_cols = {c["name"] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name not in db_cols:
                drift.append(f"{table_name}.{col.name} declared in model but missing in DB")

    if drift:
        print("[schema-drift] DB does not match models:", file=sys.stderr)
        for line in drift:
            print(f"  - {line}", file=sys.stderr)
        print(
            "[schema-drift] alembic may be stamped ahead of its DDL. "
            "Stamp down to the prior revision and re-run `alembic upgrade head`.",
            file=sys.stderr,
        )
        return 1

    print("[schema-drift] OK — DB matches models.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
