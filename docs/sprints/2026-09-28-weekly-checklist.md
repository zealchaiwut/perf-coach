# Weekly Checklist — Plan-driven habits, Home, Plan and Performance

_Captured 2026-09-28 from a design session in Claude. This doc is the input for
creating the GitHub issues and the sprint. Issue IDs below (`WC-xx`) are
placeholders until the issues exist._

## Design artifact

The full mock (mobile + desktop, every screen) is exported to:

```
~/downloads/perf-coach — Plan-driven weekly checklist.html
```

Open it in a browser. Boards in the file:

| Board | Screen |
|---|---|
| Home · mobile / desktop | Today card, Road to Bangsaen42, Today's session, Week plan |
| Habits · mobile / desktop | Weekly checklist, week at a glance, what moves the A race |
| Habits · manage (mobile page) / manage modal (desktop, gear icon) | Roles, targets, master switch, rebuild status |
| Plan · mobile / desktop | "This week serves the A race" strip, fixed session-load labels, week rows with mobility + fuel |
| Performance · mobile / desktop | A-race hero, needs-result section, what moves the estimate |
| Admin · plan library · mobility | New Mobility tab: stretch patterns + exercise pool |

Widgets are tagged in the mock: **NEW**, **CHANGED**, **REPLACES X**. Untagged
widgets are the current ones, unchanged. The mock shows week 40
(28 Sep – 4 Oct 2026) with the AC V Run 10K on Sunday as the example.

## Goal

One weekly checklist the athlete sees every week, built from the applied Plan,
so that sessions, mobility, fuel and a small set of habits show up in one place
(Habits and Home) and feed a visible "what moves the A-race estimate" view.
No data is copied: the checklist is a read model over existing rows.

## Governing decisions (from this session)

