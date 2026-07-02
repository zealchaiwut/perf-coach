# Endurance/Speed score re-anchor — analysis & proposal

Status: **PARKED** (to be revised later). This captures why the current
Endurance/Speed scores don't reflect current fitness, the machinery already
available to fix it, and a concrete proposed design. It is a decision record,
not yet implemented.

See also: [`performance-scores.md`](performance-scores.md) (current reference),
[`projection.md`](projection.md), [`training-load.md`](training-load.md).

---

## 1. Symptom that triggered this

On the Performance tab, Speed showed **43 with "↑ +43 this block"** and the
value didn't match how the athlete actually felt (not currently at Speed 43).
An **aborted** interval session (`a1d6a936-…`, "Hard Intervals", cut short from
exhaustion) *raised* Endurance and *lowered* Speed — the opposite of intuition.

Both are symptoms of the same root cause: the scores are on a **relative**
scale, not an absolute one.

## 2. How scores are computed today

Files: `backend/services/running_performance.py` (`compute_endurance_score`,
`compute_speed_score`), surfaced by `GET /api/athletes/{id}/performance`
(`backend/main.py` ~14129), and reused by `_workout_signal_scores` (~5411),
`_athlete_scores_as_of` (~5540).

Pipeline per score:

1. Build per-run "efficiency":
   - Endurance: aerobic laps (bands `easy`/`steady`), `efficiency = avg_power/avg_hr`
     (or `(distance_km/duration_min)/avg_hr` when no power), then
     `durability_factor = max(0, 1 − decoupling_pct/50)`,
     `adjusted = efficiency × durability_factor`.
   - Speed: hard/interval laps (bands `hard`/`interval`); uses stored
     `workout.speed_signal` when present, else a lap efficiency with a
     duration-curve proximity adjustment.
2. Restrict to a **90-day trailing window** (`_filter_trailing_window`,
   `PERFORMANCE_CONFIG["trailing_window_days"] = 90`).
3. **Normalize relative to the window** — the problem step:

   ```python
   # _normalise_values(values)  (running_performance.py:463)
   return [(v - min_v) / (max_v - min_v) * 100 for v in values]
   ```

4. EWMA-smooth the normalized series (`_compute_ewma_series`, alpha 0.2
   endurance / 0.3 speed, weighted by duration for endurance).
5. `direction` from the slope of the last 3 EWMA points; `score` = last EWMA
   value clamped to [0,100]; `trend[]` = the EWMA history (oldest first).

### Why this misbehaves

- **Not absolute.** `(v−min)/(max−min)×100` maps the window's worst effort to 0
  and best to 100. So "Speed 43" means *43% of the way between your worst and
  best recent session* — not a fitness level. A lifetime-best run can read ~50
  if the window also holds a better one; a mediocre window can read 100.
- **Detraining can't lower it.** Stop training and the window's min/max just
  rescale around the remaining data; the number doesn't decay.
- **A bad session distorts it.** Adding a slow/aborted session changes the
  window min/max, shifting *every* normalized value — including "current".
  That's why the aborted intervals moved Speed down (new low pulled the scale)
  and, via the durability factor on a low-HR truncated run, nudged Endurance up.
- **"+43 this block" is an artifact.** The block delta (frontend
  `training-performance.js:_blockDelta`) is `last − trend[~8 back]`. Speed's
  EWMA trend starts at the baseline floor, so the delta captures the whole
  ramp from ~0, not a block-over-block change.

## 3. Absolute machinery already in the codebase (reuse, don't reinvent)

The Projection tab already speaks an **absolute** score↔pace scale:

- `backend/services/race_finish_estimator.py` — `score_to_estimated_finish_time`:

  ```
  estimated_pace = threshold_pace × (2 − score/100)      # SLOW_FACTOR = 2.0
  ```

  → score 100 = threshold pace; score 0 = 2× threshold pace (half speed).

- `backend/services/score_ceiling.py` — `ceiling_from_b_race_result` inverts it:

  ```
  actual_pace = actual_time_seconds / distance_km
  score = (2 − actual_pace / threshold_pace) × 100        # clamped 0–100
  ```

  → maps a real race result to an absolute score.

- `projected_ctl_to_score_ceiling(ctl)`: `ctl/150 × 100` (CTL→ceiling) when no
  race anchor is available.

