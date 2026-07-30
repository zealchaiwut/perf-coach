# The lean program

Lose fat without losing fitness, on a program built for how adherence actually
behaves. The design premise is that motivation decays predictably, so the app
**lowers its demands when the athlete slips instead of escalating**. A cut the app
pauses is a cut that wasn't failed.

Everything here is code. The only LLM in the loop is the consult, which happens
outside perf-coach by design.

> Status: **Phases 0–4 complete.** This document describes what exists; the
> "Out of scope" section at the end is what deliberately does not.

## Governing decisions

| # | Decision |
|---|---|
| D1 | Deficit is the target; diet quality and protein are the mechanism. Structural, not managed |
| D6 | Three goal habits only: weigh-in, protein-first, long-run fuel |
| D7 | Never a food nudge. Weight nudge only, morning window, one per day, silent when there's nothing to ask |
| D8 | Weekly verdicts only. No daily verdicts, no streaks anywhere near food |
| D9 | `CHANGES TO APPLY` is stored in the app DB — not Notion, not a local file |
| D11 | 7 consecutive days without a weigh-in → tracking pauses |
| D12 | All of this is code. The only LLM is the consult, outside the app |

## Phase 0 — the persistent loop *(built)*

Phase 1 is the more satisfying build, but without Phase 0 the same conversation
happens in October with no way to know whether anything worked.

### The decision log

| Piece | Where |
|---|---|
| `decisions` table | `backend/models.py` → `Decision`, migration `a87e213dedbb` |
| Endpoints | `backend/routers/decisions.py` |
| Log view | `/decisions` → `frontend/pages/decisions.html` + `frontend/js/decisions.js` |
| Export block | `coach_export._assemble_decisions` |

**There is no parser, deliberately.** A consult produces a `CHANGES TO APPLY`
block; that block is pasted into one textarea and stored verbatim as `raw_text`.
A parser is a project; a textarea is an afternoon, and the value is in having the
history at all.

`raw_text` is immutable. Only the outcome fields (`applied`, `outcome_note`,
`review_on`, `tags`) can be patched, so what the consult actually said can't be
rewritten after the answer is known.

| Route | Purpose |
|---|---|
| `POST /api/decisions` | Store one pasted change list. 201 with the stored row |
| `GET /api/decisions?limit=` | Newest-first log — the view and the export both read this |
| `PATCH /api/decisions/{id}` | Record how it turned out (`outcome_note`, `applied`, `review_on`, `tags`) |
| `DELETE /api/decisions/{id}` | Remove a mis-pasted entry |

A decision with no review date is one nobody ever checks, so `review_on` defaults
to two weeks out. The export computes `due_for_review` — a review date that has
passed with no outcome recorded is the single most actionable thing in the block.

### The consult template

`coach_export.CONSULT_TEMPLATE` + `build_consult_blob()`, served at
`GET /api/coach/consult`. A second template over the **same** payload the daily
message uses — that's the reason both live server-side and versioned.

Where the daily message is one-way and short, the consult is a dialogue: it asks
two or three questions, waits for answers, then emits a change list capped at one
or two changes. Its rules extend the daily ones with four that matter for this
program:

- a `paused` tracking state means don't push on weight data — ask about training
- an active auto-pause is deliberate; support it, don't undo it
- read `decisions[]` first and don't re-propose what was declined or is running
- food suggestions come from `volume_plays[]` — don't invent a meal plan

Unlike the daily paste, the consult does **not** stamp `last_coach_export_at`. A
check-in is a conversation, not the daily message; consuming that signal would
silence the next day's season check.

### `volume_plays`

A `pref_catalog` field (`list[str]`, ≤10 items, ≤80 chars each) holding the
athlete's own high-volume dishes. The consult suggests *from* this list. A recipe
database is out of scope — this is a list of dish names and nothing more.

### Export additions

`SCHEMA_VERSION` 1 → 2, `PROMPT_VERSION` → `coach-paste-v2`, plus the new
`CONSULT_PROMPT_VERSION`. New top-level blocks:

```jsonc
"decisions":    [ {decided_on, days_ago, raw_text, tags, applied,
                   outcome_note, review_on, due_for_review} ],   // last 10
"volume_plays": [ "…" ]
```

### Acceptance

A consult produces a change list → pasted into one field → appears in the next
export, dated → the following consult references it by date.
`tests/test_lean_program__decisions.py::test_round_trip_consult_to_export_references_it_by_date`.

## Phase 1 — the daily floor *(built)*

