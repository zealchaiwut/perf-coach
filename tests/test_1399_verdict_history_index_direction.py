"""
Tests for issue #1399: verdict_history index direction drift.

The model declares ix_verdict_history_user_date on (user_id, verdict_date) ASC,
while migration bf3b956dd2e0 creates it as (user_id, verdict_date DESC). This
mismatch causes spurious diffs in future `alembic revision --autogenerate` runs.

Fix: update the model to declare verdict_date with DESC so model and migration agree.

AC coverage:
- AC1: The SQLAlchemy model's ix_verdict_history_user_date declares verdict_date DESC
- AC2: The live database index has verdict_date DESC (Postgres only)
"""
import os

import pytest
from sqlalchemy import Index
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from backend.models import VerdictHistory

_DB_URL = os.environ.get("DATABASE_URL", "")
_IS_POSTGRES = "postgres" in _DB_URL or "postgresql" in _DB_URL
requires_postgres = pytest.mark.skipif(
    not _IS_POSTGRES,
    reason="Postgres-specific catalog query; skipped in SQLite local-dev environment",
)


def _get_verdict_history_index():
    return next(
        (
            arg
            for arg in VerdictHistory.__table_args__
            if isinstance(arg, Index) and arg.name == "ix_verdict_history_user_date"
        ),
        None,
    )


# ── AC1: model declares verdict_date DESC ──────────────────────────────────


def test_ac1_index_exists_in_model():
    """AC1: ix_verdict_history_user_date must be declared in VerdictHistory.__table_args__."""
    idx = _get_verdict_history_index()
    assert idx is not None, (
        "Index 'ix_verdict_history_user_date' missing from VerdictHistory.__table_args__"
    )


def test_ac1_index_compiled_ddl_contains_desc():
    """AC1: The compiled CREATE INDEX DDL for ix_verdict_history_user_date must include DESC.

    Migration bf3b956dd2e0 creates the index as (user_id, verdict_date DESC).
    The model must declare it the same way to prevent autogenerate drift.
    """
    idx = _get_verdict_history_index()
    assert idx is not None, "Index not found in model"

    compiled = str(CreateIndex(idx).compile(dialect=postgresql.dialect()))
    assert "DESC" in compiled.upper(), (
        f"Expected verdict_date DESC in compiled index DDL, got:\n{compiled}"
    )


def test_ac1_index_ddl_covers_user_id_and_verdict_date():
    """AC1: Compiled DDL must reference both user_id and verdict_date."""
    idx = _get_verdict_history_index()
    assert idx is not None, "Index not found in model"

    compiled = str(CreateIndex(idx).compile(dialect=postgresql.dialect()))
    assert "user_id" in compiled, f"user_id missing from index DDL: {compiled}"
    assert "verdict_date" in compiled, f"verdict_date missing from index DDL: {compiled}"


# ── AC2: live database index has DESC ──────────────────────────────────────


@requires_postgres
def test_ac2_live_db_index_exists():
    """AC2: ix_verdict_history_user_date must exist in the live Postgres database."""
    from backend.db import engine
    from sqlalchemy import text

    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE schemaname = 'public' "
            "  AND tablename = 'verdict_history' "
            "  AND indexname = 'ix_verdict_history_user_date'"
        )).scalar()
    assert count == 1, (
        "Index 'ix_verdict_history_user_date' not found in DB. Run 'alembic upgrade head'."
    )


@requires_postgres
def test_ac2_live_db_index_is_desc():
    """AC2: The live DB index definition must contain verdict_date DESC."""
    from backend.db import engine
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' "
            "  AND tablename = 'verdict_history' "
            "  AND indexname = 'ix_verdict_history_user_date'"
        )).fetchone()
    assert row is not None, "Index 'ix_verdict_history_user_date' not found in DB"
    assert "DESC" in row[0].upper(), (
        f"Expected verdict_date DESC in live index definition, got:\n{row[0]}"
    )
