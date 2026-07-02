"""pg_dump / pg_restore helpers for the admin DB-backup feature.

Backups use the Postgres custom format (-Fc): compact, and restorable with
--clean so a restore fully replaces existing objects. The admin page only
CREATES backups (download); restore is intentionally CLI-only (see
scripts/db_restore.py) so there is no destructive button behind the admin
secret word.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone


class BackupError(RuntimeError):
    """Expected, user-facing backup/restore failure."""


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise BackupError(
            f"'{name}' not found on PATH. Install the Postgres client tools "
            f"(e.g. `brew install libpq` or the postgresql client package)."
        )
    return path


def default_backup_name(env_label: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(ch for ch in env_label if ch.isalnum() or ch in "-_") or "db"
    return f"perfcoach-{safe}-{stamp}.dump"


def make_backup(database_url: str, out_path: str) -> str:
    """Dump database_url to out_path (custom format). Returns out_path."""
    pg_dump = _require_tool("pg_dump")
    cmd = [
        pg_dump,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        out_path,
        database_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BackupError(f"pg_dump failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return out_path


def restore_backup(database_url: str, in_path: str) -> None:
    """Restore in_path into database_url, replacing existing objects (--clean)."""
    if not os.path.isfile(in_path):
        raise BackupError(f"Backup file not found: {in_path}")
    pg_restore = _require_tool("pg_restore")
    cmd = [
        pg_restore,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        database_url,
        in_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # pg_restore can exit non-zero on ignorable warnings; surface stderr only on
    # a hard failure (no rows restored / connection error).
    if proc.returncode != 0 and "errors ignored on restore" not in (proc.stderr or ""):
        raise BackupError(f"pg_restore failed: {proc.stderr.strip() or proc.stdout.strip()}")
