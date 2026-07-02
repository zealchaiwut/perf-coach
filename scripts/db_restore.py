"""Restore a pg_dump backup into the environment's database.

DESTRUCTIVE: runs pg_restore with --clean --if-exists, dropping and recreating
objects before loading. Restore is deliberately CLI-only (not exposed on the
admin page). You must pass --yes to actually run.

DB selection matches every other script (``ENVIRONMENT`` picks
``DATABASE_URL_UAT`` / ``DATABASE_URL_PRD``; a single ``DATABASE_URL`` wins).

Usage::

    ENVIRONMENT=uat python scripts/db_restore.py <backup.dump> --yes

Exit codes:

    0  — success
    1  — any failure (file missing, pg_restore missing, confirmation missing, error)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import database_url, environment
from backend.services.db_backup import BackupError, restore_backup


def main() -> None:
    ap = argparse.ArgumentParser(description="pg_restore a backup into the current DB")
    ap.add_argument("backup", help="path to a .dump file from db_backup.py")
    ap.add_argument(
        "--yes",
        action="store_true",
        help="required: confirm you want to OVERWRITE the target database",
    )
    args = ap.parse_args()

    if not database_url:
        print("No database_url configured (set ENVIRONMENT + DATABASE_URL_*)", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        print(
            f"Refusing to restore into '{environment}' without --yes. "
            f"This OVERWRITES the target database.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        restore_backup(database_url, args.backup)
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"Restore complete into '{environment}' from {args.backup}")


if __name__ == "__main__":
    main()
