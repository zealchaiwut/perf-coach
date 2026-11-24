# Plan-matching (planned session → workout)

How the **Plan tab** reconciles a user's hand-entered `planned_sessions` against
their already-reconciled `workouts` (the merged Strava/Stryd truth table). This
is the `planned_session → workout` matcher and is **separate** from
`reconcile.py`, which merges raw activities into `workouts`.

Implemented in `backend/services/plan_matching.py`. The thresholds below are a
**first pass — tunable**; the constants in that module are the single source of
truth.

## When it runs

1. **Post-sync** — after `reconcile_workouts` finishes and before
   `sync_jobs.mark_success` in both sync workers (`_strava_sync_worker` /
   `_stryd_sync_worker` in `backend/main.py`, via `_run_plan_matcher`). A
   matcher failure is logged and swallowed so it never fails the sync.
2. **On demand** — `POST /api/planned-sessions/reconcile`.

It is **idempotent**: re-running never overwrites a `done_manual` link or an
existing `done_auto` link — it only fills `planned` / `missed` / `needs_review`
slots. A user's manual unmatch/miss is respected until the underlying data
changes.

## Thresholds (first pass, tunable)

| Constant | Value | Meaning |
|---|---|---|
| `DAY_WINDOW` | ±1 day | candidate workouts within ±1 day of `planned_date` |
| `DURATION_AUTO` | ±20% | duration within ±20% → high-confidence auto-match |
| `DURATION_REVIEW` | ±40% | duration ±20%–±40% → review candidate; beyond ±40% → dropped |

### Type-family rules

- planned `run` ↔ workout `workout_type == 'run'` (any `run_subtype`).
- planned `strength` / `plyo` ↔ any **non-run** workout.
- planned `rest` → skipped (never matched).

A workout already claimed by another session's `done_auto`/`done_manual` link is
excluded from the candidate pool (one workout fulfils at most one session).

### Planned duration

Derived from the run `structure.blocks[]`: sum `duration_min` (× `repeat`, plus
`rest_min × (repeat-1)`). Strength/plyo have no reliable duration in the exercise
schema, so duration checks are skipped for them (a lone same-day candidate then
auto-matches on date + type alone).

## Resulting status

| status | condition |
|---|---|
| `done_auto` | exactly ONE candidate, SAME day, and (if planned duration known) within ±20% |
| `needs_review` | 2+ same-day candidates, OR a single day±1 (not same-day) candidate, OR a same-day candidate outside ±20% but within ±40% |
| `missed` | `planned_date < today` and no candidate at all |
| `planned` | future/today with no candidate yet (left unchanged) |

## Ghosts (unplanned activities)

Any workout in the queried range **not** linked to a planned session, that falls
on a day which has at least one planned session of a **compatible type-family**,
is returned by `GET /api/planned-sessions` as an `unplanned` entry for manual
mapping (Map → `POST …/match`, or Ignore client-side).

## Link + content apply (strength)

The matcher sets `planned_sessions.matched_workout_id → workouts.id`. For
strength/plyo matches, `backend/services/plan_match_apply.py` also stamps
planned `target_tss` and exercise rows onto the workout **when those fields are
empty** (typical for Strava lifts), then recomputes muscle load. Existing
workout TSS / exercises are never overwritten — runs keep Strava/Stryd TSS.
