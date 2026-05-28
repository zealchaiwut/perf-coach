# perf-coach

Personal performance dashboard. Tracks weight, habits, readiness, training log, and performance trends.

## PRD vs UAT environments

perf-coach runs against two isolated [Neon](https://neon.tech) Postgres branches:

| Environment | Port | Neon branch | Purpose |
|---|---|---|---|
| PRD | 9000 | `main` (prd) | Production data |
| UAT | 9001 | `uat` | Testing / staging |

Both environments run independently and can be started in parallel — they use different ports and different Neon connection strings, so there are no resource conflicts.

### Setup

1. Create a project on [neon.tech](https://neon.tech) named `perf-coach`.
2. Create two branches: one called `main` (or whatever you name the default) for PRD and one called `uat`.
3. Copy the connection strings for each branch from Neon → Connection Details.
4. Populate `.env.prd` and `.env.uat` at the project root:

**.env.prd:**

    ENVIRONMENT=PRD
    PORT=9000
    DATABASE_URL_PRD=<your prd branch connection string>
    DATABASE_URL_UAT=<your uat branch connection string>

**.env.uat:**

    ENVIRONMENT=UAT
    PORT=9001
    DATABASE_URL_UAT=<your uat branch connection string>
    DATABASE_URL_PRD=<your prd branch connection string>

5. Install Python dependencies:

       pip install -r requirements.txt

### Starting each environment

**PRD** (terminal 1):

    ./start_prd.sh

Visits: http://localhost:9000

**UAT** (terminal 2, can run at the same time):

    ./start_uat.sh

Visits: http://localhost:9001

Each script:
- Validates required env vars and exits with a clear error if any are missing
- Verifies the Neon DB is reachable (exits with "DB unreachable" if not)
- Runs `alembic upgrade head` against the correct Neon branch
- Starts uvicorn on the configured port

### What each environment is for

- **PRD** — real data, the source of truth. Treat it carefully.
- **UAT** — for testing new features before promoting to PRD. Data here can be wiped freely. Because Neon branches are completely isolated, data written to UAT never appears in PRD.

## API

| Endpoint | Description |
|---|---|
| `GET /api/environment` | Returns `{"environment": "PRD"\|"UAT", "version": "0.1.0"}` |
| `GET /api/health` | Returns DB connection status |
| `GET /api/users` | Returns list of users |
| `GET /training_log` | Returns training log entries; pass `include_rest=true` to include rest days |
| `GET /trends/summary` | Returns trend aggregations (readiness, HRV, RHR, sleep, energy, mood, TSS) for a date range |
| `GET /api/readiness/today` | Returns today's computed readiness score for a user |
| `GET /api/readiness` | Returns readiness scores over a date range |
| `POST /api/readiness/compute` | Computes and stores today's readiness score |

The frontend reads `/api/environment` on every page load to display the environment badge in the header. No hostname/port heuristic is used.

## Database migrations (Alembic)

Migrations live in `alembic/versions/`. The connection string is chosen from `DATABASE_URL_PRD` or `DATABASE_URL_UAT` based on the `ENVIRONMENT` env var.

**Apply migrations manually:**

    ENVIRONMENT=UAT alembic upgrade head   # against uat branch
    ENVIRONMENT=PRD alembic upgrade head   # against prd branch

The startup scripts run `alembic upgrade head` automatically, so you normally don't need to run this by hand.

**Generate a new migration after editing `backend/models.py`:**

    make migrate MSG="your description here"

**Roll back the last migration:**

    alembic downgrade -1

## Static-only (no backend)

### With the FastAPI backend (recommended)

1. Copy `.env.example` to `.env` and fill in your Neon connection strings:

       cp .env.example .env

2. Install Python dependencies:

       pip install -r requirements.txt

3. Start the server:

       ./run.sh

4. Visit http://localhost:8000

The server serves the static HTML pages and exposes `/api/health` to verify the DB connection.

## Database migrations (Alembic)

Migrations live in `alembic/versions/`. The connection string is read from the `DATABASE_URL_PRD` or `DATABASE_URL_UAT` env var based on `ENVIRONMENT`.

**Apply migrations (run automatically by `./run.sh`):**

    alembic upgrade head

**Generate a new migration after editing `backend/models.py`:**

    make migrate MSG="your description here"

**Roll back the last migration:**

    alembic downgrade -1

**Apply to both UAT and PRD Neon branches:**

1. Apply to UAT first and verify in the Neon dashboard:

       ENVIRONMENT=UAT alembic upgrade head

2. Once verified, apply to PRD:

       ENVIRONMENT=PRD alembic upgrade head

### Static-only (no backend)

Open `index.html` in a browser, or serve the directory:

    python3 -m http.server 8080

Then visit http://localhost:8080

Note: the environment badge will fall back to "DEV" when running without the backend.
