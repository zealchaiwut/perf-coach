# perf-coach

Personal performance dashboard. Tracks weight, habits, readiness, training log, and performance trends.

## Canonical working directory

**Use a single clone of this repository.** Environment selection is branch-based:

| Branch | Environment | Port | Neon branch | Purpose |
|--------|-------------|------|-------------|---------|
| `develop` | UAT | 9001 | `uat` | Testing / staging |
| `main` | PRD | 9000 | `main` (prd) | Production data |

> **Warning:** Do not maintain parallel checkouts (e.g. `perf-coach/uat/` and
> `perf-coach/main/` as separate directories). Changes in one directory are
> invisible to the other, causing config drift, missed fixes, and migration
> conflicts. Use `git checkout develop` / `git checkout main` in a single clone
> to switch environments.

## Setup

1. Create a project on [neon.tech](https://neon.tech) named `perf-coach`.
2. Create two branches: one called `main` (or whatever you name the default) for PRD and one called `uat`.
3. Copy the connection strings for each branch from Neon → Connection Details.
4. Populate a single `.env` at the project root with **both** connection strings:

**.env:**

    DATABASE_URL_PRD=<your prd branch connection string>
    DATABASE_URL_UAT=<your uat branch connection string>

5. Install Python dependencies:

       pip install -r requirements.txt

## Starting each environment

Check out the branch for the environment you want, then run the matching script:

**UAT** (`develop` branch):

    git checkout develop
    ./start_uat.sh

Visits: http://localhost:9001

**PRD** (`main` branch):

    git checkout main
    ./start_prd.sh

Visits: http://localhost:9000

Each script:
- Sources `.env` for database credentials (`DATABASE_URL_UAT` / `DATABASE_URL_PRD`)
- Sets `ENVIRONMENT` and `PORT` explicitly (overrides anything in `.env`)
- Logs the target DB **host** (not password) before running migrations
- Verifies the Neon DB is reachable (exits with "DB unreachable" if not)
- Runs `alembic upgrade head` against the correct Neon branch
- Starts uvicorn on the configured port

## What each environment is for

- **PRD** — real data, the source of truth. Treat it carefully.
- **UAT** — for testing new features before promoting to PRD. Data here can be wiped freely. Because Neon branches are completely isolated, data written to UAT never appears in PRD.

## API

| Endpoint | Description |
|---|---|
| `GET /api/environment` | Returns `{"environment": "PRD"\|"UAT", "version": "0.1.0"}` |
| `GET /api/health` | Returns DB connection status |
| `GET /api/users` | Returns list of users |
| `GET /api/training-log` | Returns training log entries with workout details (distance, duration, HR, elevation, pace); supports `from`, `to`, `types`, `search`, `include_rest` query params |
| `GET /trends/summary` | Returns trend aggregations (readiness, HRV, RHR, sleep, energy, mood, TSS) for a date range |
| `GET /api/readiness/today` | Returns today's computed readiness score for a user |
| `GET /api/readiness` | Returns readiness scores over a date range |
| `POST /api/readiness/compute` | Computes and stores today's readiness score |

The frontend reads `/api/environment` on every page load to display the environment badge in the header. No hostname/port heuristic is used.

## Database migrations (Alembic)

Migrations live in `alembic/versions/`. The connection string is chosen from `DATABASE_URL_PRD` or `DATABASE_URL_UAT` based on the `ENVIRONMENT` env var.

All migrations are idempotent — each `op.create_table`, `op.create_index`,
`op.add_column`, and corresponding drop is guarded by an existence check, so
running `alembic upgrade head` on a database that is already at head (or
partially ahead) exits 0 without error.

**Apply migrations manually:**

    ENVIRONMENT=UAT alembic upgrade head   # against uat branch
    ENVIRONMENT=PRD alembic upgrade head   # against prd branch

The startup scripts run `alembic upgrade head` automatically, so you normally don't need to run this by hand.

**Generate a new migration after editing `backend/models.py`:**

    make migrate MSG="your description here"

**Roll back the last migration:**

    alembic downgrade -1

**Test migration idempotency** (requires a throwaway Postgres DB):

    TEST_DATABASE_URL=postgresql://... bash scripts/test_migrations.sh
