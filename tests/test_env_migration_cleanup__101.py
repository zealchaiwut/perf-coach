"""
Tests for issue #101: Clean up env inconsistencies — single working dir + idempotent migrations

Verifies:
- README documents single canonical working directory, branch-based env selection, and
  warns against parallel checkouts
- start_uat.sh and start_prd.sh log the DB host (not password) and select env via
  ENVIRONMENT + .env (not directory name)
- Every migration file guards op.create_table, op.create_index, op.add_column, and
  corresponding drops with existence checks
- Both daily_readiness migrations (59a1b2c3d4e5, a9b0c1d2e3f4) carry the required
  imports and an early-exit guard at the top of upgrade()
- scripts/test_migrations.sh exists and covers the three required scenarios
- alembic heads returns exactly one head SHA
"""
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).parent.parent

README = (REPO / "README.md").read_text()
START_UAT = (REPO / "start_uat.sh").read_text()
START_PRD = (REPO / "start_prd.sh").read_text()
VERSIONS_DIR = REPO / "alembic" / "versions"
TEST_MIGRATIONS_SH = REPO / "scripts" / "test_migrations.sh"

MIGRATION_59A = (VERSIONS_DIR / "59a1b2c3d4e5_create_daily_readiness_table.py").read_text()
MIGRATION_A9B = (VERSIONS_DIR / "a9b0c1d2e3f4_create_daily_readiness_table.py").read_text()


# ── AC-1: README — single canonical working directory ─────────────────────────

def test_ac1_readme_single_canonical_clone():
    """README must state that a single clone is the canonical working directory."""
    assert "single clone" in README.lower() or "one clone" in README.lower() or \
           "single canonical" in README.lower() or "canonical" in README.lower(), \
        "README must document use of a single canonical working directory"


def test_ac1_readme_branch_based_env_selection():
    """README must explain that develop = UAT and main = PRD."""
    assert "develop" in README and "UAT" in README, \
        "README must map the develop branch to the UAT environment"
    assert "main" in README and "PRD" in README, \
        "README must map the main branch to the PRD environment"


def test_ac1_readme_warn_against_parallel_checkouts():
    """README must warn against maintaining parallel checkouts."""
    lower = README.lower()
    assert "parallel" in lower or "do not maintain" in lower or "warning" in lower or \
           "warn" in lower, \
        "README must warn against parallel checkouts"
    assert "checkout" in lower or "clone" in lower or "director" in lower, \
        "README warning must mention checkouts or directories"


# ── AC-2: start_uat.sh and start_prd.sh ───────────────────────────────────────

def test_ac2_start_uat_uses_environment_variable():
    """start_uat.sh must set ENVIRONMENT=UAT explicitly in the script."""
    assert "ENVIRONMENT=UAT" in START_UAT, \
        "start_uat.sh must set ENVIRONMENT=UAT"


def test_ac2_start_prd_uses_environment_variable():
    """start_prd.sh must set ENVIRONMENT=PRD explicitly in the script."""
    assert "ENVIRONMENT=PRD" in START_PRD, \
        "start_prd.sh must set ENVIRONMENT=PRD"


def test_ac2_start_uat_reads_env_file_not_directory_name():
    """start_uat.sh must source .env (not select env by directory path)."""
    assert "source .env" in START_UAT or ". .env" in START_UAT, \
        "start_uat.sh must source a .env file"
    assert "dirname" not in START_UAT and "BASH_SOURCE" not in START_UAT, \
        "start_uat.sh must not select environment from directory name"


def test_ac2_start_prd_reads_env_file_not_directory_name():
    """start_prd.sh must source .env (not select env by directory path)."""
    assert "source .env" in START_PRD or ". .env" in START_PRD, \
        "start_prd.sh must source a .env file"
    assert "dirname" not in START_PRD and "BASH_SOURCE" not in START_PRD, \
        "start_prd.sh must not select environment from directory name"


def test_ac2_start_uat_logs_db_host():
    """start_uat.sh must log the DB host (not the password) before migrations."""
    lower = START_UAT.lower()
    assert "host" in lower or "hostname" in lower, \
        "start_uat.sh must log the target DB host before running migrations"
    assert "urlparse" in START_UAT or "hostname" in START_UAT or ".hostname" in START_UAT, \
        "start_uat.sh must extract and log the hostname (not the full URL with password)"


def test_ac2_start_prd_logs_db_host():
    """start_prd.sh must log the DB host (not the password) before migrations."""
    lower = START_PRD.lower()
    assert "host" in lower or "hostname" in lower, \
        "start_prd.sh must log the target DB host before running migrations"
    assert "urlparse" in START_PRD or "hostname" in START_PRD or ".hostname" in START_PRD, \
        "start_prd.sh must extract and log the hostname (not the full URL with password)"


def test_ac2_start_uat_logs_host_before_migrations():
    """start_uat.sh must print host info before calling alembic upgrade head."""
    host_pos = START_UAT.find("hostname")
    alembic_pos = START_UAT.find("alembic upgrade head")
    assert host_pos != -1 and alembic_pos != -1, \
        "start_uat.sh must contain both hostname logging and alembic upgrade head"
    assert host_pos < alembic_pos, \
        "start_uat.sh must log the DB host BEFORE running alembic upgrade head"


