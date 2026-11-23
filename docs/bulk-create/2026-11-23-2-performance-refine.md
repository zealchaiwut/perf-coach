# Performance tab refinement

**Date:** 2026-11-23
**Sprint label:** sprint-149
**Default labels:** revamp, performance, manual
**Status:** posted

## Context

This sprint refines the v2 Performance tab (`/v2/performance`) to the refined mock:

- The radar shows unmeasured axes as gaps with an action, instead of plotting
  them at the centre.
- The header settings gear becomes visible, and the A race empty state becomes
  compact.
- The Endurance and Speed cards show their score breakdown and anchor efforts as
  structured lists.
- Races and projections is rebuilt on one spacing and type scale. The derivation
  chain becomes complete, so the steps actually multiply out to the estimate
  shown, and the chart tracks the next race against its own goal.
- Race rows share one column layout.

Mock: `docs/revamp/mocks/source/PerformanceRefine.dc.html` (standalone preview:
`docs/revamp/mocks/preview/PerformanceRefine.html`, screenshot:
`docs/revamp/mocks/screenshots/PerformanceRefine.png`).

**Implementation note:** issues in this sprint are implemented manually in
Cursor, not by Commander agents. Each issue body is the Cursor prompt. Read the
named mock before coding. The `manual` label marks them as hand-implemented;
Commander only dispatches tickets passed to it explicitly, so do not include
them in a dispatch call.

**Conventions:**
- The mock owns layout, hierarchy, colours, spacing and type sizes; the issue
  owns numbers and rules. Where they disagree, the issue wins. Numbers in the
  mock are illustrative (only the current estimate point on the chart reflects
  real data) and must not be copied into fixtures.
- Stack stays as it is: FastAPI, SQLAlchemy 2.0, vanilla JS, server-rendered
  inline SVG, pytest. No chart libraries.
- One reader per number: scores come from the score reader, finish estimates
  from `race_finish_estimate`, and display rounding from
  `score_format.display_score`. The frontend never recomputes or re-rounds.
- No double-quote characters inside issue bodies.

**Names checked against the repo before posting** (all named files and
functions exist; notes added in the issue bodies where reality differs):
- PR-1: `legend_flags` in radar_payload.py returns `past`, `stale`, `focus`
  today (no now or not_measured flag). The per-axis field is `never_measured`.
  The mobility test form is a drawer opened by the `#v2-mobility-log` button
  (no URL). No in-app Durability explanation exists; only
  `docs/calculations/performance-scores.md` and `phase4-axes.md`.
- PR-2: gear sizing CSS exists, but only in `frontend/css/v2-settings.css`,
  which only `v2-settings.html` loads. `revamp.css` hides `.rv-settings-label`
  on every page.
- PR-3: the card headline is the `reason` field (`reason_sentence` in
  score_cards.py). Breakdown terms already exist as `anchor_mean_now`,
  `race_floor_now`, `consistency_bonus_now`. The stacked bar is the `split`
  block (`data-card-split`); cards render in `renderScoreCard`, called by
  `loadScoreCards`. The formula field is `formula_line`.
- PR-4: the missing factor is `capped_form_factor` on projected TSB (not CTL),
  applied to the score before `score_to_estimated_finish_time`. A Riegel floor
  after the correction can also cap the time. The chain stages come today from
  `race_finish_estimator.blended_scores_estimate` (a separate module).
  Per-race daily snapshots are the `race_predictions` table (`RacePrediction`).
  The chart's goal comes via `next_a_race` in projection_view.py.
- PR-5: End/Spd pills come from `scorePill` in race rows, fed by
  `_race_specific` in race_list.py. The hero also shows End/Spd pills
  (`data-hero=race-endurance`), outside this issue's scope. Goal pace uses the
  stored `goal_pace_seconds_per_km` first, then `_pace(goal, distance)`.
- PR-6: lap_classifier.py is a 3-line re-export of lap_classify. Only tests
  import it: `tests/test_classify_lap_intensity__678.py` and
  `tests/test_detect_session_profile__682.py`.

## Issues

### PR-1

