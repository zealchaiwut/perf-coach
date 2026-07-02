# Prompt: Fix Security & Logic Loopholes

> Paste everything below this line into Claude Code, run from the perf-coach
> repo root on a fresh branch off `develop`.

---

You are working on perf-coach (FastAPI + SQLAlchemy + Postgres/Neon, vanilla-JS
frontend). Read `CLAUDE.md` first and follow its conventions exactly (session
auth via `resolve_user`, `/api/` hyphenated routes, Alembic for any schema
change with random revision ids, tests in `tests/`).

Source of truth for these findings: `docs/reviews/2026-07-architecture-review.md`
§2–§4 and `docs/calculations/*.md`. Line anchors were taken on branch
`review/architecture-docs-2026-07`; re-locate each site before editing.

Create branch `fix/security-loopholes` off `develop`. Work through the tasks
in order; commit per task with a clear message; add/adjust tests for each.

## Task 1 — Lock down unauthenticated user CRUD (highest severity)

In `backend/main.py` (~lines 283, 352, 377, 404):

- `GET /api/users` — currently no auth, enumerates all users with weight/habit
  counts and Strava/Stryd connection status.
- `POST /api/users` — anyone can create users (an admin-guarded duplicate
  already exists ~line 11779).
- `PATCH /api/users/{user_id}` and `DELETE /api/users/{user_id}` — rename or
  delete ANY user with no session; DELETE cascades all their data.

Fix: gate all four behind the existing `require_admin` dependency (see
`backend/auth.py:233` and how `/admin` endpoints use it). If the unauthenticated
POST duplicates the admin one, delete the duplicate instead of guarding both.
Check the frontend (`frontend/js/users.js`, `frontend/pages/users.html`,
admin page) for callers and route them through the admin-cookie flow; do not
break the admin Users screen.

Tests: unauthenticated request → 401/403 for each verb; admin cookie → works.

## Task 2 — IDOR on sync job status

`GET /api/sync/strava/status?job_id=` (`backend/main.py:~9780-9805`) does
`session.get(SyncJob, job_id)` and returns the row (including `user_id` and
`error_message`) with no ownership check.

Fix: after loading the job, verify `job.user_id == user.id` (resolve user via
`resolve_user` like the sibling `/api/sync/history` endpoint ~12113 does);
return 404 (not 403) on mismatch so job ids can't be probed.

Test: user A creates a job row, user B requests it → 404.

## Task 3 — Remove the legacy impersonation shim

`LEGACY_USER_ID_SHIM_ENABLED = False` (`backend/main.py:~458`) guards a path
in `resolve_user` (~461-481) that would accept `?user_id=` to become any user
if the flag were flipped.

Fix: delete the flag and the entire shim branch — `resolve_user` should only
resolve from the session cookie. Grep the repo for `LEGACY_USER_ID_SHIM` and
`user_id` query-param reads in auth paths; remove references and any tests
asserting the shim's existence (replace with a test asserting `?user_id` is
ignored).

## Task 4 — Decorative athlete_id path params

`/api/athletes/{athlete_id}/...` endpoints (`backend/main.py:~11688, 14120,
14393, 14750`) ignore the path id and silently return the session user's data.

Fix: at the top of each, `if athlete_id != user.id: raise HTTPException(404)`.
Do not change response shapes. Update any frontend caller that passes a wrong
or hardcoded id.

## Task 5 — Close the calibration loop

Accepted calibration writes `user_preferences.ctl_days` / `atl_days`
(`backend/main.py:~12777-12780`) but `backend/services/training_load.py`
always uses module constants `CTL_DAYS=42` / `ATL_DAYS=7` — the accepted
values have no effect (see `docs/calculations/training-load.md` weakness 1).

Fix: make `current_load`, `daily_update`, and `compute_load_curves` callers
pass the user's prefs when set (add optional `ctl_days`/`atl_days` params
threaded from a single prefs lookup; default to the constants). Cover every
call site of `current_load`/`daily_update` in main.py and routers/plan.py.
After changing, recompute snapshots is NOT required (they refresh on write),
but note in the commit message that historical snapshots reflect old constants.

Test: set prefs ctl_days=30, create workout, assert snapshot/current values
differ from the 42-day default.

## Task 6 — Fix broken decoupling calls (silent durability disable)

`_workout_signal_scores` (`backend/main.py:~5480-5492`) and
`_athlete_scores_as_of` (~5606-5619) call
`compute_decoupling(split_dicts, {"workout_type": ...})` — the real signature
is `(workout, splits_or_stream, threshold)` returning a tuple
(`backend/services/aerobic_decoupling.py:30-34`). The TypeError is swallowed
by `except Exception: dpct = None`, so durability adjustment is silently off
for log-card and as-of scores while the main `/performance` endpoint
(~14199-14208) calls it correctly.

Fix: correct both call sites to match the working call in the `/performance`
endpoint. Narrow the `except Exception` there to log at warning level instead
of passing silently. Add a regression test that a run with decoupling data
gets a durability-adjusted score through all three paths.

## Task 7 — Fix Plan-cache invalidation on workout edits

`training_plans.computed_cache` signature (`_plan_signature`,
`backend/main.py:~14788-14840`) hashes MAX(workouts.created_at) + COUNT — so
editing an existing workout never invalidates the cache (workouts has no
`updated_at`; see the code comment ~14799).

Fix (two parts):
1. Alembic migration adding `updated_at` to `workouts` (server default now(),
   idempotent guards per CLAUDE.md; `alembic revision -m ...` for a random id),
   plus `onupdate` in the model, plus explicit sets in the PATCH/PUT workout
   endpoints.
2. Include MAX(workouts.updated_at) in `_plan_signature`. Also include
   race-checkpoint MAX(updated_at/created_at) — checkpoint CRUD
   (`backend/routers/plan.py:~315-368`) is currently outside the signature.

Test: warm cache, PATCH a workout field used by the bundle, GET
`/api/plan/computed` → recomputed (signature changed).

## Constraints

- No new dependencies. Match existing error style (401 vs 404 vs 422).
- Every task gets at least one test; run the full test suite before the final
  commit (`tests/` hit a live server per CLAUDE.md — follow that setup).
- Do not refactor beyond the listed fixes; performance and dead-code cleanup
  are separate branches (`fix-performance.md`, `fix-deadcode.md`).
- Finish by summarizing per-task: file(s) touched, test added, anything found
  that diverged from the line anchors above.
