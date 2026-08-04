"""Tests for issue #1531: Remove unused todayStr parameter from _buildHabitRow.

Acceptance Criteria:
- _buildHabitRow signature must NOT include todayStr
- The call site must NOT pass todayStr to _buildHabitRow
"""
import re
from pathlib import Path

HABITS_JS = Path(__file__).parent.parent / "frontend" / "js" / "habits.js"


def _read_source():
    return HABITS_JS.read_text(encoding="utf-8")


def test_build_habit_row_signature_has_no_todayStr():
    """AC: todayStr is removed from _buildHabitRow's parameter list."""
    src = _read_source()
    match = re.search(r"function _buildHabitRow\(([^)]*)\)", src)
    assert match, "_buildHabitRow function not found in habits.js"
    params = match.group(1)
    assert "todayStr" not in params, (
        f"todayStr still present in _buildHabitRow signature: ({params})"
    )


def test_build_habit_row_callsite_has_no_todayStr():
    """AC: todayStr is removed from every call site of _buildHabitRow."""
    src = _read_source()
    # Find all call sites
    calls = re.findall(r"_buildHabitRow\([^)]*\)", src)
    assert calls, "_buildHabitRow call site not found in habits.js"
    for call in calls:
        assert "todayStr" not in call, (
            f"todayStr still passed to _buildHabitRow: {call}"
        )
