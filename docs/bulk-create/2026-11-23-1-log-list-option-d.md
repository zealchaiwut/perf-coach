# Training Log list redesign — option D

**Date:** 2026-11-23
**Sprint label:** sprint-148
**Default labels:** revamp, training-log, manual
**Status:** posted

## Context

This sprint redesigns the Sessions list on Training · Log (`/v2/training/log`) to
option D from the design canvas:

- Each week opens with a dark week bar that carries the week's TSS, km and
  progress against the weekly target.
- Session rows keep a single inline metrics line, with time and distance
  emphasised.
- Each session shows its TSS with its share of the week.

Nothing changes in the calendar, the chart, filters or the session drawer.

Mock: `docs/revamp/mocks/source/LogListD.dc.html` (standalone preview:
`docs/revamp/mocks/preview/LogListD.html`, screenshot:
`docs/revamp/mocks/screenshots/LogListD.png`).

**Implementation note:** issues in this sprint are implemented manually in
Cursor, not by Commander agents. Each issue body is the Cursor prompt. Read the
named mock before coding. The `manual` label marks them as hand-implemented;
Commander only dispatches tickets passed to it explicitly, so do not include
them in a dispatch call.

**Conventions:**
- The mock owns layout, hierarchy, colours and spacing; the issue owns numbers
  and rules. Where they disagree, the issue wins. Numbers in the mock are
  illustrative and must not be copied into fixtures.
- Stack stays as it is: FastAPI, SQLAlchemy 2.0, vanilla JS, inline SVG/CSS
  only, pytest.
- One reader per number: every week number comes from the weekly rollup reader,
  and every session TSS from the session TSS reader. The frontend never
  recomputes a total.
- No double-quote characters inside issue bodies.

**Names corrected against the repo before posting:**
- LL-2: the hidden-sessions row is rendered in `paintList` with the text
  `N more sessions this week`; added `paintList` to Where.
- LL-3: there is no column linking a workout to its race. `races.addon_workout_id`
  links only the post-race add-on run. Noted in the rule; rule unchanged.
- LL-3: the strength typed-at-the-gym note is today part of the same chip text,
  `UNPLANNED · TYPED AT THE GYM`; noted in the rule. `PLANNED, NOT DONE` is one
  chip.

## Issues

### LL-1

```
Title: [Log list D] Week bar: dark header with TSS, km and target progress

Mock
docs/revamp/mocks/source/LogListD.dc.html, every dark week bar.

Where
frontend/js/v2-training-log.js (paintList week header, plannedEmptyCard), frontend/css/revamp.css, backend/services/weekly_rollup.py.

Rules
- Replace the current week header line (week range on the left, TSS · km · planned on the right) with a full-width dark bar: background #0b1530, white text, radius 12px, padding 16px 20px, 16px space above each bar.
- Left side: week range at 21px weight 700 (for example 16 – 22 Nov), with a 13px sub-line in #c9d5ef: Last week or This week where it applies, the phase label when the rollup has one, the race name when the week has a race, and the session count.
- Right side, in order:
  - week TSS at 32px mono weight 700 in lime #e4ff52, with a small uppercase TSS unit;
  - distance at 20px mono white, with a km unit;
  - a 220px progress meter.
- Progress meter:
  - The track is 8px, white at 16 percent opacity, with a 2px white tick at the target position.
  - Scale the track so its full width equals max(target_tss / 0.87, tss_total). That keeps the target tick near the right end when under target, and puts the fill at 100 percent when over.
  - Under the track, a 12px line: N% of T target when at or under target; +X over T target when over.
  - Then a middle dot and the change versus the previous week (for example −233 vs prev).
- Over target: the TSS number, the fill and the +X value turn amber #ffb27a. At or under target, the fill is lime.
- No target (target_tss null): hide the meter and keep TSS and km.
- Current week with nothing logged:
  - render the bar in #33405e with a grey 0 TSS and an empty meter;
  - the line reads 0% of T target, followed by an Open in Plan link in lime to /v2/training/plan;
  - this replaces the dashed planned-sessions card.
- Remove the planned N figure from past weeks. Planned TSS shows only for the current and future weeks, inside the sub-line.
- Backend: add tss_delta_prev to each week returned by weekly_rollups (this week tss_total minus the previous week tss_total, null when the previous week is outside the data). The frontend reads it; it never subtracts weeks itself. tss_total, distance_km and target_tss already exist in the rollup.
- Each week's session rows sit in a block under its bar, with a 1px #e6ebf5 outline on the sides and bottom and a bottom radius of 12px, so a week reads as one unit.
- Phone widths (600px and below): the bar stacks with the week range on top, then the TSS, km and meter row, which wraps. The meter goes full width.

Acceptance criteria
- Fixture weeks render correctly: under target, exactly on target, over target, no target, current week empty, current week partly logged.
- The over-target state is amber in the number, the fill and the label.
- tss_delta_prev is covered by a pytest for adjacent weeks and for the first week in range (null).
- No week header shows a planned figure for a past week.
- Layout checked at 1440px and 390px against the mock.

Depends on: none
```

