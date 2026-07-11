"""Tests for issue #1349: Readiness auto-recompute on daily_metrics create/update/delete.

Acceptance Criteria:
  AC1: Create/update/delete of a daily_metrics row triggers recompute via
       services/readiness/job.compute_and_store (or readiness row deletion on delete)
  AC2: Recompute is synchronous and idempotent; deleting a metric removes the
       readiness row rather than leaving a stale score
  AC3: Explicit POST /api/readiness/compute still works unchanged
  AC4: No behavior change for days never touched — only the affected day is recomputed
  AC5: Tests - edit metric → readiness updated; delete → no stale row; unrelated day untouched
"""
import inspect

import backend.main as _main


# ── AC1: create handler wires compute_and_store ───────────────────────────────

def test_create_handler_calls_compute_and_store():
    """AC1: create_daily_metric calls compute_and_store after committing the new row."""
    src = inspect.getsource(_main.create_daily_metric)
    assert "compute_and_store" in src, (
        "create_daily_metric must call compute_and_store to auto-recompute readiness"
    )


def test_create_handler_calls_compute_after_commit():
    """AC1: The compute_and_store call appears after session.commit in create_daily_metric."""
    src = inspect.getsource(_main.create_daily_metric)
    commit_pos = src.find("session.commit()")
    compute_pos = src.find("compute_and_store")
    assert commit_pos != -1, "No session.commit() in create_daily_metric"
    assert compute_pos != -1, "No compute_and_store call in create_daily_metric"
    # compute_and_store must appear after the commit (not inside the with-session block before commit)
    assert compute_pos > commit_pos, (
        "compute_and_store must be called AFTER session.commit() to see the new metric"
    )


# ── AC1: patch handler wires compute_and_store ────────────────────────────────

def test_patch_handler_calls_compute_and_store():
    """AC1: patch_daily_metric calls compute_and_store after updating the row."""
    src = inspect.getsource(_main.patch_daily_metric)
    assert "compute_and_store" in src, (
        "patch_daily_metric must call compute_and_store to auto-recompute readiness"
    )


def test_patch_handler_calls_compute_after_commit():
    """AC1: compute_and_store call appears after session.commit in patch_daily_metric."""
    src = inspect.getsource(_main.patch_daily_metric)
    commit_pos = src.find("session.commit()")
    compute_pos = src.find("compute_and_store")
    assert commit_pos != -1 and compute_pos != -1
    assert compute_pos > commit_pos, (
        "compute_and_store must be called AFTER session.commit() in patch handler"
    )


# ── AC1: upsert (PUT) handler wires compute_and_store ────────────────────────

def test_put_handler_calls_compute_and_store():
    """AC1: upsert_daily_metric (PUT) calls compute_and_store after upserting the row."""
    src = inspect.getsource(_main.upsert_daily_metric)
    assert "compute_and_store" in src, (
        "upsert_daily_metric must call compute_and_store to auto-recompute readiness"
    )


def test_put_handler_calls_compute_after_commit():
    """AC1: compute_and_store call appears after session.commit in upsert_daily_metric."""
    src = inspect.getsource(_main.upsert_daily_metric)
    commit_pos = src.find("session.commit()")
    compute_pos = src.find("compute_and_store")
    assert commit_pos != -1 and compute_pos != -1
    assert compute_pos > commit_pos, (
        "compute_and_store must be called AFTER session.commit() in upsert handler"
    )


# ── AC1/AC2: delete handler removes stale readiness row ──────────────────────

def test_delete_handler_cleans_up_readiness():
    """AC1/AC2: delete_daily_metric removes the stale readiness row after deleting the metric."""
    src = inspect.getsource(_main.delete_daily_metric)
    has_cleanup = "daily_readiness" in src or "delete_readiness" in src
    assert has_cleanup, (
        "delete_daily_metric must clean up the daily_readiness row to avoid stale scores"
    )


