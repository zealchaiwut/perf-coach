# Phase 4 checkpoint — Performance against the mock

Manual UAT checklist for sprint 142 (issues #1848–#1861). Compare
`docs/revamp/mocks/preview/Performance.html` and `Main.html` beside
`/v2/performance` and `/v2/home` (needs `REVAMP_UI=1`).

Before reviewing, apply the sprint's migrations to the UAT database
(`alembic upgrade head`): `27d247208ac6` (history axes), `bf3569410f9f`
(form power ratio), `b12573ca9afa` (anchor lifts), `25e2032a3208`
(mobility tests), `8d8cd37743d3` (performance queue items), `040c0bcc655a`
(decision race/session links). None were run against a live database while
building the sprint.

## Reviewer checklist

- [ ] Performance preview beside the app, region by region: hero, radar, focus, score cards, projections, race list, coach block.
- [ ] Home and Performance radars show identical numbers (both mount the same server-rendered SVG).
- [ ] The chain final, the hero estimate and the race-list estimate for the A race are one number; band endpoints (estimate minus and plus the band) match on the chart, the hero range and the chain.
- [ ] Queue the focus work, open Plan, see it in suggest-sessions for the right week.
- [ ] Record a race result (race list, Record and recalibrate) and watch the calibration tiles and chain move; only pb and A races recalibrate, long run and fun races draw grey ticks.
- [ ] Run a race debrief end to end: copy the check-in, paste back with `lessons:` lines on `/coach` (race select prefilled), Debrief chip on the race row, lessons printed in the next consult prompt's Previous races block.
- [ ] Log a mobility test and watch the axis wake up (radar and the Mobility card).
- [ ] Review-due card: record an outcome, and mark another decision Did not apply; history chips read open, worked or kept, skipped.

## Automated smoke

`tests/test_phase4_checkpoint__1861.py` — static contracts for the Phase 4
routes, services, pages and docs. Per-ticket behaviour lives in
`tests/test_axis_*__18xx.py`, `test_radar_component__1853.py`,
`test_focus_ranking__1854.py`, `test_race_hero__1855.py`,
`test_score_cards__1856.py`, `test_performance__projections.py`,
`test_race_list__1858.py`, `test_coach_block__1859.py` and
`test_race_debrief__1860.py`.

## Known stopgaps

See `docs/revamp/phase4-followups.md` (issues labelled `revamp`, `phase-4`).
