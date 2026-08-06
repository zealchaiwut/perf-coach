"""Tests for issue #1714: Missing CONCURRENTLY on index creation for pre-existing
live tables in alembic migrations.

Acceptance criteria verified:
- AC1: r1f2g3h4i5j6 existing-table branch uses postgresql_concurrently=True for
       ix_weight_entries_user_entry_date.
- AC2: r1f2g3h4i5j6 wraps the concurrent create_index in an autocommit_block.
- AC3: 4ad3bf3fff49 uses CONCURRENTLY in the raw CREATE UNIQUE INDEX SQL.
- AC4: 4ad3bf3fff49 wraps the concurrent CREATE UNIQUE INDEX in an autocommit_block.
- AC5: z9n0o1p2q3r4 existing-table branch uses postgresql_concurrently=True for
       ix_habit_logs_habit_id_log_week_start.
- AC6: z9n0o1p2q3r4 wraps the concurrent create_index in an autocommit_block.
"""
import pathlib
import re

import pytest

_VERSIONS = pathlib.Path(__file__).parents[1] / "alembic" / "versions"

_WEIGHT_REVAMP = _VERSIONS / "r1f2g3h4i5j6_revamp_weight_entries_table.py"
_WEIGHT_PARTIAL = _VERSIONS / "4ad3bf3fff49_add_partial_unique_index_weight_null_.py"
_HABIT_LOGS = _VERSIONS / "z9n0o1p2q3r4_add_habit_logs_full_schema.py"


def _src(path: pathlib.Path) -> str:
    return path.read_text()


def _existing_table_branch(src: str, marker: str) -> str:
    """Return the source text of the else-path (existing-table branch) after `marker`."""
    idx = src.find(marker)
    assert idx != -1, f"Could not find marker {marker!r} in source"
    return src[idx:]


# ---------------------------------------------------------------------------
# AC1: r1f2g3h4i5j6 existing-table branch uses postgresql_concurrently=True
# ---------------------------------------------------------------------------


class TestWeightRevampConcurrentIndex:
    """AC1 + AC2: The existing-table index creation uses CONCURRENTLY."""

    def test_existing_table_branch_uses_postgresql_concurrently(self):
        """AC1: postgresql_concurrently=True present in the existing-table path."""
        src = _src(_WEIGHT_REVAMP)
        # The existing-table path follows the comment "Add index"
        tail = _existing_table_branch(src, "# ── Add index")
        assert "postgresql_concurrently" in tail, (
            "r1f2g3h4i5j6: create_index in existing-table branch must use "
            "postgresql_concurrently=True (issue #1714)."
        )

    def test_existing_table_branch_concurrently_is_true(self):
        """AC1: postgresql_concurrently is set to True (not False)."""
        src = _src(_WEIGHT_REVAMP)
        tail = _existing_table_branch(src, "# ── Add index")
        matches = re.findall(r"postgresql_concurrently\s*=\s*(\w+)", tail)
        assert matches, (
            "r1f2g3h4i5j6: no postgresql_concurrently=... assignment found in existing-table branch."
        )
        assert all(v == "True" for v in matches), (
            f"r1f2g3h4i5j6: postgresql_concurrently must be True, got {matches!r}."
        )

    def test_existing_table_branch_uses_autocommit_block(self):
        """AC2: autocommit_block context manager wraps concurrent index creation."""
        src = _src(_WEIGHT_REVAMP)
        tail = _existing_table_branch(src, "# ── Add index")
        assert "autocommit_block" in tail, (
            "r1f2g3h4i5j6: concurrent index creation in existing-table branch must be "
            "wrapped with op.get_context().autocommit_block() (issue #1714)."
        )


# ---------------------------------------------------------------------------
# AC3: 4ad3bf3fff49 uses CONCURRENTLY in raw SQL
# ---------------------------------------------------------------------------


class TestWeightPartialIndexConcurrent:
    """AC3 + AC4: The partial unique index is created with CONCURRENTLY."""

    def test_create_unique_index_uses_concurrently(self):
        """AC3: The raw SQL uses CREATE UNIQUE INDEX CONCURRENTLY."""
        src = _src(_WEIGHT_PARTIAL)
        assert "CONCURRENTLY" in src, (
            "4ad3bf3fff49: CREATE UNIQUE INDEX must include CONCURRENTLY keyword (issue #1714)."
        )

    def test_concurrently_immediately_follows_index_keyword(self):
        """AC3: CONCURRENTLY appears directly in the CREATE UNIQUE INDEX statement."""
        src = _src(_WEIGHT_PARTIAL)
        assert re.search(r"CREATE\s+UNIQUE\s+INDEX\s+CONCURRENTLY", src), (
            "4ad3bf3fff49: must use 'CREATE UNIQUE INDEX CONCURRENTLY ...' form (issue #1714)."
        )

    def test_uses_autocommit_block(self):
        """AC4: autocommit_block context manager wraps the concurrent SQL execute."""
        src = _src(_WEIGHT_PARTIAL)
        assert "autocommit_block" in src, (
            "4ad3bf3fff49: concurrent CREATE UNIQUE INDEX must be wrapped with "
            "op.get_context().autocommit_block() (issue #1714)."
        )


# ---------------------------------------------------------------------------
# AC5: z9n0o1p2q3r4 existing-table branch uses postgresql_concurrently=True
# ---------------------------------------------------------------------------


class TestHabitLogsConcurrentIndex:
    """AC5 + AC6: The existing-table index creation uses CONCURRENTLY."""

    def test_existing_table_branch_uses_postgresql_concurrently(self):
        """AC5: postgresql_concurrently=True present in the existing-table path."""
        src = _src(_HABIT_LOGS)
        tail = _existing_table_branch(src, "# 5. Composite index")
        assert "postgresql_concurrently" in tail, (
            "z9n0o1p2q3r4: create_index in existing-table branch must use "
            "postgresql_concurrently=True (issue #1714)."
        )

    def test_existing_table_branch_concurrently_is_true(self):
        """AC5: postgresql_concurrently is set to True (not False)."""
        src = _src(_HABIT_LOGS)
        tail = _existing_table_branch(src, "# 5. Composite index")
        matches = re.findall(r"postgresql_concurrently\s*=\s*(\w+)", tail)
        assert matches, (
            "z9n0o1p2q3r4: no postgresql_concurrently=... assignment found in existing-table branch."
        )
        assert all(v == "True" for v in matches), (
            f"z9n0o1p2q3r4: postgresql_concurrently must be True, got {matches!r}."
        )

    def test_existing_table_branch_uses_autocommit_block(self):
        """AC6: autocommit_block context manager wraps concurrent index creation."""
        src = _src(_HABIT_LOGS)
        tail = _existing_table_branch(src, "# 5. Composite index")
        assert "autocommit_block" in tail, (
            "z9n0o1p2q3r4: concurrent index creation in existing-table branch must be "
            "wrapped with op.get_context().autocommit_block() (issue #1714)."
        )
