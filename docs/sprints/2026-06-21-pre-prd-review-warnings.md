# Pre-PRD Review — Warnings Backlog

_Captured 2026-06-21 from the multi-agent code review of `develop` before the
`develop → master` (PRD) promotion. The **blockers** were fixed in branch
`fix/pre-prd-blockers` (see "Blockers — DONE" below). This doc tracks the
**warnings and notes** that did NOT block the deploy but should be burned down
in an upcoming sprint._

## Goal

Clear the residual risk surfaced by the pre-PRD review: tighten auth/session
hardening, kill the false-confidence in CI, fix wrong-number edge cases in the
computation services, de-duplicate the divergent service modules, and squash the
remaining frontend correctness bugs.

## Blockers — DONE (branch `fix/pre-prd-blockers`)

| # | Blocker | Fix shipped |
|---|---|---|
| 1 | Anonymous cross-user data read/write — ~28 `/api/*` endpoints derived identity from a client `user_id`/`athlete_id` with no auth | All converted to `Depends(resolve_user)`, identity from session; PR PATCH/DELETE now scope `pr.user_id == current_user.id`; `get_athlete_performance` IDOR closed. Verified: unauth requests now 401. |
| 2 | Stryd sync batch-dup crash (`ON CONFLICT … cannot affect row a second time`) | `stryd_sync.py` dedups `mapped` by `stryd_activity_id` before upsert |
| 3 | `run-detail-view.js` `ReferenceError: storedTss` under `"use strict"` | Replaced with `w.tss` fallback |
| 4 | Stored XSS — user/Strava names into `innerHTML` in `home.js`, `run-view.js`, `strength-view.js` | Added `esc()` helper to each, wrapped all sinks (incl. Strava `href`) |
| 5 | Habit autofill silently dead (`not Habit.is_archived` → constant `False`) | `Habit.is_archived.is_(False)` |

---

## Sprint backlog — WARNINGS

### W1 — CI does not gate merges (false confidence) — **HIGH**
- 397 test files; **204 hit a live server** at `127.0.0.1:9001`. CI runs only
  `migrations-check` + 2 golden-metric files. No `pytest.ini`/`conftest.py`, no
  CI step boots uvicorn or a DB.
