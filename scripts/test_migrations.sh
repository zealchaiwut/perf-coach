#!/usr/bin/env bash
# Migration idempotency test.
#
# Requires Docker. Spins up a fresh PostgreSQL container, then:
#   Run 1 — applies all migrations from scratch (normal deploy).
#   Run 2 — runs `alembic upgrade head` again; must be a no-op with no errors.
#   Run 3 — simulates the actual bug: one table already exists in the DB but
#            alembic_version has no record of it. upgrade head must still succeed.
#
# Usage:
#   cd <repo-root>/uat
#   bash scripts/test_migrations.sh
#
# Exit codes: 0 = all tests passed, 1 = any test failed.

set -euo pipefail

DB_CONTAINER="perf_coach_migration_test_$$"
DB_NAME="perf_coach_test"
DB_USER="postgres"
DB_PASSWORD="testpass"
DB_PORT="5433"
TEST_DB_URL="postgresql://${DB_USER}:${DB_PASSWORD}@localhost:${DB_PORT}/${DB_NAME}"

cleanup() {
    echo "Cleaning up container..."
    docker rm -f "$DB_CONTAINER" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Starting fresh PostgreSQL container ==="
docker run -d \
    --name "$DB_CONTAINER" \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASSWORD" \
    -e POSTGRES_DB="$DB_NAME" \
    -p "${DB_PORT}:5432" \
    postgres:15

echo "Waiting for PostgreSQL to be ready..."
for i in $(seq 1 30); do
    if docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" -q 2>/dev/null; then
        echo "PostgreSQL is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: PostgreSQL did not become ready in time." >&2
        exit 1
    fi
    sleep 1
done

export ENVIRONMENT=PRD
export DATABASE_URL_PRD="$TEST_DB_URL"
export DATABASE_URL_UAT=""

echo ""
echo "=== Run 1: fresh DB — all migrations from scratch ==="
uv run alembic upgrade head
echo "PASS: Run 1 succeeded."

echo ""
echo "=== Run 2: already-migrated DB — must be a no-op ==="
uv run alembic upgrade head
echo "PASS: Run 2 succeeded (idempotency confirmed)."

echo ""
echo "=== Run 3: simulate orphan table (bug reproduction) ==="
# Delete the alembic_version record for d4e5f6a7b8c9 to simulate a failed
# migration commit, then verify upgrade head still succeeds even though
# workout_exercises already exists in the DB.
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" \
    -c "DELETE FROM alembic_version WHERE version_num = 'd4e5f6a7b8c9';" \
    -c "UPDATE alembic_version SET version_num = 'c3d4e5f6a7b8';"

# Now workout_exercises exists in the DB but alembic thinks we're at c3d4e5f6a7b8
# Running upgrade head must not fail with DuplicateTable.
uv run alembic upgrade head
echo "PASS: Run 3 succeeded (orphan table handled gracefully)."

echo ""
echo "=== All migration tests passed ==="
