# Weight-trend rate with a confidence interval

**Service:** `backend/services/weight_trend_rate.py`
**Consumers:** `coach_export.py` (`body.*`, `athlete.mass_kg`)
**Added:** 2026-07 for the coach export (paste-to-Claude loop)

## Why it exists

Three weight signals existed before this, none of which can answer "am I actually
losing weight?":

| Existing | Answers | Cannot say |
|---|---|---|
| `weight_plan.compute_weight_status` | am I on pace for my target (plan-relative) | whether the observed movement is real |
| `weight_ewma_rate.compute_weekly_pct_bw_rate_of_change` | percent change between two EWMA points | anything about uncertainty — it is a two-point difference |
| `weight_status.compute_status_label` | ahead / on-track / behind vs a linear target line | same |

A coach message that calls a 0.05 kg/week wobble "losing weight" is wrong in a way
the athlete cannot check. This module reports the rate **with** its confidence
interval, so a movement indistinguishable from flat is labelled flat.

## Formula

Ordinary least squares on the EWMA trend over the trailing window. Given points
`(t_i, y_i)` where `t_i` is days since the window start and `y_i` is the smoothed
weight in kg:

```
slope_kg_per_day = Sxy / Sxx
residual_var     = SSE / (n - 2)
se_slope         = sqrt(residual_var / Sxx)
ci_half_width    = T_CRIT_95 * se_slope          # kg/day
rate_kg_per_week = slope_kg_per_day * 7
ci_kg_per_week   = ci_half_width * 7
```

`state` is decided by the interval, never the magnitude:

```
lower = rate - ci ;  upper = rate + ci
flat     if lower <= 0 <= upper
losing   if rate < 0
gaining  otherwise
```

## Constants

| Constant | Value | Rationale |
|---|---|---|
| `DEFAULT_WINDOW_DAYS` | 45 | long enough for a cut's signal to clear daily noise, short enough to reflect the current block |
| `MIN_COVERAGE_PCT` | 40.0 | below this the fit is arithmetic, not evidence |
| `MIN_ENTRIES` | 5 | fewer points make the CI meaningless even at high coverage |
| `T_CRIT_95` | 1.96 | normal approximation; at n ≈ 20–45 the Student-t difference is under the rounding we report, and a per-n table is precision this signal does not have |

## Inputs and contract

```python
compute_trend_rate(entries, as_of, *, window_days=45, ewma_values=None) -> dict
```

- `entries` — oldest-first dicts with `date` and `weight_kg`. Entries outside the
  window are ignored, so callers may pass a longer history unfiltered.
- `ewma_values` — optional, aligned 1:1 with `entries`. **Callers should smooth
  the full history and pass it in.** A fresh EWMA over only the window
  bootstraps on the window's first raw value and inherits its noise, which biases
  the slope. `coach_export._assemble_body` does this.

Returns: `window_days, trend_kg, last_weigh_in, rate_kg_per_week, ci_kg_per_week,
state, readable, readable_note, coverage_pct, entries_used`.

`trend_kg` is the EWMA on the most recent entry — the "trend weight" that should
be used in place of the last raw weigh-in anywhere body mass is reported.

## Readability

`readable` is False when coverage (distinct weigh-in days / window days) is below
`MIN_COVERAGE_PCT`, or when fewer than `MIN_ENTRIES` days exist. **Callers must
not present the rate as a fact when `readable` is False** — that is the whole
point of the flag. The rate is still returned so the caller can show it as
provisional if it wants to.

## Degenerate cases

| Case | Result |
|---|---|
| no entries, or none inside the window | full null shape, `state: unknown` |
| fewer than 3 weigh-in days | `trend_kg` reported, no rate (n − 2 ≤ 0, so no residual variance and therefore no CI) |
| all entries on one calendar day | `trend_kg` reported, no rate (`Sxx == 0`) |
| two weigh-ins on the same day | counted once; the later value wins |

A rate is never returned without a CI. A number that looks certain and isn't is
the failure mode this module was written to prevent.

## Worked example

Window 45 days, 30 weigh-ins, EWMA falling 78.4 → 77.5 kg roughly linearly:
slope ≈ −0.020 kg/day → `rate_kg_per_week` ≈ −0.14. With tight residuals the CI
half-width is ≈ 0.03 kg/week, so the interval (−0.17, −0.11) excludes zero and
`state` is `losing`. Add balanced ±0.9 kg scatter around the *same* line and the
central rate is unchanged at −0.14 while the CI widens past 0.3 — the interval now
spans zero and `state` becomes `flat`. Same number, opposite verdict; the CI is
what decides. (`tests/test_coach_export__body_honesty.py` pins exactly this pair.)

## Caching

None. The fit is a single pass over at most 45 points and runs once per export.

## ML-readiness

The slope is a per-window point estimate with no notion of the athlete's own
weigh-in behaviour (morning vs evening, post-long-run glycogen swings, weekend
pattern). Two upgrades, in order of value:

1. **Per-day-of-week and post-session offsets.** The residuals almost certainly
   carry structure — a Sunday long run inflates Monday. Modelling that shrinks
   the CI without any new data collection; `workouts` and `weight_entries` are
   already joinable by date.
2. **State-space filter (Kalman) instead of EWMA + OLS.** A local-linear-trend
   model gives the level and slope with a principled uncertainty on both, handles
   irregular sampling natively (no coverage threshold needed), and would replace
   `MIN_COVERAGE_PCT` with an honest widening interval.

**Log now to enable this:** nothing new is required for (1). For (2), keep
recording `weight_entries.entry_time` — it is already a column but is frequently
null, and time-of-day is the largest single nuisance term in the residuals.
