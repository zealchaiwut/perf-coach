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