| # | Decision |
|---|---|
| C1 | **Single source of truth.** The checklist has no table. It is composed at read time from `planned_sessions`, `habits`/`habit_logs`, the fuel week payload and `sleep_records`. A tick writes to the row that owns the item. |
| C2 | **Session ticks are `planned_sessions.status`.** `done_auto` via `matched_workout_id`, `done_manual` from the tap. No habit is created per session. The checklist row deep-links to the planned session. |
| C3 | **Mobility is a planned session**, not a habit (continues lean-program D5). New `session_type = mobility`, content from the plan library (patterns + stretch exercise pool), editable in Admin. |
| C4 | **Core vs optional.** Only core items count toward the day score. Optional items never render as "missed". Off hides an item without deleting history. |
| C5 | **Fuel is shown, never ticked** (lean-program D7/D8: no daily food verdicts). Targets come from `fuel.get_week_payload`; no hard-coded tiers in the UI. |
| C6 | **Warm-up and cool-down stay inside run blocks** (the slot validator already requires those phases). They are never separate checklist items. |
| C7 | **Instant vs worker.** Role, target, fuel-card and master-switch changes apply instantly (read model). Anything that changes plan content (mobility on/off/minutes, weekly build) runs on the worker through the plan pipeline: Python skeleton → pattern fill → optional AI refine. The UI keeps showing the last good checklist while a rebuild runs. |
| C8 | **LLM scope.** The LLM may only refine mobility slot content (pick/order stretches from the library, within the pattern's duration band). Habits and fuel stay deterministic (lean-program D12). |
| C9 | **No streaks** anywhere in the checklist (lean-program D8). Weekly evidence and counts only. |

## Where each checklist item lives

| Item | Source row | Ticked by | Default role |
|---|---|---|---|
| Planned session (run / strength / plyo / race) | `planned_sessions` | `status` (auto match or manual) | core, locked |
| Mobility block | `planned_sessions` (`session_type = mobility`) | `status = done_manual` | optional |
| Morning weigh-in | goal habit (`weight.logged`) | autofill | core |
| Protein first | goal habit | tap | core |
| Long-run fuel | goal habit (`long_run.fuelled`) | autofill, long-run days only | core |
| Sleep ≥ target | new habit, autofill from `sleep_records` | autofill | core |
| Zone 2 weekly | coach habit (`workout.zone2_minutes`) | autofill | optional |
| Back care | general habit, `times_per_week` = 5 | tap | optional |
| Sleep hygiene | general habit | tap | optional |
| Fuel targets | `fuel.get_week_payload` | not ticked | shown |
| Stretching (daily) — legacy `coach.stretch_daily` | habit | — | **archive** (replaced by mobility) |

## Findings from the current app (fix alongside)

- Races past their date still show **Upcoming** (KFC Run 10K, 6 Sep; BA Chiang
  Mai Half, 27 Sep). Chiang Mai's estimate was 2:00:12 vs actual 2:19:18, and the
  Bangsaen42 estimate has not been recalibrated with it.
- Two different score pairs are both called Endurance/Speed: Home shows 46/55
  (overall), the race card shows 42/45 (race-specific). Label them.
- Session load shows **ON TARGET** at 0/253, and the formula line reads
  "281 × 5% = 253". 253/281 ≈ 0.90 suggests a hold-week factor — confirm in
  `load_plan` and label it correctly.
- The legacy **Stretching** habit still shows on Home even though
  `ensure_coach_tracked_habits` no longer creates it.
- The app's Bangsaen42 goal is **4:30:00** (use the race row, not a hard-coded goal).

## Backlog

### Phase A — foundation and fixes

#### WC-01 — Races past their date need a result — **HIGH**
- Races with `race_date < today` and no `actual_time_seconds` move to a
  "Needs a result" section; prefill the actual from the matched workout when one
  exists; CTA "Record and recalibrate" → existing `POST /api/races/{id}/calibrate`.
- **Accept:** Chiang Mai shows 2:19:18 prefilled; recording it refreshes the
  A-race estimate.

#### WC-02 — Session load labels — **MED**
- Status reads "under / on / over" from planned + logged vs target, not "on
  target" at zero. Formula tiles show the real factor used for the week
  (hold / ramp / taper).
- **Accept:** week of 28 Sep reads "0/253 · under"; formula tiles add up.

#### WC-03 — Label overall vs race-specific scores — **LOW**
- Home Performance card: "overall"; race cards and A-race hero: "race-specific".

#### WC-04 — Retire the legacy Stretching habit — **MED**
- Archive the existing `coach.stretch_daily` habit (data migration), remove it
  from Home chips. `stretch_daily_min` pref stays the mobility-minutes source.

#### WC-05 — `habits.checklist_role` (core | optional | off) — **HIGH**
- Migration + model + API. Defaults per the table above.
- `ensure_goal_habits` and `ensure_coach_tracked_habits` must respect `off` and
  never re-create or re-activate it. Note: `_find` currently filters only
  `is_archived`, so archiving is not a safe way to hide a goal habit.
- **Accept:** set Protein first to off → not re-created on the next ensure call;
  history kept.

#### WC-06 — Master switch `weekly_checklist_enabled` — **MED**
- New pref (pref_catalog, same place as `stretch_daily_min`). Off = the plain
  habits page as today; Plan and fuel unaffected.

#### WC-07 — Sleep autofill source — **MED**
- New `auto_fill_source` (e.g. `sleep.hours_min`) reading `sleep_records.total_sleep_minutes`
  against the habit's `target_value` (default 7.5 h). Decide and document whether
  `daily_metrics.sleep_hours` is a fallback or ignored — do not read both silently.

#### WC-08 — Fuel day types + carb-load rule — **HIGH**
- `fuel.compute_day_type` adds `quality`, `pre_race`, `race`, `carb_load`
  (today: rest | lift | easy_run | long_run).
- Rule: race with goal time ≥ 90 min → the 2 days before are `carb_load`
  (8–10 g/kg); shorter races → the day before is `pre_race` only.
- `get_week_payload` returns per-day type and targets. Race-week phase stays
  maintenance (`fuel_periodize`).
- **Accept:** week 40 → Sat `pre_race`, Sun `race`, no carb load (AC V Run goal
  0:50). Bangsaen42 → Thu 13 and Fri 14 Nov `carb_load`.

### Phase B — mobility sessions on the worker

#### WC-09 — Investigate how `daily_extras` survive draft apply — **HIGH, do first**
- `plan_extras.attach_stretch` adds `daily_extras` to skeleton slots, but
  `planned_sessions.session_type` only allows `run | strength | plyo | rest`.
  Confirm what apply does with extras today (not verified in this session).

#### WC-10 — `session_type = mobility` — **HIGH**
- Check-constraint migration; `structure.exercises[]`; `structure.optional = true`;
  status `skipped` semantics (never counted as missed); 0 TSS.

#### WC-11 — Plan library: mobility patterns + stretch pool — **HIGH**
- `plan_patterns.kind` += `mobility`; `plan_exercises.groups` += `stretch` with
  hold, PNF-allowed and focus tags.
- Seed patterns: `stretch_core` (10–15 min, strength days), `stretch_hips`
  (easy run, Day 1), `stretch_posterior` (quality run, Day 2, PNF off),
  `stretch_upper` (easy run, Day 3), `yin` (rest day before a long run or race),
  `stretch_light` (long run or race day).
- Admin: new **Mobility** tab in `/admin/plan-library` (see mock). Stretch names
  come from the athlete's cheat sheet — entered by hand, not seeded.

#### WC-12 — Mobility in the plan pipeline — **HIGH**
- `apply_prefs_extras` → mobility slot per day → `plan_pattern_fill.fill_slot`
  picks the pattern from the day's session → validator (exercises ∈ `stretch`,
  duration within band, no PNF after quality) → optional Ask-AI refine limited
  to choosing/ordering library stretches → apply writes `planned_sessions` rows.

