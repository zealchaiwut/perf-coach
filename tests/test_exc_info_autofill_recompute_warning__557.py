"""Issue #557: exc_info=True must be present in the _recompute_autofill warning
call inside duplicate_workout so stack traces appear in logs."""

import ast
import pathlib


MAIN_PY = pathlib.Path(__file__).parent.parent / "backend" / "main.py"


def _find_duplicate_workout_autofill_warning():
    """Parse main.py and return the keyword arguments of the warning() call
    inside the _recompute_autofill except block within duplicate_workout."""
    source = MAIN_PY.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "duplicate_workout"):
            continue
        # Walk inside duplicate_workout
        for child in ast.walk(node):
            if not isinstance(child, ast.ExceptHandler):
                continue
            for stmt in ast.walk(child):
                if not isinstance(stmt, ast.Expr):
                    continue
                call = stmt.value
                if not isinstance(call, ast.Call):
                    continue
                # Match .warning() calls
                if not (isinstance(call.func, ast.Attribute) and call.func.attr == "warning"):
                    continue
                # Check if the first string arg mentions autofill
                if call.args:
                    first = call.args[0]
                    if isinstance(first, ast.Constant) and "autofill" in str(first.value):
                        return {kw.arg: kw for kw in call.keywords}
    return None


def test_autofill_warning_has_exc_info():
    """AC1: exc_info=True is present in the _recompute_autofill warning call."""
    keywords = _find_duplicate_workout_autofill_warning()
    assert keywords is not None, (
        "Could not find the autofill warning() call in duplicate_workout — "
        "check that the log message still contains the word 'autofill'"
    )
    assert "exc_info" in keywords, (
        "exc_info keyword argument is missing from the autofill warning() call"
    )
    exc_info_node = keywords["exc_info"]
    assert isinstance(exc_info_node.value, ast.Constant) and exc_info_node.value.value is True, (
        "exc_info is present but not set to True"
    )


def test_autofill_warning_exc_info_matches_daily_update_style():
    """AC2: exc_info=True placement matches the daily_update warning style."""
    source = MAIN_PY.read_text()
    tree = ast.parse(source)

    daily_update_exc_info_kwarg = None
    autofill_exc_info_kwarg = None

    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "duplicate_workout"):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.ExceptHandler):
                continue
            for stmt in ast.walk(child):
                if not isinstance(stmt, ast.Expr):
                    continue
                call = stmt.value
                if not isinstance(call, ast.Call):
                    continue
                if not (isinstance(call.func, ast.Attribute) and call.func.attr == "warning"):
                    continue
                if not call.args:
                    continue
                first = call.args[0]
                if not isinstance(first, ast.Constant):
                    continue
                msg = str(first.value)
                if "daily_update" in msg:
                    kws = {kw.arg: kw for kw in call.keywords}
                    daily_update_exc_info_kwarg = kws.get("exc_info")
                elif "autofill" in msg:
                    kws = {kw.arg: kw for kw in call.keywords}
                    autofill_exc_info_kwarg = kws.get("exc_info")

    assert daily_update_exc_info_kwarg is not None, "daily_update warning exc_info not found"
    assert autofill_exc_info_kwarg is not None, "autofill warning exc_info not found"

    # Both should be keyword arguments (not positional) with value True — same style
    assert isinstance(daily_update_exc_info_kwarg.value, ast.Constant)
    assert isinstance(autofill_exc_info_kwarg.value, ast.Constant)
    assert daily_update_exc_info_kwarg.value.value is True
    assert autofill_exc_info_kwarg.value.value is True


def test_no_other_changes_to_duplicate_workout():
    """AC3: only exc_info=True is added — the warning message text is unchanged."""
    source = MAIN_PY.read_text()
    # The original message template should still be there
    assert "autofill recompute failed for user" in source, (
        "The autofill warning message text was changed — only exc_info=True should be added"
    )
