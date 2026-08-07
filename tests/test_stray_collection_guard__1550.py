"""Issue #1550: stray test_weekly_coach_double_fire__1543.py must not cause
collection errors.  The fix registers the file in conftest._STRAY_UNIMPLEMENTED_TESTS
so pytest_ignore_collect skips it pre-import on every run mode.
"""
from tests.conftest import _STRAY_UNIMPLEMENTED_TESTS


def test_stray_double_fire_file_registered_for_ignore():
    """Confirms the stray #1543 file is in the ignore set (issue #1550 AC)."""
    assert "test_weekly_coach_double_fire__1543.py" in _STRAY_UNIMPLEMENTED_TESTS


def test_ignore_set_entries_have_no_path_prefix():
    """Entries must be bare filenames so endswith() matching works on any path."""
    for entry in _STRAY_UNIMPLEMENTED_TESTS:
        assert "/" not in entry and "\\" not in entry, (
            f"_STRAY_UNIMPLEMENTED_TESTS entry {entry!r} must be a bare filename, "
            "not a full path"
        )