- **Fix:** add a CI job running the non-live, no-DB unit subset (mark/collect
  tests that don't need port 9001), or document explicitly that the integration
  suite is local-only. Also `golden-metrics.yml` hardcodes filenames — switch to
  `pytest tests/test_golden_*.py` so new golden tests are picked up.
- Move stray `backend/test_auth.py` → `tests/test_auth.py`.

### W2 — Session cookie hardening — `backend/auth.py:119` — **HIGH**
- `set_session` sets no `secure` flag and no `max_age`/expiry; `read_session_cookie`
  has no issued-at age check → sessions effectively eternal until secret rotation.
- **Fix:** `secure=(env != "local")`, add `max_age`, enforce `issued_at` age on read.

### W3 — Threshold edits don't recompute existing TSS — `tss.py:1239` (`persist_running_tss` / `recompute_user_running_tss`) — **HIGH**
- Guard is `if workout.tss is None`, so changing FTP/HR/pace leaves old scores;
  only `tss_method` is rewritten.
- **Fix:** in the recompute path, overwrite when `tss_source != "manual"`.

### W4 — Two divergent reconcile implementations — **HIGH**
- `reconcile.py::reconcile_workouts` (used by in-memory workers) vs
  `workout_reconcile.py::reconcile_strava_to_workouts` (used by `/api/sync/strava/reconcile`).
  Different match logic (±5min only vs date AND ±5min) and source labels.
- **Fix:** consolidate to one; route all callers through it.

### W5 — UI sync path is full-pull every time — **MED**
- The incremental watermark logic lives only in `strava_sync.py::sync_strava_activities`
  (`/api/sync/strava`), which the UI does NOT call. UI hits `/api/strava/sync` /
  `/api/stryd/sync` → `_strava_sync_worker` / `_stryd_sync_worker` with no
  watermark → re-pulls all history each sync (Strava rate-limit cost; not data loss).
- **Fix:** decide the canonical path; wire the UI to the incremental endpoint or
  remove the duplicate.

### W6 — Two non-idempotent migrations on `user_preferences` — **MED**
- `8f9eee6bf79b` (strength_rpe_max) and `d915ffcb4c0c` (aerobic_decoupling) do
  unguarded `op.add_column`, unlike every sibling. This table already needed a
  drift-repair migration (`6b72b2735b17`).
- **Fix:** wrap each in `if not column_exists("user_preferences", "<col>"):`.
  (Forward-migrate is currently fine on a clean chain; this is hardening.)

### W7 — Migration structural debt — **LOW**
- Two merge nodes share parent pair `(145b95d5baf0, d915ffcb4c0c)`:
  `978bc203e81a` + `ba386d88fa17` — violates the "never a second merge node for the
  same heads" rule (guarded, so single head resolves; debt only).
- `6c67cf68fb1e` downgrade drops whole `habits` + `habit_logs` tables though
  upgrade only adds columns. Make the downgrade drop only the added columns.

### W8 — Two divergent lap classifiers both live — **MED**
- `session_profile.py` imports `classify_laps` from `lap_classifier` (basis-chosen-once,
  drops laps missing the chosen metric); `main.py` imports from `lap_classify`
  (per-lap fall-through power→pace→hr). Different bands on mixed-sensor sessions.
- **Fix:** pick one classifier; route both callers to it.

### W9 — Computation edge-case crashes — **MED**
- `normalized_power.py:104` — ZeroDivisionError when `sample_interval_seconds == 0`.
- `performance_chart.py:163` — unguarded `date.fromisoformat` 500s the endpoint on a
  malformed run date.
- `performance_chart.py:243` (`_map_trend_to_dates`) — re-derives qualifying dates and
  `zip()`s against the trend; any extra filtering silently misaligns dates to values.
- `strength_tss.py::calculate_strength_tss_per_set` — no numeric coercion/clamp on
  `rpe`/`reps`; non-numeric crashes, `rpe>10` unbounded (only global 150 clamp saves it).
- `running_performance._compute_direction` — 2-value series uses full-span slope, 3+
  uses per-step; can flip improving/flat at the boundary. Normalize to per-step.

### W10 — Sync cancel hook is dead code — `sync_jobs.py:30` — **LOW**
- `cancel_requested` is never set (no setter/endpoint); `is_cancel_requested` always
  False.
- **Fix:** wire a `request_cancel()` setter + endpoint, or remove the scaffolding.

### W11 — Performance sub-tab non-functional in prod — **MED**
- `training-performance.js` calls `/api/athletes/{id}/performance`, `/api/performance/chart`,
  `/api/athletes/{id}/daily-load`. After the blocker fix these now derive identity from
  the session (no longer 404 on auth), but confirm the tab renders end-to-end; it also
  passed `athlete_id` as a query param (now ignored). Chart.js datasets use
  `borderColor: 'var(--bg-1)'` — CSS vars don't resolve on canvas; use `getComputedStyle`/hex.
- **Fix:** verify the Performance tab works post-fix, or hide it; resolve chart colors.

### W12 — Frontend string-vs-number `===` drops optimistic updates — **MED**
- `weight.js:640` (`_recentEntries.findIndex(e => e.id === entryId)`), `habits.js:1129/1141`
  (`h.id === habitId`) compare numeric API ids to `dataset` strings → never match;
  optimistic inline update silently no-ops until reload.
- **Fix:** coerce with `String(...)` on both sides (other lookups already do).

### W13 — Other frontend correctness nits — **LOW**
- `run-view.js` (~470) lap-metric toggle listeners stack (added in `renderView` AND
  `attachToggleListeners`) → handlers fire multiply. Delegate once on the container.
- `training-plan.js` (~135) `renderRaceHeader` calls `r.priority.toLowerCase()` unguarded
  → throws on a null priority.
- `calendar.js:58,439` pass `user_id` query param (legacy shim OFF; ignored). Calendar
  is `disabled: true` in nav — drop the param when re-enabling.
- Accumulating document listeners with no removal on all close paths: `weight.js:513`,
  `habits.js:1175`.

---

## Sprint backlog — NOTES (cleanup)

- **N1 — Pre-existing unauthenticated user CRUD** (`/api/users` GET/POST,
  `/api/users/{id}` PATCH/DELETE, `/api/users/{id}/avatar`). Exists on master, so
  not a new regression, but anyone can create/rename/delete users. Gate with
  `require_admin` (verify the login user-picker still works — it reads `GET /api/users`).
- **N2 — Dead duplicate service modules** shipping beside live twins:
  `suggest_thresholds.py` (live = `threshold_suggestions.py`; the two return DIFFERENT
  shapes — confirm the endpoint uses the right one), `running_tss_power_caller.py`,
  `session_profile_caller.py`. Delete the dead ones.
- **N3 — Strength TSS pure functions dead** (`compute_strength_tss`,
  `calculate_strength_tss_per_set(_with_prefs)`, `calc_strength_tss` in `tss.py`) — not
  called; `UserPreferences` has no `strength_tss_scale`/`strength_tss_max` columns.
- **N4 — Habit week-completion disagreement:** `habit_consistency` (times_per_week) relies
  on `is_period_met`, which for binary habits ignores `schedule_target`, disagreeing with
  `habit_streak._week_met` (`days_met >= schedule_target`). Make them consistent.
- **N5 — Strava Stryd-origin heuristic** (`strava.py:73`) checks `avg_power_w`/`max_power_w`
  but raw payloads use `average_watts`/`max_watts` → power branch never fires.
- **N6 — `_call_strava_refresh`** (`strava.py:43`) does no status/`KeyError` handling; a
  revoked token surfaces as a raw error instead of a clean "reconnect Strava" message.
- **N7 — TSB convention:** `compute_load_curves` uses same-day `TSB = CTL − ATL`; classic
  TrainingPeaks uses yesterday's. Modeling choice — make it intentional/documented.

## Suggested build order

1. W1 (CI gate) + W2 (session hardening) — highest leverage, lowest blast radius.
2. W3 + W4 + W8 (correctness: TSS recompute, single reconcile, single lap classifier).
3. W9 + W12 (edge-case crashes + optimistic-update bugs).
4. W5 + W6 + W11 (sync path, migration guards, performance tab).
5. Notes / dead-code cleanup (N1–N7), W7, W10, W13.
</content>
</invoke>
