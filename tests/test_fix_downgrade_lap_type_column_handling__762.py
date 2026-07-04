"""Tests for issue #762: Fix downgrade() lap_type column handling in migration 145b95d5baf0.

Acceptance criteria verified:
- AC1: _lap_type_was_added flag is a module-level boolean, set True in upgrade()
       when the column is created from scratch.
- AC2: downgrade() calls op.drop_column('workout_splits', 'lap_type') when flag is True.
- AC3: downgrade() calls op.alter_column(..., nullable=True) when flag is False
       (column pre-existed from an earlier migration).
- AC4: Simulated upgrade→downgrade on a fresh DB leaves no lap_type column.
- AC5: Simulated upgrade→downgrade when lap_type pre-existed leaves it present and nullable.
"""
import ast
import importlib.util
import pathlib
import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest

_MIGRATION_PATH = (
    pathlib.Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "145b95d5baf0_add_power_cadence_stride_lap_type_.py"
)
_SRC = _MIGRATION_PATH.read_text()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_fn(name: str):
    """Return the AST FunctionDef node for a named function in the migration."""
    tree = ast.parse(_SRC)
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name),
        None,
    )
    assert fn is not None, f"Function '{name}' not found in migration source"
    return fn


def _load_migration(column_exists_side_effect=None, constraint_exists_side_effect=None):
    """Load the migration module in isolation with mocked dependencies.

    Returns (module, mock_op) so tests can inspect calls made to op.
    """
    mod_name = "_mig_762_test"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    # Provide a mock 'helpers' module so the migration's import resolves.
    mock_helpers = types.ModuleType("helpers")
    mock_helpers.column_exists = MagicMock(side_effect=column_exists_side_effect)
    sys.modules["helpers"] = mock_helpers

    # Provide a mock 'alembic.op' so op.* calls don't hit a real DB.
    mock_op = MagicMock()
    mock_alembic = types.ModuleType("alembic")
    mock_alembic.op = mock_op
    sys.modules.setdefault("alembic", mock_alembic)

    spec = importlib.util.spec_from_file_location(mod_name, _MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Patch module-level references.
    mod.op = mock_op
    mod.column_exists = mock_helpers.column_exists

    if constraint_exists_side_effect is not None:
        mod._constraint_exists = MagicMock(side_effect=constraint_exists_side_effect)
    else:
        mod._constraint_exists = MagicMock(return_value=False)

    mod._column_is_nullable = MagicMock(return_value=True)

    return mod, mock_op


# ---------------------------------------------------------------------------
# AC1: Module-level flag _lap_type_was_added exists and is a bool
# ---------------------------------------------------------------------------


def test_flag_defined_at_module_level():
    """AC1: _lap_type_was_added is assigned at module scope (not inside a function).

    Handles both plain assignment (x = False) and annotated assignment (x: bool = False).
    """
    tree = ast.parse(_SRC)
    names = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.append(node.target.id)
    assert "_lap_type_was_added" in names, (
        "_lap_type_was_added must be a module-level assignment in the migration"
    )


def test_flag_initialized_to_false():
    """AC1: _lap_type_was_added is initialized to False at module level."""
    tree = ast.parse(_SRC)
    for node in ast.iter_child_nodes(tree):
        # Plain assignment: _lap_type_was_added = False
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_lap_type_was_added":
                    assert isinstance(node.value, ast.Constant) and node.value.value is False, (
                        "_lap_type_was_added must be initialized to False"
                    )
                    return
        # Annotated assignment: _lap_type_was_added: bool = False
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "_lap_type_was_added":
                assert node.value is not None, "_lap_type_was_added must have an initializer"
                assert isinstance(node.value, ast.Constant) and node.value.value is False, (
                    "_lap_type_was_added must be initialized to False"
                )
                return
    pytest.fail("_lap_type_was_added not found as a module-level assignment")


def test_upgrade_sets_flag_true_in_add_branch():
    """AC1: upgrade() assigns _lap_type_was_added = True when adding the column from scratch."""
    fn = _parse_fn("upgrade")
    found = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_lap_type_was_added":
                    if isinstance(node.value, ast.Constant) and node.value.value is True:
                        found = True
    assert found, "upgrade() must contain '_lap_type_was_added = True' inside the add-column branch"


def test_upgrade_uses_global_declaration():
    """AC1: upgrade() declares 'global _lap_type_was_added' so the module variable is written."""
    fn = _parse_fn("upgrade")
    has_global = any(
        isinstance(node, ast.Global) and "_lap_type_was_added" in node.names
        for node in ast.walk(fn)
    )
    assert has_global, "upgrade() must declare 'global _lap_type_was_added'"


# ---------------------------------------------------------------------------
# AC2: downgrade() calls op.drop_column for lap_type when flag is True
# ---------------------------------------------------------------------------


def test_downgrade_contains_drop_column_for_lap_type():
    """AC2: downgrade() source contains op.drop_column with 'lap_type'."""
    fn = _parse_fn("downgrade")
    drop_calls = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "drop_column"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == "lap_type":
                    drop_calls.append(node)
    assert drop_calls, (
        "downgrade() must contain op.drop_column(..., 'lap_type') for the fresh-DB case"
    )


def test_downgrade_references_flag():
    """AC2/AC3: downgrade() references _lap_type_was_added to branch on drop vs alter."""
    fn = _parse_fn("downgrade")
    referenced = any(
        isinstance(node, ast.Name) and node.id == "_lap_type_was_added"
        for node in ast.walk(fn)
    )
    assert referenced, "downgrade() must reference _lap_type_was_added"


# ---------------------------------------------------------------------------
# AC3: downgrade() calls op.alter_column(..., nullable=True) when flag is False
# ---------------------------------------------------------------------------


def test_downgrade_contains_alter_column_nullable_true_for_lap_type():
    """AC3: downgrade() source contains op.alter_column for 'lap_type' with nullable=True."""
    fn = _parse_fn("downgrade")
    found = False
    for node in ast.walk(fn):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "alter_column"
        ):
            continue
        has_lap_type = any(
            isinstance(arg, ast.Constant) and arg.value == "lap_type"
            for arg in node.args
        )
        has_nullable_true = any(
            kw.arg == "nullable"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in node.keywords
        )
        if has_lap_type and has_nullable_true:
            found = True
    assert found, (
        "downgrade() must contain op.alter_column(..., 'lap_type', ..., nullable=True) "
        "for the pre-existing column case"
    )


