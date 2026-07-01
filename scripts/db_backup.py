"""Create a pg_dump backup of the environment's database.

Uses the same DB-selection logic as every other script (``ENVIRONMENT`` picks
``DATABASE_URL_UAT`` / ``DATABASE_URL_PRD``; a single ``DATABASE_URL`` wins if
set). Output is Postgres custom format (``-Fc``), restorable with
``scripts/db_restore.py``.

Usage::

    ENVIRONMENT=uat python scripts/db_backup.py [--out path.dump]

Exit codes:

    0  — success
    1  — any failure (pg_dump missing, no url, dump error)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import database_url, environment
from backend.services.db_backup import BackupError, default_backup_name, make_backup


def main() -> None:
    ap = argparse.ArgumentParser(description="pg_dump the current environment's DB")
    ap.add_argument("--out", help="output file path (default: ./<auto-name>.dump)")
    args = ap.parse_args()

    if not database_url:
        print("No database_url configured (set ENVIRONMENT + DATABASE_URL_*)", file=sys.stderr)
        sys.exit(1)

    out = args.out or default_backup_name(environment)
    try:
        make_backup(database_url, out)
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"Backup written: {out}")


if __name__ == "__main__":
    main()
