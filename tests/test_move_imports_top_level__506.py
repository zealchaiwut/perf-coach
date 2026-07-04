"""Tests for issue #506: ZoneInfo and func imports moved to top-level in backend/main.py."""
import ast
import pathlib

MAIN_PY = pathlib.Path(__file__).parent.parent / "backend" / "main.py"


def _parse_main():
    return ast.parse(MAIN_PY.read_text())


def _top_level_imports(tree):
    """Return all names imported at module level (not inside functions/classes)."""
    imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.append(alias.asname or alias.name)
    return imports


def _find_local_imports(tree, name_fragment: str):
    """Return list of (func_name, lineno) for local imports matching name_fragment."""
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    stmt_src = ast.dump(child)
                    if name_fragment in stmt_src:
                        results.append((func_name, child.lineno))
    return results


def test_zoneinfo_imported_at_top_level():
    """AC1: from zoneinfo import ZoneInfo is imported at the top level."""
    tree = _parse_main()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module == "zoneinfo":
                names = [alias.name for alias in node.names]
                if "ZoneInfo" in names:
                    return
    raise AssertionError("ZoneInfo is not imported at the top level of backend/main.py")


def test_func_imported_at_top_level():
    """AC2: func (from sqlalchemy) is imported at the top level."""
    tree = _parse_main()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module and "sqlalchemy" in node.module:
                names = [alias.name for alias in node.names]
                if "func" in names:
                    return
    raise AssertionError("func (from sqlalchemy) is not imported at the top level of backend/main.py")


def test_today_bkk_no_local_zoneinfo_import():
    """AC3: _today_bkk() function body no longer contains a local ZoneInfo import."""
    tree = _parse_main()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_today_bkk":
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom) and child.module == "zoneinfo":
                    raise AssertionError(
                        f"_today_bkk() still has a local 'from zoneinfo import ...' at line {child.lineno}"
                    )
            return
    raise AssertionError("_today_bkk() function not found in backend/main.py")


def test_get_weight_target_history_summary_no_local_func_import():
    """AC4: get_weight_target_history_summary no longer contains a local func import."""
    tree = _parse_main()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "get_weight_target_history_summary":
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom):
                    names = [alias.name for alias in child.names]
                    if "func" in names:
                        raise AssertionError(
                            f"get_weight_target_history_summary still has a local 'func' import at line {child.lineno}"
                        )
            return
    raise AssertionError("get_weight_target_history_summary function not found in backend/main.py")


def test_no_duplicate_local_zoneinfo_imports():
    """AC5: No other functions in main.py contain local ZoneInfo imports that duplicate the top-level one."""
    tree = _parse_main()
    local = _find_local_imports(tree, "ZoneInfo")
    assert local == [], (
        f"Found local ZoneInfo imports inside functions: {local}. "
        "All ZoneInfo imports should be at the top level."
    )


def test_no_duplicate_local_func_imports():
    """AC5: No other functions in main.py contain local func imports that duplicate the top-level one."""
    tree = _parse_main()
    local = _find_local_imports(tree, "'func'")
    assert local == [], (
        f"Found local func imports inside functions: {local}. "
        "All func imports should be at the top level."
    )