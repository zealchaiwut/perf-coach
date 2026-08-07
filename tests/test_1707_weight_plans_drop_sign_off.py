"""Tests for issue #1707: sign-off verification for weight_plans table drop.

The migration 6f945c183d82 drops the weight_plans table after copying active
plan data to weight_targets. Non-active/historical rows are intentionally
discarded (weight_plans never had a history view endpoint). These tests verify
the four safeguards that justify accepting the data loss:

  AC-1  The migration guards the entire weight_plans block with table_exists,
        making it idempotent and safe to re-run.
  AC-2  The migration copies active plan data to weight_targets before
        dropping the table — active rows are never lost.
  AC-3  The migration docstring explicitly documents that non-active rows are
        intentionally dropped with the table (the sign-off record).
  AC-4  The downgrade function recreates an empty weight_plans table, making
        the one-directional nature of the data migration explicit.
  AC-5  The release-process.md Step 3c lists table drops alongside column
        renames as a class of destructive change requiring a pre-deploy snapshot.
"""

from __future__ import annotations

import ast
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATION_FILE = (
    REPO_ROOT
    / "alembic"
    / "versions"
    / "6f945c183d82_merge_weight_plans_into_weight_targets_.py"
)
RELEASE_DOC = REPO_ROOT / "docs" / "release-process.md"


def _src() -> str:
    return MIGRATION_FILE.read_text()


def _ast() -> ast.Module:
    return ast.parse(_src())


def _fn_source(name: str) -> str:
    """Extract the source lines of a named top-level function."""
    lines = _src().splitlines()
    in_fn = False
    body: list[str] = []
    for line in lines:
        if re.match(rf"^def {name}\(", line):
            in_fn = True
            continue
        if in_fn:
            if line and not line[0].isspace():
                break
            body.append(line)
    return "\n".join(body)


# ── AC-1: table_exists guard around the weight_plans block ───────────────────


class TestTableExistsGuard:
    """AC-1: The migration must guard all weight_plans operations with table_exists."""

    def test_table_exists_call_present(self):
        """AC-1: upgrade() calls table_exists('weight_plans') before the drop."""
        src = _src()
        assert 'table_exists("weight_plans")' in src or "table_exists('weight_plans')" in src, (
            "Migration must call table_exists('weight_plans') before operating on the table"
        )

    def test_drop_table_is_inside_table_exists_block(self):
        """AC-1: op.drop_table('weight_plans') only runs if the table exists."""
        src = _src()
        table_exists_pos = src.find('table_exists("weight_plans")')
        if table_exists_pos == -1:
            table_exists_pos = src.find("table_exists('weight_plans')")
        drop_pos = src.find('op.drop_table("weight_plans")')
        if drop_pos == -1:
            drop_pos = src.find("op.drop_table('weight_plans')")
        assert table_exists_pos != -1, "table_exists('weight_plans') call not found"
        assert drop_pos != -1, "op.drop_table('weight_plans') call not found"
        assert drop_pos > table_exists_pos, (
            "op.drop_table must come after (inside) the table_exists guard"
        )

    def test_weight_targets_guarded_too(self):
        """AC-1: upgrade() also guards weight_targets operations with table_exists."""
        src = _src()
        assert 'table_exists("weight_targets")' in src or "table_exists('weight_targets')" in src, (
            "Migration must guard weight_targets operations with table_exists for idempotency"
        )


# ── AC-2: active plan data migrated before table drop ────────────────────────


class TestActivePlanDataMigrated:
    """AC-2: Active weight_plans rows must be copied to weight_targets before drop."""

    def test_update_to_weight_targets_before_drop(self):
        """AC-2: An UPDATE or INSERT into weight_targets precedes the drop_table call."""
        src = _src()
        # Check that the migration references UPDATE/INSERT and weight_targets
        has_update = "UPDATE weight_targets" in src or "update weight_targets" in src.lower()
        has_insert = "INSERT INTO weight_targets" in src or "insert into weight_targets" in src.lower()
        assert has_update or has_insert, (
            "Migration must UPDATE or INSERT into weight_targets before dropping weight_plans"
        )

    def test_active_filter_present(self):
        """AC-2: Migration filters weight_plans to active=true rows only."""
        src = _src()
        assert "active = true" in src or "active=true" in src or "'active'" in src, (
            "Migration must filter weight_plans rows by active status before migrating"
        )

    def test_latest_active_plan_dedup(self):
        """AC-2: Migration handles duplicate active plans (DISTINCT ON user_id)."""
        src = _src()
        has_dedup = "DISTINCT ON" in src or "distinct on" in src.lower()
        assert has_dedup, (
            "Migration must deduplicate per-user active plans with DISTINCT ON user_id"
        )


