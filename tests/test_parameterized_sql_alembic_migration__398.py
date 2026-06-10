"""Tests for issue #398: Use parameterized SQL in Alembic migration v5j6k7l8m9n0.

Acceptance criteria verified:
(a) No bare op.execute() with a raw string literal — all op.execute() calls must
    wrap the SQL in sa.text() so SQLAlchemy treats it as a text clause.
(b) The CREATE INDEX statement is still present (functionality not removed).
"""
import ast
import pathlib

MIGRATION = (
    pathlib.Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "v5j6k7l8m9n0_add_sync_jobs_table.py"
)


def _source():
    return MIGRATION.read_text()


# ---------------------------------------------------------------------------
# (a) No bare op.execute("...") with a raw string
# ---------------------------------------------------------------------------

def test_no_bare_op_execute_with_raw_string():
    """op.execute() must not be called with a plain string literal."""
    tree = ast.parse(_source())
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Detect op.execute(...)
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "execute"):
            continue
        # If any argument is a raw string constant, that's the violation
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                violations.append(ast.unparse(node))
    assert violations == [], (
        f"Found op.execute() call(s) with a raw string: {violations}. "
        "Wrap the SQL in sa.text() instead."
    )


# ---------------------------------------------------------------------------
# (b) sa.text() wrapping present for the CREATE INDEX call
# ---------------------------------------------------------------------------

def test_op_execute_wraps_sa_text():
    """op.execute() must use sa.text() as its argument."""
    tree = ast.parse(_source())
    sa_text_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "execute"):
            continue
        for arg in node.args:
            # sa.text(...) — an Attribute call whose attr is "text"
            if (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "text"
            ):
                sa_text_calls.append(ast.unparse(node))
    assert sa_text_calls, (
        "Expected at least one op.execute(sa.text(...)) call in the migration, "
        "but none found."
    )


# ---------------------------------------------------------------------------
# (c) CREATE INDEX statement content is preserved
# ---------------------------------------------------------------------------

def test_create_index_content_preserved():
    """The CREATE INDEX DDL for ix_sync_jobs_user_source_started_at must still exist."""
    src = _source()
    assert "ix_sync_jobs_user_source_started_at" in src, (
        "Index name 'ix_sync_jobs_user_source_started_at' not found in migration. "
        "Ensure the CREATE INDEX statement was not accidentally removed."
    )
    assert "CREATE INDEX" in src, (
        "CREATE INDEX statement not found in migration."
    )
