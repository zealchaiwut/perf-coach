# Performance Scores — Endurance & Speed

**Purpose:** two 0–100 scores summarizing how the athlete's easy/steady
running efficiency (endurance) and high-intensity capability (speed) are
trending. Computed in `backend/services/running_performance.py` (pure),
served by `GET /api/athletes/{id}/performance` (main.py:14097-14300) and two
"as-of" helpers (`_workout_signal_scores` main.py:5402, `_athlete_scores_as_of`
main.py:5531).

## Endurance score algorithm (running_performance.py:146-270)

1. **Lap classification** (`lap_classify.py:38-55`): ratio bands
   easy <0.80 ≤ steady <0.90 ≤ tempo <1.00 ≤ threshold <1.06 ≤ hard.
   Endurance uses easy+steady laps; speed uses hard+interval
   (zone_constants.py:47-48). **Tempo/threshold laps are excluded from both.**
2. **Per-run efficiency** = duration-weighted power/HR, else (km/min)/HR
   (`_efficiency_from_laps` :518-577).
3. **Durability factor** = `1 − clamp(decoupling_pct, 0, 50)/50` (:206-212).
4. **Window**: trailing 90 days (:131-139); min 3 qualifying runs
   (`MIN_QUALIFYING_RUNS=3`) else status `building_baseline`.
5. **Min-max normalize** adjusted efficiencies to 0–100 *within the window*
   (`_normalise_values` :463-475; all-equal ⇒ 50).
6. **Duration-weighted EWMA** (α=0.2, weight = min(1, dur/3600),
   `_compute_ewma_series` :478-502); score = last EWMA value; direction from
   last-3 slope vs `DIRECTION_SLOPE_THRESHOLD=0.005` (:661-684).
7. × body_modifier (weight-trend uplift/penalty, EA-proxy override —
   `body_modifier.py:57-60`), clamp 0–100.

## Speed score (running_performance.py:273-432)

- Prefers persisted `workouts.speed_signal` when present (effort weight
  = min(1, signal/1.30)); else lap-efficiency fallback with duration-curve
  proximity `adjusted = eff × (0.5 + 0.5·min(1, avg_power/best))` (:357-370).
- Confidence band ±10, ×1.5 when <5 efforts (:687-723) + `low_data_warning`.

## Per-run signals (feature extractors)

### Speed signal (`speed_signal.py`)

- Scans splits 60–360 s windows (:65-66), keeps threshold/hard bands, returns
  the **max ratio** (:86-168). Basis precedence power→pace→HR.
- Prefers manual laps derived from Stryd streams over stored 1 km auto-splits
  (:171-262) so sub-km intervals qualify.
- Out: `workouts.speed_signal`, `_basis`, `_window_seconds`, `_source`.
- Weaknesses: single best window (repeat quality invisible); window misses
  30 s reps and 8+ min efforts; HR ratio ≠ power ratio at equal effort.

### Endurance signal (`endurance_signal.py`)

- Runs > 40 min only (:34). Split at time midpoint; efficiency per half;
  `decoupling% = (e1−e2)/e1×100`; `signal = max(0, 100 − decoupling%)` (:46-171).
- Weaknesses: warm-up HR lag inflates first-half efficiency; negative splits
  exceed 100 (floored at 0, not capped); reimplements the same half-split
  math as `aerobic_decoupling.py`.

## Known weaknesses

1. **Relative normalization is the core conceptual problem.** Min-max within
   the athlete's own 90-day window means the score is not comparable across
   time or athletes; score 100 just means "best run of the last 90 days". A
   uniformly improving athlete oscillates instead of trending up.
2. Mixed efficiency units (power/HR vs speed/HR) normalized together when
   some runs lack power.
3. **Bug: durability silently disabled in two of three paths.**
   `_workout_signal_scores` (main.py:5480-5492) and `_athlete_scores_as_of`
   (main.py:5606-5619) call
   `compute_decoupling(split_dicts, {"workout_type": ...})` — real signature
   is `(workout, splits_or_stream, threshold)` returning a tuple
   (aerobic_decoupling.py:30-34). TypeError swallowed by
   `except Exception: dpct = None`. The main `/performance` endpoint calls it
   correctly → same metric, different value per endpoint.
4. Three near-verbatim copies of the run-assembly/classification logic
   (main.py:5402, :5531, :14122) with slightly different prefs handling.
5. Decoupling computed three ways (`aerobic_decoupling.py`,
   `endurance_signal.py`'s own reimplementation, the broken main.py calls).

## ML-readiness

- **Keep the per-run signals as engineered features.** The replacement target
  is the aggregation layer: min-max + EWMA → an absolute-anchored latent
  fitness state (Gaussian process or state-space model over per-run
  efficiency).
- **Labels:** race results, duration-curve bests.
- **Missing:** absolute anchoring data (regular benchmark efforts); a
  **score history table** — scores are recomputed from scratch per request,
  never persisted, so no trend dataset accumulates; heat/terrain
  normalization (`heat_correction.py` exists, unwired).

## Caching

None on this branch for `/performance` — full recompute of all runs + splits
+ classification + decoupling per request (O(total laps),
main.py:14152-14223). Weekly/monthly summaries use the in-process
`_SUMMARY_CACHE` (main.py:14350-14373). The Neon L2 persistence work lives on
the `feature/performance-tab-rework` branch, not yet merged here.
