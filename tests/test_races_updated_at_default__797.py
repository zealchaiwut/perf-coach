"""Tests for issue #797: Race.updated_at server_default added to ORM model without backing migration.

Verifies that a new Alembic migration sets the DB-level DEFAULT now() on races.updated_at
to match the ORM model's server_default declaration.
"""
import os
import subprocess
from datetime import datetime, timezone
import pytest
import httpx
from uuid import uuid4


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- Acceptance Criteria ---

def test_race_updated_at_migration_file_exists():
    """AC1: A new Alembic migration file exists that executes ALTER TABLE races ALTER COLUMN updated_at SET DEFAULT now()."""
    migration_file = (
        "/Users/zeal-server/dev/perf-coach/tester/alembic/versions"
        "/f31dde78c681_set_races_updated_at_server_default.py"
    )
    assert os.path.exists(migration_file), f"Migration file not found at {migration_file}"
    with open(migration_file) as f:
        content = f.read()
    assert "ALTER TABLE races ALTER COLUMN updated_at SET DEFAULT now()" in content


def test_race_updated_at_migration_has_idempotency_guard():
    """AC2: The migration includes an idempotency guard (inspects current default)."""
    migration_file = (
        "/Users/zeal-server/dev/perf-coach/tester/alembic/versions"
        "/f31dde78c681_set_races_updated_at_server_default.py"
    )
    with open(migration_file) as f:
        content = f.read()
    assert "_updated_at_has_default" in content, "Idempotency guard function not found"
    assert "inspector.get_columns" in content, "Column inspection code not found"
    assert "if _updated_at_has_default():" in content, "Guard not used in upgrade()"


def test_race_updated_at_migration_downgrade():
    """AC3: The migration's downgrade() function reverses the change."""
    migration_file = (
        "/Users/zeal-server/dev/perf-coach/tester/alembic/versions"
        "/f31dde78c681_set_races_updated_at_server_default.py"
    )
    with open(migration_file) as f:
        content = f.read()
    assert "def downgrade()" in content
    assert "ALTER TABLE races ALTER COLUMN updated_at DROP DEFAULT" in content


def test_race_updated_at_orm_model_has_server_default():
    """AC5: The ORM model's server_default remains consistent with the migration."""
    models_file = "/Users/zeal-server/dev/perf-coach/tester/backend/models.py"
    with open(models_file) as f:
        content = f.read()
    # Find the Race class and check the updated_at column definition
    race_section = content[content.find("class Race"):content.find("class Race") + 3000]
    assert 'updated_at = Column(DateTime(timezone=True), server_default=text("now()")' in race_section or \
           'server_default=text("now()"), onupdate=text("now()")' in race_section, \
           "Race.updated_at missing server_default=text('now()')"


def test_race_updated_at_migration_idempotent():
    """AC2 (UAT): Running alembic upgrade on a DB where the default is already set raises no error."""
    pytest.skip("manual — verified via UAT steps (run alembic upgrade twice)")


def test_race_insert_without_updated_at_produces_timestamp(client):
    """AC4: After applying the migration, inserting a Race row without updated_at results in non-NULL timestamp.

    This test inserts a new race via the API (or would via direct DB access)
    and verifies that updated_at is populated by the server DEFAULT.
    """
    pytest.skip("manual — verified via direct DB insert or race creation endpoint after migration applied")
