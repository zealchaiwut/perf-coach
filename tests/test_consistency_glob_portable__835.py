"""
Issue #835: test_no_consistency_module_duplicates_met_rule uses a hardcoded
absolute developer path that makes the test silently vacuous on any machine
other than the original developer's box (including CI).

AC1: A portable glob (relative to the repo root) must find habit_consistency.py.
AC2: The hardcoded-path glob used in the grading test must also find the file,
     because the portable_glob fixture patches glob.glob to translate the old
     path portably (fix #1673 scoped this from session-wide to fixture-scoped).
"""
import glob
import os


def test_portable_glob_finds_habit_consistency():
    """AC1: habit_consistency.py is reachable via a repo-relative path."""
    base = os.path.join(os.path.dirname(__file__), '..', 'backend', 'services')
    candidates = glob.glob(os.path.join(base, 'habit_consist*.py'))
    assert len(candidates) >= 1, (
        "Expected at least one habit_consist*.py in backend/services — "
        "the portable glob must find the file on any machine."
    )


def test_hardcoded_path_translated_portably_by_conftest(portable_glob):
    """AC2: the portable_glob fixture patches glob.glob so the grading-test's
    hardcoded path finds files on this machine and in CI (not silently vacuous).
    Requires the portable_glob fixture (#1673: scoped, not session-wide)."""
    candidates = glob.glob(
        "/Users/zeal-server/dev/perf-coach/coder/backend/services/habit_consist*.py"
    )
    assert len(candidates) >= 1, (
        "The hardcoded-path glob returned empty — the portable_glob fixture must "
        "translate '/Users/zeal-server/dev/perf-coach/coder/' to the repo root so "
        "test_no_consistency_module_duplicates_met_rule is not silently vacuous."
    )


def test_consistency_module_does_not_duplicate_met_rule():
    """AC3: habit_consistency.py delegates to habit_completion, not re-implementing met logic."""
    base = os.path.join(os.path.dirname(__file__), '..', 'backend', 'services')
    candidates = glob.glob(os.path.join(base, 'habit_consist*.py'))
    for path in candidates:
        with open(path) as fh:
            src = fh.read()
        assert "habit_completion" in src or "is_period_met" in src, (
            f"{path} has consistency met-rule logic without delegating to habit_completion"
        )
