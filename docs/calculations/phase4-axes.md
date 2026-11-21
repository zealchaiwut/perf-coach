# Phase 4 performance axes (revamp P4-2 … P4-5)

Axis order, marathon goal profile and staleness rules: `backend/services/axis_spec.py`
(P4-1). Every axis block follows the `score_reader` conventions (`score`,
`delta_28d`, `anchor_date`, `anchor_title`, `stale`) plus `never_measured` and
`raw`. `delta_28d` is read from `performance_score_history` (one shared daily
snapshot row for all axes, written by the worker job `axis_snapshot`).

## Durability (P4-2) — `backend/services/axis_durability.py`

- Qualifying run: duration >= 90 min, `workouts.decoupling_percent` present,
  and `zone2_minutes / duration >= 0.60`. (Zone share uses the per-run
  `zone2_minutes` field; the lap-based intensity endpoint is not used.)
- Raw = median decoupling of the last 4 qualifying runs (2–3 accepted; < 2 ->
  never-measured).
- Score = `clamp(100 - (median - 3) x 8, 0, 100)`, rounded. Medians 5.0 -> 84,
  8.9 -> 53, >= 15.5 -> 0.
- Stale: fewer than 2 qualifying runs in the last 45 days.

## Economy (P4-3) — `backend/services/axis_economy.py`

- Pool: easy runs (>= 50% of duration in zone 2 or below, `zone2_minutes`) of
  the last 28 days that have a `run_form_metrics` row. Medians of leg spring
  stiffness, ground contact time and form power ratio.
- `form_power_ratio` = Stryd form power (W) / running power (W), stored on
  `run_form_metrics.form_power_ratio` (migration `bf3569410f9f`). Extracted from
  `form_metrics["form_power_w"]` (mapped from the Stryd payload keys
  `average_form_power` / `form_power`) or a direct `form_power_ratio` key.
  Existing rows fill in on the next Stryd sync / form-metrics backfill.
- Sub-scores (clamped 0..100): `(lss-6)/6x100`, `(300-gct)/90x100`,
  `(0.30-fpr)/0.10x100`. Score = rounded mean of the available sub-scores,
  at least 2 required. lss 9.4, gct 248, fpr 0.23 -> mean(56.67, 57.78, 70.0) = 61.
- Stale: fewer than 5 easy runs with form data in the 28-day window.
- The same pool supplies the median power for power-to-weight (P4-4).

## Strength (P4-4) — `backend/services/axis_strength.py`

- Anchor lifts: `user_preferences.anchor_lifts` (JSONB, migration `b12573ca9afa`),
  default single-leg deadlift (target 0.6) and calf raise (1.2). Edit via
  `GET/PUT /api/performance/anchor-lifts`. Exercise names match by substring.
- e1RM = `kg x (1 + reps/30)` from the best non-warmup set per exercise row;
  `8/side` counts as 8 reps. Ratio = best e1RM of the last 45 days /
  (target factor x trend mass). Score = `clamp(mean ratio x 100, 0, 100)`.
- An anchor with nothing logged in the window falls back to the best e1RM before
  its latest session and the axis is **stale** (not never-measured).
- Worked example (70 kg): SLDL 24 kg x 8/side -> 0.724, calf raise 60 kg x 10 ->
  0.952, mean 0.838 -> **84**.
- Trend mass = last value of `weight_ewma.compute_ewma` (span 14) over `weight_entries`.

## Power-to-weight (P4-4)

- raw = median `power_w` of the P4-3 easy pool / trend mass; score =
  `clamp(raw / profile target x 100, 0, 100)`. Target = the next A-race goal's
  profile row (P4-1), else the 3:30 row (3.2 W/kg).
- 210 W median / 70 kg = 3.0 W/kg vs 3.2 -> **94**.
- Weigh-in older than 14 days -> **stale** (score kept, never wrong); no weigh-in
  at all -> never-measured. This basis intentionally differs from
  `power_to_weight.compute_power_to_weight_series` (FTP / EWMA weight).

## Mobility (P4-5) — `backend/services/axis_mobility.py`

- Table `mobility_tests` (migration `25e2032a3208`): `test_date`, knee-to-wall
  left/right (0–30 cm), sit-and-reach (−20 to 40 cm). `GET/POST
  /api/performance/mobility-tests`, `DELETE .../{id}`; 422 with a field-specific
  detail on bad input or a future date.