#### WC-13 — Worker jobs and rebuild status — **HIGH**
- Weekly: the Sunday-evening draft for next week includes mobility (confirm the
  current draft schedule on the worker).
- On change: mobility role/minutes change → rebuild remaining days of the current
  week in the background (reuse `plan_draft` dispatch).
- Manual: `POST` "rebuild this week" endpoint.
- Status for the UI (updating / up to date / last built). The checklist keeps
  serving the last good week while a rebuild runs.

### Phase C — read model and UI

#### WC-14 — Checklist read endpoint — **HIGH**
- e.g. `GET /api/checklist/week?week_start=` composing `planned_sessions`,
  habits (by role), fuel week payload and sleep. Returns days[] with items:
  `source`, `role`, `state`, `link`. Day score counts core only.
- Ticks call the owning endpoint (planned session status / habit log). No new
  table.

#### WC-15 — Planned-session deep link — **MED**
- `training.html?tab=plan&session=<id>` opens the detail panel in
  `training-plan.js` (it keeps `_detail` in memory today; no URL param found).

#### WC-16 — Habits page redesign (mobile + desktop) — **HIGH**
- Core / optional sections, fuel card, week at a glance, what moves the A race,
  build status. Gear → Manage (page on mobile, modal on desktop).

#### WC-17 — Home — **HIGH**
- Today card replaces "This morning"; Road to Bangsaen42 replaces the Race card;
  Today's session replaces Today's workout; Week plan shows real sessions and
  today's state. Reuse existing widgets and data where possible.

#### WC-18 — Plan tab — **MED**
- "This week serves the A race" strip; week rows show session, mobility, fuel
  type and checklist status.

#### WC-19 — Performance tab — **MED**
- A-race hero (goal, estimate, range, race-specific endurance/speed with paces);
  "What moves the estimate" from checklist history (key sessions, long-run fuel
  via `habit_evidence`, nights ≥ target); races split into Needs a result /
  Upcoming / Completed.

#### WC-20 — Retire the standalone Claude checklist artifact — **LOW**
- Once WC-14 and WC-16 ship, stop using the separate checklist page (it stores
  its own ticks — a third source of truth).

## Suggested sprint split

| Sprint | Issues | Why together |
|---|---|---|
| A | WC-01 – WC-08 | Fixes and data model; no UI dependency |
| B | WC-09 – WC-13 | Mobility sessions and worker; WC-09 gates the rest |
| C | WC-14 – WC-20 | Read model and all UI; needs A and B |

## Open questions

- Does the AC V Run 10K (4 Oct) exist as a race row with priority B and goal 0:50?
- Hold-week factor: is 0.90 the real rule in `load_plan`?
- Worker schedule for the weekly plan draft today (time and trigger).
- Sleep source of truth: `sleep_records` only, or with a `daily_metrics` fallback?
