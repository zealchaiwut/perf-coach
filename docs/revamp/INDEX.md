# Revamp mocks — index

Desktop mocks, 1440 px wide. Paths are relative to `docs/revamp/`. See [README.md](README.md) for
how issues should use them.

| Screen | What it shows | Phase | Source | Preview | Screenshot |
|---|---|---|---|---|---|
| Home | Home | 5 | [mocks/source/Main.dc.html](mocks/source/Main.dc.html) | [mocks/preview/Main.html](mocks/preview/Main.html) | [mocks/screenshots/Main.png](mocks/screenshots/Main.png) |
| Performance | Performance: race, radar, projections, coach | 4 | [mocks/source/Performance.dc.html](mocks/source/Performance.dc.html) | [mocks/preview/Performance.html](mocks/preview/Performance.html) | [mocks/screenshots/Performance.png](mocks/screenshots/Performance.png) |
| TrainingWeek | Training · Plan | 3 | [mocks/source/TrainingWeek.dc.html](mocks/source/TrainingWeek.dc.html) | [mocks/preview/TrainingWeek.html](mocks/preview/TrainingWeek.html) | [mocks/screenshots/TrainingWeek.png](mocks/screenshots/TrainingWeek.png) |
| TrainingPlanEdit | Session editor, planned mode | 3 | [mocks/source/TrainingPlanEdit.dc.html](mocks/source/TrainingPlanEdit.dc.html) | [mocks/preview/TrainingPlanEdit.html](mocks/preview/TrainingPlanEdit.html) | [mocks/screenshots/TrainingPlanEdit.png](mocks/screenshots/TrainingPlanEdit.png) |
| TrainingLog | Training · Log: month board, volume, list | 1 | [mocks/source/TrainingLog.dc.html](mocks/source/TrainingLog.dc.html) | [mocks/preview/TrainingLog.html](mocks/preview/TrainingLog.html) | [mocks/screenshots/TrainingLog.png](mocks/screenshots/TrainingLog.png) |
| TrainingSession | Run session drawer (incl. Consult button) | 1 | [mocks/source/TrainingSession.dc.html](mocks/source/TrainingSession.dc.html) | [mocks/preview/TrainingSession.html](mocks/preview/TrainingSession.html) | [mocks/screenshots/TrainingSession.png](mocks/screenshots/TrainingSession.png) |
| TrainingLiftView | Strength session, view | 2 | [mocks/source/TrainingLiftView.dc.html](mocks/source/TrainingLiftView.dc.html) | [mocks/preview/TrainingLiftView.html](mocks/preview/TrainingLiftView.html) | [mocks/screenshots/TrainingLiftView.png](mocks/screenshots/TrainingLiftView.png) |
| TrainingLiftEdit | Session editor, logged mode | 2 | [mocks/source/TrainingLiftEdit.dc.html](mocks/source/TrainingLiftEdit.dc.html) | [mocks/preview/TrainingLiftEdit.html](mocks/preview/TrainingLiftEdit.html) | [mocks/screenshots/TrainingLiftEdit.png](mocks/screenshots/TrainingLiftEdit.png) |
| TrainingTrends | Training · Trends | 5 | [mocks/source/TrainingTrends.dc.html](mocks/source/TrainingTrends.dc.html) | [mocks/preview/TrainingTrends.html](mocks/preview/TrainingTrends.html) | [mocks/screenshots/TrainingTrends.png](mocks/screenshots/TrainingTrends.png) |
| TrainingAdmin | Admin · training library | 5 | [mocks/source/TrainingAdmin.dc.html](mocks/source/TrainingAdmin.dc.html) | [mocks/preview/TrainingAdmin.html](mocks/preview/TrainingAdmin.html) | [mocks/screenshots/TrainingAdmin.png](mocks/screenshots/TrainingAdmin.png) |
| HomeSeason | Home · Osaka season layout — **provisional** copy of Main until canvas export | 6 · [#1883](https://github.com/zealchaiwut/perf-coach/issues/1883) | [mocks/source/HomeSeason.dc.html](mocks/source/HomeSeason.dc.html) | [mocks/preview/HomeSeason.html](mocks/preview/HomeSeason.html) | [mocks/screenshots/HomeSeason.png](mocks/screenshots/HomeSeason.png) |
| SeasonRoad | Performance · season road — **provisional** copy of Performance until canvas export | 6 · [#1880](https://github.com/zealchaiwut/perf-coach/issues/1880) | [mocks/source/SeasonRoad.dc.html](mocks/source/SeasonRoad.dc.html) | [mocks/preview/SeasonRoad.html](mocks/preview/SeasonRoad.html) | [mocks/screenshots/SeasonRoad.png](mocks/screenshots/SeasonRoad.png) |
| WeeklyCheckin | Performance · weekly check-in — **provisional** copy of Performance coach block | 6 · [#1887](https://github.com/zealchaiwut/perf-coach/issues/1887) | [mocks/source/WeeklyCheckin.dc.html](mocks/source/WeeklyCheckin.dc.html) | [mocks/preview/WeeklyCheckin.html](mocks/preview/WeeklyCheckin.html) | [mocks/screenshots/WeeklyCheckin.png](mocks/screenshots/WeeklyCheckin.png) |

## By phase

- **Phase 1:** TrainingLog, TrainingSession
- **Phase 2:** TrainingLiftView, TrainingLiftEdit
- **Phase 3:** TrainingWeek, TrainingPlanEdit
- **Phase 4:** Performance
- **Phase 5:** Main (Home), TrainingTrends, TrainingAdmin
- **Phase 6:** HomeSeason (provisional), SeasonRoad (provisional), WeeklyCheckin (provisional)

## Not included

`TrainingCalendar.dc.html` was merged into TrainingLog and is obsolete. It is not in `mocks/source/`,
though `canvas.json` (kept byte-for-byte) still lists its board.