Daily lives in Discord, not in the app. The app is the weekly surface and the
system of record; it does not need to be opened every day and is not designed to
be.

### Where the Discord part actually runs

**perf-coach never talks to Discord.** Hermes polls a notify endpoint and
delivers. This mirrors the existing `plan_draft_notify` contract so there is one
pattern for morning-window nudges rather than two:

| Piece | Where |
|---|---|
| Weight write | `POST /weight-entry` on the worker (`backend/worker_app.py`), bearer `WORKER_API_TOKEN` |
| Nudge payload | `GET /api/weight/nudge` on the worker |
| State machine | `backend/services/tracking_state.py` |
| Weigh-in autofill | `habit_autofill` source `weight.logged` (migration `1fff1ada408b`) |

Everything else in the lean program rests on the write endpoint. It upserts on
`(user, date)` with a null `entry_time`, so replying twice in one morning
*corrects* the number rather than creating a second row — which is what "reply
87.6" should mean. Entries are stored with `source='imported'`.

### The weigh-in habit ticks itself

`auto_fill_source = 'weight.logged'` fills the habit from the weight entry. A
number replied in Discord **is** the habit; asking for a confirmation tap in the
app is exactly the kind of demand this program removes. The autofill is
best-effort — a habit that failed to tick must never cost the athlete the
weigh-in itself.

### Tracking state

```
        ACTIVE ──── 7 consecutive days, no weigh-in ────► PAUSED
          ▲                                                 │
          └──── 3 weigh-ins within 7 days ──────────────────┘
```

- **ACTIVE** — daily nudge, cut diagnosis on, rate shown.
- **PAUSED** — nudge drops to **weekly, not to nothing** (lower demand, not
  abandonment). Copy: *"weight tracking paused — training continues."* No cut
  verdicts, no rate claims, nothing red, no catch-up guilt. Training is
  unaffected.

**Derived, never stored** — a pure function over weigh-in dates, so it cannot go
stale behind a job that didn't run, and all four consumers (nudge, `cut_review`,
weight card, `meta.tracking_state` in the export) compute the same answer.

The state machine is **simulated over the timeline**, not judged from the last
few days in isolation. That distinction is load-bearing: a stateless reading
can't tell "was paused, then logged once" from "has been logging", so a single
Tuesday weigh-in would silently restart the daily nudge. The thresholds are
asymmetric on purpose (7 days out, 3 weigh-ins back) so the state can't chatter.

### The nudge

One message type. **Weight only, never food** — a food nudge is the fastest way
to make a daily prompt something the athlete mutes, and a muted app can't help.
Silent when today is already logged: the nudge exists to ask for a number, not to
confirm one. `deliver_now` is true only inside the BKK morning window
(06:00–08:00, deliberately earlier than the 07:00–09:00 plan-draft window —
the weigh-in happens before breakfast) with the cadence satisfied.

Silence is the correct output most mornings, and the endpoint says so rather than
inventing something to say.

### Export addition

`meta.tracking_state` and `meta.paused_since`, so a pasted coach knows not to nag
about data the app deliberately stopped asking for (consult rule 3).

### Acceptance

Reply `87.6` in Discord → entry stored, habit ticked, nudge silent next morning.
Miss 7 days → nudge goes weekly and the copy changes; log 3 in a week → back to
ACTIVE. `tests/test_lean_program__weight_write.py`,
`tests/test_lean_program__tracking_state.py`.

## Phase 2 — structural deficit and guardrails *(built)*

The deficit that failed five times was **managed**: a daily budget, daily
decisions, daily chances to quit. This one is **structural** — set once, verified
weekly by the weight trend, with no daily food logging at all.

| Piece | Where |
|---|---|
| Auto-pause engine | `backend/services/deficit_guard.py` |
| Composition trends | `backend/services/body_composition.py` |
| Floors + carb floor | `backend/services/fuel.py` |
| Weight-trend-only review | `backend/services/cut_review.py` |
| Body-fat storage | `weight_entries.body_fat_pct` (migration `c76739716276`) |

### `cut_review` re-gated to the weight trend

This is the change that makes the rest usable. Every diagnosis gate was behind
`MIN_ADHERENCE_PCT = 70` on **fuel logs** — so a non-logger had 0% adherence
forever, `check_logging` fired forever, and the review never said anything. In
`deficit_mode="structural"` (the default now):

- `check_logging` keys on **weigh-in coverage**, not food logs — the one input
  the program actually asks for is the only one it can ask more of;
