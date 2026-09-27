#!/usr/bin/env python3
"""CLI entrypoint for the Deploy tab's "Copy PRD → UAT" action.

Invoked by Commander's data_copy_service.py (postgres_rowcopy strategy) with
this repo's own .env sourced — Commander doesn't know this project's schema,
so the actual copy logic lives here, in the project's own repo. See
backend/services/user_copy.py::copy_all_users_to_uat for what it does.

Usage:
    python scripts/copy_prd_to_uat.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.user_copy import UserCopyError, copy_all_users_to_uat  # noqa: E402


def main() -> int:
    try:
        result = copy_all_users_to_uat()
    except UserCopyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Copied {result['users_copied']} user(s).")
    for table, n in result["copied"].items():
        print(f"  {table}: {n} row(s)")

    failures = result["encryption_failures"]
    if failures:
        print(
            f"WARNING: {len(failures)} encrypted field(s) could not be re-keyed "
            "(set to NULL — that integration will need reconnecting in UAT):",
            file=sys.stderr,
        )
        for f in failures:
            print(f"  {f['table']}.{f['column']} (row {f['row_id']}): {f['reason']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
