# Projection — Forward Fitness, Race Time, Calibration

**Purpose:** project CTL/TSB forward to a race date, convert projected
fitness into a finish-time estimate, and adjust model constants from race
results afterwards.

## 1. Forward CTL projection (`backend/services/projection.py`)

- `project_fitness` (:140-198): `ctl = ctl·e^(−1/42) + load·(1−e^(−1/42))` —
  mathematically identical to training_load's EWMA but constants imported
  from `fitness_model.py` (CTL_TIME_CONSTANT=42, ATL=7), and TSB uses the
  **previous day's** CTL−ATL (fitness_model.py:18-20) unlike training_load's
  same-day convention.
- **Future load assumption:** the plan router (`routers/plan.py:434-440`)
  feeds a **flat 28-day-average TSS repeated for every future day**. The
  ramp+taper schedule generator (`plan_service.generate_planned_load_schedule`
  :248-287, `_taper_factor` step=0.70 / exponential / linear, :235-245) writes
  to `planned_load` — **but the projection router never consumes it.**
- **Confidence band:** `band = 0.5·√horizon_days`
  (`CONFIDENCE_BAND_RATE=0.5`, projection.py:89); after a B-race the band ×0.6
  (`B_RACE_TIGHTENING_FACTOR`, :69). `_recalibrate_from_race` is an explicit
  `NotImplementedError` stub (:72-84).
- Expressible score: `factor = 1 + tsb/ceiling_tsb` (:201-257) — linear,
  unbounded below.

## 2. Score ceiling → race time

Chain of three linear heuristics with three magic constants (150, 2.0, 1.06):

```
ceiling = clamp(CTL/150 × 100, 0..100)          score_ceiling.py:37-81
        + economy ceiling_bonus (triangular lag kernel, ceiling_bonus.py:31-38)
score   = ceiling × body_modifier
pace    = threshold_pace × (2 − score/100)      race_finish_estimator.py:45-110
finish  = pace × distance_km
other distances: Riegel T2 = T1·(D2/D1)^1.06    riegel.py:26-76
```

- B-race back-inference: `ceiling_from_b_race_result` inverts the pace map:
  `score = (2 − actual_pace/threshold_pace) × 100` (score_ceiling.py:84-125).
- Riegel exponent **1.06 defined twice** (riegel.py:22, projection.py:299) and
  the `2 − pace/threshold` map duplicated between race_finish_estimator.py and
  score_ceiling.py.

### Riegel floor + race-day sample (2026-07-10 fix)

Two corrections to the estimate chain, motivated by a live paradox (athlete
ran an actual half in 2:19:26 with LOWER scores than today's, yet the next
half was projected at 2:38:03):

- **Race-day sample.** The per-race "estimated" figure (`_plan_race_scores`
  and `_compute_plan_bundle`'s estimate block) now reads the LAST projection
  sample — the race's own date, after the modeled build+taper — instead of
  `projection[0]` (~tomorrow), which froze the estimate at today's
  mid-build fatigue via the `× (1 + tsb/20)` expressible factor. The
  frontend "Projected now" readout still deliberately reads sample 0.
- **Riegel floor.** Every time-curve sample (history from the demonstrated
  race's own date forward; all projection days) is capped at the Riegel
  equivalent (`T × (D2/D1)^1.06`) of the best race actually finished in the
  last 90 days — the same window the race-anchored ceiling already uses. A
  demonstrated result is a fact; a TSB-suppressed heuristic must not
  predict slower than it. Exposed as `time_curve.riegel_floor_seconds`.

Neither replaces real recalibration (§3's "closed loop that doesn't close"
still stands) — the floor is a hard sanity bound, not a learned correction.

### Weaknesses

1. Score 100 ⇒ exactly threshold pace for **any distance** — no
   distance-dependent fatigue in the primary estimate (Riegel used only for
   half-splits and the demonstrated-race floor above).
2. CTL/150 makes race prediction hostage to TSS calibration (see tss.md
   defaults problem).
3. A slow B race craters the ceiling until the race is deleted (the Riegel
   floor is one-sided — it prevents under-prediction, not over-prediction).
4. √horizon confidence band is pure heuristic, not derived from residuals.
5. Flat-average future load ignores the athlete's actual plan (and the
   race-day sample above still assumes ZERO load between now and race day —
   optimistic on TSB, pessimistic on CTL).

## 3. Plan calibration (post-race)

### Race calibration loop — CLOSED (2026-07-10, `backend/services/race_calibration.py`)

The recalibrate-from-race loop is now real (the old
`projection._recalibrate_from_race` NotImplementedError stub is superseded):

- **When a race is finished** (status `done` + `actual_time_seconds`), a
  `race_calibrations` row is created: the RAW model's race-eve prediction (a
  deterministic backcast from data as-of that date — load curves, prior-race
  anchor/floor, TSB factor, no prior correction applied) vs the actual
  result, and `correction = actual / predicted` (UNclamped in storage).
  Self-healing: `ensure_calibrations` runs from the plan bundle and the
  calibration-status endpoint — the single choke points every race-mutation
  path funnels through — so no per-endpoint done-transition hooks exist to
  miss.