- `plateau` reads a 21-day stall in the trend directly;
- `recalibrate_maintenance` treats "same swaps three weeks, still behind" as the
  evidence, because there is no intake log to corroborate with;
- `increase_deficit` no longer needs an intake-vs-budget comparison.

`deficit_mode="managed"` keeps the original behaviour intact for anyone who does
log. The `slow_down` guardrail still outranks everything — losing too fast is the
one finding that must survive the re-gate.

### Always-on floors

`compute_budget` now floors on **both** energy availability and estimated BMR
(Katch-McArdle from lean mass). EA is about fuelling training; BMR is about
staying alive. Whichever binds higher wins, `floor_binding` says which, and
neither is the athlete's to override. `DEFICIT_KCAL_RECOMMENDED_MAX = 500` is
what a recommendation may propose; `DEFICIT_KCAL_MAX = 750` is where the schema
check constraint slams the door.

`carb_floor_g_quality_day` (4 g/kg) is **independent of the deficit** — the EA
floor guards total energy, not carbohydrate, and an athlete can clear energy
availability while still under-fuelling the one substrate hard running needs.

### Auto-pause

Any one trigger pauses; the deficit actually goes to zero rather than showing a
warning next to an unchanged number.

| Trigger | Fires when |
|---|---|
| `injury_or_illness` | an open niggle, injury or illness is logged |
| `ctl_falling` | CTL down ≥ 2 TSS/day over 14 days while the deficit is on |
| `scores_declining` | endurance or speed down 2+ consecutive weeks |
| `recovery_degrading` | RHR up ≥ 3 bpm or sleep down ≥ 0.75 h vs baseline |
| `lean_mass_falling` | lean-mass trend down 3+ weeks |

**Every message says EAT MORE**, never "try harder" and never anything that reads
as the athlete's fault. `assert_eat_more_copy` enforces that at import time, so a
future edit can't quietly reintroduce a scolding. A missing input never triggers
a pause — an absent signal is not a bad signal, and a guard that fired on missing
data would pause the cut permanently for anyone without a sleep tracker.

### Body composition — a guard, never a target

Bioimpedance is poor at absolute body fat (±5 points) and acceptable at
*direction* under standardized conditions. Direction is the only thing asked of
it: answering what weight alone cannot — **fat or lean mass?**

Lean mass is derived (`weight × (1 − bf/100)`), never stored, so the two can't
drift apart. Everything is a 4-week rolling mean, and `lean_mass_4wk_delta`
compares blocks rather than individual readings, so one bad reading moves a mean
instead of flipping a verdict. Four readings are required before any direction is
reported at all.

**No target, no goal line, no "on track" flag** — the output carries none of
those keys, and a test asserts it.

### Export additions

`SCHEMA_VERSION` 2 → 3. `constraints` gains `carb_floor_g_quality_day`,
`deficit_mode`, `max_loss_rate_pct_bw_per_week`, `auto_pause_active`,
`auto_pause_reason`, `auto_pause_message`; `body` gains `body_fat_pct_trend`,
`lean_mass_kg_trend`, `lean_mass_4wk_delta`, `lean_mass_falling_weeks`,
`composition_readable`, `composition_readings[]`.

### Acceptance

A deficit set once persists without daily input; a simulated 3-week lean-mass
decline pauses the deficit with eat-more copy; `cut_review` returns a real
recommendation from weight data alone.
`tests/test_lean_program__deficit_guards.py`.

### Already in place

`fuel_periodize.py` was listed as "exists, unused" — it is in fact already wired
through `fuel.compute_effective_deficit` and `get_today_payload`, with
`auto_periodize` defaulting on. Hard days already eat big; no change was needed.

## Phase 3 — habits and week composition *(built)*

| Piece | Where |
|---|---|
| Three goal habits | `backend/services/goal_habits.py` |
| Long-run fuel signal | `workouts.fuelled` + `long_run.fuelled` autofill (migration `37e30b89c6cd`) |
| Stretch / plyo / benchmark | `backend/services/plan_extras.py` |
| Correlation evidence | `backend/services/habit_evidence.py` |

### Three goal habits, and nothing else in the goal section

| Habit | How it is satisfied |
|---|---|
| Morning weigh-in | autofills from a weight entry (Phase 1) |
| Protein first | one self-reported tap — the only one the program asks for |
| Long-run fuel | autofills from a **fuelled** long run (≥ 75 min, `fuelled = true`) |