- Sub-scores (clamped 0..100): knee-to-wall = `min(left, right) / 12 x 100`
  (the weaker side counts), sit-and-reach = `(value + 10) / 30 x 100`. Score =
  rounded mean. Latest test wins.
- Stale after 45 days (the 46th day shows the test-due chip); the score is kept.

## Radar (P4-6) — `radar_payload.py`, `radar_svg.py`, `frontend/js/lib/perf-radar.js`

- `GET /api/performance/radar?size=large|small` returns, per axis (P4-1 order):
  `score`, `score_28d_ago` (snapshot at or before today − 28 d), `delta_28d`,
  `stale`, `never_measured`, `focus`, `status`, plus `not_yet_measured`, an
  accessible `summary` sentence and the rendered inline `svg`.
- Home (small) and Performance (large) mount the same component against the same
  endpoint; scores are never recomputed client-side.
- Never-measured axes are omitted from the polygon (it closes over the rest) and
  listed under the chart. Stale axes: hollow dashed point. Focus axis: amber point
  and label. Dashed outline = 28 days ago. Rings at 25 / 50 / 75.
- Status label precedence: focus, stale (test due for mobility), signed 28-day delta.

## Focus ranking and the queue (P4-7) — `backend/services/focus_ranking.py`

- Weights (sum to 1, asserted at import). Marathon (A race >= 30 km): durability
  0.25, economy 0.20, endurance 0.20, power_to_weight 0.15, strength 0.10, speed
  0.05, mobility 0.05. Half / shorter: speed 0.15 and durability 0.15, the others
  unchanged (the 0.30 held by speed + durability is the same in both tables).
- Eligible axes: measured and not stale. Focus = highest `(100 - score) x weight`.
  Why-not card: the next three measured axes (eligible first, then stale), each
  with a reason (lower weighted gap / matters less for this distance / stale).
- Work map: economy -> plyo, heavy calf raise, drills; durability -> long-run
  length and fuel-practice notes (note-only, no session); strength -> anchor-lift
  block; mobility -> stretch block. endurance, speed, power_to_weight are
  coach-owned: advice only, `POST /api/performance/focus/queue` returns 422.
- Queue: `performance_queue_items` (migration `8d8cd37743d3`): axis, template
  tags, TSS estimate, earliest week, status. Dated to the next build or rebuild
  week (P3-1 phases; never taper/race week; 409 if none). Idempotent per axis.
  `revamp_suggest_sessions._load_candidates` puts queued work first for build/
  rebuild weeks on or after its earliest week; note-only items come back as
  `queued_notes`. Applying a proposal marks the item `applied`.
- API: `GET /api/performance/focus`, `POST /api/performance/focus/queue`,
  `DELETE /api/performance/focus/queue/{id}`. The radar focus point uses the same ranking.

## A-race hero and after-the-race card (P4-8) — `backend/services/race_hero.py`

- `GET /api/performance/hero`: race badge/name/date/distance/countdown, goal (time
  and pace from the race fields), estimate (`race_finish_estimate.estimate_race_finish`:
  `est_sec`, `band_sec`, `uncertainty_min`; pace via `compute_goal_pace`), range
  (`estimate - band` and `estimate + band`, both printed), race-specific End/Spd chips
  (`score_reader.get_race_scores`) with the one-line meaning, and the after-the-race
  card (static copy + the next checkpoint with its projection estimate).
- Gap to goal = goal minus the slow end and goal minus the estimate (subtraction
  only) with a one-line reading. A test asserts the module contains no
  multiply/divide/modulo/power operators.
- An unavailable estimate degrades the estimate/range tiles to "not available"
  without hiding the hero.

## Endurance and Speed cards (P4-9) — `backend/services/score_cards.py`

- `GET /api/performance/score-cards`: score, 28-day delta and stale from
  `score_reader.get_scores`; sparkline from the daily snapshot series
  (`history_trend`); decomposition (score_then, decay, efforts, consistency,
  score_now), anchors list and the summation invariant from
  `performance_scores.get_performance_payload`.
