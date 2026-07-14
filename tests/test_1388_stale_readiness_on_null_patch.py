"""Tests for issue #1388: Nulling all wellness inputs via PATCH leaves a stale daily_readiness row.

When compute_and_store gets a metric row but compute_readiness returns None
(because all scored inputs — hrv, resting_hr, sleep_quality, energy — are null),
any existing daily_readiness row for (user, date) must be deleted so no stale
score remains.
"""
import inspect

from services.readiness.job import compute_and_store


def _extract_if_block_body(src: str, condition_fragment: str) -> str:
    """Return the indented body of the first `if <condition_fragment>:` block found in src."""
    lines = src.splitlines()
    block_start = None
    base_indent = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if condition_fragment in line and stripped.startswith("if "):
            block_start = i
            base_indent = len(line) - len(stripped)
            break

    if block_start is None:
        return ""

    body_lines = []
    for line in lines[block_start + 1:]:
        stripped = line.lstrip()
        if not stripped:
            continue  # skip blank lines within block
        indent = len(line) - len(stripped)
        if indent <= base_indent:
            break  # returned to same or outer scope — block ended
        body_lines.append(line)
    return "\n".join(body_lines)


def test_result_is_none_branch_deletes_stale_readiness_row():
    """AC: When compute_readiness returns None, compute_and_store must delete the
    existing daily_readiness row for (user_id, date) rather than just returning None.
    """
    src = inspect.getsource(compute_and_store)
    # "result is None" only appears once: the check after compute_readiness() call
    block_body = _extract_if_block_body(src, "result is None")

    assert block_body, (
        "compute_and_store must have an 'if result is None:' block after calling compute_readiness"
    )

    has_delete = (
        "daily_readiness" in block_body
        or "DELETE" in block_body
        or "delete" in block_body.lower()
    )
    assert has_delete, (
        "When compute_readiness returns None (all inputs null), the 'if result is None:' "
        "block in compute_and_store must delete the stale daily_readiness row. "
        f"Actual block body found:\n{block_body}"
    )


def test_result_is_none_branch_only_return_none_is_the_bug():
    """Regression guard: if the block is ONLY 'return None', the bug is still present."""
    src = inspect.getsource(compute_and_store)
    block_body = _extract_if_block_body(src, "result is None")

    # Count non-blank, non-comment real lines in the block
    real_lines = [ln.strip() for ln in block_body.splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]

    assert len(real_lines) > 1 or any(
        "daily_readiness" in ln or "delete" in ln.lower() or "DELETE" in ln
        for ln in real_lines
    ), (
        "The 'if result is None:' block is just 'return None' — the stale-readiness "
        "deletion is missing. Add a DELETE of daily_readiness before returning."
    )


def test_result_is_none_branch_scopes_delete_to_user_and_date():
    """The stale-row deletion must be scoped to the correct (user_id, date) pair."""
    src = inspect.getsource(compute_and_store)
    block_body = _extract_if_block_body(src, "result is None")

    has_user_scope = "user_id" in block_body or ":uid" in block_body or "uid" in block_body
    has_date_scope = (
        "target_date" in block_body
        or ":d" in block_body
        or "date" in block_body.lower()
    )

    assert has_user_scope, (
        "Stale daily_readiness deletion must reference user_id/uid to avoid deleting "
        f"another user's row. Block body:\n{block_body}"
    )
    assert has_date_scope, (
        "Stale daily_readiness deletion must reference the date to avoid deleting "
        f"data from other days. Block body:\n{block_body}"
    )


def test_metric_row_is_none_still_returns_immediately():
    """Regression: when no metric row exists at all, compute_and_store returns None fast."""
    src = inspect.getsource(compute_and_store)
    block_body = _extract_if_block_body(src, "metric_row is None")

    assert "return None" in block_body, (
        "compute_and_store must return None immediately when metric_row is None"
    )
    # This block should NOT touch daily_readiness — there's nothing to delete
    # when the metric itself doesn't exist.
    assert "daily_readiness" not in block_body, (
        "The 'if metric_row is None:' branch must not touch daily_readiness — "
        "there's no stale row to delete when the metric row itself doesn't exist."
    )
