#!/usr/bin/env bash
# Compute-worker launcher — runs backend.worker_app on zeal-server.
# Shares the same Neon Postgres as the webapp; never imports backend.main.
set -euo pipefail

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in values." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

# Accept ENVIRONMENT case-insensitively; default to uat.
ENVIRONMENT="$(printf '%s' "${ENVIRONMENT:-uat}" | tr '[:upper:]' '[:lower:]')"
export ENVIRONMENT

if [ "$ENVIRONMENT" = "prd" ]; then
  export DATABASE_URL="${DATABASE_URL:-${DATABASE_URL_PRD:-}}"
else
  export DATABASE_URL="${DATABASE_URL:-${DATABASE_URL_UAT:-}}"
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL (or DATABASE_URL_UAT/DATABASE_URL_PRD) is not set in .env." >&2
  exit 1
fi

if [ -z "${WORKER_SHARED_SECRET:-}" ]; then
  echo "WARNING: WORKER_SHARED_SECRET is not set — /internal/* endpoints will return 503." >&2
fi

echo "Compute worker starting (ENVIRONMENT=$ENVIRONMENT, port=${WORKER_PORT:-9100})"

exec .venv/bin/uvicorn backend.worker_app:app --host 0.0.0.0 --port "${WORKER_PORT:-9100}"
