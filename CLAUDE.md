# perf-coach

A personal performance dashboard. Tracks weight, habits, workouts, and daily
wellness metrics (HRV, RHR, sleep, energy, mood) for one or more users.

## Stack

- **Backend:** FastAPI (Python 3.12), served by uvicorn
- **ORM:** SQLAlchemy with declarative models in `backend/models.py`
- **Database:** Postgres (Neon), one DB per environment (UAT / PRD)
- **Migrations:** Alembic (`alembic/` dir, config in `alembic.ini`)
- **Frontend:** Static HTML pages + vanilla JavaScript, served BY FastAPI as
  FileResponse routes. No SPA framework, no bundler. Chart.js via CDN for charts.
- **No build step** for frontend — pages are plain HTML/CSS/JS files under `frontend/`.

## Project Structure

    backend/main.py               FastAPI app — ALL API endpoints live here
    backend/models.py             SQLAlchemy models (source of truth for schema)
    backend/db.py                 Engine, session, environment detection, check_db()
    backend/seed.py               Seed/sample data
    alembic/                      Migrations (versions/ holds migration files)
    alembic.ini                   Alembic config
    frontend/css/styles.css       Shared styles
    frontend/js/                  Page-specific vanilla JS modules
    frontend/pages/               Static HTML pages, each served by a
                                  FileResponse route in main.py

## API Conventions (FOLLOW THESE EXACTLY)

- All API routes are prefixed `/api/` and use HYPHENS, not underscores or slashes:
  e.g. `/api/daily-metrics`, `/api/workouts`, `/api/habits/logs`.
- This is a MULTI-USER app. Almost every endpoint takes `user_id` as a query
  param (or path param). Never assume a single implicit user.
- Date params are ISO `YYYY-MM-DD`. Range endpoints use query aliases `from` and `to`.
- Responses are JSON via `JSONResponse`. Follow the existing `_*_dict()` helper
  pattern in main.py for serialization shape.
- Validation returns HTTP 422 with a field-specific detail; conflicts return 409;
  bad IDs return 400; missing rows return 404. Match the existing style.
- New endpoints go in `backend/main.py` alongside the existing ones, grouped by
  resource with a section comment header.

## Database / Schema

- The schema is defined ONLY in `backend/models.py`. Existing tables:
  `users`, `weight_entries`, `habits`, `habit_logs`, `workouts`,
  `workout_exercises`, `daily_metrics`.
- `workouts` currently has: `workout_date`, `name`, `workout_type`, `remarks`,
  `tss`, `tss_source`, and child `exercises`. It does NOT have distance, pace,
  heart rate, GPS, elevation, or splits. Do not assume those exist.
- `daily_metrics` has: `resting_hr`, `hrv`, `sleep_hours`, `sleep_quality`,
  `energy`, `mood`, `notes`. There is NO readiness score table.
- There is NO personal_records / PR table yet.
- ANY schema change MUST be a new Alembic migration in `alembic/versions/`.
  Never edit the DB by hand. Make migrations idempotent (guard create_table /
  add_column with existence checks).

## Conventions

- Each HTML page loads only the JS it needs. One shared CSS file.
- Env detection lives in `backend/db.py` (UAT vs PRD via env vars).
- Tests live in `tests/`. Add tests for new endpoints.

## Branching

- master = production
- develop = integration
- feature/<N>-<slug> = work branches off develop