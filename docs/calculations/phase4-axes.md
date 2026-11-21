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
