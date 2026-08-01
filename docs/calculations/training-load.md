# Training Load — CTL / ATL / TSB / ACWR

**Purpose:** fitness (CTL), fatigue (ATL), form (TSB = CTL − ATL), and
Acute:Chronic Workload Ratio (ACWR) from the daily TSS series. Classic
Banister impulse-response, EWMA form.

## Single source of truth (2026-07-10)

**Every consumer reads `training_load_snapshots` via
`backend/services/training_load.py`'s `current_load()` (single date) or
`get_snapshot_series()` (date range). No other code path may independently
compute and render these metrics.** This consolidates a bug where the
readiness cards and the weekly coach report showed *different* CTL/ATL/TSB
for the same date — two independent computations, not a display bug (the
report's ATL was mathematically impossible for the week's actual load:
decaying from ATL 48.9 at ~27 TSS/day lands near 34, not the 17.44 it
showed). Before this fix there were four independent CTL/ATL/TSB compute
paths reaching the user (readiness via `compute_fitness_series`, no
calibration, no cache; the coach report via `current_load`, calibration- and
cache-aware; the fitness/fatigue/form chart via `fitness_model.py`, a
*day-shifted* TSB convention; `/api/training-load`'s inline hardcoded-42/7
recompute) and four independent writers to `training_load_snapshots`
(`daily_update`, plus three raw-upsert duplicates with different seeding —
`main.py`'s `recompute`/`backfill` endpoints and
`scripts/backfill_training_load.py`). Any of the extra writers could leave a
snapshot row `current_load()` then trusted for the rest of that day, which
is the concrete mechanism behind the reported bug.

- **Writer:** `daily_update(user_id, target_date)` — the sole function that
  upserts a row. 180-day EWMA warm-up window, calibration-aware, stamps
  `acwr` (via `acwr.compute_acwr()`, see below) and `formula_version`.
- **Single-date reader:** `current_load(user_id, as_of=None)` — reads the
  cached row when it exists, is for the exact date, **and its
  `formula_version` matches** `training_load._FORMULA_VERSION`; otherwise
  computes live via `daily_update` and returns the fresh row. A row from
  before this consolidation (or a future formula change) has no/an old
  `formula_version` and is therefore always treated as a miss — it can never
  silently keep serving a stale shape.
- **Range reader:** `get_snapshot_series(user_id, from_date, to_date, ...)` —
  for any consumer needing a series (the fitness/fatigue/form chart,
  readiness's own trend series, monthly summary): reads what's cached+fresh,
  computes the whole range in ONE 180-day-warm-up pass for whatever's
  missing/stale, and bulk-upserts — never N independent `daily_update` calls.
- Both honor the user's saved EWMA calibration (`UserPreferences.ctl_days` /
  `atl_days` via `resolve_user_ewma_days`). Each snapshot row now records
  the `ctl_days`/`atl_days` used to compute it (nullable columns; NULL means
  the module defaults 42/7 were used). `_snap_matches_calibration()` checks
  these stored constants against the user's current calibration: a row
  computed with different constants is treated as stale and recomputed.
  Accepting a calibration via `POST /api/races/{id}/calibrate/accept` calls
  `recompute_user_snapshots()` to backfill the full snapshot history with the
  new time constants immediately.

**Consumers, all now reading one of the two functions above:**

