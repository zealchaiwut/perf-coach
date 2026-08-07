"""Tests for issue #1713: remove duplicate delta_7d_kg assignment in get_weight_chart.

AC: stats["delta_7d_kg"] must be set exactly once (in the dict literal), with no
    redundant post-construction if-block overwriting it with the same value.
"""
import ast
import pathlib


_MAIN_PY = pathlib.Path(__file__).parent.parent / "backend" / "main.py"


def _get_weight_chart_body() -> list[ast.stmt]:
    """Return the AST statement list for the get_weight_chart function body."""
    tree = ast.parse(_MAIN_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_weight_chart":
            return node.body
    raise AssertionError("get_weight_chart not found in backend/main.py")


def _count_stats_delta7d_assignments(stmts: list[ast.stmt]) -> int:
    """
    Count assignments of the form stats["delta_7d_kg"] = ... anywhere in stmts,
    including inside nested if/for/with blocks (recursive).
    Dict-literal keys are not counted — only explicit post-construction assignments.
    """
    count = 0
    for stmt in stmts:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "stats"
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "delta_7d_kg"
                    ):
                        count += 1
    return count


def test_ac_no_duplicate_delta_7d_kg_assignment():
    """AC (issue #1713): delta_7d_kg must not be assigned again after the dict literal."""
    stmts = _get_weight_chart_body()
    n = _count_stats_delta7d_assignments(stmts)
    assert n == 0, (
        f"Found {n} post-construction assignment(s) of stats['delta_7d_kg'] "
        "in get_weight_chart — the duplicate if-block must be removed."
    )