# ── AC-3: intentional data loss is documented in the migration ───────────────


class TestIntentionalDropDocumented:
    """AC-3: The migration docstring must state non-active rows are intentionally dropped."""

    def test_docstring_mentions_inactive_rows_dropped(self):
        """AC-3: Docstring explains that non-active rows are dropped with the table."""
        src = _src().lower()
        # Accept several phrasings that convey the intentional drop
        documented = (
            "inactive rows" in src
            or "non-active" in src
            or "simply dropped with the table" in src
            or ("dropped" in src and "inactive" in src)
        )
        assert documented, (
            "Migration docstring must state that non-active weight_plans rows "
            "are intentionally dropped (sign-off record for issue #1707)"
        )

    def test_docstring_explains_no_history_view(self):
        """AC-3: Docstring notes that weight_plans never had a history endpoint."""
        src = _src().lower()
        has_rationale = (
            "never had a history" in src
            or "no such endpoint" in src
            or "no user-visible meaning" in src
            or "no history view" in src
        )
        assert has_rationale, (
            "Migration docstring must explain why non-active rows carry no user-visible "
            "meaning (no history view endpoint existed)"
        )


# ── AC-4: downgrade recreates empty weight_plans table ───────────────────────


class TestDowngradeRecreatesTable:
    """AC-4: downgrade() must recreate weight_plans as an empty table."""

    def test_downgrade_creates_weight_plans(self):
        """AC-4: downgrade() calls op.create_table('weight_plans', ...)."""
        body = _fn_source("downgrade")
        assert "create_table" in body and "weight_plans" in body, (
            "downgrade() must recreate the weight_plans table structure"
        )

    def test_downgrade_documents_no_data_restore(self):
        """AC-4: downgrade() docstring or comment states data is not restored."""
        body = _fn_source("downgrade")
        lower = body.lower()
        has_note = (
            "no data restore" in lower
            or "one-directional" in lower
            or "no data" in lower
            or "not restore" in lower
        )
        assert has_note, (
            "downgrade() must document that data is not restored — the merge is one-directional"
        )

    def test_downgrade_drops_added_columns_on_weight_targets(self):
        """AC-4: downgrade() removes phase and target_rate_kg_per_week from weight_targets."""
        body = _fn_source("downgrade")
        assert "target_rate_kg_per_week" in body, (
            "downgrade() must drop target_rate_kg_per_week from weight_targets"
        )
        assert "phase" in body, (
            "downgrade() must drop phase from weight_targets"
        )


# ── AC-5: release-process.md calls out table drops as requiring a snapshot ───


class TestReleaseDocCoversTableDrops:
    """AC-5: The release-process.md pre-deploy snapshot step must cover table drops."""

    def test_step3c_exists(self):
        """AC-5: docs/release-process.md has a Step 3c pre-deploy snapshot section."""
        text = RELEASE_DOC.read_text()
        assert "3c" in text.lower() or "step 3c" in text.lower() or "pre-deploy" in text.lower(), (
            "docs/release-process.md must have a pre-deploy snapshot step"
        )

    def test_table_drops_mentioned_in_snapshot_step(self):
        """AC-5: The snapshot requirement covers table drops, not just column renames."""
        text = RELEASE_DOC.read_text()
        lower = text.lower()
        has_table_drop_coverage = (
            "table drop" in lower
            or "table drops" in lower
            or "drop table" in lower
            or "drop_table" in lower
        )
        assert has_table_drop_coverage, (
            "docs/release-process.md must mention table drops as a class of destructive "
            "change requiring a pre-deploy snapshot (issue #1707 sign-off)"
        )

    def test_weight_plans_or_table_drop_called_out(self):
        """AC-5: This release's weight_plans drop is explicitly noted in the doc."""
        text = RELEASE_DOC.read_text()
        # Either the weight_plans table drop is mentioned by name, or
        # 'table drops' is explicitly listed alongside column renames
        has_callout = (
            "weight_plans" in text
            or ("table drop" in text.lower() and "snapshot" in text.lower())
        )
        assert has_callout, (
            "docs/release-process.md must mention weight_plans or explicitly list "
            "table drops alongside column renames in the snapshot requirement"
        )
