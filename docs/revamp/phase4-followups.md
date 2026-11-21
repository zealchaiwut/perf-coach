# Phase 4 follow-up backlog (post-checkpoint)

Filed as GitHub issues with labels `revamp` and `phase-4`.

| Issue | Topic | Notes |
| --- | --- | --- |
| [#1893](https://github.com/zealchaiwut/perf-coach/issues/1893) | Revamp pages: shared CSRF-aware fetch helper | Revamp pages do not load `nav.js`, so mutating calls send no `X-CSRF-Token`; `v2-performance.js` carries its own helper. |
| [#1894](https://github.com/zealchaiwut/perf-coach/issues/1894) | Race roles from P6-4 | Roles are derived from priority / race type until the column exists; `load_calibrations` filters by role. |
| [#1895](https://github.com/zealchaiwut/perf-coach/issues/1895) | Stryd form-power key and backfill | Key name for `form_power_ratio` was a best guess. |
| [#1896](https://github.com/zealchaiwut/perf-coach/issues/1896) | Projection chart history | `race_predictions` is only written by the Plan bundle; persist daily. |
| [#1897](https://github.com/zealchaiwut/perf-coach/issues/1897) | Coach block stopgaps | First-gel chip (P1-9 field) and weekly check-in record (P6-13). |
| [#1898](https://github.com/zealchaiwut/perf-coach/issues/1898) | Race list all-races view and browser smoke test | First 8 upcoming only; no browser test for `/v2/performance`. |
