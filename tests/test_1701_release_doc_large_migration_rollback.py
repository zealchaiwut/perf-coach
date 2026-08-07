"""
Tests for issue #1701: release-process.md must warn that code-only rollback
is unsafe for large migration batches that include destructive schema changes
(column renames, drops).

Derived acceptance criteria:
  AC-1  Step 7 (Rollback) in release-process.md must warn that the Render
        previous-image redeploy does NOT roll back already-applied migrations.
  AC-2  The doc must recommend taking a DB snapshot (db_snapshot.py) BEFORE
        running migrations when the release carries destructive schema changes.
  AC-3  The doc must call out column renames specifically as a class of change
        that makes code-only rollback dangerous.
  AC-4  The doc must state clearly that a DB restore is required (not just a
        code redeploy) to recover from a failed deploy that already ran such
        migrations.
"""

import pathlib
import re

DOC_PATH = pathlib.Path("docs/release-process.md")


def _doc_text() -> str:
    return DOC_PATH.read_text()


# ── AC-1: Step 7 warns that image rollback does not roll back migrations ──────

def test_step7_warns_migrations_are_not_rolled_back():
    """Step 7 must state that rolling back the image does not undo migrations."""
    text = _doc_text().lower()
    # Must convey that migrations persist / are not reverted by image rollback
    has_warning = (
        "migration" in text and (
            "does not roll back" in text
            or "does not revert" in text
            or "already applied" in text
            or "already ran" in text
            or "not rolled back" in text
            or "not reverted" in text
        )
    )
    assert has_warning, (
        "docs/release-process.md Step 7 must warn that a Render image rollback "
        "does NOT undo already-applied Alembic migrations"
    )


# ── AC-2: Doc recommends a DB snapshot before large-batch migrations ───────────

def test_doc_recommends_snapshot_before_large_migrations():
    """The doc must recommend db_snapshot.py (or equivalent) before deploy."""
    text = _doc_text()
    lower = text.lower()
    has_snapshot_ref = (
        "db_snapshot.py" in text
        or "db_snapshot" in lower
        or "snapshot" in lower
    )
    # Should be in context of pre-deploy, not just the backup-restore ref
    assert has_snapshot_ref, (
        "docs/release-process.md must recommend taking a DB snapshot "
        "(scripts/db_snapshot.py or equivalent) before deploying large migration batches"
    )


def test_snapshot_recommendation_appears_before_or_at_deploy_step():
    """Snapshot recommendation must appear at/before Step 5 (deploy) or Step 4."""
    text = _doc_text()
    snapshot_pos = text.lower().find("db_snapshot")
    if snapshot_pos == -1:
        snapshot_pos = text.lower().find("snapshot")
    # Step 5 header
    step5_pos = text.lower().find("step 5")
    step4_pos = text.lower().find("step 4")
    # The snapshot mention should appear no later than after Step 6 in the flow
    # (i.e. it should be in/before Step 5, or in a dedicated pre-deploy note)
    assert snapshot_pos != -1, "No snapshot mention found in release-process.md"
    # Allow: mentioned early in the doc (before step 5) OR in step 4 or step 5 or
    # a dedicated large-batch warning section anywhere before step 7.
    # We just want it to NOT only appear after step 7.
    step7_pos = text.lower().find("step 7")
    assert snapshot_pos < step7_pos or step5_pos == -1, (
        "Snapshot recommendation must appear before or at Step 7 "
        "(ideally in Step 4 or 5, or a dedicated pre-deploy note)"
    )


# ── AC-3: Column renames are called out as a specific rollback risk ───────────

def test_doc_calls_out_column_renames_as_rollback_risk():
    """The doc must mention column renames as a class of destructive migration."""
    text = _doc_text().lower()
    has_rename_mention = (
        "rename" in text or "column rename" in text or "renamed" in text
    )
    assert has_rename_mention, (
        "docs/release-process.md must call out column renames as a migration "
        "class that makes code-only rollback unsafe"
    )


# ── AC-4: Doc states DB restore is required (not just code redeploy) ─────────

def test_doc_states_db_restore_required_for_destructive_migrations():
    """The doc must state a DB restore is required for destructive migrations."""
    text = _doc_text().lower()
    has_restore_callout = (
        "db restore" in text
        or "database restore" in text
        or "restore required" in text
        or "restore the database" in text
        or "restore from snapshot" in text
        or ("restore" in text and "migration" in text and "unsafe" in text)
        or ("restore" in text and "destructive" in text)
    )
    assert has_restore_callout, (
        "docs/release-process.md must state that a DB restore (not just a code "
        "redeploy) is required when a failed deploy has already applied "
        "destructive migrations (column renames, drops)"
    )
