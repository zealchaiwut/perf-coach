#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env.prd ]; then
  echo "ERROR: .env.prd not found. Create it with ENVIRONMENT, PORT, and DATABASE_URL_PRD set." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env.prd
set +a

if [ -z "${DATABASE_URL_PRD:-}" ]; then
  echo "ERROR: DATABASE_URL_PRD is not set in .env.prd." >&2
  exit 1
fi

if [ -z "${PORT:-}" ]; then
  echo "ERROR: PORT is not set in .env.prd." >&2
  exit 1
fi

export ENVIRONMENT=PRD
export PORT DATABASE_URL_PRD DATABASE_URL_UAT

echo "Verifying database connection (PRD)..."
python3 - <<'EOF'
import os, sys
from sqlalchemy import create_engine, text
url = os.environ["DATABASE_URL_PRD"]
try:
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("DB connection: ok")
except Exception as e:
    print(f"ERROR: DB unreachable — {e}", file=sys.stderr)
    sys.exit(1)
EOF

source .venv/bin/activate

echo "Applying database migrations (PRD)..."
uv run alembic upgrade head

echo "Starting perf-coach backend (PRD) on http://localhost:$PORT"
exec uv run uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
