"""Grading tests for issue #1552: remove unused `import pytest` from
tests/test_curve_data_non_emptiness_check__993.py.

Acceptance Criteria:
  - `import pytest` is not present in test_curve_data_non_emptiness_check__993.py
  - The existing tests in that file still pass (the cleanup is non-functional)
"""

import ast
import pathlib


TARGET = pathlib.Path(__file__).parent / "test_curve_data_non_emptiness_check__993.py"


class TestUnusedImportRemoved:
    def test_pytest_not_imported_in_993_test_file(self):
        """AC: `import pytest` must be absent from the 993 test file."""
        source = TARGET.read_text(encoding="utf-8")
        tree = ast.parse(source)
        pytest_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            and any(alias.name == "pytest" for alias in node.names)
        ]
        assert pytest_imports == [], (
            f"Found unused `import pytest` in {TARGET.name} at "
            f"line(s): {[n.lineno for n in pytest_imports]}"
        )

    def test_993_tests_still_importable_without_pytest(self):
        """The 993 module must be importable (removing pytest doesn't break it)."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("_test993", TARGET)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:
            raise AssertionError(
                f"test_curve_data_non_emptiness_check__993.py failed to import: {exc}"
            ) from exc
