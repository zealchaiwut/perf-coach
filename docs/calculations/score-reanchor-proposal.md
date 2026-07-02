# Endurance/Speed score re-anchor — analysis & proposal

Status: **DECIDED, not yet implemented** (design settled 2026-07-02 in an
operator discussion; see §4 decision log). This captures why the current
Endurance/Speed scores don't reflect current fitness, the machinery already
available to fix it, and the agreed design.

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

**Estimator rework is deferred.** The linear `(2 − ratio)` scale above stays in
place for the Projection tab for now; the new Performance scores use a
**universal, non-linear (VDOT-based) band** instead (see §4.1). Once real data
accumulates, the estimator/ceiling formulas get reworked onto the same VDOT
scale so "one score everywhere" is restored — the band is universal precisely
so the two can be mixed later without another migration.

## 4. Agreed re-anchor design (decided 2026-07-02)

Goal: score reflects **current demonstrated fitness on a universal absolute
scale**, calibrated to the latest race, that (a) does not fall from a single
bad/aborted session, and (b) decays with detraining.

Decision log (each point discussed and chosen explicitly):

| # | Decision | Choice |
|---|----------|--------|
| 1 | Anchor curve | Non-linear, universal band (not the linear estimator formula); estimator reworked later |
| 2 | Universal reference | **VDOT** (Daniels VO2-equivalent from pace + duration) |
| 3 | Band rescale | Linear: `score = (VDOT − 30) / 55 × 100`, clamped 0–100 |
| 4 | Aggregate | **Decayed top-3 mean** (not single max) |
| 5 | Decay | 2-week grace, then **1.5 pts/week** |
| 6 | Endurance mapping | HR-extrapolated VDOT × decoupling durability factor |
| 7 | Race calibration | Race VDOT is a perf point **and** a decayed floor |
| 8 | Window | Keep the existing 90-day trailing window (decay applies inside it) |
| 9 | Trend & delta | True `score(t)` per date; delta = now − 4 weeks ago |

### 4.1 Universal per-run performance (VDOT)

Replace the relative `_normalise_values` step with a per-run **VDOT**
(Daniels/Gilbert): from the run's velocity `v` (m/min) and effort duration,

```
VO2       = −4.60 + 0.182258·v + 0.000104·v²
%VO2max   = 0.8 + 0.1894393·e^(−0.012778·t) + 0.2989558·e^(−0.1932605·t)   # t in min
VDOT_i    = VO2 / %VO2max
```

then rescale to the displayed band:

```
perf_i = clamp( (VDOT_i − 30) / 55 × 100 , 0, 100 )      # VDOT 30 → 0, 85 → 100
```

The band is **universal** (athlete-independent): score ~45 ≈ VDOT 55, and any
athlete's runs land on the same scale. Per score:

- **Speed:** the run's best sustained hard effort (from `speed_signal` /
  duration-curve best) → pace + duration → VDOT as above. Confirm
  `speed_signal` basis (power vs pace) before mapping; if power, convert via
  the athlete's pace–power relation or fall back to lap pace.
- **Endurance:** **HR-extrapolated VDOT** — take the aerobic lap's pace and
  extrapolate to threshold intensity via heart rate,
  `equivalent_threshold_pace ≈ lap_pace × (avg_hr / threshold_hr)`
  (i.e. equivalent speed `= lap_speed / (avg_hr / threshold_hr)`), feed that
  through the VDOT formula at a threshold-effort duration, then multiply by the
  existing decoupling `durability_factor`. Same universal band as Speed.

Requires `threshold_hr` (endurance) and pace data. Missing → keep the existing
`needs_thresholds` state.

### 4.2 Aggregate = decayed top-3 mean

```
decayed_i  = perf_i − decay_points(days_since_i)          # clamp ≥ 0
decay_points(d) = 1.5 × max(0, d/7 − 2)                   # 2wk grace, 1.5 pts/wk
score(t)   = mean of the 3 largest decayed_i over runs with date ≤ t
             (within the 90-day window)
```

- Top-3 mean, not max: **outlier-resistant** — one GPS blip / downhill segment
  can't set the score for weeks, while an aborted/slow session (low `perf_i`)
  still **can never lower it** (fixes the a1d6a936 complaint).
- Decay: if training stops, the best efforts age and their decayed values fall
  → **detraining lowers the score**. 1.5 pts/week after a 2-week grace tracks
  VO2max detraining literature (~5–7% after 3–4 weeks ≈ ~6 pts/month on this
  band). Tune against real data.
- Fewer than 3 qualifying runs → existing `building_baseline` state.
- The 90-day window stays as the qualifying cutoff; decay operates inside it.
  (Known artifact: a peak effort ages out entirely at day 91 — accepted.)

### 4.3 Race calibration — perf point + floor

The latest finished race converts to VDOT directly (Daniels' native use — the
highest-confidence data point available):

```
perf_race = rescale( vdot(actual_time_seconds, distance_km) )
```

It enters the score in **two** ways:

1. As an ordinary perf point in the top-3 pool at its date.
2. As a **decayed floor**: `score(t) ≥ perf_race − decay_points(days_since_race)`
   → a couple of mediocre training weeks can't drag the score below what was
   actually raced; only time (decay) erodes the race anchor.

### 4.4 Trend & block delta

- `trend[]` = `score(t)` recomputed per date over the window (a real trajectory,
  not an EWMA of normalized values). The line is step-like — steps are real
  (new peak effort entering the top-3, or decay ticking) — no smoothing.
- Block delta = `score(now) − score(4 weeks ago)`; hide while building baseline.
  This kills the "+43 this block" artifact.

## 5. Constraints for whoever implements this

- Preserve return shapes: `score`, `direction`, `trend`, `qualifying_session_count`,
  `confidence_band` (speed), `debug`; and the `scored` / `building_baseline` /
  `needs_thresholds` / `missing` states.
- "One score everywhere" is **phased**: `/api/athletes/{id}/performance`,
  `_workout_signal_scores`, `_athlete_scores_as_of` all move to the VDOT band
  together in this change; the Projection tab (`race_finish_estimator.py`,
  `score_ceiling.py`) keeps its linear threshold scale for now and is reworked
  onto the VDOT band later, once real data exists to validate the mapping.
  Until then the two tabs are on different scales — surface that in the UI or
  docs, don't silently mix them.
- Implement the VDOT math in one shared helper (e.g.
  `backend/services/vdot.py`: `vdot_from_pace_duration`, `rescale_to_score`)
  so the later estimator rework reuses it.
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
  Endurance/Speed should feel current; sanity-check the raw VDOT behind the
  score against a recent race (Daniels tables) before trusting the band.
- Aborted intervals `a1d6a936-…`: must **not** lower Speed (top-3 mean ignores
  low perf points).
- One outlier-fast lap (GPS blip) must move the score by at most ~⅓ of its
  perf excess (top-3 mean, not max).
- A simulated training gap must **lower** the score: flat for 2 weeks (grace),
  then ~1.5 pts/week.
- A finished race must set a floor: mediocre training afterwards can't pull
  the score below `perf_race − decay`.
- Endurance vs Speed should land in a similar band for a balanced athlete
  (HR extrapolation calibrated so easy runs don't systematically read low).
- Confirm the block delta reads sensibly small (no "+43").
