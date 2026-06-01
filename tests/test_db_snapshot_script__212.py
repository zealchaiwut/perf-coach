"""Tests for issue #212: manual database snapshot script with gzip output."""
import gzip
import importlib.util
import os
import pathlib
import re
import subprocess
import sys
from unittest.mock import MagicMock, call, patch

import pytest

REPO = pathlib.Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "db_snapshot.py"
GITIGNORE = REPO / ".gitignore"
README = REPO / "scripts" / "README.md"

SCRIPT_TEXT = SCRIPT.read_text() if SCRIPT.exists() else ""
GITIGNORE_TEXT = GITIGNORE.read_text() if GITIGNORE.exists() else ""
README_TEXT = README.read_text() if README.exists() else ""


# ── AC-1: script exists ───────────────────────────────────────────────────────

def test_ac1_script_exists():
    assert SCRIPT.exists(), "scripts/db_snapshot.py must exist"


def test_ac1_script_is_python():
    assert SCRIPT_TEXT.startswith("#!/usr/bin/env python") or "import" in SCRIPT_TEXT, \
        "scripts/db_snapshot.py must be a Python script"


# ── AC-2: reads DATABASE_URL ──────────────────────────────────────────────────

def test_ac2_reads_database_url_from_env():
    assert "DATABASE_URL" in SCRIPT_TEXT, \
        "script must reference DATABASE_URL"


def test_ac2_loads_dotenv_or_os_environ():
    has_dotenv = "dotenv" in SCRIPT_TEXT or "load_dotenv" in SCRIPT_TEXT
    has_os_environ = "os.environ" in SCRIPT_TEXT or "os.getenv" in SCRIPT_TEXT
    assert has_dotenv or has_os_environ, \
        "script must read DATABASE_URL via dotenv or os.environ"


# ── AC-3: URL parsing ─────────────────────────────────────────────────────────

def test_ac3_parses_url_components():
    assert "host" in SCRIPT_TEXT, "script must extract host from DATABASE_URL"
    assert "port" in SCRIPT_TEXT, "script must extract port from DATABASE_URL"
    assert "dbname" in SCRIPT_TEXT or "database" in SCRIPT_TEXT, \
        "script must extract dbname from DATABASE_URL"
    assert "user" in SCRIPT_TEXT, "script must extract user from DATABASE_URL"
    assert "password" in SCRIPT_TEXT, "script must extract password from DATABASE_URL"


def test_ac3_uses_urlparse():
    assert "urlparse" in SCRIPT_TEXT, \
        "script must use urlparse to parse DATABASE_URL"


# ── AC-4: pg_dump flags ────────────────────────────────────────────────────────

def test_ac4_pg_dump_no_owner_flag():
    assert "--no-owner" in SCRIPT_TEXT, \
        "pg_dump must be invoked with --no-owner flag"


def test_ac4_pg_dump_no_acl_flag():
    assert "--no-acl" in SCRIPT_TEXT, \
        "pg_dump must be invoked with --no-acl flag"


# ── AC-5: output file naming ──────────────────────────────────────────────────

def test_ac5_output_path_in_snapshots_dir():
    assert "snapshots/" in SCRIPT_TEXT or "snapshots" in SCRIPT_TEXT, \
        "script must write output to snapshots/ directory"


def test_ac5_output_is_gzipped():
    assert ".sql.gz" in SCRIPT_TEXT, \
        "output file must have .sql.gz extension"


def test_ac5_timestamp_format():
    assert "strftime" in SCRIPT_TEXT, \
        "script must use strftime to generate timestamp"
    assert "%Y%m%d" in SCRIPT_TEXT and "%H%M%S" in SCRIPT_TEXT, \
        "timestamp format must be YYYYMMDD-HHMMSS"


# ── AC-6: auto-create snapshots/ ──────────────────────────────────────────────

def test_ac6_makedirs_for_snapshots():
    assert "makedirs" in SCRIPT_TEXT or "mkdir" in SCRIPT_TEXT, \
        "script must auto-create snapshots/ directory"


# ── AC-7 & AC-8: stderr messages ─────────────────────────────────────────────

def test_ac7_stderr_dumping_message():
    assert "Dumping" in SCRIPT_TEXT, \
        "script must print 'Dumping {dbname} from {host}...' to stderr"
    assert "stderr" in SCRIPT_TEXT, \
        "Dumping message must go to stderr"


