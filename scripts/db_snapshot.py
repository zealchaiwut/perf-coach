#!/usr/bin/env python3
"""Dump a gzipped SQL snapshot from DATABASE_URL to snapshots/.

Usage:
    python scripts/db_snapshot.py
"""

import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime
from urllib.parse import urlparse


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def parse_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise ValueError(f"Unsupported scheme: {parsed.scheme!r}")
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "dbname": parsed.path.lstrip("/"),
        "user": parsed.username or "",
        "password": parsed.password or "",
    }


def main() -> int:
    load_env()

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL is not set or empty", file=sys.stderr)
        return 1

    try:
        parts = parse_url(url)
    except Exception as exc:
        print(f"ERROR: Could not parse DATABASE_URL: {exc}", file=sys.stderr)
        return 1

    if not parts["dbname"]:
        print("ERROR: DATABASE_URL has no database name", file=sys.stderr)
        return 1

    if not shutil.which("pg_dump"):
        print("ERROR: pg_dump not found in PATH — install postgresql-client", file=sys.stderr)
        return 1

    os.makedirs("snapshots", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"snapshots/{parts['dbname']}-{timestamp}.sql.gz"

    print(f"Dumping {parts['dbname']} from {parts['host']}...", file=sys.stderr)

    env = os.environ.copy()
    if parts["password"]:
        env["PGPASSWORD"] = parts["password"]

    cmd = [
        "pg_dump",
        "--no-owner",
        "--no-acl",
        "-h", parts["host"],
        "-p", parts["port"],
        "-U", parts["user"],
        parts["dbname"],
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            env=env,
        )
    except Exception as exc:
        print(f"ERROR: Failed to run pg_dump: {exc}", file=sys.stderr)
        return 1

    if proc.returncode != 0:
        print(f"ERROR: pg_dump failed:\n{proc.stderr.decode()}", file=sys.stderr)
        return 1

    try:
        with gzip.open(filename, "wb") as f:
            f.write(proc.stdout)
    except Exception as exc:
        print(f"ERROR: Failed to write {filename}: {exc}", file=sys.stderr)
        if os.path.exists(filename):
            os.remove(filename)
        return 1

    size_kb = os.path.getsize(filename) // 1024
    print(f"Wrote {filename} ({size_kb} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
