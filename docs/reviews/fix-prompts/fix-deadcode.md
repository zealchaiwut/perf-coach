# Prompt: Remove Dead Code

> Paste everything below this line into Claude Code, run from the perf-coach
> repo root on a fresh branch off `develop`.

---

You are working on perf-coach (FastAPI + SQLAlchemy, vanilla-JS frontend, no
bundler). Read `CLAUDE.md` first. Source of truth for these findings:
`docs/reviews/2026-07-architecture-review.md` §6. Line anchors were taken on
branch `review/architecture-docs-2026-07`; re-verify each item is still dead
before deleting (grep for importers/references — the codebase moves fast).

Create branch `chore/dead-code-sweep` off `develop`. Deletion only — no
refactors, no behavior changes. One commit per section below so any section
can be reverted independently. If an item turns out to be alive, SKIP it and
list it in your final summary instead of forcing the deletion.

## Rule for every deletion

1. `grep -rn` the symbol/filename across backend/, frontend/, tests/, scripts/,
   alembic/ — zero non-self references (tests-only references mean: delete the
   test too, it tests dead code).
2. For frontend files, also grep the HTML pages for `<script src=` references.
3. Run the test suite after each section.

## Section 1 — Dead backend router

- `backend/routers/sessions.py` (~331 lines) — defines `/api/strength-sessions`
  + `/api/plyo-sessions` CRUD but is never imported/mounted (only `plan` and
  `strength_sessions` routers are included in main.py ~116-117). Delete the
  file and any tests that import it directly.

## Section 2 — Dead / prod-dead backend services

Fully dead (zero importers): `backend/services/weight_what_if_caller.py`.

Test-only (built, never wired to an endpoint or pipeline) — delete module +
its tests UNLESS you find a live import:

- `monthly_summary.py`, `rolling_intensity.py`, `weekly_check_in.py`,
  `strength_tss.py`, `backfill_economy.py`, `per_workout_curves.py`,
  `ea_proxy.py`, `fit_data_collector.py`, `focus_coaching.py`,
  `habit_focus.py`, `habit_breakdown.py`, `habit_slipping.py`,
  `habit_voice.py`, `channel_select.py`, `banister_validation.py`,
  `running_tss_power_caller.py`, `suggest_thresholds.py`
- **EXCEPTIONS — do NOT delete:** `refit_scheduler.py` and `model_refit.py`.
  They are unwired but planned for the Banister-fitting integration (see
  `docs/reviews/2026-07-questions.md` Q4). Leave them.

Near-duplicate pairs — delete the dead twin, keep the live one:

- `duration_curves.py` (dead) — keep `duration_curve.py` (live).
- `suggest_thresholds.py` (dead) — keep `threshold_suggestions.py` (live,
  used at main.py ~13633). Both define `suggest_thresholds`; verify which one
  main.py imports before deleting.

## Section 3 — Dead sync features inside live code

- Sync cancel flag: `cancel_requested` in `backend/services/sync_jobs.py`
  (~41, 82) — no endpoint ever sets it. Remove the flag, its checks, and the
  paragraph about cancel in `docs/sync.md`.
- Do NOT remove sync System B (`POST /api/sync/strava`, `strava_sync.py`,
  `workout_reconcile.py`) in this sweep — its retirement is a pending decision
  (questions file Q14) and it is reachable in prod.

## Section 4 — Orphan frontend pages + JS (no route serves them)

Verify against the `_PAGES` map in `backend/main.py` (~5079-5104) and the
redirects (~5121-5132) first:

- `frontend/pages/projection.html` (~835 lines) + `frontend/js/projection.js`
  (~875) — `/projection` is a 302 → `/log#plan` since issue #1226. Keep the
  redirect route; delete page + JS.
- `frontend/pages/weekly-check-in.html` + `frontend/js/weekly-check-in.js` —
  no route.
- `frontend/pages/index.html` — `/` redirects to `/home`; nothing serves it.
- Orphan JS loaded by no page: `frontend/js/home-habits.js`,
  `frontend/js/habit-adherence.js`, `frontend/js/lib/habit-voice.js`,
  `frontend/js/lib/weight-voice.js`.

## Section 5 — Mock data in production trends

- `frontend/js/mock-data.js` (~541 lines) is loaded by trends.html, and
  trends.js (~789-870) has `renderMockFallback` / `filterMockReadiness` /
  `filterMockTSS` fallback paths rendering fake charts in prod. Delete
  mock-data.js, its `<script>` tag, and the mock fallback code paths in
  trends.js — replace the fallback with the standard empty-state the page
  already uses for no-data (check `ui-states` helpers other pages use).
  This is the one section touching live logic — keep the diff minimal and
  verify /trends renders with and without data.

## Section 6 — Dead functions inside live modules

Delete only after grepping BOTH the JS file and its HTML page(s) for each name
(inline onclick handlers count as usage):

- `frontend/js/training-plan.js` (~321, 1074-1157): pre-bundle loaders
  superseded by `/api/plan/computed` — `loadCalibration`, `loadRaces`,
  `loadAllReadiness`, `loadProjection`, `loadAthletePerformance`,
  `loadThresholdPace`.
- `frontend/js/training-log.js`: `_chipClass`, `_formatStrengthExSub`,
  `_onSyncStravaClick`, `_renderSparkline`, `_zoneBarHtml`, `buildWeekGroup`,
  `renderLoadWidget`, `syncDateRangeChip`.
- `frontend/js/home.js`: `_homeFetch`, `_buildPrRow`, `avgOf`, `bangkokToday`,
  `loadLogTodayBanner`, `loadLogTodayCard`.
- `frontend/js/weight.js`: `fetchTargetHistory`, `fmtDateForRange`,
  `fmtDisplayDate`, `interpolateWeight`, `nowHHMM`.
- `frontend/js/habits.js`: `loadTodayCard`, `openNewModal`.
- `frontend/js/training.js`: `rbFillSync`, `resetRunBody`, `rowIndex`.

## Section 7 — Redundant docs

- Delete `backend/db/SCHEMA.md` and `docs/data-model.md` (both superseded by
  root `SCHEMA.md` — keep exactly one schema doc; add a one-line pointer to
  root SCHEMA.md wherever they were linked).
- Delete `docs/STATUS.md` (two stale bullets).
- Move `docs/sprint-3-summary.md`, `docs/sprint-6-summary.md`,
  `docs/sprint-21-summary.md` into `docs/sprints/`.
- Move `services/readiness/README.md` content → merge into
  `docs/calculations/readiness.md` (verify formula matches code first), leave
  a pointer file or delete if nothing links it.

## Finish

- Run full test suite. Manually load /log, /home, /trends, /weight, /habits,
  /settings and check the browser console for 404s on deleted scripts.
- Final summary: per section — lines deleted, items SKIPPED as still-alive
  (with the reference that saved them).
