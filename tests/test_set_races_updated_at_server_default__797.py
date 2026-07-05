"""Tests for issue #797: Set DB-level DEFAULT now() on races.updated_at.

Acceptance criteria verified:
- AC1: A new migration file exists that executes
       ALTER TABLE races ALTER COLUMN updated_at SET DEFAULT now().
- AC2: The migration includes an idempotency guard via inspector.get_columns.
- AC3: The downgrade() function drops the default
       (ALTER TABLE races ALTER COLUMN updated_at DROP DEFAULT).
- AC4: Inserting a Race row without updated_at produces a non-NULL timestamp
       (UAT DB required; skipped otherwise).
- AC5: The ORM model's server_default=text("now()") is present on
       Race.updated_at (no model changes needed).
"""
import os
import pathlib

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.models import Race

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = (
    _env_vals.get("DATABASE_URL_UAT")
    or os.environ.get("DATABASE_URL_UAT")
)
_engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None

_MIGRATION_DIR = _ROOT / "alembic" / "versions"


# ── AC1: migration file exists and contains the correct SQL ──────────────────

def test_ac1_migration_file_exists():
    """AC1: A migration file with the correct revision ID exists."""
    files = list(_MIGRATION_DIR.glob("f31dde78c681_*.py"))
    assert files, (
        "Migration f31dde78c681 not found under alembic/versions/. "
        "Expected file: "
        "f31dde78c681_set_races_updated_at_server_default.py"
    )


def test_ac1_migration_contains_alter_column_set_default():
    """AC1: upgrade() contains the ALTER TABLE ... SET DEFAULT now() stmt."""
    files = list(_MIGRATION_DIR.glob("f31dde78c681_*.py"))
    assert files, "Migration f31dde78c681 not found"
    src = files[0].read_text()
    assert (
        "ALTER TABLE races ALTER COLUMN updated_at SET DEFAULT now()"
        in src
    ), (
        "upgrade() must contain: "
        "ALTER TABLE races ALTER COLUMN updated_at SET DEFAULT now()"
    )


# ── AC2: idempotency guard present in the migration source ───────────────────

def test_ac2_migration_has_idempotency_guard():
    """AC2: Migration uses inspector.get_columns to guard re-running."""
    files = list(_MIGRATION_DIR.glob("f31dde78c681_*.py"))
    assert files, "Migration f31dde78c681 not found"
    src = files[0].read_text()
    assert "get_columns" in src, (
        "upgrade() must inspect current column defaults via "
        "inspector.get_columns"
    )


def test_ac2_db_updated_at_has_default_after_migration():
    """AC2 (UAT): races.updated_at has a DB-level DEFAULT after migration."""
    if _engine is None:
        pytest.skip(
            "DATABASE_URL_UAT not configured — skipping live DB test"
        )
    with _engine.connect() as conn:
        row = conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'races' "
            "AND column_name = 'updated_at'"
        )).fetchone()
    assert row is not None, "races.updated_at column not found in DB"
    assert row[0] is not None, (
        "races.updated_at must have a DB-level DEFAULT after migration; "
        "got NULL — migration f31dde78c681 may not have been applied"
    )
    assert "now" in str(row[0]).lower(), (
        "races.updated_at DEFAULT must reference now(), got: "
        + str(row[0])
    )


# ── AC3: downgrade() drops the default ───────────────────────────────────────

def test_ac3_migration_downgrade_drops_default():
    """AC3: The migration's downgrade() body contains DROP DEFAULT."""
    files = list(_MIGRATION_DIR.glob("f31dde78c681_*.py"))
    assert files, "Migration f31dde78c681 not found"
    src = files[0].read_text()
    assert (
        "ALTER TABLE races ALTER COLUMN updated_at DROP DEFAULT" in src
    ), (
        "downgrade() must contain: "
        "ALTER TABLE races ALTER COLUMN updated_at DROP DEFAULT"
    )


def test_ac3_downgrade_function_exists():
    """AC3: The migration module defines a downgrade() function."""
    files = list(_MIGRATION_DIR.glob("f31dde78c681_*.py"))
    assert files, "Migration f31dde78c681 not found"
    src = files[0].read_text()
    assert "def downgrade()" in src, (
        "Migration must define a downgrade() function"
    )


# ── AC4: inserting without updated_at gives non-NULL timestamp ───────────────

def test_ac4_insert_without_updated_at_gives_nonnull_timestamp():
    """AC4 (UAT): A new Race without updated_at stores a non-NULL stamp."""
    if _engine is None:
        pytest.skip(
            "DATABASE_URL_UAT not configured — skipping live DB test"
        )

    with _engine.connect() as conn:
        user_row = conn.execute(
            text("SELECT id FROM users WHERE name = 'Alice'")
        ).fetchone()
    if user_row is None:
        pytest.skip("Alice user not found — seed not run?")
    user_id = user_row[0]

    with Session(_engine) as session:
        race = Race(
            user_id=user_id,
            name="797 updated_at default test",
            race_date="2099-12-31",
            distance_km=10,
            goal_time_seconds=3600,
            priority="C",
            status="planned",
        )
        # Do NOT pass updated_at — the DB default must supply it
        session.add(race)
        session.flush()
        race_id = race.id
        # Expire so SQLAlchemy reloads from DB on next access
        session.expire(race)
        reloaded = session.get(Race, race_id)
        assert reloaded is not None
        assert reloaded.updated_at is not None, (
            "updated_at must be non-NULL after INSERT — "
            "DB DEFAULT now() not applied. "
            "Migration f31dde78c681 may not have been run."
        )
        session.delete(reloaded)
        session.commit()


# ── AC5: ORM model server_default is consistent ──────────────────────────────

def test_ac5_orm_model_has_server_default_on_updated_at():
    """AC5: Race.updated_at declares server_default=text("now()")."""
    col = Race.__table__.c["updated_at"]
    assert col.server_default is not None, (
        "Race.updated_at must declare server_default in the ORM model"
    )
    sd_text = str(col.server_default.arg).lower()
    assert "now()" in sd_text, (
        "Race.updated_at server_default must reference now(), got: "
        + repr(sd_text)
    )


def test_ac5_orm_model_has_onupdate_on_updated_at():
    """AC5: Race.updated_at ORM column also declares onupdate=text("now()")."""
    col = Race.__table__.c["updated_at"]
    assert col.onupdate is not None, (
        "Race.updated_at must declare onupdate in the ORM model"
    )
    ou_text = str(col.onupdate.arg).lower()
    assert "now()" in ou_text, (
        "Race.updated_at onupdate must reference now(), got: "
        + repr(ou_text)
    )
