#!/usr/bin/env bash
# deploy-stop.sh — stop the background perf-coach UAT server started by
# deploy-start.sh (Commander Deploy tab's Stop button).
#
# Kills the PID recorded in uat.pid (and any child), then frees the port as a
# fallback. Always exits 0 so "stop when already stopped" is not an error.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."   # scripts/ -> repo root

export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

PID_FILE="uat.pid"
PORT=9001
if [ -f .env ]; then
  set -a; . ./.env; set +a
  PORT="${PORT:-9001}"
fi

stopped=0
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    pkill -P "$PID" 2>/dev/null || true
    stopped=1
  fi
  rm -f "$PID_FILE"
fi

# Fallback: free the configured port if anything still holds it.
LIST="$(lsof -ti ":$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$LIST" ]; then
  # shellcheck disable=SC2086
  kill $LIST 2>/dev/null || true
  stopped=1
fi

if [ "$stopped" = "1" ]; then
  echo "perf-coach UAT stopped."
else
  echo "perf-coach UAT was not running."
fi
