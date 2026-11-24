# PWA phase 0: offline foundations (backend)

**Date:** 2026-11-24
**Sprint label:** sprint-150
**Default labels:** pwa, pwa-phase-0, manual
**Status:** posted

## Context

perf-coach gets a phone app as an installable PWA, so that the Today glance, gym logging and weigh-ins work while the Render free-tier server is asleep or the phone is offline. Phase 0 builds the backend contract that makes this safe:

- writes that are safe to repeat;
- one bundle the phone downloads;
- one sync endpoint the phone sends its queued changes to;
- a long-lived device login;
- a structured session format, so gym mode can run supersets, EMOM, intervals and holds.

Later phases build the app shell (1), the phone Today screen (2), gym mode (3) and the body tracker (5). The run debrief (4) and an Android wrapper (6) are out of scope.

Mocks: `docs/pwa/mocks/source/` (phone frames, 390x844), committed as `7025a5b0`.

**Implementation note:** issues are implemented manually in Cursor, not by Commander agents. Each issue body is the Cursor prompt. The `manual` label marks them as hand-implemented; Commander only dispatches tickets passed to it explicitly, so do not include them in a dispatch call.

**Conventions:**
- The mock owns layout, colours and spacing; the issue owns rules and numbers. Numbers in mocks are illustrative.
- Stack stays as it is: FastAPI, SQLAlchemy 2.0, alembic, vanilla JS (no framework, no build step), pytest.
- One reader per number: TSS, scores, rollups and trend weight come from their existing services. The phone never becomes a second source of truth.
- Free-tier rule: the server (Render free tier) sleeps. Every client feature must work from data stored on the phone, and writes must tolerate arriving late or twice.
- No double-quote characters inside issue bodies.

**Names checked against the repo before posting** (notes added in the issue bodies where reality differs):
- P0-1: `processed_mutations` does not exist yet (expected, new table). The worker schedule lives in `_scheduler_loop` in `backend/worker_app.py`. Migrations import `column_exists` and `table_exists` from `alembic/helpers.py` (`from helpers import ...`).
- P0-2: `backend/services/session_exercises.py` exists and has no section fields yet. The generator `plan_pattern_fill.py` keys formats as `warmup`, `superset`, `emom`, `isometric`, `finisher`, `cooldown` and writes the block label in the `block` field (Accessories and Stretch confirmed).
- P0-3: `sync_provider_status` is a module (use `build_providers` / `decorate_sync_status`), not a function. `axis_strength` is a module (use `get_strength` / `get_anchor_lifts`). `weight_ewma` is a module (`compute_ewma`). `session_tss` and `weekly_rollup` are functions. Today data lives in `GET /api/home/revamp` (`revamp_home.py`) and `GET /api/training/today-recommendation`. There is no `/api/mobile/*` route yet (expected).
- P0-4: `session_versions` is a real table (`SessionVersion`), written by `snapshot_version` in `session_versions.py`. The strength TSS path is `session_tss` then `strength_tss_block`. The user data version is `data_version.bump_data_version`. Precompute is `precompute.py` plus `job_queue.py`. Muscle load is `muscle_load.py`.
- P0-5: CSRF is the `_csrf_protect` middleware in `main.py`, with the token from `GET /api/csrf-token`. The session cookie code is in `backend/auth.py`. `device_sessions` does not exist yet (expected). Profile settings JS is `frontend/js/settings-profile.js`.

## Issues

### PWA0-1

```
Title: [PWA P0-1] Idempotent writes with client mutation ids

Why
The phone queues changes offline and resends them when the sleeping server wakes. A resend after a timeout must not apply the same change twice.

Scope
- New table processed_mutations (alembic migration) with columns: id (uuid pk), user_id, client_mutation_id (uuid, unique per user), op_type, received_at, result (jsonb).
- Helper apply_once(session, user_id, client_mutation_id, op_type, fn). If the id was seen before, return the stored result without calling fn. Otherwise call fn, store its result and return it, all inside one transaction.
- Daily cleanup: delete rows older than 30 days (hook into the existing worker schedule).
- Note: the worker schedule is _scheduler_loop in backend/worker_app.py. Migrations use column_exists and table_exists from alembic/helpers.py.

Acceptance criteria
- Calling apply_once twice with the same id runs fn once and returns the same result twice (pytest).
- Two concurrent calls with the same id never both run fn; the unique constraint wins (pytest with two sessions).
- Cleanup removes only rows older than 30 days.

Depends on: none
```

### PWA0-2

```
Title: [PWA P0-2] Structured session format: sections, supersets, EMOM, intervals, holds

Why
Gym mode needs to know how each part of a strength session is run. The generator already tags exercises with a block label (Warm-up, Superset, EMOM, Accessories, Stretch), but that label is free text and timers need structure.

Scope
- Extend the canonical session exercise schema in backend/services/session_exercises.py with optional section fields on each exercise:
  - section_id and section_title, e.g. 3 and Superset A;
  - section_format: one of straight, superset, emom, interval, hold, circuit;
  - section_rounds (int);
  - rest_after_seconds (int, rest after the exercise, or after the last exercise of a superset round);
  - pair_label (A1, A2, …) for supersets;
  - emom: minutes (int) and minute_rule (every, odd, even), saying which minutes this exercise owns;
  - interval: work_seconds, rest_seconds, intervals (int);
  - hold: target_seconds and count_mode (up or down).
- Old sessions without these fields stay valid. Map the existing block label to section_title and default section_format to straight.
- Update the generator (plan_pattern_fill.py) to emit these fields for the formats it already knows (warmup, superset, emom, isometric, finisher, cooldown).
- Validation: interval needs work_seconds, rest_seconds and intervals. An emom section's minute rules must cover each minute exactly once. Hold needs target_seconds. A superset needs at least 2 exercises with pair labels.
- Note: session_exercises.py has no section fields today. In plan_pattern_fill.py the block label is the block field on each row (Accessories and Stretch confirmed).

Acceptance criteria
- Round-trip tests for each format, including mixed sessions.
- Old sessions load unchanged.
- The generator emits valid section fields for every format it produces (pytest over seeded patterns).
- Invalid combinations return clear validation errors.

Depends on: none
```

