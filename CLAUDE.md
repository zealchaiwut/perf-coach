# perf-coach

A personal performance dashboard. Tracks weight, habits, workouts, and daily
wellness metrics (HRV, RHR, sleep, energy, mood) for one or more users.

Users log in with a username/password session (cookie-based); all data is
per-user and resolved from that session, never a client-supplied id. Workouts
can be pulled from **Strava** and **Stryd** via OAuth / credential integrations,
and a daily **readiness** score is computed from the wellness metrics.

## Stack

- **Backend:** FastAPI (Python 3.12), served by uvicorn
- **ORM:** SQLAlchemy with declarative models in `backend/models.py`
- **Database:** Postgres (Neon), one DB per environment (UAT / PRD)
- **Migrations:** Alembic (`alembic/` dir, config in `alembic.ini`)
- **Frontend:** Static HTML pages + vanilla JavaScript, served BY FastAPI as
  FileResponse routes. No SPA framework, no bundler. Chart.js via CDN for charts.
- **No build step** for frontend — pages are plain HTML/CSS/JS files under `frontend/`.

## Project Structure

    backend/main.py               FastAPI app — most API endpoints live here
    backend/worker_app.py         Standalone compute-worker FastAPI app (port
                                  9100, runs on zeal-server, shares the Neon DB;
                                  never imports main.py) — see docs/worker.md
    backend/routers/              Extracted routers (plan.py, strength_sessions.py)
    backend/models.py             SQLAlchemy models (source of truth for schema;
                                  human-readable reference: root SCHEMA.md)
    backend/auth.py               Password hashing (scrypt) + signed session cookie
    backend/db.py                 Engine, session, environment detection, check_db()
    backend/seed.py               Seed/sample data
    backend/services/             Domain logic: strava.py, stryd.py, crypto.py,
                                  reconcile.py, workout_merge.py, sync_jobs.py,
                                  sync_runner.py (shared sync core used by both
                                  main.py and worker_app.py),
                                  training_load.py, tss.py, …
    backend/utils/                Shared helpers (errors, logging, time)
    scripts/                      One-off CLIs (set_user_password.py, seed_mock_user.py)
    alembic/                      Migrations (versions/ holds migration files)
    alembic.ini                   Alembic config
    frontend/css/styles.css       Shared styles
    frontend/js/                  Page-specific vanilla JS modules; nav.js is the
                                  global nav, injected on every page
    frontend/pages/               Static HTML pages, each served by a
                                  FileResponse route in main.py
    resources/                    Non-code assets (e.g. resources/brand/ app icons)
    docs/calculations/            Formula-level docs for every score/model
                                  (TSS, CTL/ATL/TSB, readiness, projection, …)
                                  with ML-future notes — read before touching
                                  any calculation
    docs/                         Release/setup docs; docs/sprints/ holds sprint plans

## API Conventions (FOLLOW THESE EXACTLY)

- All API routes are prefixed `/api/` and use HYPHENS, not underscores or slashes:
  e.g. `/api/daily-metrics`, `/api/workouts`, `/api/habits/logs`.
