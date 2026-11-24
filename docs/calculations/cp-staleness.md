# CP staleness and Update CP flow (#1877)

Code: `backend/services/cp_staleness.py`. Deterministic; no LLM.

CP on file: `user_preferences.ftp_w` (+ `ftp_w_source`, `ftp_w_updated_at`). Scores (TSS, P2W, ...) read it from there, so a confirmed update flows through unchanged.

## Stale if (runs in last 42 days, whole-run avg power)

| Rule | Condition |
|------|-----------|
| long effort | avg power >= 0.95 x CP for >= 60 min |
| short effort | avg power >= 1.05 x CP for >= 20 min |
| age | CP not updated for 42 days (unknown update date counts as stale) |

## Suggested CP

- 60-150 min: `round(avg_power / 0.93)`
- 20-60 min: `round(avg_power / 1.0)`
- > 150 min: flags stale, never used to suggest.

Highest candidate across qualifying efforts, offered only if above CP on file. Worked example: Nov 1 half, 285 W, 2:07:30, CP 280 -> stale, suggest 306.

The latest Stryd `power_zones.critical_power_w` is returned alongside as `stryd_cp_w`.

## Flow

`GET /api/cp/staleness` (read-only) -> athlete confirms -> `POST /api/cp/update {cp_w, source}` writes prefs and a `cp_history` row (dated, with previous value). `PATCH /api/user-preferences` with a changed `ftp_w` also records a `manual` history row. `GET /api/cp/history` lists changes. CP is never auto-updated.

ML-future: efforts could feed a fitted CP model (mean-max power curve); the 0.93 divisor is a fixed prior.