### PWA0-3

```
Title: [PWA P0-3] GET /api/mobile/bundle: everything the phone needs for 7 days

Why
The phone renders from local data only, so it downloads one bundle while the server is awake.

Scope
- GET /api/mobile/bundle?days=7 (1 to 14). Returns:
  - today: date, plan phase label, block name, and sync provider status (from sync_provider_status);
  - sessions: planned or generated sessions in the window, with full exercises using the PWA0-2 section fields, estimated TSS, duration, and each session version id;
  - last_numbers: per exercise in those sessions, the latest logged sets (date, kg, reps, hold or time, RPE);
  - anchors: strength anchor targets and current best per anchor;
  - library: a trimmed exercise library (id, name, muscles, equipment, aliases) for offline search and swaps;
  - swap_history: per exercise, the user's most frequent replacement in the last 90 days;
  - recent_runs: the last 3 runs (name, date, duration, distance, pace, TSS);
  - body: trend weight, last weigh-in, Zone 2 minutes this week, and the Zone 2 target (once Phase 5 exists; null before);
  - server_time, a bundle_version, and a per-session version.
- Values must come from the existing readers: session_tss, weekly_rollup, axis_strength, weight_ewma and the Today data. No recomputation in the bundle code.
- ETag plus If-None-Match support.
- Response under 300 KB for 7 days (trim the library fields to make that work).
- Note: sync_provider_status, axis_strength and weight_ewma are modules in backend/services (use build_providers or decorate_sync_status, get_strength or get_anchor_lifts, and compute_ewma). session_tss and weekly_rollup are functions. Today data comes from GET /api/home/revamp (revamp_home.py) and GET /api/training/today-recommendation. No /api/mobile routes exist yet.

Acceptance criteria
- Snapshot test of the bundle shape for a fixture user.
- A 304 on an unchanged ETag.
- Numbers equal the existing endpoints for the same user and day (pytest comparing TSS, rollup and trend weight).

Depends on: PWA0-2
```

### PWA0-4

```
Title: [PWA P0-4] POST /api/mobile/sync: apply queued phone changes with conflict rules

Why
Offline edits come back in batches, possibly late, out of order or twice.

Scope
- POST /api/mobile/sync takes ops: a list of objects with client_mutation_id, op_type, created_at (client time), base_version (optional) and payload.
  - Supported op types: session_log (a whole logged strength session: sections, sets done, kg, reps, hold or time, RPE per exercise, session RPE, swaps, order, added sets, notes, duration), session_meta (name and notes) and weigh_in (date, kg).
- Every op runs through apply_once from PWA0-1. The response returns per op: applied, duplicate or conflict. For a conflict, include the server version.
- Conflict rules:
  - session_log: phone wins for set data and exercise order on a session logged on the phone.
  - session_meta: the newest created_at wins.
  - If the same session was edited on desktop after base_version for fields other than those above, return a conflict with both versions.
- A successful session_log:
  - creates a new session version (session_versions);
  - recomputes strength TSS through the existing session_tss path;
  - updates anchors and muscle load through their existing services;
  - bumps the user data version and enqueues precompute (or runs it inline when no worker).
- Ops in a batch apply in created_at order.
- Note: session_versions is a real table (SessionVersion, written by snapshot_version in session_versions.py). The strength TSS path is session_tss then strength_tss_block. The data version is data_version.bump_data_version. Precompute is precompute.py with job_queue.py. Muscle load is muscle_load.py.

Acceptance criteria
- Sending the same batch twice gives duplicate results the second time, with no extra versions (pytest).
- Each conflict rule is covered by a test.
- After a session_log, the strength TSS and anchor values match what the desktop editor would produce for the same sets (pytest).
- A batch with one invalid op still applies the others, and reports the invalid one.

Depends on: PWA0-1, PWA0-2
```

### PWA0-5

```
Title: [PWA P0-5] Long-lived device session and CSRF refresh for offline clients

Why
Offline edits must not fail on an expired login or CSRF token when they are finally sent.

Scope
- Add a remember-this-device sign-in: a device session cookie with a 90-day rolling expiry, stored in a device_sessions table (id, user_id, label, created_at, last_seen_at, revoked_at).
- POST /api/mobile/sync and GET /api/mobile/bundle accept the device session. CSRF for sync: the response to bundle and sync carries a fresh token, and sync accepts the most recent one, or the one before it, to cover a token rotating mid-flush.
- Settings › Profile lists devices with last seen and a Sign out device button (revokes).
- Note: CSRF is the _csrf_protect middleware in backend/main.py, with tokens from GET /api/csrf-token. Session cookie code is in backend/auth.py. The device_sessions table does not exist yet. The Profile settings JS is frontend/js/settings-profile.js.

Acceptance criteria
- A sync 60 days after the last bundle still succeeds with the device session (time-travel test).
- A revoked device gets 401 and can't sync.
- CSRF rotation between the bundle and a delayed sync doesn't fail.

Depends on: none
```
