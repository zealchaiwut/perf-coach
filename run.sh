#!/usr/bin/env bash
set -euo pipefail

# Load .env if present
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

ENVIRONMENT="${ENVIRONMENT:-PRD}"
PORT="${PORT:-8000}"

# Validate required env vars
if [ -z "${DATABASE_URL_PRD:-}" ]; then
  echo "ERROR: DATABASE_URL_PRD is not set. Copy .env.example to .env and fill in your Neon connection strings." >&2
  exit 1
fi

if [ -z "${DATABASE_URL_UAT:-}" ]; then
  echo "ERROR: DATABASE_URL_UAT is not set. Copy .env.example to .env and fill in your Neon connection strings." >&2
  exit 1
fi

export ENVIRONMENT PORT DATABASE_URL_PRD DATABASE_URL_UAT

echo "Applying database migrations (ENVIRONMENT=$ENVIRONMENT)..."
alembic upgrade head

echo "Seeding database..."
python backend/seed.py

echo "Starting perf-coach backend (ENVIRONMENT=$ENVIRONMENT) on http://localhost:$PORT"
exec uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