`ensure_goal_habits` is idempotent and **adopts** an existing habit with the same
name rather than duplicating it, so an athlete who already tracked one keeps
their history. Habits in the `general` section (journaling and the like) are
never touched.

`workouts.fuelled` is nullable and **None means unknown, not "no"** — a habit must
never claim the athlete fuelled a run when nothing recorded that they did.

### Stretch, plyo and drills move into the plan

D5: a checkbox asks the athlete to remember and then to confirm; a planned
session that verifies itself from a logged workout does neither.

`plan_extras.apply_prefs_extras` **decorates** a built skeleton rather than
changing `build_skeleton`. That engine has a "same inputs ⇒ identical skeleton"
contract and several callers, so threading three more preferences through its
budget maths would risk changing everyone's week for a preference most athletes
leave off. With empty prefs and a non-benchmark week the decorator is the
identity function — a test pins exactly that.

`plan_draft` calls it after **both** of its `build_skeleton` sites, so the extras
reach a real week; a test asserts the counts match, because a skeleton built and
not decorated is a week where stretch and plyo silently vanish.

**The stretch target moved with it.** It used to be stored as the "Daily stretch"
habit's `target_value`, which is why the habit couldn't simply be deleted — it
*was* the storage. `stretch_daily_min` is now a `pref_catalog` field (0–60 min),
`ensure_coach_tracked_habits` no longer creates the habit, and
`prefs_for_assemble_facts` falls back to an existing habit's value when the pref
is unset. Nobody loses a target they already set; the habit is simply never
created again. Zone 2 was never in scope for D5 and still lives on Habits.

- **stretch** attaches to every day including rest days (mobility on a rest day
  is the point) and carries **no TSS** — it is not a training session and must
  not eat the load budget;
- **plyo** hangs off a strength day in `superset` mode, or claims its own
  midweek day in `standalone` mode, and only ever takes a day the skeleton left
  as rest or easy — never the long run or a quality session;
- **the monthly benchmark** flags the month's first long run, decided from the
  calendar rather than stored so it can't drift out of sync with a job that
  didn't run.

### Correlation evidence instead of streaks

D8. A streak turns one missed day into a reason to stop; on a food habit that is
actively harmful. So the habit surface shows an argument instead:

> Weeks you fuelled the long run, HR drift averaged 3.0% vs 6.8%.

`habit_evidence` refuses to speak when it shouldn't: below six aligned weeks, or
when one group is empty (all-yes weeks compare nothing), the answer is "not
enough data yet", said plainly. Lower-is-better metrics are handled explicitly so
falling HR drift reads as the win it is, a negligible gap is reported as "about
the same" rather than dressed up as a finding, and the copy states what the
numbers did — never that the habit caused it.

Nothing in `goal_habits` or `habit_evidence` computes a streak; a test strips
docstrings and asserts the word appears nowhere in the actual code, since both
modules discuss streaks at length in prose.

`build_user_evidence` feeds it real rows: one pair per **week** (the claim is
"weeks you fuelled the long run", and a long run happens once a week — daily
alignment would compare a Tuesday tick to a Tuesday with no long run in it),
pairing the long-run-fuel habit against that week's long-run HR drift. Weeks with
no long run are dropped: there was nothing to fuel, so the week is evidence of
neither outcome. The export'"'"'s `habits.evidence[]` renders whatever comes back,
and only readable comparisons are returned — saying "not enough data yet" three
times is worse than silence.

### The monthly benchmark exists for the evidence

Without a fixed route at a fixed effort, "HR drift on long runs" compares a flat
90-minute run to a hilly two-hour one and reports the terrain. The benchmark is
what gives the correlation a clean signal.

### Acceptance

Stretch and plyo appear as planned sessions and auto-verify; no habit renders a
red day (there is no streak or daily verdict to render one from); at least one
correlation sentence appears with real numbers.
`tests/test_lean_program__habits.py`, `tests/test_lean_program__plan_extras.py`.

## Phase 4 — sprints and the hypothesis *(built)*

| Piece | Where |
|---|---|
| Calibration sprints | `backend/services/calibration_sprint.py`, migration `13f189e87eec` |
| Maintenance recalibration | `fuel.calibrate(min_days=, min_entries=)` |
| Weight hypothesis | `backend/services/weight_hypothesis.py` |
| Endpoints | `backend/routers/decisions.py` |

### A measurement week, never a diet

5–7 days of deliberate logging, once a month, **with the end date visible from
the moment it starts**. That bound is the feature: an open-ended "just track your
food for a while" is precisely the shape of the five attempts that already
failed. `assert_measurement_copy` enforces the framing at import, the same way
`deficit_guard` enforces its eat-more contract.

