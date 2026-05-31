# Training Load

## Purpose

Training load metrics help runners and endurance athletes understand the balance
between fitness built over weeks and the fatigue accumulated in recent days.
perf-coach computes three values — CTL, ATL, and TSB — from the daily TSS
(Training Stress Score) recorded on each workout. Together they tell you whether
you are ready to race, in a productive build phase, or at risk of overtraining.

## The Math

All three metrics use an exponential weighted moving average (EWMA) of daily TSS:

```
new_value = prev_value + (tss - prev_value) × (1 − e^(−1 / τ))
```

where `τ` is the time constant in days.

| Metric | Full name                | Time constant (τ) | Meaning                      |
|--------|--------------------------|--------------------|------------------------------|
| CTL    | Chronic Training Load    | 42 days            | Long-term fitness            |
| ATL    | Acute Training Load      | 7 days             | Short-term fatigue           |
| TSB    | Training Stress Balance  | —                  | CTL − ATL (freshness)        |

**TSB = CTL − ATL**

A positive TSB means freshness (ATL has dropped below CTL). A negative TSB
means accumulated fatigue (ATL exceeds CTL).

Cold-start assumption: CTL and ATL begin at 0 on the day before the first data
point. Early values are underestimated until the EWMAs charge up; at least 42
days of data (ideally 90+) are needed for CTL to converge.

## Interpreting Values

### TSB thresholds

| TSB range          | Label                    | Meaning                                    |
|--------------------|--------------------------|--------------------------------------------|
| TSB ≥ 5            | Fresh                    | Rested; good for racing or key workouts    |
| −5 < TSB < 5       | Neutral                  | Moderate readiness; normal training        |
| −15 < TSB ≤ −5     | Productive (high load)   | Accumulating fitness; monitor recovery     |
| TSB ≤ −15          | Overreached (high risk)  | High fatigue; reduce load or rest          |

### CTL qualifiers

When CTL context is available the label is extended:

- CTL > 60 → `"<label>, well-trained"` — high aerobic base
- CTL < 30 → `"<label>, undertrained"` — low base, injury risk if load spikes
- 30 ≤ CTL ≤ 60 → label only

### Examples

| CTL  | ATL  | TSB  | Interpretation                        |
|------|------|------|---------------------------------------|
| 70   | 65   | 5    | Fresh, well-trained                   |
| 45   | 43   | 2    | Neutral                               |
| 25   | 32   | −7   | Productive (high load), undertrained  |
| 65   | 83   | −18  | Overreached (high risk), well-trained |

## Limitations

- **Cold-start bias**: CTL is underestimated for the first 6–8 weeks of data.
  Seed the model with at least 90 days of history for reliable CTL values.
- **TSS quality**: The model is only as good as the TSS values on each workout.
  Workouts without TSS contribute zero load and will understate ATL/CTL.
- **Single-metric fatigue**: TSB captures training load only. Sleep quality, life
  stress, illness, and nutrition are not modelled and can cause readiness to
  differ significantly from the TSB prediction.
- **Individual variation**: The default τ values (42-day CTL, 7-day ATL) are
  population averages. Individual athletes may respond faster or slower.
  Configurable threshold overrides are tracked as future work.
- **No intra-day resolution**: One TSS value per workout date is aggregated.
  Multiple workouts on the same day are summed.

## Data Sources

| Source             | Field written        | Notes                                      |
|--------------------|----------------------|--------------------------------------------|
| Manual entry       | `workouts.tss`       | User-specified numeric TSS on a workout    |
| Strava import      | `workouts.tss`       | Computed from Strava's suffer score or HR  |
| Stryd (running)    | `workouts.tss`       | Power-based TSS from Stryd export          |
| `training_load_snapshots` | CTL/ATL/TSB cache | Pre-computed daily snapshots for fast reads |

The `training_load_snapshots` table stores one row per user per date. The
`/api/training-log` endpoint reads today's snapshot when it exists and falls back
to on-demand EWMA computation otherwise.

## Endpoints

### `GET /api/training-load`

Returns CTL/ATL/TSB curves for a date range alongside a `current` summary.

**Query params:** `user_id` (required), `from` (YYYY-MM-DD), `to` (YYYY-MM-DD)

**Response shape:**
```json
{
  "as_of": "2025-05-31",
  "current": { "date": "...", "tss": 80, "ctl": 55.2, "atl": 61.4, "tsb": -6.2 },
  "curves": [
    { "date": "2025-03-01", "tss": 0, "ctl": 52.1, "atl": 48.3, "tsb": 3.8 },
    ...
  ]
}
```

### `GET /api/training-load/current`

Returns today's (or `as_of`) CTL/ATL/TSB with an `interpretation` string.

**Query params:** `user_id` (required), `as_of` (YYYY-MM-DD, optional)

**Response shape:**
```json
{
  "date": "2025-05-31",
  "ctl": 55.2,
  "atl": 61.4,
  "tsb": -6.2,
  "interpretation": "Productive (high load), well-trained"
}
```

### `GET /api/training-log`

Returns weekly grouped training history. Includes a `load_context` object when
the user has ≥ 7 days of logged training data; `null` otherwise.

**Query params:** `user_id` (required), `from`, `to`, `types`, `search`,
`include_rest`

**`load_context` shape (when present):**
```json
{
  "ctl": 55.2,
  "atl": 61.4,
  "tsb": -6.2,
  "interpretation": "Productive (high load), well-trained",
  "as_of": "2025-05-31"
}
```

## References

- Banister EW (1991). "Modeling elite athletic performance." In: MacDougall JD,
  Wenger HA, Green HJ (eds). *Physiological Testing of Elite Athletes*. Human
  Kinetics, Champaign IL. pp 403–424.
- Coggan AR (2003). "Training and racing using a power meter: an introduction."
  Presented at USA Cycling Expert Coach Seminar; subsequently published in
  Coggan AR & Allen H (2010). *Training and Racing with a Power Meter*, 2nd ed.
  VeloPress, Boulder CO.