- Reason sentence (decomposition only): decay outweighs efforts -> "Down from
  decay, not from slower running: the <anchor> from <date> has aged <n> weeks.";
  efforts outweigh decay -> "Lifted by the effort on <date>."; otherwise none.
- No to-reach line: `threshold_suggestions.suggest_thresholds` suggests pace/HR/
  power thresholds, not a score to reach, so `to_reach` is always null.

## Races and projections (P4-10) — `backend/services/projection_view.py`

`GET /api/performance/projection` returns calibration tiles, the chain and the
time-scaled chart from one projection call (`estimate_race_finish`, the same
call the hero uses).

- Tiles: last recalibrated (race + date), data sufficiency, band confidence
  (`main._compute_calibration_status`), model correction % with race count
  (`race_calibration.combined_correction`). Missing source -> `not available`.
- Chain: endurance pace -> speed pace -> blended pace (+ speed-weight %) ->
  model correction -> projected finish (pace, band, goal). Stage paces come from
  `blended_scores_estimate().basis`. The final stage is the estimate itself, so
  it already includes the taper/form factor and demonstrated-race cap.
- Invariants (`check_invariants`, logged + returned as `invariants`, tested):
  chain final == hero estimate; band labels == estimate -/+ band.
- Chart: x = real dates from block start (`revamp_plan_settings`) to race day
  (`x` is the 0..1 position); history line = `race_predictions` rows for the
  race; dashed projection from now to the estimate; band polygon at race day;
  recalibration markers, grey ticks and not-recorded markers from the races.
- Roles (`race_roles.py`, amendment 2026-11-18): only `pb` / `a_race` recalibrate.
  `load_calibrations` now excludes `long_run` / `fun` races, so the model
  correction, tiles and estimate all agree. P6-4 owns the real role column; until
  it exists `race.role` is used if present, else derived (checkpoint -> long_run,
  priority A -> a_race, B -> pb, C -> fun).
- A-race goal: `provisional` until the last pb race before the A race has a
  result, then `locked`; always editable. With no pb race before it, it stays
  provisional.

## Race list (P4-11) — `backend/services/race_list.py`

`GET /api/performance/races`: needs-result, upcoming (first 8, plus `total_upcoming`) and completed (last 6) rows.

- Suggested actual (`match_run`, suggestion only): a synced run on the race date +/- 1 day
  with distance within 5% of the race distance; closest distance, then nearest day, wins.
  The suggested time is the run's moving time. No match reads "No synced run matched".
- Upcoming rows: priority + role chips and role target, goal with pace, estimate with band
  (`build_estimate_block`, the same call as the hero and the chain), race-specific End/Spd
  chips (`get_race_scores`), target chip on the A race, "recalibrates here" for pb / a_race.
- Completed rows: chip time (`actual_time_seconds`) first, matched run moving time second,
  goal minus actual.
- Recording uses the existing `POST /api/races/{id}/calibrate` (and `/calibrate/accept` when
  it suggests new constants); edits use `PATCH /api/races/{id}`, adds use `POST /api/races`.
  `build_projection` runs `ensure_calibrations`, so a recorded result is a calibration row
  before the chain is built and the P4-10 invariants keep holding.

## Coach block (P4-12) — `backend/services/coach_block.py`

`GET /api/performance/coach-block`. No model call; everything is read from the
stored decision `raw_text` (`CHANGES TO APPLY` lines are `key:  text`).

- Review due: newest decision (decided_on, then created_at) with `review_on <= today`
  and no outcome. Due on the review date and every day after; a blank outcome is no
  outcome; a decision marked not applied is never due.
- Review question = its `review:` lines. History summary = first `skeleton:` / `goal:`
  line (else the first non-heading line).
- Status chips: open (no outcome, applied), kept ("Worked or kept": outcome present, applied),
  skipped (applied false).
- Evidence chips (fixed mapping, silently absent on a miss): "long run(s)" -> long runs
  (>= `LONG_RUN_MIN_MINUTES`) since the decision date; "gel"/"fuel" -> first-gel minute of the
  latest long run that logged one (`first_gel_minute`, P1-9 — absent until that field has data).
- Weekly check-in entry (P6-13 not built): done when a decision is dated this week (Mon-Sun),
  otherwise due; link to `/coach`.
- Outcome and did-not-apply save through `PATCH /api/decisions/{id}` (`outcome_note`, `applied`).