```
Title: [Perf refine] Radar: show unmeasured axes as gaps with an action, not at the centre

Mock
docs/revamp/mocks/source/PerformanceRefine.dc.html, Status card.

Where
backend/services/radar_svg.py, backend/services/radar_payload.py, frontend/js/lib/perf-radar.js, frontend/css/revamp.css.

Rules
- Revert the centre-plot behaviour added in the radar center-plot commit (fa59e06a). A never-measured axis no longer contributes a vertex at the centre.
- Now polygon:
  - Fill only across the measured axes, in fixed axis order.
  - Stroke an edge solid blue (3px) when the two measured axes it joins are adjacent spokes.
  - When an edge skips one or more unmeasured spokes, stroke it grey #8792a8, 2px, dashed 5 5.
  - With fewer than 3 measured axes, draw no fill: only the points and edges.
- Unmeasured spoke:
  - The spoke line is #c3cbdb, dashed 4 4.
  - At the outer ring, draw an 11px white circle with a dashed #c3cbdb border and a grey plus sign.
  - No point anywhere else on that spoke.
- Unmeasured label:
  - The axis name is in muted #8792a8.
  - Replace the score line with a 13px action link in #1f3b8a:
    - Mobility: Log a test, linking to the mobility test form;
    - Durability: Needs a 90-min easy run, linking to the Durability explanation;
    - any other axis: Not measured yet.
  - Add an action_label and action_href per axis in the radar payload, so the copy lives in one place.
  - Note: the mobility test form is a drawer opened by the #v2-mobility-log button in v2-performance.js (no URL today). No in-app Durability explanation exists yet; the explanation lives only in docs/calculations/performance-scores.md and phase4-axes.md.
- Stale point: a white circle with a solid 3px blue ring and a small grey centre dot. No dashes, so stale never looks like the not-measured style.
- Legend (centered, top divider): Now, Stale, Focus, Not measured yet (a short grey dashed line). Each item is shown only when present, using the payload legend flags. Add a not_measured flag.
  - Note: legend_flags in radar_payload.py returns past, stale and focus today. The per-axis field for unmeasured axes is never_measured.
- Keep the 50 and 75 ring labels (10px mono #8792a8) on the top spoke.
- Payload score stays null for unmeasured axes. Ranking and snapshots are unchanged.

Acceptance criteria
- Fixtures render correctly with 0, 1, 2 and 5 unmeasured axes. Skipped edges are dashed grey, adjacent edges solid.
- No vertex at the centre for an unmeasured axis.
- Legend items follow the payload flags.
- A pytest on radar_svg covers the bridge-edge logic and the no-fill case for fewer than 3 measured axes.

Depends on: none
```

### PR-2

```
Title: [Perf refine] Header settings gear visible, compact A race empty state

Mock
docs/revamp/mocks/source/PerformanceRefine.dc.html, header and first row.

Where
frontend/js/v2-nav.js, frontend/css/revamp.css, frontend/js/v2-performance.js (hero / A race card).

Rules
- Settings gear (bug): v2-nav.js renders an svg with class rv-settings-gear, but no CSS gives it a size, so it collapses and is invisible. The rv-settings-label text is also visually hidden.
  - Note: sizing CSS exists only in frontend/css/v2-settings.css, which only v2-settings.html loads; revamp.css hides .rv-settings-label on every page. Put the rules below in revamp.css.
  - Give .rv-settings-gear width and height 18px, display block, and color currentColor.
  - Make rv-settings-label visible: 14px, weight 700, with a 7px gap after the icon.
  - The util link reads gear + Settings, with the sync dot before it and the existing divider before both.
  - The link stays readable on the inverted (dark) nav: color #e3ecff, and white with a light pill when on.
- At 600px and below, hide the label text again and keep the 18px gear with aria-label Settings.
- This applies on every v2 page, because the nav is shared.
- A race card, empty state:
  - One row: label A RACE and a 14px sentence on the left, and a secondary button (+ Add an A race: white, 1px #c9d2e3 border, 40px min height) on the right.
  - Remove the full-width black button.
  - The card height follows its content (about 90px).
- The After the race card stays beside it in the soft panel style, with copy trimmed to one sentence.
- Only Queue this work keeps a filled (lime) button on this page.

Acceptance criteria
- The gear and Settings label are visible on Home, Training and Performance at 1440px. Only the gear shows at 390px.
- The A race empty state is one row with a secondary button.
- Screenshot comparison against the mock at 1440px.

Depends on: none
```

### PR-3

