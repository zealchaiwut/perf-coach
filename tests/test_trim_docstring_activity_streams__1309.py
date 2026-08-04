"""AC: activity_streams_to_strava_dict has a single-line docstring (issue #1309)."""
import ast
import pathlib

SRC = pathlib.Path(__file__).parent.parent / "backend/services/activity_streams.py"


def test_docstring_is_single_line():
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "activity_streams_to_strava_dict":
            ds = ast.get_docstring(node)
            assert ds is not None, "Function should still have a docstring"
            assert len(ds.splitlines()) == 1, (
                f"Expected a single-line docstring, got {len(ds.splitlines())} lines"
            )
            return
    raise AssertionError("activity_streams_to_strava_dict not found in activity_streams.py")
