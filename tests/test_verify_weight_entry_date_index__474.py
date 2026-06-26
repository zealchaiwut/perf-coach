"""
Tests for issue #474: Verify WeightEntry.entry_date is indexed for large datasets.

AC: The composite index ix_weight_entries_user_entry_date on (user_id, entry_date)
must exist both in the SQLAlchemy model declaration and in the live database so
that the range=ALL query — which orders by entry_date to find the earliest row —
is protected against sequential scans.
"""
import os

import pytest
from sqlalchemy import Index, text

from backend.db import engine
from backend.models import WeightEntry

# DB-level index tests require Postgres; skip when DATABASE_URL points at SQLite.
_DB_URL = os.environ.get("DATABASE_URL", "")
_IS_POSTGRES = "postgres" in _DB_URL or "postgresql" in _DB_URL
requires_postgres = pytest.mark.skipif(
    not _IS_POSTGRES,
    reason="Postgres-specific catalog query; skipped in SQLite local-dev environment",
)


# ── AC1: index declared in SQLAlchemy model ────────────────────────────────────

def test_index_declared_in_model():
    """WeightEntry.__table_args__ must contain the composite index on (user_id, entry_date)."""
    index_names = {
        arg.name
        for arg in WeightEntry.__table_args__
        if isinstance(arg, Index)
    }
    assert "ix_weight_entries_user_entry_date" in index_names, (
        "Index 'ix_weight_entries_user_entry_date' is missing from "
        "WeightEntry.__table_args__ in backend/models.py"
    )


def test_index_covers_user_id_and_entry_date():
    """The declared index must cover both user_id and entry_date columns (in that order)."""
    target = next(
        (
            arg
            for arg in WeightEntry.__table_args__
            if isinstance(arg, Index) and arg.name == "ix_weight_entries_user_entry_date"
        ),
        None,
    )
    assert target is not None, "Index 'ix_weight_entries_user_entry_date' not found in model"

    col_names = [c.key for c in target.columns]
    assert col_names == ["user_id", "entry_date"], (
        f"Expected index columns ['user_id', 'entry_date'], got {col_names}"
    )


# ── AC2: index exists in the live database ────────────────────────────────────

@requires_postgres
def test_index_exists_in_database():
    """Index ix_weight_entries_user_entry_date must be present in the live DB (pg_indexes)."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE schemaname = 'public' "
            "  AND tablename = 'weight_entries' "
            "  AND indexname = 'ix_weight_entries_user_entry_date'"
        )).scalar()
    assert count == 1, (
        "Index 'ix_weight_entries_user_entry_date' not found in the database. "
        "Run 'alembic upgrade head' to apply all migrations."
    )


@requires_postgres
def test_index_includes_entry_date_column_in_database():
    """Live DB: the index must cover the entry_date column (confirmed via pg_index catalog)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'weight_entries'
              AND indexname = 'ix_weight_entries_user_entry_date'
            """
        )).fetchone()
    assert row is not None, "Index 'ix_weight_entries_user_entry_date' not found"
    assert "entry_date" in row[0], (
        f"entry_date not found in index definition: {row[0]}"
    )


# ── AC3: entry_date column is NOT NULL (required for an index to be useful) ───

@requires_postgres
def test_entry_date_is_not_nullable_in_database():
    """weight_entries.entry_date must be NOT NULL so every row is covered by the index."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = 'weight_entries' "
            "  AND column_name = 'entry_date'"
        )).fetchone()
    assert row is not None, "Column 'entry_date' not found in weight_entries"
    assert row[0] == "NO", (
        "entry_date must be NOT NULL so all rows are covered by the index"
    )