```
Title: [Perf refine] Endurance and Speed cards: score breakdown list and anchor table

Mock
docs/revamp/mocks/source/PerformanceRefine.dc.html, Endurance and Speed cards.

Where
backend/services/score_cards.py, frontend/js/v2-performance.js (loadScoreCards, renderScoreCard), frontend/css/revamp.css.

Rules
- Card order: label row with a Trend link, then the big score (54px mono) with a delta chip and a sparkline, then a one-line 14.5px headline, then Where N comes from, then the target callout, then anchor efforts. Body text is 14px everywhere in these cards; nothing larger except the score.
- Where N comes from: replace the single formula line (formula_line) with a structured list from score_cards fields (add any field that is missing; do not parse the formula string). The breakdown terms already exist as anchor_mean_now, race_floor_now and consistency_bonus_now. The rows are:
  - Average of 3 anchor efforts, after decay (value);
  - Race floor, used only if higher (value; muted when it is not the one used);
  - Consistency bonus (signed value, green);
  - a Score row with raw value → display_score.

  Each row is a 7px bullet dot, the label and a right-aligned mono value, on a #f7f9fd panel with hairline dividers.
- Remove the decay versus consistency stacked bar (the split block, data-card-split). The list replaces it.
- Headline copy must agree with the delta (the headline is the reason field, built by reason_sentence in score_cards.py):
  - when delta_28d is positive, never say down;
  - when the score rose but most anchors are stale, say so, for example: Up 15, but two of three anchors are over five weeks old and decaying.
  - Generate this in score_cards (one place), from the delta and the anchor ages.
- Target callout: a tinted strip (blue for Endurance, amber for Speed) with a mono arrow and the target score, then the existing to-reach sentence.
- Anchor efforts:
  - A table, open by default, with columns Date, Raw, Age and Status.
  - Dates are formatted as 18 Nov.
  - Status chip: Fresh (green) or Stale · decaying (amber), from the existing is_stale.
  - Remove the details/summary toggle and the bullet list.
- Speed keeps its amber score colour (#b45309) and amber sparkline. Endurance keeps blue.

Acceptance criteria
- Breakdown rows sum to the raw score shown in the Score row (pytest on score_cards).
- No headline says down when delta_28d is positive (pytest with positive, negative and zero deltas).
- The anchor table renders the fresh and stale chips from fixtures.
- Visual check against the mock at 1440px and 390px.

Depends on: none
```

### PR-4

```
Title: [Perf refine] Races and projections: complete derivation chain and next-race chart

Mock
docs/revamp/mocks/source/PerformanceRefine.dc.html, Races and projections card, top half.

Where
backend/services/projection_view.py, backend/services/race_finish_estimate.py, frontend/js/v2-performance.js (loadProjection), frontend/css/revamp.css.

Rules
- Header: a 20px title and a 13px sub-line on the left. On the right, two secondary buttons: Recalibrate and + Add a race. No filled buttons here.
- Four equal tiles: Last recalibrated (date · race, with the result and CP on a 12px sub-line and a CP stale chip when stale), Data, Band confidence and Model correction. Each tile has a 12px label and a 15px value.
- Derivation chain (bug):
  - Today the steps shown (blend 5:38 /km, then correction 1.011294763) do not multiply out to the estimate (1:53:02 for 21.1 km is about 5:21 /km). The race-day fitness adjustment inside _compute_race_day_estimate is missing from the chain.
  - Note: in _compute_race_day_estimate that adjustment is capped_form_factor on the projected TSB (not CTL), applied to the score before score_to_estimated_finish_time. A Riegel floor from recent done races can also cap the time after the correction. The chain stages shown today come from race_finish_estimator.blended_scores_estimate, a separate module.
  - Return the full chain from the backend as ordered steps, each with a label, a value and a unit:
    1. Endurance and Speed paces;
    2. blend with the speed share;
    3. race-day fitness factor (from the projected CTL used by the estimate);
    4. model correction as a multiplier;
    5. the finish estimate with its band and pace.
  - The steps must come from the same computation that produced est_sec, not a second calculation.
  - Show the correction as ×1.011 (3 decimals). Never show a raw float.
- The last chain step shows the next race name and date, the estimate with its band, the pace, and the gap to goal.
  - Amber (#7a3a10 on #fff7ec) when the estimate is slower than goal; green when at or under.
  - It never shows not available while the race list has an estimate for the same race. If there is truly no estimate, show the reason from the estimate payload.
- Chart:
  - It tracks the next race's estimate over time against that race's own goal. Today it uses the A-race or marathon goal (4:30) for a half; fix that. (Note: projection_view.py resolves the race via next_a_race.)
  - y axis: finish time, faster higher, with gridlines and mono labels. x axis: from the earliest snapshot to race day.
  - Draw the estimate line, a Now marker labelled with the current estimate, a dashed extension to race day, the band as a cone to race day, the goal as a dashed green line, and race day as an amber dashed vertical.
  - Race markers: small open circles on the line, with names in rounded tags below the x axis, offset vertically when two would overlap. No text on the plot area.
  - Unrecorded checkpoints use an amber tag (CP · not recorded).
  - Data comes from prediction snapshots for that race (the race_predictions table, model RacePrediction).
- Legend above the chart: Estimate, Band to race day, Goal h:mm:ss.

Acceptance criteria
- A pytest asserts the chain steps multiply to est_sec within 1 second for a fixture race.
- The correction is formatted to 3 decimals. The last step's colour follows faster or slower than goal.
- The chart uses the next race's goal. Tags do not overlap in a fixture with two races 6 days apart.
- No not-available result when race_list has an estimate for the same race.

Depends on: none
```

