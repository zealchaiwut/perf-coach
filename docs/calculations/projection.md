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

### Weaknesses

1. Score 100 ⇒ exactly threshold pace for **any distance** — no
   distance-dependent fatigue in the primary estimate (Riegel used only for
   half-splits).
2. CTL/150 makes race prediction hostage to TSS calibration (see tss.md
   defaults problem).
3. A slow B race craters the ceiling until the race is deleted.
4. √horizon confidence band is pure heuristic, not derived from residuals.
5. Flat-average future load ignores the athlete's actual plan.

## 3. Plan calibration (post-race)

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
