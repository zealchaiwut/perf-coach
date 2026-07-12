# Power-to-Weight (W/kg) Trend

**Endpoint:** `GET /api/weight/power-to-weight?range=`

## What it computes

Each point in the series is:

```
w_per_kg = power_w / weight_kg_ewma
```

- `power_w` — the user's threshold/critical power (FTP) from `user_preferences.ftp_w`.
- `weight_kg_ewma` — the 14-day EWMA-smoothed bodyweight for that calendar day (same
  computation as the weight-chart EWMA series; see `backend/services/weight_ewma.py`).

## power_basis field

The response payload includes a `power_basis` field that describes how `power_w`
was sourced:

| Value | Meaning |
|---|---|
| `"flat_current"` | `ftp_w` is the user's current threshold setting, applied as a constant over every day in the range. There is no historical time-series of threshold changes; if the user updated their FTP mid-range the earlier W/kg values will reflect the current threshold, not what was set at the time. |
| `null` | Power data unavailable (`available: false`). |

## Availability

- `available: false` is returned (and the weight-page card is hidden) when the
  user has no `ftp_w` set in `user_preferences`. This covers users without Stryd
  or any power data.
- No error is raised — callers should check `available` before displaying the card.

## Range tokens

Same set as `/api/weight-chart`: `7D`, `30D`, `90D`, `6M`, `1Y`, `ALL`.
Default when the `range` query parameter is omitted: `30D`.

## current stat block

```json
{
  "w_per_kg":  3.57,
  "power_w":   280,
  "weight_kg": 78.4,
  "delta_30d": 0.12
}
```

`delta_30d` is `current_w_per_kg − w_per_kg_30_days_ago`.  Positive means
improvement (lighter or more powerful). `null` when the range is shorter than
30 days.

## ML-readiness

Once the user accumulates threshold-update history (e.g. via accepted
`threshold_suggestions`), the endpoint can switch to a `"historical"` power_basis
that uses the threshold value that was active on each date rather than the current
flat scalar.  The `power_basis` field is the hook for that migration.
