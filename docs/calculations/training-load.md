# Training Load — CTL / ATL / TSB

**Purpose:** fitness (CTL), fatigue (ATL), form (TSB = CTL − ATL) from the
daily TSS series. Classic Banister impulse-response, EWMA form.

This doc supersedes `docs/training-load.md` for the math; that older doc still
documents endpoints with the removed `?user_id` param.

## Current formula

`backend/services/training_load.py`:

```
α(days)   = 1 − exp(−1/days)              (training_load.py:83-85)
new_value = prev + (tss − prev) · α       (compute_load_curves, :133-172)
TSB       = CTL − ATL   (same-day)
```

- Constants: `CTL_DAYS=42`, `ATL_DAYS=7` (:38-40); form zones
  `FORM_BURIED_CEILING=-10`, `FORM_FRESH_FLOOR=5` (:44-46); taper band
  TSB 5..25, `DEFAULT_TAPER_DAYS=14` (:51-56); `PEAK_TRACKING_TOLERANCE=5` (:61).
- `daily_tss_series` (:88-130) sums `workouts.tss` per day, zero-fills gaps.
- `current_load` (:175-203) recomputes with a **180-day warm-up window** on
  every call.
- `daily_update` (:206-258) upserts into `training_load_snapshots`.
- Derived pure functions: `performance_curve` zone classification (:270-355),
  `project_form` (:358-499), `taper_recommendation` (:548-669),
  `peak_tracking` (:701-797), `readiness_label` (:917-938).

## Inputs / outputs

- **In:** `workouts.tss` by date. Cold start CTL=ATL=0.
- **Out:** `training_load_snapshots` (user_id, snapshot_date unique), plus
  live values served by `/api/training-load*` endpoints.

## Known weaknesses / open issues

1. **Calibration loop doesn't close.** `user_preferences.ctl_days/atl_days`
   exist and the calibration accept endpoint writes them
   (main.py:12777-12780), but `compute_load_curves` / `current_load` /
   `daily_update` **never read them** — they always use the module constants.
   Accepted calibration suggestions have zero effect on the live curves.
2. **Two parallel Banister stacks.** `training_load.py` (EWMA form, same-day
   TSB) vs `fitness_model.py` + `projection.py` (decay form
   `ctl·e^(−1/42) + load·(1−e^(−1/42))` — mathematically identical EWMA — but
   **TSB = previous day's CTL−ATL**, fitness_model.py:18-20). Same constants
   duplicated in two modules; the day-convention difference means the same
   date can show different TSB in the Log tab vs the Projection tab.
3. **Snapshot cache bypassed on hot paths.** `current_load` ignores
   `training_load_snapshots` and rebuilds the 180-day series per request; used
   by `/api/training-load/current`, readiness CTL branch, plan router
   projection, taper/monthly endpoints. The snapshot table is mainly read by
   calibration.
4. Historical workout edits/backfills do not rewrite old snapshots unless
   `daily_update` re-runs for those dates. Post-write `daily_update` failures
   are swallowed (main.py:6538-6541) → workout saves with permanently stale
   snapshot.
5. Cold start underestimates CTL for ~6 weeks (documented, :17-19). Missing
   TSS (NULL) counts as zero training; non-run sports without TSS invisible.
6. TSB zone thresholds are population constants, not personalized.

## Per-user Banister personalization (Sprint 96)

- `banister_params.py` (per-user τ params, 5-min in-process TTL cache),
  `banister_fitting.py` (least-squares fit vs performance proxies),
  `banister_pipeline.py` (weekly refit — run by a module-level daemon thread,
  main.py:15873).
- `model_refit.py` / `refit_scheduler.py` are **not wired into prod** (only
  import each other + tests).
- Restart resets the 7-day refit timer (first `time.sleep` before first run,
  main.py:15845) — frequent redeploys can starve the weekly refit forever.

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

`training_load_snapshots` upsert per user/day. Write triggers: workout
create/patch/duplicate, manual `POST /api/training-load/refresh`, series
endpoint backfill loops. See weaknesses 3–4 for the gaps.
