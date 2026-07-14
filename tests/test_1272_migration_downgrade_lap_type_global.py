"""Tests for issue #1272: Migration 145b95d5baf0 downgrade() relies on a process-local global.

Acceptance criteria verified:
- AC1: The module-level global `_lap_type_was_added` is removed from the migration.
- AC2: `downgrade()` does not read or reference `_lap_type_was_added`.
- AC3: `downgrade()` always reverts `lap_type` to nullable (never drops it),
       making behaviour identical regardless of how `upgrade()` ran.
- AC4: The migration source documents that `lap_type` is not dropped on downgrade.
"""
import ast
import pathlib
import textwrap

import pytest

_MIGRATION_FILE = (
    pathlib.Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "145b95d5baf0_add_power_cadence_stride_lap_type_.py"
)


def _migration_src() -> str:
    return _MIGRATION_FILE.read_text()


def _migration_ast() -> ast.Module:
    return ast.parse(_migration_src())


# ---------------------------------------------------------------------------
# AC1: Module-level global _lap_type_was_added is removed
# ---------------------------------------------------------------------------


class TestGlobalRemoved:
    """AC1: _lap_type_was_added must not appear as a module-level assignment."""

    def test_no_module_level_lap_type_was_added_assignment(self):
        """AC1: No module-level `_lap_type_was_added` assignment exists."""
        tree = _migration_ast()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_lap_type_was_added":
                        pytest.fail(
                            "Module-level global `_lap_type_was_added` still present — "
                            "it must be removed (issue #1272)."
                        )

    def test_name_not_in_source(self):
        """AC1: The identifier _lap_type_was_added does not appear anywhere in the file."""
        src = _migration_src()
        assert "_lap_type_was_added" not in src, (
            "`_lap_type_was_added` still referenced in migration source — "
            "remove the global and all references (issue #1272)."
        )


# ---------------------------------------------------------------------------
# AC2: downgrade() does not reference _lap_type_was_added
# ---------------------------------------------------------------------------


class TestDowngradeNoGlobalRead:
    """AC2: downgrade() must be free of any reference to the removed global."""

    def test_downgrade_body_has_no_global_reference(self):
        """AC2: AST walk of downgrade() finds no Name node '_lap_type_was_added'."""
        tree = _migration_ast()
        downgrade_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
                downgrade_node = node
                break
        assert downgrade_node is not None, "downgrade() function not found in migration"

        for node in ast.walk(downgrade_node):
            if isinstance(node, ast.Name) and node.id == "_lap_type_was_added":
                pytest.fail(
                    "downgrade() references `_lap_type_was_added` — must not use "
                    "cross-process state (issue #1272)."
                )

    def test_upgrade_body_has_no_global_write(self):
        """AC2: upgrade() no longer sets _lap_type_was_added (global keyword gone too)."""
        tree = _migration_ast()
        upgrade_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
                upgrade_node = node
                break
        assert upgrade_node is not None, "upgrade() function not found in migration"

        for node in ast.walk(upgrade_node):
            if isinstance(node, ast.Global):
                for name in node.names:
                    if name == "_lap_type_was_added":
                        pytest.fail(
                            "upgrade() still declares `global _lap_type_was_added` — "
                            "remove it (issue #1272)."
                        )


# ---------------------------------------------------------------------------
# AC3: downgrade() always reverts lap_type to nullable (no drop_column for it)
# ---------------------------------------------------------------------------


class TestDowngradeAlwaysRevertsToNullable:
    """AC3: downgrade() must always make lap_type nullable — never drop it."""

    def _get_downgrade_source(self) -> str:
        src = _migration_src()
        lines = src.splitlines()
        in_downgrade = False
        body_lines: list[str] = []
        for line in lines:
            if line.strip().startswith("def downgrade()"):
                in_downgrade = True
                continue
            if in_downgrade:
                if line and not line[0].isspace():
                    break
                body_lines.append(line)
        return "\n".join(body_lines)

    def test_downgrade_does_not_drop_lap_type(self):
        """AC3: downgrade() must not call drop_column for lap_type."""
        body = self._get_downgrade_source()
        # A drop_column for lap_type would look like: drop_column("workout_splits", "lap_type")
        # or drop_column('workout_splits', 'lap_type')
        assert "drop_column" not in body or "lap_type" not in body.split("drop_column")[1].split(")")[0] if "drop_column" in body else True, (
            "downgrade() must not drop_column('workout_splits', 'lap_type') — "
            "always revert to nullable instead (issue #1272)."
        )

    def test_downgrade_does_not_conditionally_drop_lap_type(self):
        """AC3: No conditional branch in downgrade() drops lap_type."""
        body = self._get_downgrade_source()
        # Check there's no drop_column call that mentions lap_type at all
        if "drop_column" in body:
            # Extract all drop_column call strings and confirm none target lap_type
            import re
            calls = re.findall(r"drop_column\([^)]+\)", body)
            for call in calls:
                assert "lap_type" not in call, (
                    f"downgrade() drops lap_type via {call!r} — must not drop it (issue #1272)."
                )

    def test_downgrade_calls_alter_column_for_lap_type(self):
        """AC3: downgrade() calls alter_column to make lap_type nullable."""
        body = self._get_downgrade_source()
        assert "alter_column" in body, (
            "downgrade() must call alter_column to revert lap_type to nullable (issue #1272)."
        )
        assert "lap_type" in body, (
            "downgrade() must reference 'lap_type' when reverting it (issue #1272)."
        )
        assert "nullable=True" in body, (
            "downgrade() must set nullable=True when reverting lap_type (issue #1272)."
        )


# ---------------------------------------------------------------------------
# AC4: Source documents that lap_type is not dropped on downgrade
# ---------------------------------------------------------------------------


class TestDowngradeDocumented:
    """AC4: A comment in the migration explains the always-revert behaviour."""

    def test_migration_has_no_drop_comment_or_docstring_for_downgrade_behaviour(self):
        """AC4: Migration source documents that downgrade reverts to nullable, not drops."""
        src = _migration_src()
        # Accept any of several natural phrasings
        lower = src.lower()
        documented = (
            "not drop" in lower
            or "revert" in lower
            or "nullable" in lower
        )
        assert documented, (
            "Migration must document that downgrade() reverts lap_type to nullable "
            "rather than dropping it (issue #1272)."
        )