The sprint ends on its own date — nobody has to remember to stop it — and the
countdown includes the final day, so the last day reads "1 to go" rather than
"0" while there is still logging left in it.

| Route | Purpose |
|---|---|
| `GET /api/calibration-sprint` | countdown, logged days, whether one is due |
| `POST /api/calibration-sprint` | open a 5–7 day window (409 if one is running) |
| `POST /api/calibration-sprint/close?abandon=` | close and recalibrate |
| `GET /api/weight-hypothesis` | the weight band where scores were highest |

### Why the recalibration needed unblocking

`fuel.calibrate` already did the arithmetic but demanded 14 days and 10 fuel
entries — thresholds a structural-deficit athlete never reaches, because they
never log food. That is why the feature sat at `insufficient_data` forever. It
now takes `min_days` / `min_entries` overrides, and a sprint passes its own
bounds (5 days). Closing a sprint with enough logged days writes the new
maintenance and flips `maintenance_source` to `measured`.

A sprint that fell short is **completed, not failed**. The copy names the
shortfall and moves on; there is no penalty state, because a measurement that
didn't take is not a moral event.

### Optimal racing weight as a hypothesis

`weight_hypothesis` buckets the athlete's own history — weight trend against
endurance score — and reports the band where the scores were highest. **The
output has no `target_kg` and never will.** "As lean as I can" has no stopping
rule, which is what makes it dangerous; a number off a chart or a peer
percentile is a guess dressed as a goal, and in runners specifically that framing
drives disordered patterns.

It refuses to overclaim in three ways:

- fewer than 30 paired days → "not enough data yet";
- fewer than four populated weight bands → "the range you've actually trained at
  is too narrow to locate a peak" (an athlete who has only ever been 84–85 kg
  has no evidence about 80);
- a bucket with fewer than three days can't be the peak, so one freak day never
  becomes the recommendation.

Confidence is coverage-based and **never earns "high"**, and the sentence ends
with *"this is where the numbers were best, not proof that the weight caused
it"* — a build block raises weight and score together.

**On removing the fixed 82 kg target:** there was no hard-coded 82 kg in the
codebase. That number is the athlete's own `WeightTarget` row, which other
features legitimately read, so nothing was deleted. The hypothesis view is what
replaces *relying* on it: a soft band with stated confidence instead of a single
number to chase.

### Export additions

`SCHEMA_VERSION` 3 → 4. New `sprint` (active, dates, countdown, logged days,
`can_recalibrate`, `due`) and `hypothesis` (peak estimate, band, confidence,
buckets — no target) blocks.

### DQS servings stay paste-only

Deliberately. Spec §11: build an app feature for it **only after two sprints
actually happen**. Logging it in notes and pasting into the consult is the MVP.

### Acceptance

A sprint starts and ends on its own dates; maintenance updates from ≥5 days of
data and flips `maintenance_source` to `measured`; the hypothesis renders without
a hard target. `tests/test_lean_program__sprints.py`.

### Guardrails still outstanding

The always-on family from spec §4 is built **except** three that need the plan
pipeline rather than the fuel model, and are therefore Phase 3+ work:

- **never the biggest deficit on the biggest training day** — needs the week's
  session plan to know which day is biggest; the calorie-cycling half of it
  already works via `fuel_periodize`;
- **cut window closes at week 10** — needs the race-anchored block position, so
  it belongs with the load-plan wiring;
- **ACWR ceiling independent of any weight goal** — already true structurally
  (the ceiling comes from `load_plan`, which never reads a weight target); no
  code was needed, and a test asserting the independence is worth adding when
  the deficit starts influencing the plan.

## Open items

- Discord nudge window: **assumed 06:00–08:00 BKK** and implemented as
  `_WEIGHT_NUDGE_START_HOUR` / `_WEIGHT_NUDGE_END_HOUR` in `worker_app.py` — two
  constants to change if it should follow the actual wake time instead.
- Body-fat scale: assume the weekly reading is typed by hand; auto-import is a
  bonus, not a dependency.
- Whether the Sunday consult and the Sunday prefs reconfirm merge into one
  touchpoint (default: yes).

## Out of scope

Continuous calorie or macro tracking; any daily food verdict; parsing a consult
reply back into the app; a Notion integration beyond an optional later one-way
mirror; any LLM inside perf-coach; body-composition targets or peer-percentile
leanness goals; a recipe database.