### PR-5

```
Title: [Perf refine] Race rows: one column layout, honest estimate colour, drop End/Spd chips

Mock
docs/revamp/mocks/source/PerformanceRefine.dc.html, Needs a result / Upcoming / Completed.

Where
backend/services/race_list.py, frontend/js/v2-performance.js (loadRaces), frontend/css/revamp.css.

Rules
- Every race row in all three sections uses one grid:
  - name block (role badge 34px, name 15.5px bold, mono meta line: date, distance, role note);
  - Goal (12px label, 17px mono time + 12px pace);
  - Estimate or Actual (same type);
  - status chip;
  - action column (220px, right-aligned).
- Section labels: 12px uppercase NEEDS A RESULT, UPCOMING (with Season road › on the right), COMPLETED.
- Needs a result: a soft amber row. The action column holds an h:mm:ss input (92px, labelled for screen readers) and a lime Record button at 40px height. Not a full-width tall block.
- Upcoming:
  - Estimate with band. Status chip: N slower than goal (amber) or N faster than goal (green), computed in race_list, not in JS.
  - The estimate colour follows the same rule. Today a slower-than-goal estimate shows green; fix it.
  - Action: an Edit secondary button.
- Completed:
  - Actual time. Status chip: N over goal (red) or N under goal (green).
  - Action: a Debrief link to the session.
  - Show only the latest completed race, plus a Show N earlier races button.
- Remove the End and Spd chips from race rows. They show the race-specific speed (for example 24.3) beside the overall Speed 53, under the same label, which reads as a contradiction.
  - Note: the row pills come from scorePill in v2-performance.js, fed by _race_specific in race_list.py. The hero also shows End/Spd pills (data-hero race-endurance / race-speed); those are not race rows.
- Goal pace uses the race's exact distance (21.0975 km for a half), so 1:50:00 shows 5:13 /km.
  - Note: race_list uses the stored goal_pace_seconds_per_km first and falls back to _pace(goal, distance).

Acceptance criteria
- Fixtures: an upcoming race slower than goal (amber), an upcoming race faster than goal (green), a completed race over and under goal, and an unrecorded checkpoint.
- No End or Spd chips anywhere in race rows.
- All rows align on the same column edges at 1440px. At 390px each row stacks into name, then goal and estimate side by side, then the action.

Depends on: PR-4
```

### PR-6

```
Title: [Perf refine] Cleanup: delete unused lap_classifier module

Where
backend/services/lap_classifier.py.

Rules
- services/lap_classify.py is the single lap classifier. lap_classifier.py appears to have no importers left.
  - Note: lap_classifier.py is a 3-line re-export of classify_laps and classify_laps_for_workout from lap_classify. No backend or scripts code imports it; tests/test_classify_lap_intensity__678.py and tests/test_detect_session_profile__682.py still do.
- Confirm with a repo-wide search (backend, scripts, tests). If nothing imports it, delete it and any tests that only cover it.
- If something still imports it, switch that import to lap_classify (keeping the basis argument behaviour), then delete it.

Acceptance criteria
- No file named lap_classifier.py remains, and the full pytest suite passes.

Depends on: none
```

## Posted Issues

| ID | Issue | Title |
|---|---|---|
| PR-1 | #1948 | [Perf refine] Radar: show unmeasured axes as gaps with an action, not at the centre |
| PR-2 | #1949 | [Perf refine] Header settings gear visible, compact A race empty state |
| PR-3 | #1950 | [Perf refine] Endurance and Speed cards: score breakdown list and anchor table |
| PR-4 | #1951 | [Perf refine] Races and projections: complete derivation chain and next-race chart |
| PR-5 | #1952 | [Perf refine] Race rows: one column layout, honest estimate colour, drop End/Spd chips |
| PR-6 | #1953 | [Perf refine] Cleanup: delete unused lap_classifier module |