- **Every finish estimate is multiplied by the blended correction**:
  weighted geometric mean of stored corrections, recency-weighted
  (`RECENCY_HALF_LIFE_DAYS = 180`) × distance-similarity-weighted
  (`exp(-|ln(d_target/d_race)|)` — a race at 2×/½× the target distance
  counts half), clamped to `CORRECTION_CLAMP = (0.90, 1.10)`. Applied
  BEFORE the Riegel floor cap; unlike the 90-day anchor/floor it never
  expires, only fades as newer races out-weigh it. Surfaced as
  `time_curve.calibration_correction` / `calibration_n_races` and on the
  calibration-status card (`correction_pct`, `n_calibrations`;
  "last recalibrated" now means a real calibration row, not the last done
  race's updated_at).
- **Predictions are persisted** (`race_predictions`, one row per race per
  day the bundle computes an estimate — what was actually SHOWN, correction
  included). Not consumed by the correction math (corrections measure the
  raw model via backcast, each an independent bias sample); this is the
  residual history a future learned confidence band needs (ML-readiness
  item 1).
- Known approximations: the backcast uses TODAY's threshold-pace preference
  (preferences aren't versioned), and per-user Banister time-constant
  fitting remains a separate unintegrated stack (below).

### Legacy ctl/atl-days suggestions (still open)

`training_load.compute_calibration_suggestions` (:800-914) + endpoints
(main.py:12686-12950):

- `timing_delta = actual_peak_week − predicted_peak_week`; if |delta| > 1 week,
  suggest `ctl_days ± |delta|×2`, clamped [14, 84].
- `peak_level_delta_pct` is reported but **drives nothing**.
- **"Predicted" peak week is hardcoded to the race week** (main.py:12671) — an
  assumption, not a stored prediction.
- Accept writes `user_preferences.ctl_days/atl_days` (main.py:12777-12780) —
  **which nothing downstream reads** (training-load.md weakness 1).
  **Calibration is a closed loop that doesn't close.**
- Parallel unintegrated effort: the `banister_fitting.py` / `model_refit.py` /
  `refit_scheduler.py` stack does proper parameter fitting; the calibration
  endpoints don't use it.

## Caching — `computed_cache`

The Plan-tab bundle (`GET /api/plan/computed`, main.py:15040-15064, collapses
~10 calls into 1) is cached in `training_plans.computed_cache` JSONB +
`computed_signature` (models.py:1149; migration `5d1ce0a241f1`).

- Signature (`_plan_signature` main.py:14788-14840): SHA-256 over
  MAX(workouts.created_at) | COUNT(workouts) | MAX(races.updated_at/created_at)
  | threshold-pace stamp | plan.updated_at.
- **Gaps:** `workouts` has no `updated_at`, so editing a workout changes
  neither count nor MAX(created_at) → stale cache. Race-checkpoint CRUD and
  daily_metrics/readiness changes are also outside the signature. No TTL, no
  explicit invalidation writers.
- `_compute_plan_bundle` (main.py:14902-15021) calls endpoint functions
  in-process, including `get_race_readiness` **per upcoming race** — an N+1
  fan-out on cache miss. The signature itself costs 5 aggregate queries even
  on hits.
- `GET /api/projection` (main.py:15083) and the plan-router projection are
  **uncached** full simulations per request.

## ML-readiness

The cleanest ML slot in the app.

- **Features:** CTL/ATL/TSB at race date, duration-curve bests
  (`per_workout_curves`, `duration_curve_best_effort`), endurance/speed
  scores, weight trend, (weather — not stored).
- **Label:** `races.actual_time_seconds` (already stored).
- **Model:** regression on log(pace) with distance as a feature — a learned
  Riegel exponent and a learned score→pace map in one model.
- **Blocking gap:** predictions are never persisted at prediction time. Start
  writing `(user, made_on, horizon, predicted ctl/atl/tsb, predicted race
  time, band)` rows now; the confidence band can then become empirical
  forecast-error quantiles. Race-day conditions not stored either.
