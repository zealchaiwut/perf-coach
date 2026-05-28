#!/usr/bin/env bash
# Test that all migrations are idempotent and alembic has exactly one head.
#
# Usage:
#   TEST_DATABASE_URL=postgresql://user:pass@host/db bash scripts/test_migrations.sh
#
# Requires a throwaway Postgres database — this script resets it completely.
# Never point this at UAT or PRD data.
set -euo pipefail

if [ -z "${TEST_DATABASE_URL:-}" ]; then
  echo "ERROR: TEST_DATABASE_URL env var required." >&2
  echo "       Point it at a throwaway Postgres DB, e.g.:" >&2
  echo "       TEST_DATABASE_URL=postgresql://... bash scripts/test_migrations.sh" >&2
  exit 1
fi

export DATABASE_URL_PRD="$TEST_DATABASE_URL"
export ENVIRONMENT=PRD

PASS=0
FAIL=0

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

# Drop all tables and alembic_version so each test starts from a clean slate.
reset_db() {
  python3 - <<'PYEOF'
import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL_PRD"])
with engine.connect() as conn:
    conn.execute(text("DROP SCHEMA public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
    conn.commit()
PYEOF
}

# ── Test 1: alembic upgrade head twice on a fresh DB ─────────────────────────
echo ""
echo "=== Test 1: double alembic upgrade head on fresh DB ==="
reset_db
alembic upgrade head

SECOND_OUT=$(alembic upgrade head 2>&1)
if echo "$SECOND_OUT" | grep -q "Running upgrade"; then
  fail "second upgrade applied unexpected migration steps"
else
  pass "second upgrade applied no new migrations"
fi

# ── Test 2: upgrade head when daily_readiness pre-exists ─────────────────────
echo ""
echo "=== Test 2: alembic upgrade head with pre-existing daily_readiness ==="
reset_db
python3 - <<'PYEOF'
import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL_PRD"])
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    conn.execute(text("""
        CREATE TABLE daily_readiness (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL,
            date        DATE NOT NULL,
            score       NUMERIC(5,2) NOT NULL,
            components  JSONB NOT NULL,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            daily_metric_id UUID
        )
    """))
    conn.commit()
PYEOF

if alembic upgrade head 2>&1; then
  pass "upgrade head with pre-existing daily_readiness exits 0"
else
  fail "upgrade head with pre-existing daily_readiness failed"
fi

# ── Test 3: alembic heads returns exactly one head ───────────────────────────
echo ""
echo "=== Test 3: alembic heads returns exactly one head ==="
HEAD_COUNT=$(alembic heads 2>/dev/null | grep -c "(head)" || true)
if [ "$HEAD_COUNT" -eq 1 ]; then
  pass "alembic heads returns exactly one head"
else
  fail "alembic heads returned $HEAD_COUNT heads (expected 1)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