# ---------------------------------------------------------------------------
# AC4: Functional — fresh DB: upgrade then downgrade drops the column
# ---------------------------------------------------------------------------


def test_functional_fresh_db_drop_column():
    """AC4: When lap_type did not pre-exist, downgrade() drops it (not alters to nullable)."""
    # During upgrade: lap_type does NOT exist yet; all other columns exist.
    def col_exists_upgrade(table, col):
        if table == "workout_splits" and col == "lap_type":
            return False
        return True

    mod, mock_op = _load_migration(column_exists_side_effect=col_exists_upgrade)

    # --- upgrade ---
    mod.upgrade()

    # Flag should now be True because upgrade() created the column.
    assert mod._lap_type_was_added is True, (
        "_lap_type_was_added should be True after upgrade() added the column"
    )

    # For downgrade, column_exists should return True for lap_type
    # (it was just created by upgrade and now exists in the DB).
    mod.column_exists = MagicMock(return_value=True)

    # --- downgrade ---
    mock_op.reset_mock()
    mod.downgrade()

    # op.drop_column should have been called with 'lap_type'
    drop_calls = [
        c for c in mock_op.drop_column.call_args_list
        if "lap_type" in c.args
    ]
    assert drop_calls, (
        "downgrade() must call op.drop_column('workout_splits', 'lap_type') "
        "when _lap_type_was_added is True (fresh-DB case)"
    )

    # op.alter_column should NOT have been called with lap_type + nullable=True
    alter_lap_type_nullable = [
        c for c in mock_op.alter_column.call_args_list
        if "lap_type" in c.args and c.kwargs.get("nullable") is True
    ]
    assert not alter_lap_type_nullable, (
        "downgrade() must NOT call op.alter_column(nullable=True) for lap_type "
        "when _lap_type_was_added is True"
    )


# ---------------------------------------------------------------------------
# AC5: Functional — pre-existing column: downgrade restores to nullable
# ---------------------------------------------------------------------------


def test_functional_preexisting_column_alter_to_nullable():
    """AC5: When lap_type pre-existed, downgrade() alters it to nullable (does not drop)."""
    # column_exists returns True for everything — lap_type was already present.
    def col_exists(table, col):
        return True

    mod, mock_op = _load_migration(column_exists_side_effect=col_exists)
    # _column_is_nullable returns True for the pre-existing nullable lap_type.
    mod._column_is_nullable = MagicMock(return_value=True)

    # --- upgrade ---
    mod.upgrade()

    # Flag should remain False (we went into the else branch)
    assert mod._lap_type_was_added is False, (
        "_lap_type_was_added should be False after upgrade() only tightened the column"
    )

    # --- downgrade ---
    mock_op.reset_mock()
    mod.downgrade()

    # op.alter_column should have been called with lap_type and nullable=True
    alter_lap_type_nullable = [
        c for c in mock_op.alter_column.call_args_list
        if "lap_type" in c.args and c.kwargs.get("nullable") is True
    ]
    assert alter_lap_type_nullable, (
        "downgrade() must call op.alter_column(..., 'lap_type', ..., nullable=True) "
        "when _lap_type_was_added is False (pre-existing column case)"
    )

    # op.drop_column should NOT have been called with 'lap_type'
    drop_lap_type = [
        c for c in mock_op.drop_column.call_args_list
        if "lap_type" in c.args
    ]
    assert not drop_lap_type, (
        "downgrade() must NOT drop lap_type when _lap_type_was_added is False"
    )
