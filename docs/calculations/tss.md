# TSS — Per-Workout Training Stress

**Purpose:** convert one workout into a scalar stress value. TSS is the fuel
for everything downstream: CTL/ATL/TSB, ACWR, guardrail, projections. If TSS
is mis-calibrated, every model above it inherits the error.

## Current formula

Core (`backend/services/tss.py:35`):

```
TSS = duration_s × IF² / 36        (≡ hours × IF² × 100, Coggan)
```

### Running TSS — method precedence Power → Pace → HR

`compute_running_tss` (tss.py:98-279):

- **Power**: delegates to `running_tss_power.py` (NP-based, IF = NP/FTP).
- **Pace**: per-lap `lap_IF = threshold_pace / lap_pace`, summed
  `lap_dur/3600 × IF² × 100` (tss.py:204-229).
- **HR**: `IF = avg_hr / threshold_hr`; per-lap when all laps have HR
  (tss.py:250-277).
- `partial=True` when lap coverage < 95 % of duration (tss.py:225) or
  whole-workout averages were used.

### Fallback estimator

`estimate_tss_for_workout` (tss.py:713-737): power → pace → hr →
**`duration_only` with hardcoded IF = 0.7** (tss.py:737).

### Strength TSS

- Session-RPE: `TSS = (rpe/10)² × hours × 100` (tss.py:575-710).
- Per-set: `Σ reps × (rpe/10)²` scaled by `STRENGTH_TSS_SCALE = 5.85`,
  clamped at `STRENGTH_TSS_MAX = 150` (tss.py:26-30, 740-845).
- Pref-driven variant `compute_strength_tss` (tss.py:966-1195).

### Persistence

`persist_running_tss` (tss.py:1198-1243) writes `workouts.tss` only when NULL
(manual entry wins), always writes `tss_method`.
`recompute_user_running_tss` (tss.py:1304-1321) recomputes when thresholds
change — but only `workout_type ilike 'run%'`.

## Inputs / outputs

- **In:** `workouts` (duration, np, avg_hr, distance), `workout_splits`
  (per-lap dur/dist/hr/power), `user_preferences` (ftp_w, threshold_hr,
  threshold_pace_seconds_per_km, strength scale/max).
- **Out:** `workouts.tss`, `tss_source`, `tss_method`.

## Constants and assumptions

- Module defaults `THRESHOLD_PACE_SEC_PER_KM=270`, `THRESHOLD_HR=170`,
  `FTP_W=280` (tss.py:17-19) — **silently applied** when prefs are missing
  (`get_user_thresholds`, tss.py:53-95). A new user gets TSS calibrated to a
  4:30/km runner.
- `duration_only` IF=0.7 assumes every unquantified workout is a moderate
  endurance session.
- Quadratic IF assumes Coggan's power model transfers to pace/HR ratios (no
  NGP grade correction on the pace path — `treadmill_ngp.py` exists but is
  separate).

## Known weaknesses

1. **Two code paths with different calibration**: `compute_running_tss`
   (prefs-strict) vs `estimate_tss_for_workout` (silent hardcoded defaults).
   Reconcile uses the default-happy one (`reconcile.py:499-509`), workout CRUD
   uses the strict one → **synced runs can be scored on a different scale
   than manually entered runs for the same user**.
2. HR-based TSS ignores cardiac drift and temperature; pace TSS ignores
   elevation.
3. Threshold-change recompute misses non-run workout types.

## ML-readiness

- **Features already stored:** NP, avg/max HR, splits, streams
  (`activity_streams`), cadence, stride, elevation.
- **Label:** session-RPE / `workout_feel` (table exists — coverage is the gap).
- **Model shape:** gradient-boosted regression predicting sRPE-TSS from stream
  features replaces the IF² heuristic.
- **Missing logging:** per-workout temperature/humidity; consistent feel
  capture; the chosen method + inputs at compute time (a debug dict is built
  and returned but not persisted).

## Caching

Persisted in `workouts.tss`; invalidated by threshold change (run-type only).
