"""Tests for issue #1386: verdict_history migration downgrade() is a no-op.

Acceptance criteria verified:
- AC1: downgrade() is not a bare pass (actually contains substantive logic).
- AC2: downgrade() drops the ix_verdict_history_user_date index, guarded by index_exists.
- AC3: downgrade() drops the verdict_history table, guarded by table_exists.
- AC4: Drop order is correct — index dropped before table.
"""
import ast
import pathlib
import re

import pytest

_MIGRATION_FILE = (
    pathlib.Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "bf3b956dd2e0_add_verdict_history_table.py"
)


def _src() -> str:
    return _MIGRATION_FILE.read_text()


def _ast() -> ast.Module:
    return ast.parse(_src())


def _downgrade_src() -> str:
    src = _src()
    lines = src.splitlines()
    in_dg = False
    body: list[str] = []
    for line in lines:
        if line.strip().startswith("def downgrade"):
            in_dg = True
            continue
        if in_dg:
            if line and not line[0].isspace():
                break
            body.append(line)
    return "\n".join(body)


# ---------------------------------------------------------------------------
# AC1: downgrade() is not a bare pass
# ---------------------------------------------------------------------------

class TestDowngradeNotNoOp:
    """AC1: downgrade() must contain substantive logic, not just pass."""

    def test_downgrade_body_is_not_just_pass(self):
        """AC1: downgrade() body contains more than a bare `pass` statement."""
        body = _downgrade_src()
        stripped = "\n".join(
            ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")
        )
        assert stripped.strip() != "pass", (
            "downgrade() is a bare pass — must implement actual rollback logic (issue #1386)."
        )

    def test_downgrade_not_empty(self):
        """AC1: downgrade() body is non-empty."""
        body = _downgrade_src()
        non_empty = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        assert non_empty, "downgrade() has no substantive lines (issue #1386)."


# ---------------------------------------------------------------------------
# AC2: index is dropped, guarded by index_exists
# ---------------------------------------------------------------------------

class TestDowngradeDropsIndex:
    """AC2: downgrade() drops ix_verdict_history_user_date guarded by index_exists."""

    def test_downgrade_references_index_exists(self):
        """AC2: downgrade() calls index_exists before dropping the index."""
        body = _downgrade_src()
        assert "index_exists" in body, (
            "downgrade() must guard the index drop with index_exists(...) (issue #1386)."
        )

    def test_downgrade_drops_verdict_history_index(self):
        """AC2: downgrade() drops the ix_verdict_history_user_date index."""
        body = _downgrade_src()
        assert "ix_verdict_history_user_date" in body, (
            "downgrade() must drop 'ix_verdict_history_user_date' (issue #1386)."
        )
        assert "drop_index" in body or "DROP INDEX" in body.upper(), (
            "downgrade() must issue a drop for the index (issue #1386)."
        )


# ---------------------------------------------------------------------------
# AC3: table is dropped, guarded by table_exists
# ---------------------------------------------------------------------------

class TestDowngradeDropsTable:
    """AC3: downgrade() drops verdict_history table guarded by table_exists."""

    def test_downgrade_references_table_exists(self):
        """AC3: downgrade() calls table_exists before dropping the table."""
        body = _downgrade_src()
        assert "table_exists" in body, (
            "downgrade() must guard the table drop with table_exists(...) (issue #1386)."
        )

    def test_downgrade_drops_verdict_history_table(self):
        """AC3: downgrade() drops the verdict_history table."""
        body = _downgrade_src()
        assert "verdict_history" in body, (
            "downgrade() must reference 'verdict_history' (issue #1386)."
        )
        assert "drop_table" in body, (
            "downgrade() must call drop_table for 'verdict_history' (issue #1386)."
        )


# ---------------------------------------------------------------------------
# AC4: index is dropped before table
# ---------------------------------------------------------------------------

class TestDowngradeDropOrder:
    """AC4: Index must be dropped before the table in downgrade()."""

    def test_index_drop_before_table_drop(self):
        """AC4: ix_verdict_history_user_date reference appears before drop_table."""
        body = _downgrade_src()
        idx_pos = body.find("ix_verdict_history_user_date")
        tbl_pos = body.find("drop_table")
        assert idx_pos != -1, "downgrade() must reference the index name (issue #1386)."
        assert tbl_pos != -1, "downgrade() must call drop_table (issue #1386)."
        assert idx_pos < tbl_pos, (
            "downgrade() must drop the index before the table (issue #1386)."
        )
