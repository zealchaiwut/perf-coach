#!/usr/bin/env bash
# LOCAL DEV ONLY — Render uses render.yaml, not this script.
set -euo pipefail

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in values." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [ "${ENVIRONMENT:-}" != "uat" ]; then
  echo "ERROR: ENVIRONMENT must be 'uat' in .env to run this script." >&2
  exit 1
fi

CONFIGURED_PORT=9001

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set in .env." >&2
  exit 1
fi

# Log target DB host (not password)
python3 - <<'EOF'
import os, sys
from urllib.parse import urlparse
url = os.environ.get("DATABASE_URL", "")
host = urlparse(url).hostname or "(unknown)"
print(f"Target DB host (UAT): {host}")
EOF

echo "Verifying database connection (UAT)..."
python3 - <<'EOF'
import os, sys
from sqlalchemy import create_engine, text
url = os.environ["DATABASE_URL"]
try:
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("DB connection: ok")
except Exception as e:
    print(f"ERROR: DB unreachable — {e}", file=sys.stderr)
    sys.exit(1)
EOF

# Select an available port, falling back to a random free port if configured port is occupied
PORT=$(python3 - "$CONFIGURED_PORT" <<'EOF'
import socket
import random
import sys

RESERVED_PORTS = {21, 22, 23, 25, 80, 443, 1433, 1521, 3000, 3306, 5432, 6379, 8080, 8443, 27017}
MAX_RETRIES = 100

def is_port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False

configured_port = int(sys.argv[1])

if is_port_free(configured_port):
    print(configured_port)
    sys.exit(0)

for _ in range(MAX_RETRIES):
    port = random.randint(1024, 65535)
    if port not in RESERVED_PORTS and is_port_free(port):
        print(port)
        sys.exit(0)

print("ERROR: Unable to find a free port after 100 attempts", file=sys.stderr)
sys.exit(1)
EOF
)

export PORT
echo "Server listening on port $PORT"

source .venv/bin/activate

echo "Applying database migrations (UAT)..."
uv run alembic upgrade head

exec uv run uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
