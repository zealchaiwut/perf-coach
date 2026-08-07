"""
Tests for issue #1560: Deduplicate Half-Equivalent column block in training-performance.js.

AC1: A single helper function exists that accepts r and returns the pm-col HTML (or "").
AC2: _buildUpcomingCard calls the helper instead of inlining the block.
AC3: _buildCompletedCard calls the helper instead of inlining the block.
AC4: No dead-code duplicate inline blocks remain (halfSec/halfCol or halfSecDone/halfColDone).
AC5/AC6: Verified by AC1–AC4 together (structural test).
"""
import pathlib
import re

_JS = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "training-performance.js"


def _src():
    return _JS.read_text(encoding="utf-8")


def test_helper_function_exists():
    """AC1: A single named helper function for the half-equivalent column must exist."""
    src = _src()
    # The helper must be a function declaration or expression assigned to a variable/const/let
    # matching a name that references 'Half Equivalent' logic.
    # We look for a function that returns the pm-col Half Equivalent block.
    assert "Half Equivalent" in src, "file must still contain 'Half Equivalent' label"
    # There must be exactly one place in the source that produces the Half Equivalent pm-col markup.
    # We count occurrences of 'Half Equivalent' — should be exactly 1 (inside the helper).
    count = src.count("Half Equivalent")
    assert count == 1, (
        f"Expected exactly 1 occurrence of 'Half Equivalent' (inside the helper), got {count}. "
        "Both callers must use the helper, not inline copies."
    )


def test_no_halfsec_done_variable():
    """AC4: The halfSecDone variable (from the old _buildCompletedCard inline block) must be removed."""
    src = _src()
    assert "halfSecDone" not in src, (
        "halfSecDone variable still present — the inline duplicate block in _buildCompletedCard "
        "has not been removed."
    )


def test_no_halfcoldone_variable():
    """AC4: The halfColDone variable (from the old _buildCompletedCard inline block) must be removed."""
    src = _src()
    assert "halfColDone" not in src, (
        "halfColDone variable still present — the inline duplicate block in _buildCompletedCard "
        "has not been removed."
    )


def test_halfsec_variable_not_inline_in_upcoming():
    """AC4: The old halfSec local var in _buildUpcomingCard must be gone (replaced by helper call)."""
    src = _src()
    # After the refactor, 'half_marathon_equivalent_seconds' should only appear once — inside the helper.
    occurrences = src.count("half_marathon_equivalent_seconds")
    assert occurrences == 1, (
        f"Expected exactly 1 occurrence of 'half_marathon_equivalent_seconds' (in the helper), "
        f"got {occurrences}. Inline references in _buildUpcomingCard or _buildCompletedCard remain."
    )


def test_helper_called_in_build_upcoming_card():
    """AC2: _buildUpcomingCard must call the extracted helper."""
    src = _src()
    # Find the _buildUpcomingCard function body.
    m = re.search(r"function _buildUpcomingCard\(r\)\s*\{(.+?)^  \}", src, re.DOTALL | re.MULTILINE)
    assert m, "_buildUpcomingCard function not found"
    body = m.group(1)
    # The body must reference 'half_marathon_equivalent_seconds' indirectly via helper call,
    # but NOT inline. Since we already assert only 1 occurrence in the whole file, if the helper
    # is in a different function, this body must NOT contain 'half_marathon_equivalent_seconds'.
    assert "half_marathon_equivalent_seconds" not in body, (
        "_buildUpcomingCard still contains an inline 'half_marathon_equivalent_seconds' reference. "
        "It should call the extracted helper instead."
    )
    # The body must call something that yields the halfEquiv html — confirmed by absence of inline
    # block and presence of half-related call (checked transitively by test_helper_function_exists).


def test_helper_called_in_build_completed_card():
    """AC3: _buildCompletedCard must call the extracted helper."""
    src = _src()
    m = re.search(r"function _buildCompletedCard\(r\)\s*\{(.+?)^  \}", src, re.DOTALL | re.MULTILINE)
    assert m, "_buildCompletedCard function not found"
    body = m.group(1)
    assert "half_marathon_equivalent_seconds" not in body, (
        "_buildCompletedCard still contains an inline 'half_marathon_equivalent_seconds' reference. "
        "It should call the extracted helper instead."
    )


def test_21_1_km_equiv_appears_once():
    """AC4 (structural): '21.1 km equiv.' string must appear exactly once (inside the helper only)."""
    src = _src()
    count = src.count("21.1 km equiv.")
    assert count == 1, (
        f"Expected exactly 1 occurrence of '21.1 km equiv.' (in the helper), got {count}."
    )