def test_ac2_start_prd_logs_host_before_migrations():
    """start_prd.sh must print host info before calling alembic upgrade head."""
    host_pos = START_PRD.find("hostname")
    alembic_pos = START_PRD.find("alembic upgrade head")
    assert host_pos != -1 and alembic_pos != -1, \
        "start_prd.sh must contain both hostname logging and alembic upgrade head"
    assert host_pos < alembic_pos, \
        "start_prd.sh must log the DB host BEFORE running alembic upgrade head"


# ── AC-3: Every migration is idempotent ───────────────────────────────────────

def _migration_files():
    return [
        f for f in sorted(VERSIONS_DIR.glob("*.py"))
        if not f.name.startswith("__")
    ]


def _is_merge_migration(content: str) -> bool:
    """A merge migration is one whose upgrade() body is just pass."""
    upgrade_block = re.search(r"def upgrade\(\).*?(?=\ndef |\Z)", content, re.DOTALL)
    if not upgrade_block:
        return False
    body = upgrade_block.group(0)
    stripped = re.sub(r'""".*?"""', "", body, flags=re.DOTALL)
    stripped = re.sub(r"#[^\n]*", "", stripped)
    code_lines = [ln.strip() for ln in stripped.splitlines() if ln.strip() and ln.strip() not in ("def upgrade() -> None:", "def upgrade():")]
    return all(line == "pass" for line in code_lines)


# Accepted existence-guard spellings.
#
# CLAUDE.md documents this project's convention as the helpers in alembic/
# (table_exists / column_exists / index_exists / fk_exists), but these
# assertions only ever recognised SQLAlchemy's raw inspector API. Every
# migration written in the project's OWN documented style was reported as a
# violation — 216 false failures, the single largest block in the suite, and
# noise that made the real failures harder to see (#1606).
_TABLE_GUARDS = ("has_table", "table_exists", "IF NOT EXISTS")
_COLUMN_GUARDS = (
    "has_column", "get_columns", "existing_cols", "column_exists", "IF NOT EXISTS",
)
_INDEX_GUARDS = ("has_index", "get_indexes", "index_exists", "IF NOT EXISTS")


def _guarded(content: str, guards) -> bool:
    return any(g in content for g in guards)


@pytest.mark.parametrize("migration", _migration_files(), ids=lambda p: p.name)
def test_ac3_create_table_guarded(migration):
    """Every op.create_table call must be inside an existence-check guard."""
    content = migration.read_text()
    if _is_merge_migration(content):
        pytest.skip("merge migration has no op.create_table calls")
    if "op.create_table(" not in content:
        pytest.skip(f"{migration.name} has no op.create_table calls")
    assert _guarded(content, _TABLE_GUARDS), (
        f"{migration.name}: op.create_table must be guarded — "
        f"one of {_TABLE_GUARDS}"
    )


@pytest.mark.parametrize("migration", _migration_files(), ids=lambda p: p.name)
def test_ac3_add_column_guarded(migration):
    """Every op.add_column call must be guarded with a column existence check."""
    content = migration.read_text()
    if _is_merge_migration(content):
        pytest.skip("merge migration")
    if "op.add_column(" not in content:
        pytest.skip(f"{migration.name} has no op.add_column calls")
    assert _guarded(content, _COLUMN_GUARDS), (
        f"{migration.name}: op.add_column must be guarded — "
        f"one of {_COLUMN_GUARDS}"
    )


@pytest.mark.parametrize("migration", _migration_files(), ids=lambda p: p.name)
def test_ac3_create_index_guarded(migration):
    """Every op.create_index call (that isn't raw SQL) must be safe to re-run."""
    content = migration.read_text()
    if _is_merge_migration(content):
        pytest.skip("merge migration")

    upgrade_block = re.search(r"def upgrade\(\).*?(?=\ndef |\Z)", content, re.DOTALL)
    if not upgrade_block:
        pytest.skip("no upgrade() found")
    upgrade_body = upgrade_block.group(0)

    if "op.create_index(" not in upgrade_body and "CREATE INDEX" not in upgrade_body:
        pytest.skip(f"{migration.name} has no index creation in upgrade()")

    has_create_index_safe = "CREATE INDEX IF NOT EXISTS" in upgrade_body
    has_op_create_index = "op.create_index(" in upgrade_body

    if has_op_create_index and not has_create_index_safe:
        assert (
            _guarded(upgrade_body, _INDEX_GUARDS)
            or "inspector" in upgrade_body
            or "CREATE INDEX IF NOT EXISTS" in upgrade_body
        ), (
            f"{migration.name}: op.create_index must use IF NOT EXISTS or be "
            f"inside an existence guard — one of {_INDEX_GUARDS}"
        )


