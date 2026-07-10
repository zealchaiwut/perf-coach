# Calculations & Models — Index

This directory documents every scoring / estimation / model calculation in
perf-coach: the exact current formula, its inputs and outputs, hardcoded
constants, known weaknesses, caching behaviour, and — for each one — how a
future ML model could replace the heuristic and what data must be logged
**now** to make that possible.

Written 2026-07 from a full code review (branch `review/architecture-docs-2026-07`).
Line anchors reference that checkout; treat them as approximate after merges.

## The pipeline

```
workout (manual / Strava / Stryd)
        │  reconcile.py + workout_merge.py   (source precedence, ±5 min match)
        ▼
workouts row  ──► TSS (tss.py: power → pace → HR → duration-only fallback)
        │
        ├─► per-run signals: speed_signal.py, endurance_signal.py, decoupling
        │
        ▼
daily TSS series ──► CTL / ATL / TSB (training_load.py, EWMA 42/7 d)
        │                    │
        │                    ├─► training_load_snapshots (durable cache)
        │                    ├─► ACWR + guardrail (acwr.py, guardrail.py)
        │                    └─► forward projection (projection.py)
        ▼
endurance / speed scores (running_performance.py, 90-day window)
        │  × body_modifier (weight-trend uplift/penalty, EA guard)
        ▼
score ceiling (CTL/150) ──► race pace (2 − score/100 × threshold) ──► finish time
                                     └─► Riegel T·(D2/D1)^1.06 for other distances

daily_metrics (HRV, RHR, sleep, energy, mood) ──► readiness (4 formulas! see readiness.md)
```

## Documents

| Doc | Covers | Key services |
|---|---|---|
| [tss.md](tss.md) | Per-workout training stress | `tss.py`, `running_tss_power.py`, `normalized_power.py` |
| [training-load.md](training-load.md) | CTL/ATL/TSB, Banister stacks, snapshots | `training_load.py`, `fitness_model.py`, `banister_*.py` |
| [performance-scores.md](performance-scores.md) | Endurance/speed scores, per-run signals | `running_performance.py`, `speed_signal.py`, `endurance_signal.py` |
| [projection.md](projection.md) | Forward CTL projection, race time, calibration | `projection.py`, `score_ceiling.py`, `riegel.py`, `race_finish_estimator.py` |
| [readiness.md](readiness.md) | Daily readiness score(s) | `services/readiness/`, inline formulas in `main.py` |
| [acwr-guardrail.md](acwr-guardrail.md) | Injury-risk ratio + ramp warnings | `acwr.py`, `guardrail.py` |
| [plan-matching.md](plan-matching.md) | Plan-tab planned-session → workout matcher (states, thresholds) | `plan_matching.py` |
| [load-plan.md](load-plan.md) | Race-anchored ramp/hold/taper weekly TSS targets (Session Load Plan) | `load_plan.py` |
| [fuel.md](fuel.md) | Daily calorie budget, macro targets, weekly deficit projection | `fuel.py` |

## Caching summary

| Result | Cache | Invalidation | Gap |
|---|---|---|---|
| `workouts.tss`, signals | persisted columns | threshold change → recompute (runs only) | non-run types never recomputed |
| CTL/ATL/TSB daily | `training_load_snapshots` upsert | on workout write + manual refresh | historical edits not back-propagated; hot read paths (`current_load`) bypass the table and recompute live |
| `daily_readiness` | table upsert | explicit `POST /api/readiness/compute` only | editing `daily_metrics` leaves stale readiness |
| Plan-tab bundle | `training_plans.computed_cache` JSONB + `computed_signature` | content signature (workout count/created_at, race updated_at, prefs, plan.updated_at) | **workout edits invisible** — `workouts` has no `updated_at`; checkpoint CRUD also outside signature |
| Weekly/monthly summaries | in-process `_SUMMARY_CACHE` dict | signature; lost on restart (by design) | per-worker in multi-worker deploys |
| `/api/athletes/{id}/performance` | none | — | full recompute of all runs + splits per request |

## ML roadmap (concept)

Each doc has a detailed "ML-readiness" section. The cross-cutting picture:

**Ready to model today** (features and labels already in the DB):
- Race time prediction — features: CTL/ATL/TSB at race date, duration-curve
  bests, endurance/speed scores, weight trend; label: `races.actual_time_seconds`.
  Regression on log(pace) with distance as a feature (a *learned* Riegel exponent).
  Cleanest first ML project in the app.
- Per-user Banister time constants — the fitting stack (`banister_fitting.py`,
  `model_refit.py`, `refit_scheduler.py`) already exists but is only partially
  wired (weekly daemon thread runs `banister_pipeline`; the refit_scheduler
  stack is test-only). Finishing the wiring beats writing anything new.

**Blocked on data logging — start collecting now:**
1. **Persist every prediction with a timestamp** (projected CTL/TSB, predicted
   race time, predicted peak week, confidence band). Without a
   forecast-vs-actual dataset, no confidence band or projection model can ever
   be learned. Today projections are computed and discarded.
2. **Injury / illness / missed-session log.** Required label for any learned
   guardrail or ACWR replacement. Not collected at all today.
3. **Consistent session-RPE / feel coverage** linked to morning readiness
   (`workout_feel` table exists; coverage and linkage are the gap). Label for
   both a learned TSS (predict sRPE from stream features) and a personalized
   readiness model.
4. **Environment per workout** (temperature/humidity — `heat_correction.py`
   exists but is not wired into any signal) and terrain/elevation in TSS.
5. **Score history table.** Endurance/speed scores are recomputed on the fly
   and never stored as a time series, so no trend model can be trained and the
   trend arrow is re-derived per request.
6. **Merge provenance from reconcile** (which source won each field) — needed
   for any future data-quality model, and cheap to log.
7. **Formula/version stamp on every persisted derived value** (`daily_readiness`
   rows, cached bundles). `tss_method` already does this for TSS — extend the
   pattern, or retraining datasets will mix formula generations.

**Model shapes** (details per doc): TSS → gradient-boosted regression on
stream features vs sRPE label. Fitness → state-space / Kalman over daily load
(or just per-user fitted τ1/τ2). Readiness → per-user hierarchical regression
with population prior for cold start. Race time → log-pace regression.
Guardrail → survival/classification once injury labels exist. Scores → keep
per-run signals as engineered features; replace min-max+EWMA with an
absolute-anchored latent fitness state.
