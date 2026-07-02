# Prompt: Re-anchor Endurance/Speed Scores to Universal VDOT Band

> Paste everything below this line into Claude Code, run from the perf-coach
> repo root on a fresh branch off `develop`.

---

You are working on perf-coach (FastAPI + SQLAlchemy, vanilla-JS frontend, no
bundler). Read `CLAUDE.md` first. Source of truth for this design:
`docs/calculations/score-reanchor-proposal.md` (status DECIDED 2026-07-02 —
follow its §4 decision log exactly; do not re-litigate the choices). Also read
`docs/calculations/performance-scores.md` for the current behavior you are
replacing.

Create branch `feature/score-reanchor-vdot` off `develop`. Backend + tests
only — no frontend changes except where §5 below says so. Commit per section
so each step is independently revertable.

## Why

Current Endurance/Speed scores in
`backend/services/running_performance.py` normalize per-run efficiency
**relative to the 90-day window min/max** (`_normalise_values`,
running_performance.py:463). Result: "Speed 43" means 43% of the way between
your worst and best recent session — not a fitness level. Detraining can't
lower it, an aborted session distorts it, and the block delta shows artifacts
like "+43 this block".

## The decided design (summary — full detail in the proposal doc)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Anchor | Universal non-linear band; Projection estimator rework DEFERRED |
| 2 | Reference | VDOT (Daniels VO2-equivalent from pace + duration) |
| 3 | Rescale | `score = (VDOT − 30) / 55 × 100`, clamped 0–100 |
| 4 | Aggregate | Decayed **top-3 mean** (not max, not EWMA of normalized values) |
| 5 | Decay | 2-week grace, then 1.5 pts/week |
| 6 | Endurance | HR-extrapolated VDOT × decoupling durability factor |
| 7 | Race | Race VDOT = perf point in pool **and** decayed floor |
| 8 | Window | Keep existing 90-day trailing window; decay applies inside it |
| 9 | Trend/delta | True `score(t)` per date, step-like, no smoothing; delta = now − 4wk |

## Section 1 — Shared VDOT helper

Create `backend/services/vdot.py` with pure functions (no DB, no FastAPI):

- `vdot_from_pace_duration(velocity_m_per_min, duration_min) -> float` using
  Daniels/Gilbert:
  `VO2 = −4.60 + 0.182258·v + 0.000104·v²`,
  `%VO2max = 0.8 + 0.1894393·e^(−0.012778·t) + 0.2989558·e^(−0.1932605·t)`,
  `VDOT = VO2 / %VO2max`.
- `rescale_to_score(vdot) -> float` = `clamp((vdot − 30) / 55 × 100, 0, 100)`.
- `decay_points(days) -> float` = `1.5 × max(0, days/7 − 2)`.
- Constants (`VDOT_FLOOR = 30`, `VDOT_CEIL = 85`, `GRACE_WEEKS = 2`,
  `DECAY_PER_WEEK = 1.5`, `TOP_K = 3`) at module top so tuning is one-line.
- Unit tests: known Daniels table anchors (e.g. 5k in 20:00 → VDOT ≈ 49–50;
  marathon 3:30 → VDOT ≈ 45–46), rescale endpoints, decay grace behavior.

This helper is deliberately standalone: the Projection tab's
`race_finish_estimator.py` / `score_ceiling.py` will be reworked onto it
LATER — do NOT touch them in this branch.

## Section 2 — Per-run perf in running_performance.py

In `backend/services/running_performance.py`:

- **Speed:** per qualifying run, take the best sustained hard effort
  (`speed_signal` / duration-curve best as today). **First verify the basis of
  `speed_signal` (power vs pace) by reading the code that writes it** — if it
  is power-based, convert to pace via the run's own pace–power relation or
  fall back to hard-lap pace. Feed pace + effort duration into
  `vdot_from_pace_duration` → `rescale_to_score` → `perf_i`.
