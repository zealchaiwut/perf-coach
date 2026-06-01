# Local Development Guide

End-to-end setup guide for running perf-coach locally. Target: working app in under 15 minutes from `git clone`.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | **3.12** | Required. Use `asdf` or `pyenv` to manage versions. |
| uv | latest | Used by `start_uat.sh` to run uvicorn and alembic. Install via Homebrew: `brew install uv` or `pip install uv`. |
| PostgreSQL / Neon | n/a | A Neon project (cloud Postgres) is the supported DB. Local Postgres works too — see [Database Setup](#database-setup). |
| psql | any | Optional, useful for inspecting the DB interactively. |

### Install Python 3.12 with asdf

```bash
asdf plugin add python
asdf install python 3.12.13
asdf local python 3.12.13   # writes .tool-versions in the repo root
```

### Install Python 3.12 with pyenv

```bash
pyenv install 3.12.13
pyenv local 3.12.13         # writes .python-version in the repo root
```

---

## Initial Setup

```bash
# 1. Clone
git clone https://github.com/zealchaiwut/perf-coach.git
cd perf-coach

# 2. Create virtualenv
python3.12 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .\.venv\Scripts\activate  # Windows (not officially supported)

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy env template
cp .env.example .env
```

### Configure `.env`

Open `.env` and fill in the values below. Everything else has a working default or is optional for basic development.

| Variable | Required? | Notes |
|----------|-----------|-------|
| `DATABASE_URL_UAT` | **Yes** | Neon UAT branch connection string. See [Database Setup](#database-setup). |
| `DATABASE_URL_PRD` | **Yes** | Neon PRD branch connection string. Script also validates it exists. |
| `ENVIRONMENT` | No | `start_uat.sh` overrides this to `UAT` — leave the placeholder value. |
| `PORT` | No | Overridden to `9001` by `start_uat.sh` — leave the placeholder value. |
| `STRAVA_CLIENT_ID` | No | Only needed for `/api/strava/*` endpoints. |
| `STRAVA_CLIENT_SECRET` | No | Only needed for `/api/strava/*` endpoints. |
| `STRAVA_STATE_SECRET` | No | Only needed for `/api/strava/*` endpoints. |
| `STRAVA_REDIRECT_URI` | No | Defaults to `http://localhost:9001/api/strava/callback`. |
| `STRYD_FERNET_KEY` | No | Only needed for Stryd credential storage/sync. |

---

## Database Setup

### Option A — Neon (recommended)

1. Create a project at [neon.tech](https://neon.tech) named `perf-coach`.
2. Create two branches inside the Neon project: one for UAT and one for PRD.
3. Copy each branch's connection string from **Neon → Connection Details → psql**. The format is:

   ```
   postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require
   ```

4. Paste both strings into `.env`:

   ```
   DATABASE_URL_UAT=postgresql://user:pass@ep-yyy.region.aws.neon.tech/dbname?sslmode=require
   DATABASE_URL_PRD=postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require
   ```

### Option B — Local Postgres

Use a local `postgresql://` URL without `sslmode=require`:

```
DATABASE_URL_UAT=postgresql://postgres:password@localhost:5432/perfcoach_uat
DATABASE_URL_PRD=postgresql://postgres:password@localhost:5432/perfcoach_prd
```

Create the databases first:

```bash
psql -U postgres -c "CREATE DATABASE perfcoach_uat;"
psql -U postgres -c "CREATE DATABASE perfcoach_prd;"
```

### Apply migrations

```bash
source .venv/bin/activate
export ENVIRONMENT=UAT
alembic upgrade head
```

### Seed sample data

```bash
source .venv/bin/activate
export ENVIRONMENT=UAT
python backend/seed.py
```

This creates users Alice, Bob, and Carol with sample habits, workouts, and weight entries. Safe to re-run — it checks for existing data before inserting.

---

## Running the App

```bash
bash start_uat.sh
```

Expected terminal output:

```
Target DB host (UAT): ep-xxx.region.aws.neon.tech
Verifying database connection (UAT)...
DB connection: ok
Server listening on port 9001
Applying database migrations (UAT)...
INFO  [alembic.runtime.migration] Running upgrade ...
INFO:     Started server process [...]
INFO:     Uvicorn running on http://0.0.0.0:9001
```

App is ready at **http://localhost:9001**.

### Verify

```bash
curl http://localhost:9001/api/users
# Expected: [{"id": 1, "name": "Alice"}, ...]
```

If port 9001 is already in use, `start_uat.sh` automatically selects a free port and prints `Server listening on port <N>`.

---

## Running Tests

Tests are live integration tests — they hit the running server. Start the app first (see above), then in a separate terminal:

```bash
source .venv/bin/activate
pytest tests/
```

Test files live in `tests/` and are named `test_<feature>__<issue_number>.py`. Each file targets `http://127.0.0.1:9001`.

To run a single test file:

```bash
pytest tests/test_user_management__16.py -v
```

---

## Common Tasks

### Add a migration

```bash
source .venv/bin/activate
export ENVIRONMENT=UAT

# 1. Edit backend/models.py with your schema change

# 2. Autogenerate the migration
alembic revision --autogenerate -m "describe_your_change"

# 3. Review the generated file in alembic/versions/ — autogenerate is not always
#    perfect. Verify the upgrade/downgrade ops match your intent.

# 4. Apply
alembic upgrade head
```

Always guard new `create_table` / `add_column` operations with existence checks to keep migrations idempotent.

### Add an API endpoint

Edit `backend/main.py`. All endpoints are prefixed `/api/` with hyphens:

```python
# --- My Resource ---

@app.get("/api/my-resource")
async def get_my_resource(user_id: int):
    ...
```

Conventions (from CLAUDE.md):
- Use `user_id` as a query or path param — never assume a single user.
- Date params as ISO `YYYY-MM-DD`. Range endpoints use `from` and `to` query aliases.
- Return `JSONResponse`. Follow the `_*_dict()` helper pattern for shape.
- Return 404 for missing rows, 409 for conflicts, 422 for validation errors, 400 for bad IDs.

### Add a model

Edit `backend/models.py`, then create an Alembic migration (see above). Do not edit the DB by hand.

---

## Troubleshooting

### `DATABASE_URL` format error

**Symptom:** `sqlalchemy.exc.ArgumentError: Could not parse rfc1738 URL`

**Fix:** Ensure the connection string starts with `postgresql://`, not `postgres://`. Neon sometimes shows `postgres://` — replace it.

### Missing env var at startup

**Symptom:** `ERROR: DATABASE_URL_UAT is not set in .env.` or `RuntimeError: DATABASE_URL_UAT env var is not set`

**Fix:** Check `.env` exists in the repo root (not inside `backend/`) and that `DATABASE_URL_UAT` is set to a non-empty value.

### Port 9001 already in use

**Symptom:** `start_uat.sh` prints `Server listening on port 9XXX` instead of 9001.

**Cause:** Something else is bound to 9001. The script auto-selects a free port.

**Fix:** Either stop the conflicting process (`lsof -i :9001` then `kill <PID>`) or use the alternate port shown in the output.

### Migration head mismatch

**Symptom:** `alembic.util.exc.CommandError: Can't locate revision identified by '...'` or multiple heads detected.

**Fix:**
```bash
alembic heads          # list current heads
alembic history        # view full migration graph
alembic upgrade head   # re-run; if multiple heads, create a merge migration
alembic merge heads -m "merge_heads"
alembic upgrade head
```

### Missing pip packages

**Symptom:** `ModuleNotFoundError: No module named 'fastapi'` (or similar).

**Fix:** Ensure the venv is activated before running anything:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Check you're not accidentally using the system Python: `which python3` should point inside `.venv/`.

### `uv: command not found`

**Symptom:** `start_uat.sh` fails with `uv: command not found`.

**Fix:** Install uv:
```bash
brew install uv          # macOS via Homebrew
# OR
pip install uv           # via pip
```