- This is a MULTI-USER app with **session auth**. Endpoints derive the user from
  the `resolve_user` dependency (the signed session cookie), NOT a client-supplied
  `user_id`. The legacy `?user_id` shim is OFF (`LEGACY_USER_ID_SHIM_ENABLED =
  False`). Anonymous requests get **401**; never trust a client id for identity,
  and never read/write across users. (A few admin/CLI-style writes still take an
  explicit id in the body — match the surrounding endpoint, don't add new ones.)
- Date params are ISO `YYYY-MM-DD`. Range endpoints use query aliases `from` and `to`.
- Responses are JSON via `JSONResponse`. Follow the existing `_*_dict()` helper
  pattern in main.py for serialization shape.
- Validation returns HTTP 422 with a field-specific detail; conflicts return 409;
  bad IDs return 400; missing rows return 404. Match the existing style.
- New endpoints go in `backend/main.py` alongside the existing ones, grouped by
  resource with a section comment header.

## Database / Schema

- The schema is defined ONLY in `backend/models.py`. Current tables:
  `users`, `weight_entries`, `habits`, `habit_logs`, `workouts`,
  `workout_exercises`, `workout_splits`, `daily_metrics`, `daily_readiness`,
  `personal_records`, `workout_feel`, `sleep_imports`, `training_load_snapshots`,
  `strava_tokens`, `strava_activities`, `stryd_credentials`, `stryd_activities`,
  `google_oauth_credentials`.
- `users` has `name`, `is_admin`, `is_active`, `password_hash`, `avatar`,
  `avatar_mime`, `created_at`.
- `workouts` DOES now have distance/duration/HR/elevation and source links:
  `workout_date`, `name`, `workout_type`, `remarks`, `tss`, `tss_source`,
  `source`, `distance_km`, `duration_seconds`, `avg_hr`, `max_hr`, `elevation_m`,
  `start_time`, `strava_activity_url`, `strava_activity_pk`, `stryd_activity_pk`,
  `manual_overrides`, plus child `workout_exercises` and `workout_splits`.
- `daily_metrics` has `resting_hr`, `hrv`, `sleep_hours`, `sleep_quality`,
  `energy`, `mood`, `notes`. Readiness IS its own table (`daily_readiness`),
  computed from these via `POST /api/readiness/compute`.
- `personal_records` exists (PR tracks). `strava_activities` / `stryd_activities`
  hold raw pulled activities; `reconcile.py` (using `workout_merge.py` helpers)
  reconciles them into `workouts`.
- ANY schema change MUST be a new Alembic migration in `alembic/versions/`.
  Never edit the DB by hand. Make migrations idempotent (guard create_table /
  add_column with existence checks; helpers `column_exists` / `table_exists` in
  `alembic/`). Always create migrations with `alembic revision -m "<msg>"` and
  let Alembic generate the random hex revision id — do NOT hand-author ids or
  continue the old sequential-letter-prefix chain. Hand-picked sequential ids
  caused repeated duplicate-revision / multiple-head collisions when parallel
  feature branches each grabbed the "next letter"; random ids make that nearly
  impossible. If two branches still land separate heads, reconcile with a single
  `alembic merge heads -m "merge_heads"` node (also random-id) — never add a
  second merge node for the same heads. The CI gate
  (`.github/workflows/migrations-check.yml`) blocks any PR with duplicate
  revision ids or more than one head.

## Auth & Sessions

- `backend/auth.py` does password hashing (`hashlib.scrypt`) and a signed
  httpOnly session cookie (HMAC over `SESSION_SECRET`). Endpoints: `POST
  /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST
  /api/auth/change-password`. Login has brute-force lockout.
- Page routes are auth-gated: unauthenticated browser requests to app pages
  redirect to `/login`; API requests get 401. Pages: `/login`, `/settings`
  (Profile / Security / Integrations, reached via the avatar in the nav), `/admin`.
- `/admin` is gated by a per-environment secret word (`ADMIN_SECRET_UAT` /
  `ADMIN_SECRET_PRD`) behind a separate admin cookie + `require_admin`.
- Set a user's password with `scripts/set_user_password.py <username>`.

## Integrations & Sync

- **Strava** (OAuth) and **Stryd** (encrypted credentials via `STRYD_FERNET_KEY`)
  and **Google** (OAuth, off by default). Connect/status/disconnect endpoints
  live in `main.py` (`/api/strava/*`, `/api/stryd/*`, `/api/google/*`) and are
  managed from Settings → Integrations. Tokens/credentials are tied to the
  session user. Reuse the existing OAuth/credential code — do not rebuild it.
- Syncing pulls activities into `strava_activities` / `stryd_activities`, then
  `reconcile.py` merges them into `workouts`. The multi-phase background sync IS
  built (daemon thread per job, phases `pulling_strava` → `pulling_stryd` →
  `reconciling`, with progress polled by the nav status bar). Endpoints: `POST
  /api/strava/sync` starts a job (202; 409 if one is already running for the
  user), `GET /api/sync/status` returns its state. Sync state is an **in-memory
  job registry** (`backend/services/sync_jobs.py`, one job per user, 409
  single-flight), NOT a DB table — intentionally lost on restart, which is safe
  because every upsert is idempotent (`ON CONFLICT DO UPDATE`). **`docs/sync.md`
  is the full reference** (job model, phases, cancel hook, polling cadence).
- The sync core (pull loops + reconcile + plan matcher) lives in
  `backend/services/sync_runner.py` behind a `SyncRecorder` protocol; `main.py`
  drives it with the in-memory registry above, and `backend/worker_app.py`
  (the compute worker on zeal-server, port 9100) drives the same code on a
  schedule, persisting job runs to the `worker_job_runs` table. The heavy
  paths (stream ingest, performance backfill, weekly Banister refit) belong on
  the worker — **`docs/worker.md`** is the reference (endpoints, manual
  trigger, deploy).

## LLM policy — MINIMAL, not zero

The rule is **minimal LLM**. Not "no LLM", and not "LLM wherever it helps" —
the first is false and the second is how this codebase ended up with three
planning paths and three coach-message producers for two jobs (see the
Priority 2 consolidation, PR #1597).

**Exactly two surfaces are sanctioned:**

| Surface | Where | What it does |
|---|---|---|
| **Ask-AI single session** | webapp, interactive | fills ONE session's content once the skeleton has fixed the day/type/TSS |
| **Daily coach message warmth rephrase** | worker, `weekly_coach_message._call_llm_narrative` | rewrites the prose around the deterministic message |

Adding a third needs a decision, not a convenient import.

**Rules that apply to both:**

- **The LLM never produces a number.** Every figure comes from the engines
  (`training_load`, `tss`, `coach_plan`, `coach_projection`). The rephrase is
  guarded by `_numbers_preserved()`, which discards any output whose numerals
  differ from the deterministic text — a warm sentence is not worth a wrong one.
- **Every path falls back.** Disabled provider, network error, malformed
  response, failed validation — all return the deterministic text. The athlete
  always gets a message; an LLM surface must never 500 or block.
- **The LLM never decides.** Verdicts, guardrails, and load decisions are
  computed deterministically upstream and passed in as GIVENS. The LLM explains
  them; it does not derive or override them
  (see `weekly_summary.validate_summary` and `docs/calculations/acwr-guardrail.md`).

**Parked and staying parked in the worker** (Priority 2, D4/D1) — do not
re-import these into `backend/worker_app.py`: `coach_narrative`,
`coach_orch_langgraph`, `coach_claude_cli`, and `gap_analysis/phrasing.py`'s
LLM path. These four are genuinely unreferenced anywhere and pending deletion
after a quiet release. Between them they carried atom validators, retry loops,
a `claude -p` transport, and a second cache — that sprawl is what "minimal"
exists to prevent.

`plan_draft` and `plan_slot_cache` are a different case — **parked from the
worker only, still live in the webapp.** `backend/worker_app.py`'s dispatch
table explicitly does not route to `plan_draft`, but `backend/main.py` and
`backend/routers/projection.py` import it directly, backing the live
`/api/plan/draft*` routes that `frontend/js/training-plan.js` and
`frontend/js/home-coach-strip.js` actually call. Do not delete either module —
they're load-bearing for the Training → Plan draft-review feature.

`tests/test_consolidation__worker_has_no_llm.py` enforces the parked list by
importing `backend.worker_app` in a clean interpreter and inspecting
`sys.modules`.

**Judgment belongs in the paste loop.** The coach export
(`GET /api/coach/export/paste`, `GET /api/coach/consult`) builds a blob the
athlete pastes into Claude themselves. That is not an in-app LLM call and is not
counted here — it is the reason the in-app surface can stay this small.

## Local Development

- Copy `.env.example` to `.env` and fill in values before running locally. Local
  `.env` selects the DB by `ENVIRONMENT` (`uat`/`prd`) and provides
  `DATABASE_URL_UAT` / `DATABASE_URL_PRD` (Render injects a single `DATABASE_URL`
  in prod). Auth/integrations also read `SESSION_SECRET`, `STRAVA_*`, `STRYD_*`,
  `GOOGLE_*`, `ADMIN_SECRET_*` — see `.env.example`.
- The venv is **uv-managed**: install deps with
  `uv pip install --python .venv/bin/python -r requirements.txt`, and run tools as
  `.venv/bin/python` / `.venv/bin/alembic`. Tests need `pytest` + `httpx`.
- `start_uat.sh` / `start_prd.sh` exist but assume lowercase `ENVIRONMENT` and a
  single `DATABASE_URL`; to run directly: source `.env`, export
  `ENVIRONMENT=uat` and `DATABASE_URL=$DATABASE_URL_UAT`, then
  `uvicorn backend.main:app`. Integration tests in `tests/` hit a live server at
  `http://127.0.0.1:9001` and authenticate via a session (set a password, then
  `POST /api/auth/login`).
- **Deprecated:** the old `uat/` + `main/` parallel-checkout pattern (two
  separate clones in sibling directories) is no longer supported. The canonical
  workflow is one clone — switch between `develop` (UAT) and `master` (PRD) via
  `git checkout`.

## Deployment

Deployments are managed by Render via `render.yaml`. See:

- `docs/release-process.md` — step-by-step release procedure
- `docs/render-setup.md` — Render service configuration reference

Do not describe deployment steps inline here; those docs are the source of
truth.

## Conventions

- Each HTML page loads only the JS it needs. One shared CSS file.
- Env detection lives in `backend/db.py` (UAT vs PRD via env vars).
- Tests live in `tests/`. Add tests for new endpoints.

## Branching

- master = production
- develop = integration
- feature/<N>-<slug> = work branches off develop