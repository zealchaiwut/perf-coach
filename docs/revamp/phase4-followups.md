# Phase 4 follow-ups (post-checkpoint)

Filed as GitHub issues with labels `revamp` and `phase-4`. Shipped together on
`feature/p4-follow-ups` (#1893–#1898).

| Issue | Topic | What shipped |
| --- | --- | --- |
| [#1893](https://github.com/zealchaiwut/perf-coach/issues/1893) | Revamp pages: shared CSRF-aware fetch helper | `frontend/js/lib/csrf-fetch.js` patches `window.fetch` + `sendJSON`; every mutating `/v2/*` page loads it. |
| [#1894](https://github.com/zealchaiwut/perf-coach/issues/1894) | Race roles from P6-4 | `races.role` is the only source (missing → `fun`); drawer role select is independent of priority; `ROLE_TARGETS` copy is real. |
| [#1895](https://github.com/zealchaiwut/perf-coach/issues/1895) | Stryd form-power key and backfill | Form power is mean of streams `vertical_power_list`. Sync + `form_metrics_backfill` write `form_power_ratio`. |
| [#1896](https://github.com/zealchaiwut/perf-coach/issues/1896) | Projection chart history | Confirmed: worker `race_predictions` daily job (#1937). GET projection does not write. |
| [#1897](https://github.com/zealchaiwut/perf-coach/issues/1897) | Coach block stopgaps | `workouts.first_gel_minute` (0–300) + Training field; check-in done uses `is_week_checkin_done`. `CopyForClaude` lib on Home/Performance. |
| [#1898](https://github.com/zealchaiwut/perf-coach/issues/1898) | Race list all-races view and browser smoke test | `GET /api/performance/races?all=1` + Show all; TestClient HTML smoke for `/v2/performance`. |
