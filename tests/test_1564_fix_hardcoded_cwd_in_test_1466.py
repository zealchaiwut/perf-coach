"""Tests for issue #1564: Hardcoded absolute path in test_1466 subprocess cwd.

Verifies that all subprocess.run calls in tests/test_1466_consistent_run_matching.py
use a dynamic cwd derived from the test file's location, making them portable
across different clone directories.
"""
import pathlib
import re

TEST_FILE = pathlib.Path(__file__).resolve().parents[0] / "test_1466_consistent_run_matching.py"


def _read_test_file() -> str:
    return TEST_FILE.read_text()


def test_1564__no_hardcoded_zeal_server_path():
    """AC: No hardcoded absolute path containing /Users/zeal-server remains."""
    content = _read_test_file()
    assert "/Users/zeal-server" not in content, (
        "Hardcoded /Users/zeal-server path still present in test_1466_consistent_run_matching.py"
    )


def test_1564__pathlib_import_present():
    """AC: import pathlib is present in the imports section."""
    content = _read_test_file()
    assert "import pathlib" in content, (
        "import pathlib not found in test_1466_consistent_run_matching.py"
    )


def test_1564__all_cwd_calls_use_dynamic_path():
    """AC: All five subprocess.run calls use cwd=str(pathlib.Path(__file__).resolve().parents[1])."""
    content = _read_test_file()

    dynamic_pattern = r"cwd=str\(pathlib\.Path\(__file__\)\.resolve\(\)\.parents\[1\]\)"
    dynamic_count = len(re.findall(dynamic_pattern, content))

    assert dynamic_count == 5, (
        f"Expected 5 dynamic cwd= calls, found {dynamic_count}. "
        "All subprocess.run calls must use cwd=str(pathlib.Path(__file__).resolve().parents[1])"
    )


def test_1564__no_hardcoded_cwd_calls():
    """AC: No cwd= argument contains a hardcoded absolute path."""
    content = _read_test_file()

    hardcoded_pattern = r'cwd\s*=\s*"/[^"]*"'
    hardcoded_matches = re.findall(hardcoded_pattern, content)

    assert len(hardcoded_matches) == 0, (
        f"Hardcoded cwd= calls still present: {hardcoded_matches}"
    )


def test_1564__dynamic_cwd_resolves_to_valid_git_repo():
    """AC: The dynamic path resolves to a valid git repository root.

    Simulates what the fixed test does: uses the same dynamic path logic
    and verifies it points to a directory containing a .git folder.
    """
    # This uses the same expression as the fix: parents[1] of the test file
    # gives the repo root (tests/ -> repo root)
    resolved_cwd = pathlib.Path(__file__).resolve().parents[1]
    git_dir = resolved_cwd / ".git"
    assert git_dir.exists(), (
        f"Dynamic cwd {resolved_cwd} does not contain a .git directory. "
        "The dynamic path must resolve to the git repository root."
    )