### LL-2

```
Title: [Log list D] Session row: inline metrics emphasis and TSS share of week

Mock
docs/revamp/mocks/source/LogListD.dc.html, session rows.

Where
frontend/js/v2-training-log.js (renderSessionRow, sessionMeta, and the more-sessions row in paintList), frontend/css/revamp.css.

Rules
- Keep the current single-line layout. Do not split metrics into table columns.
- The row grid is date (56px) | name, chips and metrics | feel buttons | TSS block (170px), with 16px gaps and 14px 16px padding. Rows are separated by a 1px #eef1f7 divider inside the week block (no separate card border per row).
- Metrics line: 13.5px mono. Duration and distance are bold #0b1530. Pace, power and HR stay in muted #7a869f. The order is unchanged: time · km · pace /km · W · HR.
- TSS block, right-aligned:
  - the session TSS at 24px mono weight 700 in #1f3b8a;
  - under it, a 110px by 6px share bar (#eef2fb track, #1f3b8a fill) plus a mono percent label;
  - share = session TSS divided by the week tss_total from the rollup, rounded to a whole percent;
  - hide the share when the week total is 0.
- Race sessions:
  - the row background is #fbffe0, the TSS number #4a5200, and the share fill #8f9a00;
  - a RACE chip (#f4ff9e background, #4a5200 text, 1px #b8c400 border) replaces any plan chip.
- The N more sessions this week row (rendered in paintList) stays at the bottom of the week block, with the TSS and km of the hidden sessions on the right.

Acceptance criteria
- The share percents of the visible and hidden sessions add up to about 100 for a fixture week (within rounding).
- A race row renders with the race styling and the RACE chip.
- The session TSS shown equals the session TSS reader value (no client-side rounding beyond Math.round of the reader value).
- Checked at 1440px and 390px; at 390px the feel buttons drop under the metrics line.

Depends on: LL-1
```

### LL-3

```
Title: [Log list D] Chips: show plan status only when it carries information

Mock
docs/revamp/mocks/source/LogListD.dc.html, chips beside session names.

Where
frontend/js/v2-training-log.js (badgeChips, isRaceLike).

Rules
- Remove the UNPLANNED chip from synced runs. Most runs are unplanned, so the chip is noise. Keep MATCHED COACH PLAN, PLANNED, NOT DONE and the strength typed-at-the-gym note (today this note is the chip text UNPLANNED · TYPED AT THE GYM in badgeChips).
- Race detection must recognise a race even when the week rollup has no race_items (past weeks):
  - match on the workout being linked to a race row (note: no column links a workout to its race today; races.addon_workout_id links only the post-race add-on run);
  - or on the workout date equalling a race_date for the user, with a name containing the race name.
  - A matched race shows the RACE chip from LL-2.
- Source chips (STRAVA, STRYD) stay as they are.

Acceptance criteria
- A past race week (fixture: a race named Bangsaen42 and a workout named Bangsaen42 2026 on the race date) shows RACE, not UNPLANNED.
- Ordinary unplanned runs show only their source chips.

Depends on: LL-2
```

## Posted Issues

| ID | Issue | Title |
|---|---|---|
| LL-1 | #1943 | [Log list D] Week bar: dark header with TSS, km and target progress |
| LL-2 | #1944 | [Log list D] Session row: inline metrics emphasis and TSS share of week |
| LL-3 | #1945 | [Log list D] Chips: show plan status only when it carries information |