def test_ac8_stderr_wrote_message():
    assert "Wrote" in SCRIPT_TEXT, \
        "script must print 'Wrote {filename} ({size_kb} KB)' to stderr"


# ── AC-9: exit codes ──────────────────────────────────────────────────────────

def test_ac9_exit_0_on_success():
    assert "return 0" in SCRIPT_TEXT or "sys.exit(0)" in SCRIPT_TEXT or \
           "sys.exit(main())" in SCRIPT_TEXT, \
        "script must exit with code 0 on success"


def test_ac9_exit_1_on_failure():
    assert "return 1" in SCRIPT_TEXT or "sys.exit(1)" in SCRIPT_TEXT, \
        "script must exit with code 1 on any failure"


# ── AC-10: missing pg_dump error ─────────────────────────────────────────────

def test_ac10_detects_missing_pg_dump():
    has_which = "shutil.which" in SCRIPT_TEXT or "which(" in SCRIPT_TEXT
    has_file_error = "FileNotFoundError" in SCRIPT_TEXT or "not found" in SCRIPT_TEXT.lower()
    assert has_which or has_file_error, \
        "script must detect and report when pg_dump is not found in PATH"


def test_ac10_pg_dump_error_message_is_clear():
    lower = SCRIPT_TEXT.lower()
    assert "pg_dump" in lower, \
        "error message must reference pg_dump when binary is not found"


# ── AC-11: missing/malformed DATABASE_URL ────────────────────────────────────

def test_ac11_handles_missing_database_url():
    assert "DATABASE_URL" in SCRIPT_TEXT, \
        "script must check for missing DATABASE_URL"
    assert "not set" in SCRIPT_TEXT or "empty" in SCRIPT_TEXT or \
           "missing" in SCRIPT_TEXT.lower() or "not url" in SCRIPT_TEXT.lower() or \
           "is not set" in SCRIPT_TEXT, \
        "script must print clear error when DATABASE_URL is missing"


def test_ac11_handles_malformed_database_url():
    has_try_except = "except" in SCRIPT_TEXT and "urlparse" in SCRIPT_TEXT
    has_scheme_check = "scheme" in SCRIPT_TEXT or "postgres" in SCRIPT_TEXT
    assert has_try_except or has_scheme_check, \
        "script must handle malformed DATABASE_URL with a clear error"


# ── AC-12: .gitignore ─────────────────────────────────────────────────────────

def test_ac12_snapshots_in_gitignore():
    assert "snapshots/" in GITIGNORE_TEXT or "snapshots" in GITIGNORE_TEXT, \
        "snapshots/ must be in .gitignore"


# ── AC-13: scripts/README.md ─────────────────────────────────────────────────

def test_ac13_readme_exists():
    assert README.exists(), "scripts/README.md must exist"


def test_ac13_readme_documents_db_snapshot():
    assert "db_snapshot.py" in README_TEXT, \
        "scripts/README.md must document db_snapshot.py"


def test_ac13_readme_documents_usage_command():
    assert "python scripts/db_snapshot.py" in README_TEXT or \
           "python3 scripts/db_snapshot.py" in README_TEXT, \
        "scripts/README.md must show the usage command"


def test_ac13_readme_mentions_pg_dump_prerequisite():
    lower = README_TEXT.lower()
    assert "pg_dump" in lower or "postgresql-client" in lower or "postgresql" in lower, \
        "scripts/README.md must mention pg_dump as a prerequisite"


def test_ac13_readme_mentions_env_prerequisite():
    lower = README_TEXT.lower()
    assert ".env" in lower or "database_url" in lower.upper() or "DATABASE_URL" in README_TEXT, \
        "scripts/README.md must mention .env / DATABASE_URL as a prerequisite"


# ── Functional: script logic via mocks ────────────────────────────────────────

