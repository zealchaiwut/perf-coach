# Readiness Score — Methodology

## Overview

The daily readiness score summarises recovery and training readiness as a single
number in **[0, 100]**. Higher is better. It is computed from four physiological
and subjective signals stored in `daily_metrics` and a rolling baseline window.

---

## Formula

### Signals and weights

| Signal | Column | Weight |
|---|---|---|
| Heart-rate variability (HRV) | `hrv` | **0.40** |
| Resting heart rate (RHR) | `resting_hr` | 0.20 |
| Sleep quality | `sleep_quality` | 0.20 |
| Subjective energy | `energy` | 0.20 |

All four weights sum to **1.0**.

### Per-signal component scores (0–100)

**HRV (CV approach, HRV4Training methodology)**

1. Collect HRV values from the preceding `HRV_WINDOW = 7` days (excludes today).
2. Compute the baseline mean and population standard deviation.
3. Derive the coefficient of variation: `CV = std / mean`.
4. Compute CV-normalised deviation:
   ```
   z = (today_hrv − mean) / (CV × mean)   if CV ≥ 0.01
   z = (today_hrv − mean) / max(1, std)    otherwise (low-variability fallback)
   ```
5. Map to [0, 100]:
   ```
   hrv_score = clamp(50 + z × 20, 0, 100)
   ```
   Interpretation: z = +2.5 → 100 (strongly above baseline); z = −2.5 → 0.

Reference: Altini, M. & Plews, D. (2021). *What Is behind Changes in Resting Heart Rate
and Heart Rate Variability?* Frontiers in Physiology, 12, 696872.
https://doi.org/10.3389/fphys.2021.696872

**RHR (30-day deviation)**

1. Collect RHR values from the preceding `RHR_WINDOW = 30` days.
2. Compute the same CV-normalised z-score, but negate it (lower RHR is better):
   ```
   z = −(today_rhr − mean) / denom
   rhr_score = clamp(50 + z × 20, 0, 100)
   ```

**Sleep quality (linear scale)**

```
sleep_score = (sleep_quality − 1) / 4 × 100
```

`sleep_quality` is stored as an integer 1–5; values map linearly from 0 to 100.

**Energy (linear scale)**

```
energy_score = (energy − 1) / 4 × 100
```

Same linear mapping as sleep quality.

### Final score

```
final_score = Σ (w_i / total_available_weight) × component_score_i
```

where `total_available_weight` is the sum of weights for signals that are **present
and have a sufficient baseline**. This normalises the weights so they always sum to 1.0
even when some signals are absent.

Each signal's additive contribution stored in the `components` JSON satisfies:

```
hrv_contribution + rhr_contribution + sleep_contribution + energy_contribution
    = final_score   (within floating-point tolerance)
```

---

## Edge-case handling

| Situation | Behaviour |
|---|---|
| Fewer than `HRV_MIN_DAYS = 2` HRV baseline days | HRV signal omitted; its weight redistributed proportionally to other available signals |
| Fewer than `RHR_MIN_DAYS = 3` RHR baseline days | RHR signal omitted; weight redistributed |
| `sleep_quality` or `energy` is NULL | Signal omitted; weight redistributed |
| All signals absent (all NULL, no baseline) | Function returns `None`; no row is written to `daily_readiness` |
| Baseline mean == 0 | Component score defaults to 50 (neutral) |
| CV < 0.01 (near-constant baseline) | Falls back to absolute std (floor 1) as denominator |

---

## Determinism

The function `compute_readiness` in `services/readiness/calculator.py` is a pure
function. Given the same `(hrv, resting_hr, sleep_quality, energy, hrv_baseline,
rhr_baseline)` tuple, it always produces the same `ReadinessResult`. There is no
randomness, clock access, or I/O inside the function.

---

## `daily_readiness` table

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, `gen_random_uuid()` |
| `user_id` | UUID | FK → `users.id` (CASCADE) |
| `date` | DATE | Target date |
| `score` | NUMERIC(5,2) | Final readiness score |
| `components` | JSONB | Per-signal additive contributions |
| `computed_at` | TIMESTAMPTZ | Timestamp of computation |
| `daily_metric_id` | UUID | FK → `daily_metrics.id` (SET NULL on delete) |

Unique constraint: `(user_id, date)`.

### `components` JSON structure

```json
{
  "hrv_contribution":    12.34,
  "rhr_contribution":    10.00,
  "sleep_contribution":  25.00,
  "energy_contribution": 18.75
}
```

---

## Triggering computation

**Admin API endpoint** (POST, requires running backend):

```
POST /api/readiness/compute?user_id=<uuid>&date=<YYYY-MM-DD>
```

The endpoint is idempotent: if a row already exists for `(user_id, date)` it is
upserted (overwritten) with the freshly computed value.

**CLI** (for backfilling):

```bash
python -m services.readiness.job --user-id <uuid> --date <YYYY-MM-DD>
# or for a date range:
python -m services.readiness.job --user-id <uuid> --from 2026-01-01 --to 2026-05-27
```
