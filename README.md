# perf-coach

Personal performance dashboard. Tracks weight and habits.

## Run locally

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