def _load_module():
    spec = importlib.util.spec_from_file_location("db_snapshot", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_success_path(tmp_path, monkeypatch):
    """Happy path: pg_dump succeeds → gzipped file written, exit 0."""
    mod = _load_module()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.com:5432/mydb")
    monkeypatch.chdir(tmp_path)

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = b"-- SQL DUMP\n"
    fake_proc.stderr = b""

    with patch("shutil.which", return_value="/usr/bin/pg_dump"), \
         patch("subprocess.run", return_value=fake_proc):
        rc = mod.main()

    assert rc == 0, "main() must return 0 on success"
    gz_files = list((tmp_path / "snapshots").glob("mydb-*.sql.gz"))
    assert len(gz_files) == 1, "exactly one .sql.gz file must be created"
    with gzip.open(gz_files[0], "rb") as f:
        assert f.read() == b"-- SQL DUMP\n"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_missing_database_url(tmp_path, monkeypatch, capsys):
    """Missing DATABASE_URL → exit 1 with error to stderr."""
    mod = _load_module()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = mod.main()

    assert rc == 1, "main() must return 1 when DATABASE_URL is missing"
    captured = capsys.readouterr()
    assert "DATABASE_URL" in captured.err, \
        "error message must reference DATABASE_URL"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_pg_dump_not_found(tmp_path, monkeypatch, capsys):
    """pg_dump not in PATH → exit 1 with clear error."""
    mod = _load_module()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.com:5432/mydb")
    monkeypatch.chdir(tmp_path)

    with patch("shutil.which", return_value=None):
        rc = mod.main()

    assert rc == 1, "main() must return 1 when pg_dump is not found"
    captured = capsys.readouterr()
    assert "pg_dump" in captured.err, \
        "error message must mention pg_dump"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_pg_dump_invoked_with_correct_flags(tmp_path, monkeypatch):
    """pg_dump must be called with --no-owner and --no-acl."""
    mod = _load_module()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.com:5432/mydb")
    monkeypatch.chdir(tmp_path)

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = b"-- SQL\n"
    fake_proc.stderr = b""

    with patch("shutil.which", return_value="/usr/bin/pg_dump"), \
         patch("subprocess.run", return_value=fake_proc) as mock_run:
        mod.main()

    args = mock_run.call_args[0][0]
    assert "--no-owner" in args, "pg_dump must be called with --no-owner"
    assert "--no-acl" in args, "pg_dump must be called with --no-acl"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_pg_dump_failure_returns_1(tmp_path, monkeypatch, capsys):
    """pg_dump non-zero exit → main() returns 1."""
    mod = _load_module()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.com:5432/mydb")
    monkeypatch.chdir(tmp_path)

    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.stdout = b""
    fake_proc.stderr = b"connection refused"

    with patch("shutil.which", return_value="/usr/bin/pg_dump"), \
         patch("subprocess.run", return_value=fake_proc):
        rc = mod.main()

    assert rc == 1, "main() must return 1 when pg_dump exits non-zero"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_snapshots_dir_auto_created(tmp_path, monkeypatch):
    """snapshots/ directory must be created if absent."""
    mod = _load_module()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.com:5432/mydb")
    monkeypatch.chdir(tmp_path)

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = b"-- SQL\n"
    fake_proc.stderr = b""

    assert not (tmp_path / "snapshots").exists()

    with patch("shutil.which", return_value="/usr/bin/pg_dump"), \
         patch("subprocess.run", return_value=fake_proc):
        mod.main()

    assert (tmp_path / "snapshots").is_dir(), \
        "snapshots/ directory must be created automatically"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_stderr_messages(tmp_path, monkeypatch, capsys):
    """Correct stderr lines on success."""
    mod = _load_module()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.com:5432/mydb")
    monkeypatch.chdir(tmp_path)

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = b"-- SQL\n"
    fake_proc.stderr = b""

    with patch("shutil.which", return_value="/usr/bin/pg_dump"), \
         patch("subprocess.run", return_value=fake_proc):
        mod.main()

    captured = capsys.readouterr()
    assert "Dumping mydb from db.example.com" in captured.err, \
        "stderr must contain 'Dumping {dbname} from {host}...'"
    assert "Wrote" in captured.err and "mydb-" in captured.err and ".sql.gz" in captured.err, \
        "stderr must contain 'Wrote snapshots/{db}-{timestamp}.sql.gz ({N} KB)'"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_malformed_url_returns_1(tmp_path, monkeypatch, capsys):
    """Malformed DATABASE_URL (non-postgres scheme) → exit 1."""
    mod = _load_module()
    monkeypatch.setenv("DATABASE_URL", "mysql://user:pass@host/db")
    monkeypatch.chdir(tmp_path)

    rc = mod.main()

    assert rc == 1, "main() must return 1 for non-postgres DATABASE_URL"
    captured = capsys.readouterr()
    assert captured.err.strip(), "stderr must contain an error message for malformed URL"