- Latest race selection (main.py ~12938):

  ```sql
  SELECT * FROM races
  WHERE user_id = ? AND status = 'done' AND actual_time_seconds IS NOT NULL
  ORDER BY updated_at DESC LIMIT 1
  ```

- Thresholds in `UserPreferences`: `threshold_pace_seconds_per_km`, `ftp_w`,
  `threshold_hr`, `aerobic_decoupling_threshold`.

The Performance tab scores should live on this **same** absolute scale so the
number on Log / Performance / Projection all mean the same thing
("one score everywhere").

## 4. Proposed re-anchor design (for later implementation)

Goal: score reflects **current demonstrated fitness on an absolute scale**,
calibrated to the latest race, that (a) does not fall from a single bad/aborted
session, and (b) decays with detraining.

### 4.1 Absolute per-run performance

Replace the relative `_normalise_values` step with an absolute map anchored on
threshold, identical in scale to the race formula:

```
perf_i = clamp( (2 − effort_ratio_i) × 100 , 0, 100 )
```

where `effort_ratio_i = demonstrated_pace_i / threshold_pace`
(power analogue: `threshold_power / demonstrated_power`), computed from:

- **Speed:** the run's best sustained hard effort (use `speed_signal` /
  duration-curve best). Confirm `speed_signal` basis (power vs pace) and what
  value equals threshold before mapping.
- **Endurance:** the durability-adjusted aerobic effort expressed as an
  equivalent threshold-relative pace at controlled HR (keep the decoupling
  durability factor).

Requires threshold_pace (and/or ftp_w). Missing → keep the existing
`needs_thresholds` state.

### 4.2 Aggregate = recency-decayed demonstrated peak

```
score(t) = max over runs i with date ≤ t of
           ( perf_i − decay_points(days_since_i) )        # clamp ≥ 0
```

- Best recent effort sets the score → **an aborted/slow session (low perf_i)
  can never lower the max** (fixes the a1d6a936 complaint).
- `decay_points(d) = DECAY_PER_WEEK × max(0, d/7 − GRACE_WEEKS)` → if training
  stops, the best effort ages and its decayed contribution falls → **detraining
  lowers the score**. Suggested starting constants: `GRACE_WEEKS ≈ 2`,
  `DECAY_PER_WEEK ≈ 2–3` pts (tune against real data / CTL 42-day half-life).

### 4.3 Race calibration

Inject the latest finished race as a high-confidence perf data point at its
date: `perf_race = ceiling_from_b_race_result(actual_time, distance, threshold_pace)`.
The race then directly anchors the demonstrated peak and keeps Performance
consistent with the Projection tab's estimate for that race.

### 4.4 Trend & block delta

- `trend[]` = `score(t)` recomputed per date over the window (a real trajectory,
  not an EWMA of normalized values).
- Block delta = `score(now) − score(4 weeks ago)`; hide while building baseline.
  This kills the "+43 this block" artifact.

## 5. Constraints for whoever implements this

- Preserve return shapes: `score`, `direction`, `trend`, `qualifying_session_count`,
  `confidence_band` (speed), `debug`; and the `scored` / `building_baseline` /
  `needs_thresholds` / `missing` states.
- Keep "one score everywhere": `/api/athletes/{id}/performance`,
  `_workout_signal_scores`, `_athlete_scores_as_of`, and the Projection tab must
  all read the same absolute scale.
- Cache: bump a VERSION token inside `_performance_signature` (main.py ~14481)
  when the formula changes so the durable `summary_cache` (Neon) busts.
- Tests that assert the old relative behavior must be **updated to the new
  absolute contract**, not deleted:
  `test_running_performance__701`, `test_ewma_performance_scores__1051`,
  `test_speed_score_sparse_signal_density__1164`,
  `test_wire_body_modifier_power_to_weight__1159`, and the ceiling/estimator
  tests (`__1108`, `__1106`, `__1162`).

## 6. Validation targets (sanity-check with real data)

- Athlete `zeal` (id `4a07e4f2-69a6-4123-b77e-b1f7dce758cf`): resulting
  Endurance/Speed should feel current and be consistent with the Projection
  race estimate.
- Aborted intervals `a1d6a936-…`: must **not** lower Speed.
- A simulated training gap must **lower** the score over time (detraining).
- Confirm the block delta reads sensibly small (no "+43").