- **Endurance:** per qualifying aerobic lap set, compute
  `equivalent_speed = lap_speed / (avg_hr / threshold_hr)` (extrapolation to
  threshold intensity), feed through VDOT at a threshold-effort duration, then
  multiply the resulting score by the existing decoupling `durability_factor`.
  Requires `threshold_hr` from `UserPreferences` — missing → existing
  `needs_thresholds` state.
- **Delete** `_normalise_values` and the EWMA-of-normalized-values pipeline
  (`_compute_ewma_series` usage for these scores) once nothing references them.

## Section 3 — Aggregate, floor, trend

- `decayed_i = max(0, perf_i − decay_points(days_since_i))`.
- `score(t)` = mean of the **3 largest** `decayed_i` among qualifying runs with
  date ≤ t inside the 90-day window. Fewer than 3 qualifying runs → existing
  `building_baseline` state.
- **Race floor:** fetch the latest finished race (same query as main.py ~12938:
  `status='done' AND actual_time_seconds IS NOT NULL ORDER BY updated_at DESC
  LIMIT 1`). `perf_race = rescale_to_score(vdot_from_pace_duration(...))` from
  actual time + distance. It enters the top-3 pool at its date AND enforces
  `score(t) ≥ perf_race − decay_points(days_since_race)`.
- `trend[]` = `score(t)` recomputed per date over the window, oldest first.
  Step-like is correct — no smoothing.
- `direction` from the slope of the last 3 trend points (keep existing rule).
- Block delta consumers use `score(now) − score(4 weeks ago)` — see Section 5.

## Section 4 — Contract preservation + cache

- Preserve return shapes exactly: `score`, `direction`, `trend`,
  `qualifying_session_count`, `confidence_band` (speed), `debug`; and states
  `scored` / `building_baseline` / `needs_thresholds` / `missing`.
- All three consumers must read the new scale together:
  `GET /api/athletes/{id}/performance` (main.py ~14129),
  `_workout_signal_scores` (~5411), `_athlete_scores_as_of` (~5540).
- Bump the VERSION token inside `_performance_signature` (main.py ~14481) so
  the durable `summary_cache` (Neon) busts.
- The Projection tab stays on its old linear scale in this branch — that
  divergence is a KNOWN, documented state (proposal doc §5). Do not "fix" it.

## Section 5 — Frontend block delta (minimal)

`frontend/js/training-performance.js` `_blockDelta`: switch to
`trend[last] − trend[value ~4 weeks back]` by date, and hide the delta while
`building_baseline`. No other frontend changes. (No bundler — plain JS edit.)

## Section 6 — Tests

Update, don't delete, the tests asserting the old relative contract:
`test_running_performance__701`, `test_ewma_performance_scores__1051`,
`test_speed_score_sparse_signal_density__1164`,
`test_wire_body_modifier_power_to_weight__1159`. Leave the ceiling/estimator
tests (`__1108`, `__1106`, `__1162`) untouched — estimator is out of scope.

New tests must cover the proposal doc §6 validation targets:

1. Aborted/slow session (like workout `a1d6a936-…`) does NOT lower Speed
   (top-3 mean ignores low perf points).
2. One outlier-fast perf point moves the score by at most ~⅓ of its excess.
3. Training gap: score flat for 2 weeks (grace), then falls ~1.5 pts/week.
4. Race floor holds: mediocre runs after a race can't pull score below
   `perf_race − decay`.
5. Fewer than 3 qualifying runs → `building_baseline`.
6. Missing `threshold_hr` → `needs_thresholds` (endurance).
7. Block delta small/sane on a normal ramp (no "+43" artifact).

Run the full test suite before finishing. Final summary must list: any
`speed_signal` basis findings (Section 2), any contract shape you had to
change, and the raw VDOT values produced for the seeded/dev athlete so the
operator can sanity-check against Daniels tables.