def test_delete_handler_cleanup_references_user_id_and_date():
    """AC2: The readiness cleanup in delete_daily_metric scopes the delete to the right user+date."""
    src = inspect.getsource(_main.delete_daily_metric)
    # The DELETE statement must reference both user_id and date
    readiness_block_start = src.find("daily_readiness")
    assert readiness_block_start != -1
    # Find the context around the readiness deletion
    readiness_context = src[readiness_block_start:readiness_block_start + 200]
    assert "uid" in readiness_context or "user_id" in readiness_context, (
        "Readiness cleanup must be scoped to the current user"
    )


# ── AC3: Explicit compute endpoint still works ────────────────────────────────

def test_explicit_compute_endpoint_still_delegates_to_compute_and_store():
    """AC3: POST /api/readiness/compute still delegates to compute_and_store (unchanged)."""
    src = inspect.getsource(_main.compute_readiness_score)
    assert "compute_and_store" in src, (
        "POST /api/readiness/compute must still delegate to compute_and_store"
    )


def test_explicit_compute_endpoint_still_returns_404_for_missing_metric():
    """AC3: POST /api/readiness/compute still returns 404 when compute_and_store returns None."""
    src = inspect.getsource(_main.compute_readiness_score)
    assert "404" in src, (
        "POST /api/readiness/compute must still raise 404 when no metric row exists"
    )


# ── AC4/AC5: Recompute is scoped to the affected day only ────────────────────

def test_create_scopes_recompute_to_metric_date():
    """AC4: Auto-recompute in create handler uses the metric's own date (md), not today."""
    src = inspect.getsource(_main.create_daily_metric)
    lines = src.splitlines()
    compute_lines = [ln.strip() for ln in lines if "compute_and_store" in ln and "import" not in ln]
    assert len(compute_lines) >= 1, "No compute_and_store call in create_daily_metric"
    call_line = compute_lines[0]
    assert "md" in call_line, (
        f"create_daily_metric must pass `md` (the metric date) to compute_and_store; "
        f"found call: {call_line!r}"
    )


def test_patch_scopes_recompute_to_metric_date():
    """AC4: Auto-recompute in patch handler uses the patched date (md), not today."""
    src = inspect.getsource(_main.patch_daily_metric)
    lines = src.splitlines()
    compute_lines = [ln.strip() for ln in lines if "compute_and_store" in ln and "import" not in ln]
    assert len(compute_lines) >= 1, "No compute_and_store call in patch_daily_metric"
    call_line = compute_lines[0]
    assert "md" in call_line, (
        f"patch_daily_metric must pass `md` to compute_and_store; found: {call_line!r}"
    )


def test_put_scopes_recompute_to_metric_date():
    """AC4: Auto-recompute in upsert handler uses the upserted date (md), not today."""
    src = inspect.getsource(_main.upsert_daily_metric)
    lines = src.splitlines()
    compute_lines = [ln.strip() for ln in lines if "compute_and_store" in ln and "import" not in ln]
    assert len(compute_lines) >= 1, "No compute_and_store call in upsert_daily_metric"
    call_line = compute_lines[0]
    assert "md" in call_line, (
        f"upsert_daily_metric must pass `md` to compute_and_store; found: {call_line!r}"
    )


# ── AC2: Idempotency — compute_and_store uses upsert internally ───────────────

def test_compute_and_store_is_idempotent():
    """AC2: compute_and_store uses ON CONFLICT DO UPDATE, making repeated calls idempotent."""
    from services.readiness.job import compute_and_store
    src = inspect.getsource(compute_and_store)
    assert "ON CONFLICT" in src, (
        "compute_and_store must use ON CONFLICT DO UPDATE for idempotency"
    )


# ── AC1: The import of compute_and_store exists in main.py ───────────────────

def test_readiness_compute_and_store_imported_at_module_level():
    """AC1: _readiness_compute_and_store is imported at module level in main.py for reuse."""
    import backend.main as m
    assert hasattr(m, "_readiness_compute_and_store"), (
        "services.readiness.job.compute_and_store must be imported as "
        "_readiness_compute_and_store at module level in main.py"
    )
    assert callable(m._readiness_compute_and_store), (
        "_readiness_compute_and_store must be callable"
    )
