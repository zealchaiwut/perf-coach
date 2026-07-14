"""Tests for issue #1396: Readiness delete must run in the same transaction as the metric delete.

Context: sprint-103.1 code review of #1349 raised that delete_daily_metric opened two
separate Session contexts — the daily_metrics row was committed before the daily_readiness
delete ran. If the second statement raised, the metric was gone but a stale readiness row
remained, violating the 'no stale row' guarantee from AC #1349.

Acceptance Criteria (derived from issue body):
  AC1: Both the daily_metrics delete and the daily_readiness delete execute inside a SINGLE
       session/transaction so both commit or roll back together.
  AC2: The readiness row delete is NOT in a separate 'with Session' block that opens after
       the first session has already committed.
"""
import inspect
import ast

import backend.main as _main


# ── AC1: Only one Session context is opened ──────────────────────────────────

def test_delete_daily_metric_uses_single_session_block():
    """AC1: delete_daily_metric must use exactly one 'with Session' block, not two."""
    src = inspect.getsource(_main.delete_daily_metric)
    # Count occurrences of opening a new Session context
    count = src.count("with Session(")
    assert count == 1, (
        f"delete_daily_metric opens {count} Session contexts; "
        "both deletes must share a single session/transaction. "
        "Expected exactly 1 'with Session(' block."
    )


# ── AC2: The readiness DELETE is inside the same session block as the metric delete ──

def test_readiness_delete_precedes_single_commit():
    """AC2: The daily_readiness DELETE must appear before the single session.commit()."""
    src = inspect.getsource(_main.delete_daily_metric)
    readiness_pos = src.find("daily_readiness")
    commit_pos = src.find("session.commit()")
    assert readiness_pos != -1, (
        "delete_daily_metric must still reference 'daily_readiness' for cleanup"
    )
    assert commit_pos != -1, (
        "delete_daily_metric must have a session.commit()"
    )
    assert readiness_pos < commit_pos, (
        "The daily_readiness deletion must appear BEFORE session.commit(), "
        "not in a second session that opens after the first commit."
    )


def test_metric_delete_and_readiness_delete_both_before_commit():
    """AC1/AC2: session.delete(row) and daily_readiness DELETE both precede the commit."""
    src = inspect.getsource(_main.delete_daily_metric)
    metric_delete_pos = src.find("session.delete(row)")
    readiness_pos = src.find("daily_readiness")
    commit_pos = src.find("session.commit()")

    assert metric_delete_pos != -1, "session.delete(row) not found in delete_daily_metric"
    assert readiness_pos != -1, "daily_readiness not found in delete_daily_metric"
    assert commit_pos != -1, "session.commit() not found in delete_daily_metric"

    assert metric_delete_pos < commit_pos, (
        "session.delete(row) must come before session.commit()"
    )
    assert readiness_pos < commit_pos, (
        "daily_readiness deletion must come before session.commit() — "
        "it must be in the same transaction as the metric delete"
    )


def test_no_second_commit_after_readiness_delete():
    """AC1: There must be only one session.commit() call — not one per Session block."""
    src = inspect.getsource(_main.delete_daily_metric)
    commit_count = src.count("session.commit()")
    assert commit_count == 1, (
        f"delete_daily_metric has {commit_count} session.commit() calls; "
        "both deletes must be covered by a single commit."
    )