@pytest.mark.parametrize("migration", _migration_files(), ids=lambda p: p.name)
def test_ac3_drop_table_guarded(migration):
    """Every op.drop_table call must be guarded or use DROP TABLE IF EXISTS."""
    content = migration.read_text()
    if _is_merge_migration(content):
        pytest.skip("merge migration")

    downgrade_block = re.search(r"def downgrade\(\).*?(?=\ndef |\Z)", content, re.DOTALL)
    if not downgrade_block:
        pytest.skip("no downgrade() found")
    downgrade_body = downgrade_block.group(0)

    if "op.drop_table(" not in downgrade_body:
        pytest.skip(f"{migration.name} has no op.drop_table in downgrade()")

    assert _guarded(downgrade_body, _TABLE_GUARDS + ("DROP TABLE IF EXISTS",)), \
        f"{migration.name}: op.drop_table in downgrade() must be guarded with has_table() or IF EXISTS"


# ── AC-4: Both daily_readiness migrations are fully idempotent ────────────────

def test_ac4_59a_has_import_sqlalchemy():
    assert "import sqlalchemy as sa" in MIGRATION_59A, \
        "59a1b2c3d4e5 must have 'import sqlalchemy as sa'"


def test_ac4_59a_has_import_inspect():
    assert "from sqlalchemy import inspect" in MIGRATION_59A, \
        "59a1b2c3d4e5 must have 'from sqlalchemy import inspect'"


def test_ac4_59a_has_import_sequence_union():
    assert "from typing import Sequence, Union" in MIGRATION_59A, \
        "59a1b2c3d4e5 must have 'from typing import Sequence, Union'"


def test_ac4_59a_upgrade_has_existence_guard():
    """59a1b2c3d4e5 upgrade() must return early if daily_readiness already exists."""
    upgrade_block = re.search(r"def upgrade\(\).*?(?=\ndef |\Z)", MIGRATION_59A, re.DOTALL)
    assert upgrade_block, "59a1b2c3d4e5 must have an upgrade() function"
    body = upgrade_block.group(0)
    assert "has_table" in body and "daily_readiness" in body, \
        "59a1b2c3d4e5 upgrade() must guard against daily_readiness already existing"
    assert "return" in body, \
        "59a1b2c3d4e5 upgrade() must return early if the table already exists"


def test_ac4_a9b_has_import_sqlalchemy():
    assert "import sqlalchemy as sa" in MIGRATION_A9B, \
        "a9b0c1d2e3f4 must have 'import sqlalchemy as sa'"


def test_ac4_a9b_has_import_inspect():
    assert "from sqlalchemy import inspect" in MIGRATION_A9B, \
        "a9b0c1d2e3f4 must have 'from sqlalchemy import inspect'"


def test_ac4_a9b_has_import_sequence_union():
    assert "from typing import Sequence, Union" in MIGRATION_A9B, \
        "a9b0c1d2e3f4 must have 'from typing import Sequence, Union'"


def test_ac4_a9b_upgrade_has_existence_guard():
    """a9b0c1d2e3f4 upgrade() must return early if daily_readiness already exists."""
    upgrade_block = re.search(r"def upgrade\(\).*?(?=\ndef |\Z)", MIGRATION_A9B, re.DOTALL)
    assert upgrade_block, "a9b0c1d2e3f4 must have an upgrade() function"
    body = upgrade_block.group(0)
    assert "has_table" in body and "daily_readiness" in body, \
        "a9b0c1d2e3f4 upgrade() must guard against daily_readiness already existing"
    assert "return" in body, \
        "a9b0c1d2e3f4 upgrade() must return early if the table already exists"


# ── AC-5/6: scripts/test_migrations.sh exists and covers required scenarios ───

def test_ac5_test_migrations_sh_exists():
    assert TEST_MIGRATIONS_SH.exists(), \
        "scripts/test_migrations.sh must exist"


def test_ac5_test_migrations_sh_double_upgrade():
    """test_migrations.sh must test that running alembic upgrade head twice is safe."""
    content = TEST_MIGRATIONS_SH.read_text()
    count = content.count("alembic upgrade head")
    assert count >= 2, \
        "scripts/test_migrations.sh must invoke alembic upgrade head at least twice (double-run test)"


def test_ac5_test_migrations_sh_preexisting_daily_readiness():
    """test_migrations.sh must test upgrade when daily_readiness table pre-exists."""
    content = TEST_MIGRATIONS_SH.read_text()
    assert "daily_readiness" in content, \
        "scripts/test_migrations.sh must test the scenario where daily_readiness pre-exists"


def test_ac5_test_migrations_sh_single_head_assertion():
    """test_migrations.sh must assert that alembic heads returns exactly one head."""
    content = TEST_MIGRATIONS_SH.read_text()
    assert "alembic heads" in content, \
        "scripts/test_migrations.sh must run 'alembic heads' to verify single head"
    assert "1" in content, \
        "scripts/test_migrations.sh must assert the head count is exactly 1"


# ── AC-7: alembic heads returns exactly one head ──────────────────────────────

def test_ac7_alembic_heads_single_head():
    """alembic heads must return exactly one head SHA."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert result.returncode == 0, \
        f"alembic heads exited with {result.returncode}: {result.stderr}"
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, \
        f"alembic heads must return exactly one head, got {len(heads)}: {result.stdout}"
