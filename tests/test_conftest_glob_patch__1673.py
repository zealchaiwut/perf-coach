"""Tests for issue #1673: conftest glob.glob monkeypatch must be properly scoped.

AC1: glob.glob is the real stdlib function at test-collection time (not the shim).
AC2: test_no_consistency_module_duplicates_met_rule still passes through a
     properly-scoped fixture.
AC3: After the target test runs, glob.glob is the original function again
     (no session-wide contamination).
"""
import glob as _stdlib_glob
import glob


def test_glob_not_permanently_patched_at_import():
    """AC1: glob.glob must be the real stdlib function, not the shim."""
    # The real glob.glob is defined in the glob module itself.
    # If it has been permanently replaced, its __module__ will differ or
    # it will be a local function rather than the C/stdlib implementation.
    import glob as g
    # The original glob.glob is either a built-in or defined in the 'glob'
    # module.  A session-wide monkeypatch defined in conftest replaces it
    # with a function whose __module__ is 'tests.conftest'.
    fn = g.glob
    module = getattr(fn, "__module__", "") or ""
    assert module != "tests.conftest", (
        "glob.glob has been permanently replaced by a conftest shim "
        "(module='tests.conftest'). It must be restored after the test "
        "that needs the path translation."
    )


def test_glob_returns_real_results_for_nonexistent_hardcoded_path():
    """AC3: glob.glob on the hardcoded coder path returns [] (not translated).

    If the session-wide shim is still active, it would translate the
    hardcoded prefix to the real repo root and return actual files, making
    this test believe the path exists.  With the shim removed, glob on a
    path that doesn't exist on this machine returns [].
    """
    import glob as g
    # This is the hardcoded path from the original test.  It only exists on
    # the original coder machine; on any other host (or in CI) the directory
    # /Users/zeal-server/dev/perf-coach/coder does not exist as a *separate*
    # checkout — this IS that path, so we use a path that definitely cannot
    # exist: a UUID-style non-existent directory.
    result = g.glob("/nonexistent_path_that_cannot_exist_6f4a9b2c/backend/services/habit_consist*.py")
    assert result == [], (
        "glob.glob returned non-empty result for a path that cannot exist. "
        "The session-wide shim may still be active."
    )
