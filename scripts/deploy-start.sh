#!/usr/bin/env bash
# deploy-start.sh — launch the perf-coach UAT server as a background daemon for
# the Commander Deploy tab's Start button.
#
# Unlike start_uat.sh (which runs uvicorn in the FOREGROUND for an interactive
# terminal), this returns as soon as the server is launched and records a PID
# file so deploy-stop.sh can stop it. The Commander dashboard runs this via
# `subprocess.run(..., capture_output=True)` and WAITS for it to exit, so it
# must not block — migrations + uvicorn run inside a backgrounded shell so a
# slow database never hangs the Start request.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."   # scripts/ -> repo root

# Homebrew / uv may not be on the dashboard subprocess PATH.
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

[ -f .env ] || { echo "ERROR: .env not found in $(pwd)" >&2; exit 1; }
set -a; . ./.env; set +a

PORT="${PORT:-9001}"
PID_FILE="uat.pid"
LOG_FILE="uat.log"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
  echo "perf-coach UAT already running (PID $(cat "$PID_FILE"))."
  exit 0
fi

if lsof -ti ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: port $PORT is already in use; stop the existing listener first." >&2
  exit 1
fi

# Render injects DATABASE_URL; locally fall back to the UAT-specific var.
if [ -z "${DATABASE_URL:-}" ] && [ -n "${DATABASE_URL_UAT:-}" ]; then
  export DATABASE_URL="$DATABASE_URL_UAT"
fi

echo "Starting perf-coach UAT on :$PORT (background); logs -> $LOG_FILE"

# Background the whole startup (migrations + server). `exec` makes uvicorn take
# over the subshell's PID, so the recorded PID stops the server directly.
nohup bash -c '
  set -e
  source .venv/bin/activate
  echo "[deploy-start] applying migrations (alembic upgrade head)…"
  uv run alembic upgrade head
  echo "[deploy-start] checking schema drift (models vs DB)…"
  # Use the project venv directly: `uv run python` resolves the parent ~/dev
  # workspace env, which lacks the app deps. Abort the deploy ONLY on real
  # drift (exit 1); a guard-internal failure (exit 2 / crash) must warn but
  # never block a deploy.
  if .venv/bin/python scripts/check_schema_drift.py; then
    :
  else
    rc=$?
    if [ "$rc" -eq 1 ]; then
      echo "[deploy-start] ABORT: schema drift detected (see above)." >&2
      exit 1
    fi
    echo "[deploy-start] WARN: schema-drift check could not run (exit $rc); continuing." >&2
  fi
  echo "[deploy-start] launching uvicorn on :'"$PORT"'…"
  exec uv run uvicorn backend.main:app --host 0.0.0.0 --port '"$PORT"'
' > "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
sleep 1
echo "Started (PID $(cat "$PID_FILE")). Tail logs: tail -f $LOG_FILE"
