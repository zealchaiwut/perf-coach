# Revamp cleanup ledger (P5-11)

Do not delete in the cutover PR — this list is the source for one later deletion pass.

## Routes → `/v2` replacements

| Legacy route | Page file | Replacement |
| --- | --- | --- |
| `/home` | `frontend/pages/home.html` | `/v2/home` |
| `/log` | `frontend/pages/training-log.html` | `/v2/training/log` |
| `/training` | `frontend/pages/training.html` | `/v2/training/plan` (+ `/v2/performance`) |

## Nav

| Asset | Notes |
| --- | --- |
| `frontend/js/nav.js` — Weight / Habits links | Hidden when `REVAMP_UI` is on; pages kept for `?legacy=1` |
| `injectRevampLink` | Removed at cutover (default UI is v2) |

## Admin

| Legacy | Replacement |
| --- | --- |
| `/admin/plan-library` | `/v2/training/admin` |

## Scripts likely superseded (verify before delete)

- `frontend/js/training.js` — plan/projection tab shell (partial; log still uses some helpers)
- `frontend/pages/training.html` — old plan + performance tabs