| Consumer | Endpoint | Reads |
|---|---|---|
| Readiness cards | `GET /api/readiness` | `get_snapshot_series` |
| Fitness/fatigue/form chart | `GET /api/performance/chart` | `get_snapshot_series`, passed into `performance_chart.compute_performance_chart`'s `snapshot_series` param |
| Weekly coach report | `GET /api/weekly-summary` | `current_load` (unchanged — this was already correct pre-consolidation; the bug was upstream, in what the cache could contain) |
| "Summary" digest card | `GET /api/athletes/{id}/summary/weekly` | `get_snapshot_series` |
| Monthly summary | `GET /api/athletes/{id}/summary/monthly` | `get_snapshot_series` |
| `/api/training-load` (range) | `GET /api/training-load` | `get_snapshot_series` (was: inline hardcoded-42/7, cold-starting at 0 for any date missing a snapshot) |
| `/api/training-load/recompute`, `/backfill` | `POST` | `get_snapshot_series` (was: a byte-for-byte duplicate raw-upsert implementation each, seeded from only the prior day's snapshot instead of a full warm-up) |
| `scripts/backfill_training_load.py` | ops script | `get_snapshot_series` (was: standalone raw SQL, hardcoded 42/7) |

**Deliberately out of scope** (forward-looking *projections* of a
hypothetical future state, not "today's actual snapshot" — a different
computation, not part of this bug): `project_form`/`get_projected_form`,
`projection.py`'s `project_fitness`, and the projection portion of
race-readiness. Their anchor (today's real CTL/ATL) still comes from
`current_load`; only the forward-simulated days are untouched.

## ACWR — now persisted per snapshot

`acwr` on each `TrainingLoadSnapshot` row is `acwr.compute_acwr()`'s
`ratio` — acute = sum of the trailing 7 days' TSS; chronic = mean of up to 4
prior non-overlapping 7-day windows (days -35..-8, current week excluded).
See `docs/calculations/acwr-guardrail.md` for the full formula and the
`LOWER_BOUND`/`UPPER_BOUND`/`HIGH_BOUND` band constants — this module never
reimplements that math, it only calls it. `acwr` is `None` when there isn't
`_MIN_DAYS` (28) of trailing history yet, same convention as every other
ACWR consumer (`guardrail.py`, `plan_suggestions.py`).

## Current formula

```
α(days)   = 1 − exp(−1/days)              (_ewma_alpha)
new_value = prev + (tss − prev) · α       (compute_load_curves)
TSB       = CTL − ATL   (same-day)
```

- Constants: `CTL_DAYS=42`, `ATL_DAYS=7`; form zones `FORM_BURIED_CEILING=-10`,
  `FORM_FRESH_FLOOR=5`; taper band TSB 5..25, `DEFAULT_TAPER_DAYS=14`;
  `PEAK_TRACKING_TOLERANCE=5`.
- **Taper length is chosen by race priority** (issue #711, restored in #1605):
  `A_RACE_TAPER_DAYS=14` for a goal race, `B_RACE_TAPER_DAYS=7` for a tune-up.
  `taper_recommendation` reads `fitness_state["priority"]`, which `main.py`
  threads from `races.priority`. Anything other than `"B"` — including a null
  or a `"C"` — falls back to the A-race length, so an unknown priority stays
  conservative rather than accidentally shortening a taper.
  When the race is too close for form to reach `target_form`,
  `taper_start_date` is `None` and `achievable` is `False` — the function says
  the peak is unreachable rather than returning a start date already in the past.
- `daily_tss_series` sums `workouts.tss` per day, zero-fills gaps.
- `daily_update`/`get_snapshot_series` use a **180-day warm-up window** before
  the requested date/range so the EWMA has time to converge.
- Derived pure functions (unchanged by this consolidation — they already
  read their anchor state via `current_load`): `performance_curve` zone
  classification, `project_form`, `taper_recommendation`, `peak_tracking`,
  `readiness_label`.

## Inputs / outputs

- **In:** `workouts.tss` by date. Cold start CTL=ATL=0.
- **Out:** `training_load_snapshots` (user_id, snapshot_date unique; plus
  `acwr`, `formula_version`), read by every consumer table above.

## Known weaknesses / open issues

1. **Two parallel Banister stacks still exist in code, but only one is
   reachable by a live consumer.** `fitness_model.py` (day-shifted TSB) is
   no longer called by `performance_chart.py` (it now takes CTL/ATL/TSB via
   the `snapshot_series` param instead) but the module itself, and
   `training_load.py`'s own `compute_fitness_series`, are kept for their
   existing pure-function test coverage and as a documented fallback shape
   for direct unit tests. Do not reintroduce a live call to either from an
   endpoint — call `current_load`/`get_snapshot_series` instead.
2. Historical workout edits/backfills do not rewrite old snapshots unless
   `daily_update`/`get_snapshot_series` re-runs for those dates (the
   `formula_version` check only catches a *formula* change, not a workout
   edit after the fact). Post-write `daily_update` failures on the
   workout-creation hook are swallowed (main.py) → a workout save can leave
   a permanently stale snapshot until the next explicit recompute.
   **TODO:** a worker backfill job to recompute snapshots for users whose
   workout history changed (see `backend/worker_app.py`) is not yet built.
3. Cold start underestimates CTL for ~6 weeks (documented above). Missing
   TSS (NULL) counts as zero training; non-run sports without TSS invisible.
4. TSB zone thresholds are population constants, not personalized.
5. `get_snapshot_series`'s per-day ACWR window recompute is O(range ×
   window) in Python (one 35-day slide per requested day) — fine at today's
   scale (chart ranges are ~30-90 days), but not a design that would hold up
   for a bulk multi-year backfill without batching.

## Per-user Banister personalization (Sprint 96)

- `banister_params.py` (per-user τ params, 5-min in-process TTL cache),
  `banister_fitting.py` (least-squares fit vs performance proxies),
  `banister_pipeline.py` (weekly refit — run by a module-level daemon thread).
- `model_refit.py` / `refit_scheduler.py` are **not wired into prod** (only
  import each other + tests).
- Restart resets the 7-day refit timer (first `time.sleep` before first
  run) — frequent redeploys can starve the weekly refit forever.

## ML-readiness

- This IS the impulse-response model; the individualization layer exists but
  is half-wired. Finish that before inventing anything new.
- **Labels** for a learned replacement: race results, duration-curve bests,
  readiness, endurance/speed signal series.
- **Model shape:** state-space / Kalman filter over daily load, or a small RNN;
  or simply per-user fitted τ1/τ2 (the existing stack).
- **Missing:** a consistent performance criterion time series (e.g. weekly
  benchmark efforts) to fit against; persisted predictions to score fits.

## Caching

`training_load_snapshots` upsert per user/day, via `daily_update` (single
date, the workout-creation hook and `/api/training-load/refresh`) or
`get_snapshot_series` (range, batched). See weaknesses 2 for the remaining
gap (workout edits don't proactively rewrite old snapshots).
