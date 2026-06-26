"""Tests for issue #470: Document habit tracking_type immutability constraint (code review)"""
import pathlib


def test_tracking_type_deletion_is_documented():
    """AC: Add comment documenting why tracking_type is deleted during habit edits"""
    # Read the habits.js file
    habits_js = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "habits.js"
    assert habits_js.exists(), "frontend/js/habits.js not found"

    content = habits_js.read_text()

    # Verify the immutability comment exists near the tracking_type deletion
    expected_comment = "// tracking_type is immutable after creation — backend rejects it in PATCH"
    assert expected_comment in content, (
        f"Expected comment '{expected_comment}' not found in habits.js"
    )

    # Count occurrences - should have at least one, but ideally both locations documented
    comment_count = content.count(expected_comment)
    assert comment_count >= 1, (
        f"Expected at least 1 occurrence of the immutability comment, found {comment_count}"
    )

    # Verify the comment is near the deletion statements
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if "delete payload.tracking_type" in line and "_sf" not in line:
            # For non-SF version, check if comment is 1-2 lines above
            found_comment = any(
                expected_comment in lines[j]
                for j in range(max(0, i - 3), i)
            )
            assert found_comment, (
                f"Immutability comment missing above 'delete payload.tracking_type' at line {i + 1}"
            )
