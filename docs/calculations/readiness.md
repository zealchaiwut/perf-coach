# Readiness — Daily Wellness Score

**Purpose:** one 0–100 number each morning from wellness inputs (HRV, RHR,
sleep, energy, mood).

**Problem: four different "readiness" formulas coexist**, three of them
scoring the same wellness inputs differently. The home card, the trends
chart, and the stored `daily_readiness` row can disagree for the same day.

## 1. Canonical (persisted) — `services/readiness/`

`calculator.py` + `job.py`; triggered ONLY by `POST /api/readiness/compute`
(main.py:8035-8060) or the CLI. (Note: lives in top-level `services/`, not
`backend/services/`.)

- Weights: HRV 0.40 / RHR 0.20 / sleep-quality 0.20 / energy 0.20
  (calculator.py:13-16), **renormalized over available signals** (:129-137).
- HRV/RHR: CV-normalized z-score vs baseline (HRV 7-day, RHR 30-day windows;
  min 2/3 baseline days); `score = clamp(50 + z·20)` (ZSCORE_SCALE=20,
  :52-76).
- Sleep quality / energy: linear `(x−1)/4 × 100`.
- Stored in `daily_readiness` (score, components JSONB, computed_at) via
  raw-SQL upsert on (user_id, date) (job.py:92-111).
- **Invalidation gap:** editing a `daily_metrics` row does NOT recompute the
  stored readiness — stale until the compute endpoint is called again.

## 2. Home readiness — `GET /api/home/readiness` (main.py:2606-2760)

- Different weights: sleep_hours 0.30 / HRV 0.25 / RHR 0.20 / mood 0.15 /
  energy 0.10.
- Per-factor `50 ± delta_pct` vs 7-day mean; **missing factor = 50, not
  renormalized**.
- Labels ≥80 Excellent … <20 Recovery (main.py:2591-2603).

## 3. Trends readiness — `_compute_readiness` (main.py:7777-7797)

- Unweighted mean of fixed linear maps: HRV 20→100 ms ⇒ 0→100; RHR 90→40 bpm
  ⇒ 0→100; sleep 4→9 h ⇒ 0→100; quality/energy/mood `(x−1)/4`.
- No baselines at all. Used by trends/summary series (main.py:7967, 8000).

## 4. TSB "readiness" label — `training_load.readiness_label` (:917-938)

Fatigued/Optimal/Fresh from TSB; surfaces as `readiness_next_week` in the
weekly summary (main.py:14456). A completely different concept sharing the
name.

## Known weaknesses

1. Three wellness formulas → three numbers for the same day.
2. No HRV outlier rejection; short baseline windows give unstable CV early on.
3. Missing mood ⇒ contributes exactly 50 in formula 2 (bias toward the middle).
4. Stored rows carry no formula-version stamp — retraining data would mix
   generations.

## ML-readiness

The most textbook ML target in the app.

- **Features:** `daily_metrics`, prior TSS/ATL, sleep imports, weight EWMA.
- **Label options:** next-day subjective energy; session-RPE-vs-planned
  deviation; HRV rebound.
- **Model:** per-user personalized regression / Bayesian hierarchical model
  (population prior for cold start).
- **Missing logging:** post-workout outcome tied to morning readiness ("did
  the session go as planned?") — `workout_feel` + `feel_link.py` exist, but
  coverage and linkage are the gap; formula version stamps on stored rows.

## Caching

`daily_readiness` upsert, explicit-compute only (see invalidation gap above).
Formulas 2–4 are computed live per request, uncached.
