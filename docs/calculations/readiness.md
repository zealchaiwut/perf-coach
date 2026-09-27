# Readiness — Daily Wellness Score

**Purpose:** one 0–100 number each morning from wellness inputs (HRV, RHR,
sleep quality, energy).

**Canonical formula (sprint 103 / #1348):** every wellness surface uses
`services/readiness/calculator.py`. Home (`GET /api/home/readiness` and the
`/api/home/summary` readiness block), trends, and `POST /api/readiness/compute`
all call this calculator. Auto-recompute runs after
`POST`/`PATCH`/`PUT /api/daily-metrics` (#1349).

## Weights

HRV 0.40 / RHR 0.20 / sleep quality 0.20 / energy 0.20
(calculator.py). Missing signals are **renormalized** over the ones present.
Mood is logged on Home but is **not** a scored input. Sleep **hours** are
logged and shown in the explanation; the scored sleep signal is
`sleep_quality` (1–5).

- HRV/RHR: CV-normalized z-score vs baseline (HRV 7-day, RHR 30-day;
  min 2/3 baseline days); `score = clamp(50 + z·20)`.
- Sleep quality / energy: linear `(x−1)/4 × 100`.
- All scored inputs absent → `compute_readiness` returns `None`, no row
  written (Home shows “No metrics logged yet”).
- HRV omitted if fewer than 2 baseline days; RHR omitted if fewer than 3.

Stored in `daily_readiness` via upsert on (user_id, date). Home also
recomputes live on read (same formula) so the tile matches the latest
metrics even if a write-path recompute failed.

CLI: `python -m services.readiness.job --user-id <uuid> --date <YYYY-MM-DD>`.

## TSB form is not this score

`training_load.readiness_label` maps TSB to Fatigued / Optimal / Fresh.
API payloads use `form_label` (preferred) with a deprecated
`readiness_label` alias, and weekly summary still exposes
`readiness_next_week` as that TSB form string. That is training-load
freshness, not the 0–100 wellness score. Do not mix the two.

## Known weaknesses

1. Short HRV/RHR windows make early scores jumpy.
2. No HRV outlier rejection.
3. Mood is collected and unused.
4. Stored rows carry no formula-version stamp.

## ML-readiness

Still the most textbook ML target in the app (next-day energy, RPE vs plan,
HRV rebound). Parked until logging coverage on `workout_feel` is real.
